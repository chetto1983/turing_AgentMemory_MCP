"""Document ingest/search/lifecycle mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-02). `_active_chunk_rows` and
`_document_chunk_batch_query` live in store_chunking.py (moved there in 01-01 per
the RESEARCH.md sub-split note); `_rerank_documents`/`_reranked_score_details`
live in store_search.py — both keep this module under the 600-LOC cap.

Ported to ArcadeDB (04-06, ARC-04/ARC-05/ARC-06/PERF-01): document + chunk
ingest builds a flat list of bound-param `Statement`s (`store_documents_queries.py`)
committed in ONE managed transaction via `store_core.py`'s `_write_many` (D-08)
-- the old TuringDB-shaped byte-budget batch splitter (`_document_graph_queries`/
`_document_chunk_batch_query`) is retired along with it, since D-08's single
managed transaction has no submit-before-match visibility gap to work around
(store_core.py's docstring). Every Chunk's `id` is `ids.stable_id()` (ARC-08);
the dense `embedding` and both lexical channels (`lexical_tokens`/
`lexical_weights`, the both-channels decision) are inline record properties --
no legacy synthetic-integer join property, no separate CSV vector-load step
(ARC-05). Document search runs native HNSW (`vectorNeighbors`) plus native
Lucene full-text (`SEARCH_INDEX`) as two bound, `user_identifier`-scoped
channels, replacing the old full active-chunk-rows table scan this module's
docstring used to fall back on for lexical matching -- the §1.3 full-scan the
port fixes for free.
"""

from __future__ import annotations

from typing import Any

from turing_agentmemory_mcp.hybrid import blend_hybrid_score, lexical_score
from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.models import DocumentHit, IngestedDocument
from turing_agentmemory_mcp.search_controls import (
    build_score_details,
    passes_threshold,
    validate_search_query,
    validate_threshold,
)
from turing_agentmemory_mcp.sparse_encoder import sparse_vector
from turing_agentmemory_mcp.store_documents_queries import (
    chunk_create_statement,
    chunk_delete_statement,
    chunk_hard_delete_statement,
    chunk_lucene_search_statement,
    chunk_metadata_update_statement,
    chunk_vector_search_statement,
    document_create_statement,
    document_delete_statement,
    document_edge_statement,
    document_hard_delete_statement,
    document_select_statement,
    document_update_statement,
    has_chunk_edge_statement,
    next_chunk_edge_statement,
)


