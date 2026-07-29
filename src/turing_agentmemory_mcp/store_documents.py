"""Document read/search/lifecycle mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-02). `_active_chunk_rows` and
`_document_chunk_batch_query` live in store_chunking.py (moved there in 01-01 per
the RESEARCH.md sub-split note); `_rerank_documents`/`_reranked_score_details`
live in store_search.py — both keep this module under the 600-LOC cap.

The ingest write path lives in store_documents_ingest.py (phase 07.1-02).

Ported to ArcadeDB (04-06, ARC-04/ARC-05/ARC-06/PERF-01): document + chunk
ingest builds a flat list of bound-param `Statement`s (`store_documents_queries.py`)
committed in ONE managed transaction via `store_core.py`'s `_write_many` (D-08)
-- the batch mechanism is that single managed transaction, with no separate
byte-budget batch splitter needed (`store_core.py`'s docstring). Every Chunk's
`id` is `ids.stable_id()` (ARC-08);
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
from turing_agentmemory_mcp.models import DocumentHit, IngestedDocument
from turing_agentmemory_mcp.search_controls import (
    build_score_details,
    passes_threshold,
    validate_search_query,
    validate_threshold,
)
from turing_agentmemory_mcp.store_documents_queries import (
    chunk_delete_statement,
    chunk_lucene_search_statement,
    chunk_vector_search_statement,
    document_delete_statement,
    document_select_statement,
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
        self._require_user(user_identifier)
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

    def delete_document(self, *, user_identifier: str, document_id: str) -> dict[str, object]:
        self._require_user(user_identifier)
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
        self._require_user(user_identifier)
        # user_identifier deliberately omitted -- see ingest_document_text's
        # comment above (ARC-07/D-07 central sanitizer is the backstop).
        with self._span(
            "document.search",
            {"document_id": document_id, "limit": limit},
        ):
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
