"""Memory read/update/delete-path mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-01). `_row_is_expired`/`_active_memory_rows`/
`_memory_matches_filters` are also consumed by `store_search.py`'s fused search path and
`store_memory_write.py`'s write path, resolved via the TuringAgentMemory MRO at runtime.

Ported to ArcadeDB (04-05, ARC-04/ARC-05): every query is a bound-param ArcadeDB
SQL `SELECT`/`UPDATE` built in `store_memory_queries.py`; rows come back keyed
by their bare (unqualified) property name (`"id"`, `"expires_at"`, ...) --
ArcadeDB's own projection convention, not the retired Cypher `RETURN m.id`
alias shape (`"m.id"`). `store_search.py`/`store_evidence.py` still read the
old `"m."`-prefixed convention from `_active_memory_rows`/`_memory_from_row`
until their own Wave-4 port (04-07) updates their call sites to match.
`update_memory`'s kind-update no longer sets the legacy synthetic-integer join
property -- the dense `embedding` and both lexical channels
(`lexical_tokens`/`lexical_weights`) are inline record properties updated in
the same bound-param `UPDATE` statement (ARC-05; no separate CSV vector-load
step remains).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from turing_agentmemory_mcp.models import MemoryItem
from turing_agentmemory_mcp.sparse_encoder import sparse_vector
from turing_agentmemory_mcp.sparse_index import SparseDocument, SparseMutation
from turing_agentmemory_mcp.store_memory_queries import (
    memory_delete_statements,
    memory_list_statement,
    memory_select_statement,
    memory_update_statement,
)


class _MemoryReadMixin:
    def get_memory(self, *, user_identifier: str, memory_id: str) -> MemoryItem | None:
        self._require_user(user_identifier)
        if not memory_id.strip():
            raise ValueError("memory_id is required")
        statement, params = memory_select_statement(
            memory_id=memory_id, user_identifier=user_identifier
        )
        rows = self._records(self._query(statement, operation="memory.get", params=params))
        active_rows = [row for row in rows if not self._row_is_expired(row, "expires_at")]
        return self._memory_from_row(active_rows[0]) if active_rows else None

    def list_memories(
        self,
        *,
        user_identifier: str,
        limit: int = 25,
        session_id: str = "",
        memory_types: list[str] | None = None,
        source: str = "",
        tags: list[str] | None = None,
        created_after: str = "",
        created_before: str = "",
        updated_after: str = "",
        updated_before: str = "",
    ) -> list[MemoryItem]:
        self._require_user(user_identifier)
        limit = self._clean_limit(limit)
        created_after_dt = self._parse_filter_datetime(created_after, "created_after")
        created_before_dt = self._parse_filter_datetime(created_before, "created_before")
        updated_after_dt = self._parse_filter_datetime(updated_after, "updated_after")
        updated_before_dt = self._parse_filter_datetime(updated_before, "updated_before")
        rows = self._active_memory_rows(user_identifier)
        items = [
            self._memory_from_row(row)
            for row in rows
            if not self._row_is_expired(row, "expires_at")
        ]
        items = [
            item
            for item in items
            if self._memory_matches_filters(
                item,
                session_id=session_id,
                memory_types=memory_types,
                source=source,
                tags=tags,
                created_after=created_after_dt,
                created_before=created_before_dt,
                updated_after=updated_after_dt,
                updated_before=updated_before_dt,
            )
        ]
        items.sort(key=lambda item: (item.updated_at, item.created_at, item.id), reverse=True)
        return items[:limit]

    def update_memory(
        self,
        *,
        user_identifier: str,
        memory_id: str,
        content: str | None = None,
        kind: str | None = None,
        session_id: str | None = None,
        role: str | None = None,
        source: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
        vector: list[float] | None = None,
        load_vector: bool = True,
    ) -> MemoryItem:
        existing = self.get_memory(user_identifier=user_identifier, memory_id=memory_id)
        if existing is None:
            raise ValueError(f"memory {memory_id} not found")
        if self.memory_extractor is not None and existing.kind == "message":
            requested = {
                "content": content,
                "kind": kind,
                "session_id": session_id,
                "role": role,
                "source": source,
                "tags": tags,
                "metadata": metadata,
                "expires_at": expires_at,
            }
            if any(value is not None for value in requested.values()):
                raise ValueError(f"immutable temporal episode cannot be changed: {memory_id}")
        next_content = existing.content if content is None else content
        if not next_content.strip():
            raise ValueError("content is required")
        next_kind = existing.kind if kind is None else kind
        next_session_id = existing.session_id if session_id is None else session_id
        next_role = existing.role if role is None else role
        next_source = existing.source if source is None else source
        next_tags = existing.tags if tags is None else self._clean_tags(tags)
        next_metadata = existing.metadata if metadata is None else dict(metadata)
        next_expires_at = existing.expires_at if expires_at is None else expires_at
        if content is not None:
            next_content, next_metadata = self._process_text_for_storage(
                next_content, next_metadata
            )
        updated_at = self._now_iso()
        content_changed = next_content != existing.content
        embedding = None
        if load_vector and content_changed:
            embedding = (
                vector
                if vector is not None
                else self._embed_text(next_content, operation="memory.update")
            )
        lexical_tokens, lexical_weights = sparse_vector(next_content)
        sparse_batch_id = None
        if self.sparse_index is not None:
            sparse_batch_id = self.sparse_index.prepare(
                [
                    SparseMutation.upsert(
                        SparseDocument(
                            doc_key=self._sparse_doc_key(
                                user_identifier,
                                self._sparse_kind(next_kind),
                                memory_id,
                            ),
                            user_identifier=user_identifier,
                            source_id=memory_id,
                            kind=self._sparse_kind(next_kind),
                            content=next_content,
                            source=next_source,
                            session_id=next_session_id,
                            created_at=existing.created_at,
                            expires_at=next_expires_at,
                        )
                    )
                ]
            )
        statement = memory_update_statement(
            memory_id=memory_id,
            user_identifier=user_identifier,
            kind=next_kind,
            content=next_content,
            session_id=next_session_id,
            role=next_role,
            source=next_source,
            tags_json=self._json_dumps(next_tags),
            metadata_json=self._json_dumps(next_metadata),
            expires_at=next_expires_at,
            updated_at=updated_at,
            lexical_tokens=lexical_tokens,
            lexical_weights=lexical_weights,
            embedding=embedding,
        )
        try:
            self._write_many([statement])
        except Exception:
            if sparse_batch_id is not None and self.sparse_index is not None:
                self.sparse_index.discard_prepared(sparse_batch_id)
            raise
        if sparse_batch_id is not None and self.sparse_index is not None:
            self.sparse_index.commit_batch(sparse_batch_id)
            self.sparse_index.replay(batch_id=sparse_batch_id)
        item = MemoryItem(
            id=memory_id,
            user_identifier=user_identifier,
            kind=next_kind,
            content=next_content,
            session_id=next_session_id,
            role=next_role,
            score=1.0,
            created_at=existing.created_at,
            updated_at=updated_at,
            expires_at=next_expires_at,
            source=next_source,
            tags=next_tags,
            metadata=next_metadata,
        )
        self._audit(
            operation="memory.update",
            user_identifier=user_identifier,
            resource_type="memory",
            resource_id=memory_id,
        )
        return item

    def delete_memory(self, *, user_identifier: str, memory_id: str) -> dict[str, object]:
        existing = self.get_memory(user_identifier=user_identifier, memory_id=memory_id)
        if existing is None:
            return {"memory_id": memory_id, "deleted": False}
        updated_at = self._now_iso()
        fact_ids = self._fact_ids_for_memory(user_identifier, memory_id)
        sparse_batch_id = None
        if self.sparse_index is not None:
            sparse_batch_id = self.sparse_index.prepare(
                [
                    SparseMutation.delete(
                        self._sparse_doc_key(user_identifier, "episode", memory_id)
                    ),
                    *[
                        SparseMutation.delete(
                            self._sparse_doc_key(user_identifier, "fact", fact_id)
                        )
                        for fact_id in fact_ids
                    ],
                ]
            )
        statements = memory_delete_statements(
            memory_id=memory_id,
            user_identifier=user_identifier,
            fact_ids=fact_ids,
            updated_at=updated_at,
        )
        try:
            self._write_many(statements)
        except Exception:
            if sparse_batch_id is not None and self.sparse_index is not None:
                self.sparse_index.discard_prepared(sparse_batch_id)
            raise
        if sparse_batch_id is not None and self.sparse_index is not None:
            self.sparse_index.commit_batch(sparse_batch_id)
            self.sparse_index.replay(batch_id=sparse_batch_id)
        self._audit(
            operation="memory.delete",
            user_identifier=user_identifier,
            resource_type="memory",
            resource_id=memory_id,
        )
        return {"memory_id": memory_id, "deleted": True, "updated_at": updated_at}

    def _memory_from_row(self, row: dict[str, Any], *, score: float = 1.0) -> MemoryItem:
        tags = self._json_loads(row.get("tags_json"), [])
        metadata = self._json_loads(row.get("metadata_json"), {})
        created_at = str(row.get("created_at") or "")
        return MemoryItem(
            id=str(row.get("id", "")),
            user_identifier=str(row.get("user_identifier", "")),
            kind=str(row.get("kind", "")),
            content=str(row.get("content", "")),
            session_id=str(row.get("session_id", "")),
            role=str(row.get("role", "")),
            score=score,
            created_at=created_at,
            updated_at=str(row.get("updated_at") or created_at),
            expires_at=str(row.get("expires_at") or ""),
            source=str(row.get("source", "")),
            tags=tags if isinstance(tags, list) else [],
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    def _row_is_expired(self, row: dict[str, Any], key: str) -> bool:
        return self._is_expired(str(row.get(key) or ""))

    def _memory_matches_filters(
        self,
        item: MemoryItem,
        *,
        session_id: str = "",
        memory_types: list[str] | None = None,
        source: str = "",
        tags: list[str] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
    ) -> bool:
        allowed = set(memory_types or [])
        required_tags = set(self._clean_tags(tags))
        if session_id and item.session_id != session_id:
            return False
        if allowed and item.kind not in allowed:
            return False
        if source and item.source != source:
            return False
        if required_tags and not required_tags <= set(item.tags):
            return False
        if not self._timestamp_in_range(
            item.created_at,
            after=created_after,
            before=created_before,
        ):
            return False
        return self._timestamp_in_range(
            item.updated_at,
            after=updated_after,
            before=updated_before,
        )

    def _row_matches_metadata_filters(
        self,
        row: dict[str, Any],
        *,
        prefix: str = "",
        source: str = "",
        required_tags: set[str] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
    ) -> bool:
        # `prefix=""` (the default, ArcadeDB's bare unqualified row-key
        # convention -- store_documents.py, 04-06) reads e.g. "source"
        # directly; a non-empty `prefix` (the retired Cypher `RETURN c.source`
        # alias shape) reads "c.source" -- kept for any still-unported caller.
        def key(name: str) -> str:
            return f"{prefix}.{name}" if prefix else name

        if source and str(row.get(key("source"), "")) != source:
            return False
        tags = self._json_loads(row.get(key("tags_json")), [])
        if required_tags and not required_tags <= set(tags if isinstance(tags, list) else []):
            return False
        if not self._timestamp_in_range(
            str(row.get(key("created_at")) or ""),
            after=created_after,
            before=created_before,
        ):
            return False
        return self._timestamp_in_range(
            str(row.get(key("updated_at")) or ""),
            after=updated_after,
            before=updated_before,
        )

    def _active_memory_rows(self, user_identifier: str) -> list[dict[str, Any]]:
        statement, params = memory_list_statement(user_identifier=user_identifier)
        return self._records(self._query(statement, operation="memory.active_rows", params=params))

    @staticmethod
    def _clean_limit(limit: int) -> int:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return min(limit, 200)

    @staticmethod
    def _clean_tags(tags: list[str] | None) -> list[str]:
        clean: list[str] = []
        seen: set[str] = set()
        for tag in tags or []:
            value = str(tag).strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            clean.append(value[:80])
        return clean[:20]