class _DocumentMixin:
    def get_context(
        self,
        *,
        user_identifier: str,
        query: str,
        session_id: str = "",
        memory_types: list[str] | None = None,
        source: str = "",
        tags: list[str] | None = None,
        created_after: str = "",
        created_before: str = "",
        updated_after: str = "",
        updated_before: str = "",
        limit: int = 5,
        threshold: float = 0.0,
    ) -> dict[str, object]:
        items = self.search_memory(
            user_identifier=user_identifier,
            query=query,
            limit=limit,
            memory_types=memory_types,
            session_id=session_id,
            source=source,
            tags=tags,
            created_after=created_after,
            created_before=created_before,
            updated_after=updated_after,
            updated_before=updated_before,
            threshold=threshold,
        )
        return {
            "query": query,
            "user_identifier": user_identifier,
            "items": [item.to_dict() for item in items],
            "context": "\n".join(f"- [{item.kind}] {item.content}" for item in items),
        }

    def ingest_document_text(
        self,
        *,
        user_identifier: str,
        title: str,
        text: str,
        document_id: str | None = None,
        chunk_chars: int = 360,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> IngestedDocument:
        with self._span(
            "document.ingest_text",
            {
                "user_identifier": user_identifier,
                "document_id": document_id or "",
                "source": source,
            },
        ):
            self._require_user(user_identifier)
            if not title.strip():
                raise ValueError("title is required")
            if not text.strip():
                raise ValueError("text is required")
            text, metadata = self._process_text_for_storage(text, metadata)
            document_id = document_id or stable_id("doc", user_identifier, title, text[:128])
            text_hash = self._document_text_hash(text)
            chunks = self._chunk_document_text(text, chunk_chars=chunk_chars)
            self._ensure_user(user_identifier)
            existing = self.get_document(user_identifier=user_identifier, document_id=document_id)
            if existing is not None:
                if existing.text_hash != text_hash or existing.chunk_chars != chunk_chars:
                    raise ValueError(
                        f"document {document_id} already exists with different text; use document_reindex_text"
                    )
                return self._update_document_metadata(
                    user_identifier=user_identifier,
                    document_id=document_id,
                    title=title,
                    source=source,
                    tags=tags,
                    metadata=metadata,
                    expires_at=expires_at,
                    preserve_updated_at=False,
                )
            item = self._create_document(
                user_identifier=user_identifier,
                document_id=document_id,
                title=title,
                text=text,
                chunks=chunks,
                chunk_chars=chunk_chars,
                text_hash=text_hash,
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at or "",
            )
            self._audit(
                operation="document.ingest_text",
                user_identifier=user_identifier,
                resource_type="document",
                resource_id=item.document_id,
            )
            return item

    def get_document(self, *, user_identifier: str, document_id: str) -> IngestedDocument | None:
        self._require_user(user_identifier)
        if not document_id.strip():
            raise ValueError("document_id is required")
        statement, params = document_select_statement(
            document_id=document_id, user_identifier=user_identifier
        )
        rows = self._records(self._query(statement, operation="document.get", params=params))
        active_rows = [row for row in rows if not self._row_is_expired(row, "expires_at")]
        return self._document_from_row(active_rows[0]) if active_rows else None

    def reindex_document_text(
        self,
        *,
        user_identifier: str,
        document_id: str,
        title: str,
        text: str,
        chunk_chars: int = 360,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> IngestedDocument:
        with self._span(
            "document.reindex_text",
            {"user_identifier": user_identifier, "document_id": document_id, "source": source},
        ):
            self._require_user(user_identifier)
            if not document_id.strip():
                raise ValueError("document_id is required")
            if not title.strip():
                raise ValueError("title is required")
            if not text.strip():
                raise ValueError("text is required")
            text, metadata = self._process_text_for_storage(text, metadata)
            existing = self.get_document(user_identifier=user_identifier, document_id=document_id)
            # HI-03: hard-delete (not the soft `delete_document()` a
            # user-facing delete uses -- a soft-deleted row still occupies
            # its slot in Document[id]'s UNIQUE index, so recreating the
            # SAME id right after would raise DuplicatedKeyException, Rule 1
            # bug, found live via the 04-09 E2E capture) is folded into the
            # SAME `_write_many` transaction as the recreate below, not a
            # separate prior commit -- live-confirmed against a real
            # ArcadeDB 26.7.1 container that an intra-transaction DELETE
            # followed by a same-id CREATE VERTEX on a UNIQUE-indexed
            # property succeeds (read-your-writes within one session). Two
            # separate transactions left a window where a concurrent reader
            # observed the document as fully absent, and a crash between
            # them left it permanently deleted with no recreate.
            extra_statements: list[tuple[str, dict[str, object]]] = []
            if existing is not None:
                extra_statements = [
                    document_hard_delete_statement(
                        document_id=document_id, user_identifier=user_identifier
                    ),
                    chunk_hard_delete_statement(
                        document_id=document_id, user_identifier=user_identifier
                    ),
                ]
            chunks = self._chunk_document_text(text, chunk_chars=chunk_chars)
            item = self._create_document(
                user_identifier=user_identifier,
                document_id=document_id,
                title=title,
                text=text,
                chunks=chunks,
                chunk_chars=chunk_chars,
                text_hash=self._document_text_hash(text),
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at
                if expires_at is not None
                else existing.expires_at
                if existing is not None
                else "",
                created_at=existing.created_at if existing is not None else None,
                extra_statements=extra_statements,
            )
            self._audit(
                operation="document.reindex_text",
                user_identifier=user_identifier,
                resource_type="document",
                resource_id=item.document_id,
            )
            return item

    def delete_document(self, *, user_identifier: str, document_id: str) -> dict[str, object]:
        existing = self.get_document(user_identifier=user_identifier, document_id=document_id)
        if existing is None:
            return {"document_id": document_id, "deleted": False}
        updated_at = self._now_iso()
        self._write_many(
            [
                document_delete_statement(
                    document_id=document_id, user_identifier=user_identifier, updated_at=updated_at
                ),
                chunk_delete_statement(
                    document_id=document_id, user_identifier=user_identifier, updated_at=updated_at
                ),
            ]
        )
        self._audit(
            operation="document.delete",
            user_identifier=user_identifier,
            resource_type="document",
            resource_id=document_id,
        )
        return {"document_id": document_id, "deleted": True, "updated_at": updated_at}

    def _create_document(
        self,
        *,
        user_identifier: str,
        document_id: str,
        title: str,
        text: str,
        chunks: list[str],
        chunk_chars: int,
        text_hash: str,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
        created_at: str | None = None,
        extra_statements: list[tuple[str, dict[str, object]]] | None = None,
    ) -> IngestedDocument:
        self._ensure_user(user_identifier)
        created_at = created_at or self._now_iso()
        updated_at = self._now_iso()
        clean_tags = self._clean_tags(tags)
        clean_metadata = dict(metadata or {})
        # PERF-01: one batched embedding round-trip for every chunk.
        vectors = self._embed_many(chunks)

        # HI-03: `extra_statements` (reindex_document_text's hard-delete of
        # the old Document/Chunk rows) runs FIRST in the SAME transaction as
        # the CREATE below -- not a separate prior commit.
        statements: list[tuple[str, dict[str, object]]] = list(extra_statements or [])
        statements += [
            document_create_statement(
                document_id=document_id,
                user_identifier=user_identifier,
                title=title,
                chunk_count=len(chunks),
                chunk_chars=chunk_chars,
                text_hash=text_hash,
                source=source,
                tags_json=self._json_dumps(clean_tags),
                metadata_json=self._json_dumps(clean_metadata),
                created_at=created_at,
                updated_at=updated_at,
                expires_at=expires_at,
            ),
            document_edge_statement(user_identifier=user_identifier, document_id=document_id),
        ]
        previous_chunk_id = ""
        for idx, (chunk_text, vector) in enumerate(zip(chunks, vectors, strict=True), start=1):
            # ARC-08: stable_id() is the sole chunk identifier -- no legacy
            # synthetic-integer join property.
            chunk_id = stable_id("chunk", user_identifier, document_id, str(idx))
            locator = f"chunk={idx}"
            lexical_tokens, lexical_weights = sparse_vector(chunk_text)
            statements.append(
                chunk_create_statement(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    user_identifier=user_identifier,
                    title=title,
                    ordinal=idx,
                    locator=locator,
                    source=source,
                    tags_json=self._json_dumps(clean_tags),
                    metadata_json=self._json_dumps(clean_metadata),
                    created_at=created_at,
                    updated_at=updated_at,
                    expires_at=expires_at,
                    text=chunk_text,
                    embedding=vector,
                    lexical_tokens=lexical_tokens,
                    lexical_weights=lexical_weights,
                )
            )
            statements.append(
                has_chunk_edge_statement(
                    document_id=document_id,
                    chunk_id=chunk_id,
                    ordinal=idx,
                    user_identifier=user_identifier,
                )
            )
            if previous_chunk_id:
                statements.append(
                    next_chunk_edge_statement(
                        previous_chunk_id=previous_chunk_id,
                        chunk_id=chunk_id,
                        user_identifier=user_identifier,
                    )
                )
            previous_chunk_id = chunk_id

        # D-08: the whole document + every chunk + every edge is ONE managed
        # transaction -- no byte-budget batch splitter is needed (that solved
        # TuringDB's submit-before-match visibility gap, which does not exist
        # under ArcadeDB's session-header read-your-writes model).
        self._write_many(statements)
        return IngestedDocument(
            document_id=document_id,
            title=title,
            chunk_count=len(chunks),
            user_identifier=user_identifier,
            created_at=created_at,
            updated_at=updated_at,
            expires_at=expires_at,
            source=source,
            tags=clean_tags,
            metadata=clean_metadata,
            text_hash=text_hash,
            chunk_chars=chunk_chars,
        )

    def _update_document_metadata(
        self,
        *,
        user_identifier: str,
        document_id: str,
        title: str,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
        preserve_updated_at: bool = False,
    ) -> IngestedDocument:
        existing = self.get_document(user_identifier=user_identifier, document_id=document_id)
        if existing is None:
            raise ValueError(f"document {document_id} not found")
        next_source = existing.source if source == "" else source
        next_tags = existing.tags if tags is None else self._clean_tags(tags)
        next_metadata = existing.metadata if metadata is None else dict(metadata)
        next_expires_at = existing.expires_at if expires_at is None else expires_at
        updated_at = existing.updated_at if preserve_updated_at else self._now_iso()
        self._write_many(
            [
                document_update_statement(
                    document_id=document_id,
                    user_identifier=user_identifier,
                    title=title,
                    source=next_source,
                    tags_json=self._json_dumps(next_tags),
                    metadata_json=self._json_dumps(next_metadata),
                    expires_at=next_expires_at,
                    updated_at=updated_at,
                ),
                chunk_metadata_update_statement(
                    document_id=document_id,
                    user_identifier=user_identifier,
                    title=title,
                    source=next_source,
                    tags_json=self._json_dumps(next_tags),
                    metadata_json=self._json_dumps(next_metadata),
                    expires_at=next_expires_at,
                    updated_at=updated_at,
                ),
            ]
        )
        return IngestedDocument(
            document_id=document_id,
            title=title,
            chunk_count=existing.chunk_count,
            user_identifier=user_identifier,
            created_at=existing.created_at,
            updated_at=updated_at,
            expires_at=next_expires_at,
            source=next_source,
            tags=next_tags,
            metadata=next_metadata,
            text_hash=existing.text_hash,
            chunk_chars=existing.chunk_chars,
        )

    def search_documents(
        self,
        *,
        user_identifier: str,
        query: str,
        limit: int = 5,
        document_id: str = "",
        source: str = "",
        tags: list[str] | None = None,
        created_after: str = "",
        created_before: str = "",
        updated_after: str = "",
        updated_before: str = "",
        threshold: float = 0.0,
        explain: bool = False,
    ) -> list[DocumentHit]:
        with self._span(
            "document.search",
            {"user_identifier": user_identifier, "document_id": document_id, "limit": limit},
        ):
            self._require_user(user_identifier)
            query = validate_search_query(query)
            limit = self._clean_limit(limit)
            threshold = validate_threshold(threshold)
            required_tags = set(self._clean_tags(tags))
            created_after_dt = self._parse_filter_datetime(created_after, "created_after")
            created_before_dt = self._parse_filter_datetime(created_before, "created_before")
            updated_after_dt = self._parse_filter_datetime(updated_after, "updated_after")
            updated_before_dt = self._parse_filter_datetime(updated_before, "updated_before")
            embedding = self._embed_text(query, operation="document.search")
            # D-03: adaptive over-fetch-then-filter default -- filtered ANN
            # k-underfills post-filter (spike-confirmed), so both channels
            # over-fetch before the tenant/status/document/metadata filters run.
            over_fetch = max(limit * 4, limit)

            rows_by_id: dict[str, dict[str, Any]] = {}
            semantic_by_id: dict[str, float] = {}

            vector_statement, vector_params = chunk_vector_search_statement(
                embedding=embedding,
                k=over_fetch,
                user_identifier=user_identifier,
                document_id=document_id,
            )
            for row in self._records(
                self._query(
                    vector_statement, operation="document.vector_search", params=vector_params
                )
            ):
                if self._row_is_expired(row, "expires_at"):
                    continue
                chunk_id = str(row.get("id", ""))
                if not chunk_id:
                    continue
                # vectorNeighbors returns a cosine distance (0 = identical);
                # convert to a similarity-style score for blend_hybrid_score.
                semantic_score = max(0.0, 1.0 - float(row.get("distance") or 0.0))
                semantic_by_id[chunk_id] = max(semantic_by_id.get(chunk_id, 0.0), semantic_score)
                rows_by_id[chunk_id] = row

            # Native Lucene full-text channel replaces the old full
            # active-chunk-rows table scan this module used to fall back on
            # for lexical matching (the §1.3 full-scan the port fixes for free).
            lucene_statement, lucene_params = chunk_lucene_search_statement(
                query=query,
                limit=over_fetch,
                user_identifier=user_identifier,
                document_id=document_id,
            )
            for row in self._records(
                self._query(
                    lucene_statement, operation="document.lexical_search", params=lucene_params
                )
            ):
                chunk_id = str(row.get("id", ""))
                if chunk_id and chunk_id not in rows_by_id:
                    rows_by_id[chunk_id] = row

            seeds: list[DocumentHit] = []
            for chunk_id, row in rows_by_id.items():
                if self._row_is_expired(row, "expires_at"):
                    continue
                if not self._row_matches_metadata_filters(
                    row,
                    source=source,
                    required_tags=required_tags,
                    created_after=created_after_dt,
                    created_before=created_before_dt,
                    updated_after=updated_after_dt,
                    updated_before=updated_before_dt,
                ):
                    continue
                semantic_score = semantic_by_id.get(chunk_id, 0.0)
                lexical = lexical_score(
                    query,
                    self._row_search_text(row, text_key="text", metadata_key="metadata_json"),
                )
                final_score = blend_hybrid_score(
                    semantic_score=semantic_score, lexical_score=lexical
                )
                if semantic_score <= 0.0 and lexical <= 0.0:
                    continue
                if not passes_threshold(final_score, threshold):
                    continue
                context = self._chunk_context(chunk_id, user_identifier=user_identifier)
                tags_value = self._json_loads(row.get("tags_json"), [])
                metadata_value = self._json_loads(row.get("metadata_json"), {})
                seeds.append(
                    DocumentHit(
                        chunk_id=chunk_id,
                        document_id=str(row.get("document_id", "")),
                        title=str(row.get("title", "")),
                        locator=str(row.get("locator", "")),
                        text=str(row.get("text", "")),
                        score=final_score,
                        context=context,
                        expires_at=str(row.get("expires_at") or ""),
                        source=str(row.get("source", "")),
                        tags=tags_value if isinstance(tags_value, list) else [],
                        metadata=metadata_value if isinstance(metadata_value, dict) else {},
                        score_details=(
                            build_score_details(
                                semantic_score=semantic_score,
                                lexical_score=lexical,
                                threshold=threshold,
                                final_score=final_score,
                            )
                            if explain
                            else None
                        ),
                    )
                )
            seeds = sorted(seeds, key=lambda item: item.score, reverse=True)[
                : max(limit * 3, limit)
            ]
            return self._rerank_documents(query, seeds)[:limit]
