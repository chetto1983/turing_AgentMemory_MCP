"""Pure/value helper mixin for TuringAgentMemory: IDs, vectors, datetime, text redaction.

Split out of store.py (D-08/D-09, phase 01-01). No instance state is defined here — all
these helpers operate on parameters or on `self.<attr>` assigned in `_StoreCore.__init__`
and resolved via the TuringAgentMemory MRO at runtime.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from turing_agentmemory_mcp.entity_extraction import ProcessedText, entity_metadata_search_text
from turing_agentmemory_mcp.ids import cypher_var, quote, vector_id
from turing_agentmemory_mcp.models import MemoryItem
from turing_agentmemory_mcp.temporal_graph import EdgeProjection


class _UtilsMixin:
    @classmethod
    def _projection_edge_literals(cls, edges: tuple[EdgeProjection, ...]) -> list[str]:
        literals: list[str] = []
        for edge in edges:
            source_var = cypher_var(edge.source_id)
            target_var = cypher_var(edge.target_id)
            properties = {"id": edge.id, **edge.properties}
            property_text = ", ".join(
                f'{cypher_var(name)}: {cls._cypher_value(value)}'
                for name, value in properties.items()
            )
            literals.append(
                f"({source_var})-[:{edge.kind} {{{property_text}}}]->({target_var})"
            )
        return literals

    @staticmethod
    def _cypher_value(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return f'"{quote(str(value))}"'

    def _process_text_for_storage(
        self,
        text: str,
        metadata: dict[str, object] | None,
    ) -> tuple[str, dict[str, object]]:
        return self._process_texts_for_storage([(text, dict(metadata or {}))])[0]

    def _process_texts_for_storage(
        self,
        rows: list[tuple[str, dict[str, object]]],
    ) -> list[tuple[str, dict[str, object]]]:
        if not rows:
            return []
        redacted_rows = [self._redact_for_storage(text, metadata) for text, metadata in rows]
        texts = [text for text, _ in redacted_rows]
        process_many = getattr(self.entity_processor, "process_many", None)
        processed = (
            process_many(texts)
            if callable(process_many)
            else [self.entity_processor.process(text) for text in texts]
        )
        if not isinstance(processed, list) or len(processed) != len(rows):
            count = len(processed) if isinstance(processed, list) else 0
            raise RuntimeError(f"entity processor returned {count} results for {len(rows)} inputs")
        if not all(isinstance(item, ProcessedText) for item in processed):
            raise RuntimeError("entity processor returned an invalid result")
        return [
            self._merge_entity_metadata(item, metadata)
            for item, (_, metadata) in zip(processed, redacted_rows, strict=True)
        ]

    def _redact_for_storage(
        self,
        text: str,
        metadata: dict[str, object],
    ) -> tuple[str, dict[str, object]]:
        clean_metadata = dict(metadata or {})
        redacted = self.redactor.redact(text)
        if redacted.metadata:
            clean_metadata.update(redacted.metadata)
        return redacted.text, clean_metadata

    def _merge_entity_metadata(
        self,
        processed: ProcessedText,
        metadata: dict[str, object],
    ) -> tuple[str, dict[str, object]]:
        clean_metadata = dict(metadata)
        if processed.metadata:
            clean_metadata.update(processed.metadata)
        else:
            for key in getattr(self.entity_processor, "metadata_keys", ()):
                clean_metadata.pop(str(key), None)
        return processed.text, clean_metadata

    def _row_search_text(self, row: dict[str, Any], *, text_key: str, metadata_key: str) -> str:
        text = str(row.get(text_key, ""))
        metadata = self._json_loads(row.get(metadata_key), {})
        if isinstance(metadata, dict):
            extra = entity_metadata_search_text(metadata)
            if extra:
                return f"{text}\n{extra}"
        return text

    def _embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._span(
            "embed",
            {"count": len(texts), "dimensions": self.dimensions, "operation": "batch"},
        ):
            embed_documents = getattr(self.embedder, "embed_documents", None)
            if callable(embed_documents):
                return embed_documents(texts)
            embed_many = getattr(self.embedder, "embed_many", None)
            if callable(embed_many):
                return embed_many(texts)
            return [self.embedder.embed(text) for text in texts]

    def _embed_text(self, text: str, *, operation: str) -> list[float]:
        with self._span(
            "embed",
            {"count": 1, "dimensions": self.dimensions, "operation": operation},
        ):
            if operation in {"memory.search", "document.search"}:
                embed_query = getattr(self.embedder, "embed_query", None)
                if callable(embed_query):
                    return embed_query(text)
            else:
                embed_documents = getattr(self.embedder, "embed_documents", None)
                if callable(embed_documents):
                    return embed_documents([text])[0]
            return self.embedder.embed(text)

    @staticmethod
    def _vector_literal(vec: list[float]) -> str:
        return "(" + ", ".join(f"{value:.8f}" for value in vec) + ")"

    @staticmethod
    def _is_expired(expires_at: str) -> bool:
        if not expires_at.strip():
            return False
        try:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return expires <= datetime.now(UTC)

    @classmethod
    def _parse_filter_datetime(cls, value: str, field_name: str) -> datetime | None:
        if not value.strip():
            return None
        parsed = cls._parse_datetime(value)
        if parsed is None:
            raise ValueError(f"{field_name} must be an ISO-8601 timestamp")
        return parsed

    @classmethod
    def _timestamp_in_range(
        cls,
        value: str,
        *,
        after: datetime | None,
        before: datetime | None,
    ) -> bool:
        if after is None and before is None:
            return True
        parsed = cls._parse_datetime(value)
        if parsed is None:
            return False
        if after is not None and parsed < after:
            return False
        return before is None or parsed <= before

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        if not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    @staticmethod
    def _int_value(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _memory_vector_id(user_identifier: str, memory_id: str) -> int:
        return vector_id("memory", f"{user_identifier}:{memory_id}")

    @staticmethod
    def _entity_vector_id(user_identifier: str, entity_id: str) -> int:
        return vector_id("entity", f"{user_identifier}:{entity_id}")

    @staticmethod
    def _fact_vector_id(user_identifier: str, fact_id: str) -> int:
        return vector_id("fact", f"{user_identifier}:{fact_id}")

    @staticmethod
    def _community_vector_id(user_identifier: str, community_id: str) -> int:
        return vector_id("community", f"{user_identifier}:{community_id}")

    @staticmethod
    def _document_vector_id(user_identifier: str, chunk_id: str) -> int:
        return vector_id("chunk", f"{user_identifier}:{chunk_id}")

    @staticmethod
    def _document_text_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _batch_payload_key(self, payload: dict[str, object]) -> tuple[object, ...]:
        return (
            payload.get("session_id", ""),
            payload.get("role", ""),
            payload.get("content", ""),
            payload.get("source", ""),
            self._json_dumps(payload.get("tags") or []),
            self._json_dumps(payload.get("metadata") or {}),
            payload.get("expires_at", ""),
        )

    def _memory_matches_payload(
        self,
        item: MemoryItem,
        payload: dict[str, object],
    ) -> bool:
        return self._batch_payload_key(payload) == (
            item.session_id,
            item.role,
            item.content,
            item.source,
            self._json_dumps(item.tags),
            self._json_dumps(item.metadata),
            item.expires_at,
        )
