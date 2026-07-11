"""Document ingest/search/lifecycle mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-02). `_active_chunk_rows` and
`_document_chunk_batch_query` live in store_chunking.py (moved there in 01-01 per
the RESEARCH.md sub-split note); `_rerank_documents`/`_reranked_score_details`
live in store_search.py — both keep this module under the 600-LOC cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from turing_agentmemory_mcp.hybrid import blend_hybrid_score, lexical_score
from turing_agentmemory_mcp.ids import cypher_var, quote, stable_id
from turing_agentmemory_mcp.models import DocumentHit, IngestedDocument
from turing_agentmemory_mcp.search_controls import (
    build_score_details,
    passes_threshold,
    validate_search_query,
    validate_threshold,
)


@dataclass(frozen=True)
class _DocumentChunkGraphUnit:
    chunk_id: str
    chunk_var: str
    node: str
    has_chunk_edge: str
    previous_chunk_id: str = ""
    previous_var: str = ""
    next_chunk_edge: str = ""


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
            {"user_identifier": user_identifier, "document_id": document_id or "", "source": source},
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
        try:
            rows = self._records(
                self._query(
                    f'MATCH (d:Document) WHERE d.id = "{quote(document_id)}" '
                    f'AND d.user_identifier = "{quote(user_identifier)}" AND d.status = "searchable" '
                    "RETURN d.id, d.user_identifier, d.title, d.chunk_count, d.created_at, "
                    "d.updated_at, d.expires_at, d.source, d.tags_json, d.metadata_json, "
                    "d.text_hash, d.chunk_chars",
                    operation="document.get",
                )
            )
        except Exception as exc:
            if "Unknown label: Document" not in str(exc):
                raise
            return None
        matching_rows = [
            row
            for row in rows
            if str(row.get("d.id", "")) == document_id and not self._row_is_expired(row, "d.expires_at")
        ]
        return self._document_from_row(matching_rows[0]) if matching_rows else None

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
            if existing is not None:
                self.delete_document(user_identifier=user_identifier, document_id=document_id)
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
                expires_at=expires_at if expires_at is not None else existing.expires_at if existing is not None else "",
                created_at=existing.created_at if existing is not None else None,
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
        self._write(
            f'MATCH (d:Document) WHERE d.id = "{quote(document_id)}" '
            f'AND d.user_identifier = "{quote(user_identifier)}" '
            f'SET d.status = "deleted", d.updated_at = "{quote(updated_at)}"'
        )
        self._write(
            f'MATCH (c:Chunk) WHERE c.document_id = "{quote(document_id)}" '
            f'AND c.user_identifier = "{quote(user_identifier)}" '
            f'SET c.status = "deleted", c.updated_at = "{quote(updated_at)}"'
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
    ) -> IngestedDocument:
        self._ensure_user(user_identifier)
        doc_var = cypher_var(document_id)
        created_at = created_at or self._now_iso()
        updated_at = self._now_iso()
        clean_tags = self._clean_tags(tags)
        clean_metadata = dict(metadata or {})
        document_node = (
            f'({doc_var}:Document {{id: "{quote(document_id)}", user_identifier: "{quote(user_identifier)}", '
            f'title: "{quote(title)}", chunk_count: {len(chunks)}, chunk_chars: {chunk_chars}, '
            f'text_hash: "{quote(text_hash)}", source: "{quote(source)}", '
            f'tags_json: "{quote(self._json_dumps(clean_tags))}", '
            f'metadata_json: "{quote(self._json_dumps(clean_metadata))}", '
            f'created_at: "{quote(created_at)}", updated_at: "{quote(updated_at)}", '
            f'expires_at: "{quote(expires_at)}", status: "searchable"}})'
        )
        user_document_edge = f"(u)-[:HAS_DOCUMENT]->({doc_var})"
        chunk_units: list[_DocumentChunkGraphUnit] = []
        vector_rows: list[tuple[int, list[float]]] = []
        vectors = self._embed_many(chunks)
        previous_chunk_id = ""
        previous_var = ""
        for idx, (chunk_text, vector) in enumerate(zip(chunks, vectors, strict=True), start=1):
            chunk_id = f"{document_id}#{idx}"
            chunk_var = cypher_var(chunk_id)
            vid = self._document_vector_id(user_identifier, chunk_id)
            locator = f"chunk={idx}"
            node = (
                f'({chunk_var}:Chunk {{chunk_id: "{quote(chunk_id)}", vector_id: {vid}, '
                f'document_id: "{quote(document_id)}", user_identifier: "{quote(user_identifier)}", '
                f'title: "{quote(title)}", ordinal: {idx}, locator: "{locator}", '
                f'source: "{quote(source)}", tags_json: "{quote(self._json_dumps(clean_tags))}", '
                f'metadata_json: "{quote(self._json_dumps(clean_metadata))}", '
                f'created_at: "{quote(created_at)}", updated_at: "{quote(updated_at)}", '
                f'expires_at: "{quote(expires_at)}", status: "active", text: "{quote(chunk_text)}"}})'
            )
            has_chunk_edge = f"({doc_var})-[:HAS_CHUNK {{ordinal: {idx}}}]->({chunk_var})"
            next_chunk_edge = (
                f"({previous_var})-[:NEXT_CHUNK]->({chunk_var})" if previous_var else ""
            )
            chunk_units.append(
                _DocumentChunkGraphUnit(
                    chunk_id=chunk_id,
                    chunk_var=chunk_var,
                    node=node,
                    has_chunk_edge=has_chunk_edge,
                    previous_chunk_id=previous_chunk_id,
                    previous_var=previous_var,
                    next_chunk_edge=next_chunk_edge,
                )
            )
            previous_chunk_id = chunk_id
            previous_var = chunk_var
            vector_rows.append((vid, vector))
        graph_queries = self._document_graph_queries(
            user_identifier=user_identifier,
            document_id=document_id,
            doc_var=doc_var,
            document_node=document_node,
            user_document_edge=user_document_edge,
            chunk_units=chunk_units,
        )
        if len(graph_queries) == 1:
            self._write(graph_queries[0])
        else:
            self._write_many(graph_queries)
        self._load_vectors(
            self._tenant_vector_index(self.document_index, user_identifier),
            vector_rows,
            f"document_{document_id}",
        )
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

    def _document_graph_queries(
        self,
        *,
        user_identifier: str,
        document_id: str,
        doc_var: str,
        document_node: str,
        user_document_edge: str,
        chunk_units: list[_DocumentChunkGraphUnit],
    ) -> list[str]:
        user_match = f'MATCH (u:User) WHERE u.identifier = "{quote(user_identifier)}"'
        all_literals = [document_node, *(unit.node for unit in chunk_units), user_document_edge]
        for unit in chunk_units:
            all_literals.append(unit.has_chunk_edge)
            if unit.next_chunk_edge:
                all_literals.append(unit.next_chunk_edge)
        combined = f"{user_match} CREATE " + ", ".join(all_literals)
        if len(combined.encode("utf-8")) <= self.document_graph_batch_bytes:
            return [combined]

        document_query = f"{user_match} CREATE {document_node}, {user_document_edge}"
        if len(document_query.encode("utf-8")) > self.document_graph_batch_bytes:
            raise ValueError(
                "document metadata exceeds AGENTMEMORY_DOCUMENT_GRAPH_BATCH_BYTES"
            )

        queries = [document_query]
        batch: list[_DocumentChunkGraphUnit] = []
        for unit in chunk_units:
            candidate = [*batch, unit]
            candidate_query = self._document_chunk_batch_query(
                user_identifier=user_identifier,
                document_id=document_id,
                doc_var=doc_var,
                units=candidate,
            )
            exceeds_limit = len(candidate_query.encode("utf-8")) > self.document_graph_batch_bytes
            exceeds_count = len(candidate) > self.document_graph_batch_chunks
            if batch and (exceeds_limit or exceeds_count):
                queries.append(
                    self._document_chunk_batch_query(
                        user_identifier=user_identifier,
                        document_id=document_id,
                        doc_var=doc_var,
                        units=batch,
                    )
                )
                batch = [unit]
                candidate_query = self._document_chunk_batch_query(
                    user_identifier=user_identifier,
                    document_id=document_id,
                    doc_var=doc_var,
                    units=batch,
                )
            else:
                batch = candidate
            if len(candidate_query.encode("utf-8")) > self.document_graph_batch_bytes:
                raise ValueError(
                    f"document chunk {unit.chunk_id} exceeds "
                    "AGENTMEMORY_DOCUMENT_GRAPH_BATCH_BYTES"
                )
        if batch:
            queries.append(
                self._document_chunk_batch_query(
                    user_identifier=user_identifier,
                    document_id=document_id,
                    doc_var=doc_var,
                    units=batch,
                )
            )
        return queries

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
        self._write(
            f'MATCH (d:Document) WHERE d.id = "{quote(document_id)}" '
            f'AND d.user_identifier = "{quote(user_identifier)}" AND d.status = "searchable" '
            f'SET d.title = "{quote(title)}", d.source = "{quote(next_source)}", '
            f'd.tags_json = "{quote(self._json_dumps(next_tags))}", '
            f'd.metadata_json = "{quote(self._json_dumps(next_metadata))}", '
            f'd.expires_at = "{quote(next_expires_at)}", '
            f'd.updated_at = "{quote(updated_at)}"'
        )
        self._write(
            f'MATCH (c:Chunk) WHERE c.document_id = "{quote(document_id)}" '
            f'AND c.user_identifier = "{quote(user_identifier)}" AND c.status = "active" '
            f'SET c.title = "{quote(title)}", c.source = "{quote(next_source)}", '
            f'c.tags_json = "{quote(self._json_dumps(next_tags))}", '
            f'c.metadata_json = "{quote(self._json_dumps(next_metadata))}", '
            f'c.expires_at = "{quote(next_expires_at)}", '
            f'c.updated_at = "{quote(updated_at)}"'
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
            literal = self._vector_literal(self._embed_text(query, operation="document.search"))
            document_filter = ""
            if document_id:
                document_filter = f' AND c.document_id = "{quote(document_id)}"'
            document_index = self._ensure_tenant_vector_index(
                self.document_index, user_identifier
            )
            try:
                vector_rows = self._records(
                    self._query(
                        f"VECTOR SEARCH IN {document_index} FOR {max(limit * 4, limit)} {literal} "
                        f"YIELD ids, score MATCH (c:Chunk) "
                        f'WHERE c.vector_id = ids AND c.user_identifier = "{quote(user_identifier)}" '
                        f'AND c.status = "active"{document_filter} '
                        "RETURN c.chunk_id, c.document_id, c.title, c.locator, c.text, c.vector_id, "
                        "c.created_at, c.updated_at, c.expires_at, c.source, "
                        "c.tags_json, c.metadata_json, score",
                        operation="document.vector_search",
                    )
                )
            except Exception as exc:
                if "Unknown label: Chunk" not in str(exc):
                    raise
                return []
            rows_by_id: dict[str, dict[str, Any]] = {}
            semantic_by_id: dict[str, float] = {}
            for row in vector_rows:
                if self._row_is_expired(row, "c.expires_at"):
                    continue
                chunk_id = str(row.get("c.chunk_id", ""))
                if not chunk_id:
                    continue
                semantic_by_id[chunk_id] = max(
                    semantic_by_id.get(chunk_id, 0.0),
                    float(row.get("score") or 0.0),
                )
                rows_by_id[chunk_id] = row
            for row in self._active_chunk_rows(user_identifier, document_id=document_id):
                chunk_id = str(row.get("c.chunk_id", ""))
                if chunk_id and chunk_id not in rows_by_id:
                    rows_by_id[chunk_id] = row

            seeds: list[DocumentHit] = []
            for chunk_id, row in rows_by_id.items():
                if self._row_is_expired(row, "c.expires_at"):
                    continue
                if not self._row_matches_metadata_filters(
                    row,
                    prefix="c",
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
                    self._row_search_text(row, text_key="c.text", metadata_key="c.metadata_json"),
                )
                final_score = blend_hybrid_score(semantic_score=semantic_score, lexical_score=lexical)
                if semantic_score <= 0.0 and lexical <= 0.0:
                    continue
                if not passes_threshold(final_score, threshold):
                    continue
                context = self._chunk_context(int(row.get("c.vector_id") or 0))
                tags = self._json_loads(row.get("c.tags_json"), [])
                metadata = self._json_loads(row.get("c.metadata_json"), {})
                seeds.append(
                    DocumentHit(
                        chunk_id=str(row.get("c.chunk_id", "")),
                        document_id=str(row.get("c.document_id", "")),
                        title=str(row.get("c.title", "")),
                        locator=str(row.get("c.locator", "")),
                        text=str(row.get("c.text", "")),
                        score=final_score,
                        context=context,
                        expires_at=str(row.get("c.expires_at") or ""),
                        source=str(row.get("c.source", "")),
                        tags=tags if isinstance(tags, list) else [],
                        metadata=metadata if isinstance(metadata, dict) else {},
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
