"""Legacy SQLite-FTS5 sparse-index outbox rebuild mixin for TuringAgentMemory.

Split out of `store_rebuild.py` (04-08) purely to keep that file under the
600-LOC cap while porting its vector-projection/community-graph rebuild to
ArcadeDB -- this module itself is NOT part of that port. `rebuild_sparse_
projection`/`_canonical_sparse_documents`/`_prepare_sparse_projection` are
deliberately left Cypher-shaped here, matching 04-05-SUMMARY.md's explicit
precedent that the legacy SQLite `sparse_index.py` outbox is a separate,
later concern (ARC-06's bootstrap-time outbox retirement), out of scope for
ARC-04/ARC-05/INFRA-03. `_sparse_doc_key`/`_sparse_kind` are shared with
`store_rebuild.py`'s (ArcadeDB-ported) `rebuild_communities`, resolved at
runtime through `TuringAgentMemory`'s mixin MRO.
"""

from __future__ import annotations

from typing import Any

from turing_agentmemory_mcp.sparse_index import SparseDocument, SparseMutation
from turing_agentmemory_mcp.temporal_graph import EntityProjection, TemporalProjection


class _RebuildSparseMixin:
    def _prepare_sparse_projection(
        self,
        *,
        user_identifier: str,
        payloads: list[dict[str, object]],
        projections: list[TemporalProjection],
        entities: list[EntityProjection],
    ) -> str | None:
        if self.sparse_index is None or not payloads:
            return None
        payload_by_memory_id = {str(payload["memory_id"]): payload for payload in payloads}
        mutations: list[SparseMutation] = []
        for payload in payloads:
            source_id = str(payload["memory_id"])
            mutations.append(
                SparseMutation.upsert(
                    SparseDocument(
                        doc_key=self._sparse_doc_key(user_identifier, "episode", source_id),
                        user_identifier=user_identifier,
                        source_id=source_id,
                        kind="episode",
                        content=str(payload["content"]),
                        source=str(payload["source"]),
                        session_id=str(payload["session_id"]),
                        created_at=str(payload["created_at"]),
                        expires_at=str(payload["expires_at"]),
                    )
                )
            )
        for entity in entities:
            source_payload = payload_by_memory_id.get(entity.source_memory_id, {})
            mutations.append(
                SparseMutation.upsert(
                    SparseDocument(
                        doc_key=self._sparse_doc_key(user_identifier, "entity", entity.id),
                        user_identifier=user_identifier,
                        source_id=entity.id,
                        kind="entity",
                        content=entity.content,
                        source=str(source_payload.get("source") or ""),
                        session_id=str(source_payload.get("session_id") or ""),
                        created_at=entity.observed_at,
                        expires_at=entity.expires_at,
                    )
                )
            )
        for projection in projections:
            for fact in projection.facts:
                mutations.append(
                    SparseMutation.upsert(
                        SparseDocument(
                            doc_key=self._sparse_doc_key(user_identifier, "fact", fact.id),
                            user_identifier=user_identifier,
                            source_id=fact.id,
                            kind="fact",
                            content=fact.content,
                            source=fact.source,
                            session_id=fact.session_id,
                            created_at=fact.observed_at,
                            expires_at=fact.expires_at,
                        )
                    )
                )
        return self.sparse_index.prepare(mutations)

    @staticmethod
    def _sparse_doc_key(user_identifier: str, kind: str, source_id: str) -> str:
        return f"{user_identifier}:{kind}:{source_id}"

    @staticmethod
    def _sparse_kind(memory_kind: str) -> str:
        return "episode" if memory_kind == "message" else memory_kind

    def rebuild_sparse_projection(self) -> dict[str, object]:
        if self.sparse_index is None:
            raise RuntimeError("sparse projection is not configured")
        documents = self._canonical_sparse_documents()
        self.sparse_index.rebuild(documents)
        return self.sparse_index.status()

    def _canonical_sparse_documents(self) -> list[SparseDocument]:
        documents: list[SparseDocument] = []
        memory_rows = self._sparse_rebuild_rows(
            "Memory",
            'MATCH (m:Memory) WHERE m.status = "active" '
            "RETURN m.id, m.user_identifier, m.kind, m.content, m.source, m.session_id, "
            "m.created_at, m.expires_at",
            "sparse.rebuild.memory",
        )
        for row in memory_rows:
            source_id = str(row.get("m.id") or "")
            user_identifier = str(row.get("m.user_identifier") or "")
            kind = self._sparse_kind(str(row.get("m.kind") or "memory"))
            content = str(row.get("m.content") or "")
            if not source_id or not user_identifier or not content:
                continue
            documents.append(
                SparseDocument(
                    doc_key=self._sparse_doc_key(user_identifier, kind, source_id),
                    user_identifier=user_identifier,
                    source_id=source_id,
                    kind=kind,
                    content=content,
                    source=str(row.get("m.source") or ""),
                    session_id=str(row.get("m.session_id") or ""),
                    created_at=str(row.get("m.created_at") or ""),
                    expires_at=str(row.get("m.expires_at") or ""),
                )
            )
        for label, variable, kind, operation in (
            ("Entity", "e", "entity", "sparse.rebuild.entity"),
            ("Fact", "f", "fact", "sparse.rebuild.fact"),
            ("Community", "c", "community", "sparse.rebuild.community"),
        ):
            rows = self._sparse_rebuild_rows(
                label,
                f'MATCH ({variable}:{label}) WHERE {variable}.status = "active" '
                f"RETURN {variable}.id, {variable}.user_identifier, {variable}.content, "
                f"{variable}.source, {variable}.session_id, "
                f"{variable}.observed_at, {variable}.created_at, {variable}.expires_at",
                operation,
            )
            for row in rows:
                source_id = str(row.get(f"{variable}.id") or "")
                user_identifier = str(row.get(f"{variable}.user_identifier") or "")
                content = str(row.get(f"{variable}.content") or "")
                if not source_id or not user_identifier or not content:
                    continue
                created_at = str(
                    row.get(f"{variable}.observed_at") or row.get(f"{variable}.created_at") or ""
                )
                documents.append(
                    SparseDocument(
                        doc_key=self._sparse_doc_key(user_identifier, kind, source_id),
                        user_identifier=user_identifier,
                        source_id=source_id,
                        kind=kind,
                        content=content,
                        source=str(row.get(f"{variable}.source") or ""),
                        session_id=str(row.get(f"{variable}.session_id") or ""),
                        created_at=created_at,
                        expires_at=str(row.get(f"{variable}.expires_at") or ""),
                    )
                )
        return documents

    def _sparse_rebuild_rows(
        self,
        label: str,
        query: str,
        operation: str,
    ) -> list[dict[str, Any]]:
        # Legacy SQLite-sparse-index outbox path only -- still Cypher-shaped,
        # deliberately untouched (see module docstring). Kept defensive since
        # this path is not covered by the ArcadeDB schema bootstrap guarantee
        # the ported queries in store_rebuild.py now rely on.
        try:
            return self._records(self._query(query, operation=operation))
        except Exception as exc:
            if f"Unknown label: {label}" not in str(exc):
                raise
            return []
