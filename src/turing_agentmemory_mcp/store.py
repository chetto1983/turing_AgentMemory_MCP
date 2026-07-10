from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from turingdb import TuringDB

from turing_agentmemory_mcp.embeddings import Embedder, OpenAICompatibleEmbedder
from turing_agentmemory_mcp.entity_extraction import (
    EntityProcessor,
    ProcessedText,
    entity_metadata_search_text,
    entity_processor_from_env,
)
from turing_agentmemory_mcp.governance import (
    AuditSink,
    Redactor,
    audit_event,
    audit_sink_from_env,
    redactor_from_env,
)
from turing_agentmemory_mcp.hybrid import blend_hybrid_score, lexical_score
from turing_agentmemory_mcp.ids import cypher_var, quote, stable_id, vector_id
from turing_agentmemory_mcp.models import DocumentHit, IngestedDocument, MemoryItem
from turing_agentmemory_mcp.observability import SpanRecorder, span_recorder_from_env
from turing_agentmemory_mcp.provider_config import provider_env
from turing_agentmemory_mcp.rerank import OpenAICompatibleReranker, apply_rerank_guard
from turing_agentmemory_mcp.search_controls import (
    build_score_details,
    passes_threshold,
    validate_search_query,
    validate_threshold,
)

_MISSING = object()


class TuringAgentMemory:
    def __init__(
        self,
        client: TuringDB,
        *,
        turing_home: str | Path,
        graph: str = "agent_memory",
        dimensions: int = 768,
        memory_index: str = "agent_memory_vectors",
        document_index: str = "document_chunk_vectors",
        embedder: Embedder | None = None,
        reranker: OpenAICompatibleReranker | None = None,
        entity_processor: EntityProcessor | None = None,
        observer: SpanRecorder | None = None,
        redactor: Redactor | None = None,
        audit_sink: AuditSink | None = None,
        rerank_threshold: float | None = None,
        rerank_blend: bool | None = None,
        rerank_preserve_seed_margin: float | None = None,
    ) -> None:
        self.client = client
        self.turing_home = Path(turing_home)
        self.graph = graph
        self.dimensions = getattr(embedder, "dimensions", dimensions)
        self.memory_index = memory_index
        self.document_index = document_index
        self.embedder = embedder or OpenAICompatibleEmbedder.from_env(dimensions=self.dimensions)
        self.reranker = reranker or OpenAICompatibleReranker.from_env()
        self.entity_processor = entity_processor or entity_processor_from_env()
        self.observer = observer or span_recorder_from_env()
        self.redactor = redactor or redactor_from_env()
        self.audit_sink = audit_sink or audit_sink_from_env()
        self.rerank_threshold = (
            float(provider_env("RERANK_THRESHOLD", default="0"))
            if rerank_threshold is None
            else rerank_threshold
        )
        self.rerank_blend = (
            provider_env("RERANK_BLEND").lower() in {"1", "true", "yes", "on"}
            if rerank_blend is None
            else rerank_blend
        )
        self.rerank_preserve_seed_margin = (
            max(0.0, float(provider_env("RERANK_PRESERVE_SEED_MARGIN", default="0.05")))
            if rerank_preserve_seed_margin is None
            else max(0.0, rerank_preserve_seed_margin)
        )
        self.data_dir = self.turing_home / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def bootstrap(self) -> None:
        self.turing_home.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_graph_loaded()
        self._ensure_vector_index(self.memory_index)
        self._ensure_vector_index(self.document_index)

    def store_message(
        self,
        *,
        user_identifier: str,
        session_id: str,
        role: str,
        content: str,
        memory_id: str | None = None,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
    ) -> MemoryItem:
        with self._span("memory.store_message", {"user_identifier": user_identifier, "source": source}):
            self._require_user(user_identifier)
            content, metadata = self._process_text_for_storage(content, metadata)
            memory_id = memory_id or stable_id("mem", user_identifier, session_id, role, content)
            item = self._write_memory(
                user_identifier=user_identifier,
                memory_id=memory_id,
                kind="message",
                content=content,
                session_id=session_id,
                role=role,
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at,
            )
            self._audit(
                operation="memory.store_message",
                user_identifier=user_identifier,
                resource_type="memory",
                resource_id=item.id,
            )
            return item

    def store_messages(
        self,
        *,
        user_identifier: str,
        messages: list[dict[str, object]],
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
    ) -> list[MemoryItem]:
        with self._span(
            "memory.store_messages",
            {"user_identifier": user_identifier, "source": source, "count": len(messages)},
        ):
            self._require_user(user_identifier)
            if not messages:
                return []
            prepared: list[dict[str, object]] = []
            raw_rows: list[tuple[str, dict[str, object]]] = []
            for idx, message in enumerate(messages):
                if not isinstance(message, dict):
                    raise ValueError(f"messages[{idx}] must be an object")
                session_id = str(message.get("session_id") or "")
                role = str(message.get("role") or "")
                content = str(message.get("content") or "")
                if not session_id.strip():
                    raise ValueError(f"messages[{idx}].session_id is required")
                if not role.strip():
                    raise ValueError(f"messages[{idx}].role is required")
                if not content.strip():
                    raise ValueError(f"messages[{idx}].content is required")
                item_source = str(message.get("source") if "source" in message else source)
                item_tags = self._clean_tags(
                    message.get("tags") if "tags" in message else tags  # type: ignore[arg-type]
                )
                item_metadata = dict(
                    message.get("metadata") if isinstance(message.get("metadata"), dict) else metadata or {}
                )
                item_expires_at = str(message.get("expires_at") if "expires_at" in message else expires_at)
                prepared.append(
                    {
                        "memory_id": str(message.get("memory_id") or ""),
                        "session_id": session_id,
                        "role": role,
                        "content": content,
                        "source": item_source,
                        "tags": item_tags,
                        "metadata": item_metadata,
                        "expires_at": item_expires_at,
                    }
                )
                raw_rows.append((content, item_metadata))

            processed_rows = self._process_texts_for_storage(raw_rows)
            unique_by_id: dict[str, dict[str, object]] = {}
            for payload, (content, item_metadata) in zip(prepared, processed_rows, strict=True):
                payload["content"] = content
                payload["metadata"] = item_metadata
                memory_id = str(payload["memory_id"]) or stable_id(
                    "mem",
                    user_identifier,
                    str(payload["session_id"]),
                    str(payload["role"]),
                    content,
                )
                payload["memory_id"] = memory_id
                existing_payload = unique_by_id.get(memory_id)
                if existing_payload is not None and self._batch_payload_key(
                    existing_payload
                ) != self._batch_payload_key(payload):
                    raise ValueError(f"conflicting duplicate memory_id in batch: {memory_id}")
                unique_by_id.setdefault(memory_id, payload)

            unique_payloads = list(unique_by_id.values())
            existing_by_id = {
                str(payload["memory_id"]): self.get_memory(
                    user_identifier=user_identifier,
                    memory_id=str(payload["memory_id"]),
                )
                for payload in unique_payloads
            }
            needs_embedding = [
                payload
                for payload in unique_payloads
                if existing_by_id[str(payload["memory_id"])] is None
                or existing_by_id[str(payload["memory_id"])].content != str(payload["content"])
            ]
            vectors = self._embed_many([str(payload["content"]) for payload in needs_embedding])
            vector_by_id = {
                str(payload["memory_id"]): vector
                for payload, vector in zip(needs_embedding, vectors, strict=True)
            }

            item_by_id: dict[str, MemoryItem] = {}
            vector_rows: list[tuple[int, list[float]]] = []
            new_payloads = [
                payload
                for payload in unique_payloads
                if existing_by_id[str(payload["memory_id"])] is None
            ]
            for item in self._create_memories_batch(
                user_identifier=user_identifier,
                payloads=new_payloads,
            ):
                item_by_id[item.id] = item
            for payload in unique_payloads:
                memory_id = str(payload["memory_id"])
                if memory_id in item_by_id:
                    continue
                vector = vector_by_id.get(memory_id)
                item = self._write_memory(
                    user_identifier=user_identifier,
                    memory_id=memory_id,
                    kind="message",
                    content=str(payload["content"]),
                    session_id=str(payload["session_id"]),
                    role=str(payload["role"]),
                    source=str(payload["source"]),
                    tags=payload["tags"],  # type: ignore[arg-type]
                    metadata=payload["metadata"],  # type: ignore[arg-type]
                    expires_at=str(payload["expires_at"]),
                    existing=existing_by_id[memory_id],
                    vector=vector,
                    load_vector=False,
                )
                item_by_id[memory_id] = item
            for memory_id, vector in vector_by_id.items():
                vector_rows.append((self._memory_vector_id(user_identifier, memory_id), vector))
            if vector_rows:
                self._load_vectors(self.memory_index, vector_rows, "memory_batch")
            items = [item_by_id[str(payload["memory_id"])] for payload in prepared]
            self._audit(
                operation="memory.store_messages",
                user_identifier=user_identifier,
                resource_type="memory",
                resource_id="",
                details={"count": len(items)},
            )
            return items

    def add_entity(
        self,
        *,
        user_identifier: str,
        name: str,
        entity_type: str,
        description: str = "",
    ) -> MemoryItem:
        content = f"{name} ({entity_type}) {description}".strip()
        memory_id = stable_id("entity", user_identifier, name, entity_type)
        return self._write_memory(
            user_identifier=user_identifier,
            memory_id=memory_id,
            kind="entity",
            content=content,
            role="system",
        )

    def add_preference(
        self,
        *,
        user_identifier: str,
        category: str,
        preference: str,
        context: str = "",
    ) -> MemoryItem:
        content = f"{category}: {preference}. {context}".strip()
        memory_id = stable_id("pref", user_identifier, category, preference)
        return self._write_memory(
            user_identifier=user_identifier,
            memory_id=memory_id,
            kind="preference",
            content=content,
            role="system",
        )

    def add_fact(
        self,
        *,
        user_identifier: str,
        subject: str,
        predicate: str,
        object_value: str,
        context: str = "",
    ) -> MemoryItem:
        content = f"{subject} {predicate} {object_value}. {context}".strip()
        memory_id = stable_id("fact", user_identifier, subject, predicate, object_value)
        return self._write_memory(
            user_identifier=user_identifier,
            memory_id=memory_id,
            kind="fact",
            content=content,
            role="system",
        )

    def search_memory(
        self,
        *,
        user_identifier: str,
        query: str,
        limit: int = 5,
        memory_types: list[str] | None = None,
        session_id: str = "",
        source: str = "",
        tags: list[str] | None = None,
        created_after: str = "",
        created_before: str = "",
        updated_after: str = "",
        updated_before: str = "",
        threshold: float = 0.0,
        explain: bool = False,
    ) -> list[MemoryItem]:
        with self._span(
            "memory.search",
            {
                "user_identifier": user_identifier,
                "limit": limit,
                "session_id": session_id,
                "source": source,
            },
        ):
            self._require_user(user_identifier)
            query = validate_search_query(query)
            limit = self._clean_limit(limit)
            threshold = validate_threshold(threshold)
            created_after_dt = self._parse_filter_datetime(created_after, "created_after")
            created_before_dt = self._parse_filter_datetime(created_before, "created_before")
            updated_after_dt = self._parse_filter_datetime(updated_after, "updated_after")
            updated_before_dt = self._parse_filter_datetime(updated_before, "updated_before")
            literal = self._vector_literal(self._embed_text(query, operation="memory.search"))
            try:
                vector_rows = self._records(
                    self._query(
                        f"VECTOR SEARCH IN {self.memory_index} FOR {max(limit * 4, limit)} {literal} "
                        f"YIELD ids, score MATCH (m:Memory) "
                        f'WHERE m.vector_id = ids AND m.user_identifier = "{quote(user_identifier)}" '
                        'AND m.status = "active" '
                        "RETURN m.id, m.user_identifier, m.kind, m.content, m.session_id, m.role, "
                        "m.created_at, m.updated_at, m.expires_at, m.source, "
                        "m.tags_json, m.metadata_json, score",
                        operation="memory.vector_search",
                    )
                )
            except Exception as exc:
                if "Unknown label: Memory" not in str(exc):
                    raise
                return []
            allowed = set(memory_types or [])
            rows_by_id: dict[str, dict[str, Any]] = {}
            semantic_by_id: dict[str, float] = {}
            for row in vector_rows:
                if self._row_is_expired(row, "m.expires_at"):
                    continue
                memory_id = str(row.get("m.id", ""))
                if not memory_id:
                    continue
                semantic_by_id[memory_id] = max(
                    semantic_by_id.get(memory_id, 0.0),
                    float(row.get("score") or 0.0),
                )
                rows_by_id[memory_id] = row
            for row in self._active_memory_rows(user_identifier):
                memory_id = str(row.get("m.id", ""))
                if memory_id and memory_id not in rows_by_id:
                    rows_by_id[memory_id] = row

            seeds: list[MemoryItem] = []
            for memory_id, row in rows_by_id.items():
                if self._row_is_expired(row, "m.expires_at"):
                    continue
                kind = str(row.get("m.kind", ""))
                item = self._memory_from_row(row)
                if not self._memory_matches_filters(
                    item,
                    session_id=session_id,
                    memory_types=memory_types,
                    source=source,
                    tags=tags,
                    created_after=created_after_dt,
                    created_before=created_before_dt,
                    updated_after=updated_after_dt,
                    updated_before=updated_before_dt,
                ):
                    continue
                semantic_score = semantic_by_id.get(memory_id, 0.0)
                lexical = lexical_score(
                    query,
                    self._row_search_text(row, text_key="m.content", metadata_key="m.metadata_json"),
                )
                final_score = blend_hybrid_score(semantic_score=semantic_score, lexical_score=lexical)
                if allowed and kind not in allowed:
                    continue
                if semantic_score <= 0.0 and lexical <= 0.0:
                    continue
                if not passes_threshold(final_score, threshold):
                    continue
                item = MemoryItem(
                    id=item.id,
                    user_identifier=item.user_identifier,
                    kind=item.kind,
                    content=item.content,
                    session_id=item.session_id,
                    role=item.role,
                    score=final_score,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    expires_at=item.expires_at,
                    source=item.source,
                    tags=item.tags,
                    metadata=item.metadata,
                )
                if explain:
                    item = MemoryItem(
                        **{
                            **item.to_dict(),
                            "score_details": build_score_details(
                                semantic_score=semantic_score,
                                lexical_score=lexical,
                                threshold=threshold,
                                final_score=final_score,
                            ),
                        }
                    )
                seeds.append(item)
            seeds = sorted(seeds, key=lambda item: item.score, reverse=True)[
                : max(limit * 3, limit)
            ]
            return self._rerank_memory(query, seeds)[:limit]

    def get_memory(self, *, user_identifier: str, memory_id: str) -> MemoryItem | None:
        self._require_user(user_identifier)
        if not memory_id.strip():
            raise ValueError("memory_id is required")
        try:
            rows = self._records(
                self._query(
                    f'MATCH (m:Memory) WHERE m.id = "{quote(memory_id)}" '
                    f'AND m.user_identifier = "{quote(user_identifier)}" AND m.status = "active" '
                    "RETURN m.id, m.user_identifier, m.kind, m.content, m.session_id, m.role, "
                    "m.created_at, m.updated_at, m.expires_at, m.source, m.tags_json, m.metadata_json",
                    operation="memory.get",
                )
            )
        except Exception as exc:
            if "Unknown label: Memory" not in str(exc):
                raise
            return None
        matching_rows = [
            row
            for row in rows
            if str(row.get("m.id", "")) == memory_id and not self._row_is_expired(row, "m.expires_at")
        ]
        return self._memory_from_row(matching_rows[0]) if matching_rows else None

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
        try:
            rows = self._records(
                self._query(
                    f'MATCH (m:Memory) WHERE m.user_identifier = "{quote(user_identifier)}" '
                    'AND m.status = "active" '
                    "RETURN m.id, m.user_identifier, m.kind, m.content, m.session_id, m.role, "
                    "m.created_at, m.updated_at, m.expires_at, m.source, m.tags_json, m.metadata_json",
                    operation="memory.list",
                )
            )
        except Exception as exc:
            if "Unknown label: Memory" not in str(exc):
                raise
            return []
        items = [self._memory_from_row(row) for row in rows if not self._row_is_expired(row, "m.expires_at")]
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
            next_content, next_metadata = self._process_text_for_storage(next_content, next_metadata)
        updated_at = self._now_iso()
        vid = self._memory_vector_id(user_identifier, memory_id)
        self._write(
            f'MATCH (m:Memory) WHERE m.id = "{quote(memory_id)}" '
            f'AND m.user_identifier = "{quote(user_identifier)}" '
            f'SET m.vector_id = {vid}, m.kind = "{quote(next_kind)}", '
            f'm.content = "{quote(next_content)}", m.session_id = "{quote(next_session_id)}", '
            f'm.role = "{quote(next_role)}", m.source = "{quote(next_source)}", '
            f'm.tags_json = "{quote(self._json_dumps(next_tags))}", '
            f'm.metadata_json = "{quote(self._json_dumps(next_metadata))}", '
            f'm.expires_at = "{quote(next_expires_at)}", '
            f'm.updated_at = "{quote(updated_at)}", m.status = "active"'
        )
        if load_vector and next_content != existing.content:
            self._load_vectors(
                self.memory_index,
                [
                    (
                        vid,
                        vector
                        if vector is not None
                        else self._embed_text(next_content, operation="memory.update"),
                    )
                ],
                f"memory_{memory_id}",
            )
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
        self._write(
            f'MATCH (m:Memory) WHERE m.id = "{quote(memory_id)}" '
            f'AND m.user_identifier = "{quote(user_identifier)}" '
            f'SET m.status = "deleted", m.updated_at = "{quote(updated_at)}"'
        )
        self._audit(
            operation="memory.delete",
            user_identifier=user_identifier,
            resource_type="memory",
            resource_id=memory_id,
        )
        return {"memory_id": memory_id, "deleted": True, "updated_at": updated_at}

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
        nodes = [
            f'({doc_var}:Document {{id: "{quote(document_id)}", user_identifier: "{quote(user_identifier)}", '
            f'title: "{quote(title)}", chunk_count: {len(chunks)}, chunk_chars: {chunk_chars}, '
            f'text_hash: "{quote(text_hash)}", source: "{quote(source)}", '
            f'tags_json: "{quote(self._json_dumps(clean_tags))}", '
            f'metadata_json: "{quote(self._json_dumps(clean_metadata))}", '
            f'created_at: "{quote(created_at)}", updated_at: "{quote(updated_at)}", '
            f'expires_at: "{quote(expires_at)}", status: "searchable"}})'
        ]
        edges = [f"(u)-[:HAS_DOCUMENT]->({doc_var})"]
        vector_rows: list[tuple[int, list[float]]] = []
        vectors = self._embed_many(chunks)
        previous_var = ""
        for idx, (chunk_text, vector) in enumerate(zip(chunks, vectors, strict=True), start=1):
            chunk_id = f"{document_id}#{idx}"
            chunk_var = cypher_var(chunk_id)
            vid = self._document_vector_id(user_identifier, chunk_id)
            locator = f"chunk={idx}"
            nodes.append(
                f'({chunk_var}:Chunk {{chunk_id: "{quote(chunk_id)}", vector_id: {vid}, '
                f'document_id: "{quote(document_id)}", user_identifier: "{quote(user_identifier)}", '
                f'title: "{quote(title)}", ordinal: {idx}, locator: "{locator}", '
                f'source: "{quote(source)}", tags_json: "{quote(self._json_dumps(clean_tags))}", '
                f'metadata_json: "{quote(self._json_dumps(clean_metadata))}", '
                f'created_at: "{quote(created_at)}", updated_at: "{quote(updated_at)}", '
                f'expires_at: "{quote(expires_at)}", status: "active", text: "{quote(chunk_text)}"}})'
            )
            edges.append(f"({doc_var})-[:HAS_CHUNK {{ordinal: {idx}}}]->({chunk_var})")
            if previous_var:
                edges.append(f"({previous_var})-[:NEXT_CHUNK]->({chunk_var})")
            previous_var = chunk_var
            vector_rows.append((vid, vector))
        self._write(
            f'MATCH (u:User) WHERE u.identifier = "{quote(user_identifier)}" CREATE '
            + ", ".join(nodes + edges)
        )
        self._load_vectors(self.document_index, vector_rows, f"document_{document_id}")
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
            try:
                vector_rows = self._records(
                    self._query(
                        f"VECTOR SEARCH IN {self.document_index} FOR {max(limit * 4, limit)} {literal} "
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

    def load_graph_after_restart(self) -> None:
        self.client.load_graph(self.graph, raise_if_loaded=False)
        self.client.set_graph(self.graph)

    def _write_memory(
        self,
        *,
        user_identifier: str,
        memory_id: str,
        kind: str,
        content: str,
        session_id: str = "",
        role: str = "",
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
        existing: MemoryItem | None | object = _MISSING,
        vector: list[float] | None = None,
        load_vector: bool = True,
    ) -> MemoryItem:
        self._ensure_user(user_identifier)
        if existing is _MISSING:
            existing = self.get_memory(user_identifier=user_identifier, memory_id=memory_id)
        if existing is not None:
            return self.update_memory(
                user_identifier=user_identifier,
                memory_id=memory_id,
                content=content,
                kind=kind,
                session_id=session_id,
                role=role,
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at,
                vector=vector,
                load_vector=load_vector,
            )
        vid = self._memory_vector_id(user_identifier, memory_id)
        mem_var = cypher_var(memory_id)
        created_at = self._now_iso()
        clean_tags = self._clean_tags(tags)
        clean_metadata = dict(metadata or {})
        self._write(
            f'MATCH (u:User) WHERE u.identifier = "{quote(user_identifier)}" '
            f'CREATE ({mem_var}:Memory {{id: "{quote(memory_id)}", vector_id: {vid}, '
            f'user_identifier: "{quote(user_identifier)}", kind: "{quote(kind)}", '
            f'content: "{quote(content)}", session_id: "{quote(session_id)}", '
            f'role: "{quote(role)}", source: "{quote(source)}", '
            f'tags_json: "{quote(self._json_dumps(clean_tags))}", '
            f'metadata_json: "{quote(self._json_dumps(clean_metadata))}", '
            f'created_at: "{quote(created_at)}", updated_at: "{quote(created_at)}", '
            f'expires_at: "{quote(expires_at)}", '
            'status: "active"}), '
            f"(u)-[:HAS_MEMORY]->({mem_var})"
        )
        if load_vector:
            self._load_vectors(
                self.memory_index,
                [
                    (
                        vid,
                        vector
                        if vector is not None
                        else self._embed_text(content, operation="memory.store"),
                    )
                ],
                f"memory_{memory_id}",
            )
        return MemoryItem(
            id=memory_id,
            user_identifier=user_identifier,
            kind=kind,
            content=content,
            session_id=session_id,
            role=role,
            score=1.0,
            created_at=created_at,
            updated_at=created_at,
            expires_at=expires_at,
            source=source,
            tags=clean_tags,
            metadata=clean_metadata,
        )

    def _create_memories_batch(
        self,
        *,
        user_identifier: str,
        payloads: list[dict[str, object]],
    ) -> list[MemoryItem]:
        if not payloads:
            return []
        self._ensure_user(user_identifier)
        nodes: list[str] = []
        edges: list[str] = []
        items: list[MemoryItem] = []
        for payload in payloads:
            memory_id = str(payload["memory_id"])
            mem_var = cypher_var(memory_id)
            vid = self._memory_vector_id(user_identifier, memory_id)
            created_at = self._now_iso()
            content = str(payload["content"])
            session_id = str(payload["session_id"])
            role = str(payload["role"])
            source = str(payload["source"])
            expires_at = str(payload.get("expires_at") or "")
            clean_tags = self._clean_tags(payload.get("tags"))  # type: ignore[arg-type]
            clean_metadata = dict(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {})
            nodes.append(
                f'({mem_var}:Memory {{id: "{quote(memory_id)}", vector_id: {vid}, '
                f'user_identifier: "{quote(user_identifier)}", kind: "message", '
                f'content: "{quote(content)}", session_id: "{quote(session_id)}", '
                f'role: "{quote(role)}", source: "{quote(source)}", '
                f'tags_json: "{quote(self._json_dumps(clean_tags))}", '
                f'metadata_json: "{quote(self._json_dumps(clean_metadata))}", '
                f'created_at: "{quote(created_at)}", updated_at: "{quote(created_at)}", '
                f'expires_at: "{quote(expires_at)}", '
                'status: "active"})'
            )
            edges.append(f"(u)-[:HAS_MEMORY]->({mem_var})")
            items.append(
                MemoryItem(
                    id=memory_id,
                    user_identifier=user_identifier,
                    kind="message",
                    content=content,
                    session_id=session_id,
                    role=role,
                    score=1.0,
                    created_at=created_at,
                    updated_at=created_at,
                    expires_at=expires_at,
                    source=source,
                    tags=clean_tags,
                    metadata=clean_metadata,
                )
            )
        self._write(
            f'MATCH (u:User) WHERE u.identifier = "{quote(user_identifier)}" CREATE '
            + ", ".join(nodes + edges)
        )
        return items

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

    def _ensure_graph_loaded(self) -> None:
        try:
            loaded_graphs = self.client.list_loaded_graphs()
        except Exception:
            loaded_graphs = []
        if self.graph not in loaded_graphs:
            try:
                self.client.load_graph(self.graph, raise_if_loaded=False)
            except Exception:
                try:
                    self.client.create_graph(self.graph)
                except Exception:
                    pass
        self.client.set_graph(self.graph)

    def _ensure_vector_index(self, name: str) -> None:
        try:
            self._query(
                f"CREATE VECTOR INDEX {name} WITH DIMENSION {self.dimensions} METRIC COSINE",
                operation="vector_index.ensure",
            )
        except Exception:
            pass

    def _ensure_user(self, user_identifier: str) -> None:
        try:
            rows = self._records(
                self._query(
                    f'MATCH (u:User) WHERE u.identifier = "{quote(user_identifier)}" '
                    "RETURN u.identifier",
                    operation="user.ensure",
                )
            )
        except Exception as exc:
            if "Unknown label: User" not in str(exc):
                raise
            rows = []
        if rows:
            return
        user_var = cypher_var(f"user_{user_identifier}")
        self._write(
            f'CREATE ({user_var}:User {{identifier: "{quote(user_identifier)}", '
            f'display: "{quote(user_identifier)}"}})'
        )

    def _span(self, name: str, attributes: dict[str, object] | None = None) -> Any:
        return self.observer.span(name, attributes or {})

    def _audit(
        self,
        *,
        operation: str,
        user_identifier: str,
        resource_type: str,
        resource_id: str,
        success: bool = True,
        details: dict[str, object] | None = None,
    ) -> None:
        self.audit_sink.record(
            audit_event(
                {
                    "operation": operation,
                    "user_identifier": user_identifier,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "success": success,
                    "details": details or {},
                }
            )
        )

    def _query(self, query: str, *, operation: str) -> Any:
        statement = query.lstrip().split(None, 1)[0].upper() if query.strip() else ""
        with self._span(
            "turingdb.query",
            {"operation": operation, "statement": statement, "graph": self.graph},
        ):
            return self.client.query(query)

    def _write(self, query: str) -> None:
        with self._span("turingdb.write_transaction", {"graph": self.graph}):
            self.client.new_change()
            try:
                self._query(query, operation="write")
                self._query("CHANGE SUBMIT", operation="write.submit")
            finally:
                self.client.checkout()

    def _load_vectors(self, index_name: str, rows: list[tuple[int, list[float]]], stem: str) -> None:
        if not rows:
            return
        with self._span(
            "vector.load",
            {"index": index_name, "rows": len(rows), "stem": stem, "dimensions": self.dimensions},
        ):
            filename = f"{cypher_var(stem)}_{int(time.time() * 1000)}.csv"
            path = self.data_dir / filename
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for vid, vec in rows:
                    handle.write(str(vid))
                    handle.write(",")
                    handle.write(",".join(f"{value:.8f}" for value in vec))
                    handle.write("\n")
            self._query(f'LOAD VECTOR FROM "{filename}" IN {index_name}', operation="vector.load")

    def _chunk_context(self, vector: int) -> list[dict[str, object]]:
        if vector <= 0:
            return []
        rows = self._records(
            self._query(
                "MATCH (c:Chunk)-[:NEXT_CHUNK]->(n:Chunk) "
                f'WHERE c.vector_id = {vector} AND c.status = "active" AND n.status = "active" '
                "RETURN n.chunk_id, n.locator, n.text",
                operation="document.chunk_context",
            )
        )
        return [
            {
                "chunk_id": row.get("n.chunk_id", ""),
                "locator": row.get("n.locator", ""),
                "text": row.get("n.text", ""),
            }
            for row in rows
        ]

    def _memory_from_row(self, row: dict[str, Any], *, score: float = 1.0) -> MemoryItem:
        tags = self._json_loads(row.get("m.tags_json"), [])
        metadata = self._json_loads(row.get("m.metadata_json"), {})
        created_at = str(row.get("m.created_at") or "")
        return MemoryItem(
            id=str(row.get("m.id", "")),
            user_identifier=str(row.get("m.user_identifier", "")),
            kind=str(row.get("m.kind", "")),
            content=str(row.get("m.content", "")),
            session_id=str(row.get("m.session_id", "")),
            role=str(row.get("m.role", "")),
            score=score,
            created_at=created_at,
            updated_at=str(row.get("m.updated_at") or created_at),
            expires_at=str(row.get("m.expires_at") or ""),
            source=str(row.get("m.source", "")),
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
        prefix: str,
        source: str = "",
        required_tags: set[str] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
    ) -> bool:
        if source and str(row.get(f"{prefix}.source", "")) != source:
            return False
        tags = self._json_loads(row.get(f"{prefix}.tags_json"), [])
        if required_tags and not required_tags <= set(tags if isinstance(tags, list) else []):
            return False
        if not self._timestamp_in_range(
            str(row.get(f"{prefix}.created_at") or ""),
            after=created_after,
            before=created_before,
        ):
            return False
        return self._timestamp_in_range(
            str(row.get(f"{prefix}.updated_at") or ""),
            after=updated_after,
            before=updated_before,
        )

    def _active_memory_rows(self, user_identifier: str) -> list[dict[str, Any]]:
        try:
            return self._records(
                self._query(
                    f'MATCH (m:Memory) WHERE m.user_identifier = "{quote(user_identifier)}" '
                    'AND m.status = "active" '
                    "RETURN m.id, m.user_identifier, m.kind, m.content, m.session_id, m.role, "
                    "m.created_at, m.updated_at, m.expires_at, m.source, m.tags_json, m.metadata_json",
                    operation="memory.active_rows",
                )
            )
        except Exception as exc:
            if "Unknown label: Memory" not in str(exc):
                raise
            return []

    def _active_chunk_rows(self, user_identifier: str, *, document_id: str = "") -> list[dict[str, Any]]:
        document_filter = ""
        if document_id:
            document_filter = f' AND c.document_id = "{quote(document_id)}"'
        try:
            return self._records(
                self._query(
                    f'MATCH (c:Chunk) WHERE c.user_identifier = "{quote(user_identifier)}" '
                    f'AND c.status = "active"{document_filter} '
                    "RETURN c.chunk_id, c.document_id, c.title, c.locator, c.text, c.vector_id, "
                    "c.created_at, c.updated_at, c.expires_at, c.source, c.tags_json, c.metadata_json",
                    operation="document.active_chunk_rows",
                )
            )
        except Exception as exc:
            if "Unknown label: Chunk" not in str(exc):
                raise
            return []

    def _document_from_row(self, row: dict[str, Any]) -> IngestedDocument:
        tags = self._json_loads(row.get("d.tags_json"), [])
        metadata = self._json_loads(row.get("d.metadata_json"), {})
        created_at = str(row.get("d.created_at") or "")
        return IngestedDocument(
            document_id=str(row.get("d.id", "")),
            title=str(row.get("d.title", "")),
            chunk_count=self._int_value(row.get("d.chunk_count")),
            user_identifier=str(row.get("d.user_identifier", "")),
            created_at=created_at,
            updated_at=str(row.get("d.updated_at") or created_at),
            expires_at=str(row.get("d.expires_at") or ""),
            source=str(row.get("d.source", "")),
            tags=tags if isinstance(tags, list) else [],
            metadata=metadata if isinstance(metadata, dict) else {},
            text_hash=str(row.get("d.text_hash", "")),
            chunk_chars=self._int_value(row.get("d.chunk_chars")),
        )

    def _rerank_memory(self, query: str, seeds: list[MemoryItem]) -> list[MemoryItem]:
        if len(seeds) < 2 or self.reranker is None:
            return seeds
        with self._span("rerank", {"kind": "memory", "count": len(seeds)}):
            scored = self.reranker.rerank(query, [item.content for item in seeds])
        ordered = apply_rerank_guard(
            seeds,
            scored,
            threshold=self.rerank_threshold,
            blend=self.rerank_blend,
            seed_scores=[item.score for item in seeds],
            preserve_seed_margin=self.rerank_preserve_seed_margin,
        )
        return [
            MemoryItem(
                id=item.id,
                user_identifier=item.user_identifier,
                kind=item.kind,
                content=item.content,
                session_id=item.session_id,
                role=item.role,
                score=float(score if score is not None else item.score),
                created_at=item.created_at,
                updated_at=item.updated_at,
                expires_at=item.expires_at,
                source=item.source,
                tags=item.tags,
                metadata=item.metadata,
                score_details=self._reranked_score_details(item.score_details, item.score, score),
            )
            for item, score in ordered
        ]

    def _rerank_documents(self, query: str, seeds: list[DocumentHit]) -> list[DocumentHit]:
        if len(seeds) < 2 or self.reranker is None:
            return seeds
        with self._span("rerank", {"kind": "document", "count": len(seeds)}):
            scored = self.reranker.rerank(query, [item.text for item in seeds])
        ordered = apply_rerank_guard(
            seeds,
            scored,
            threshold=self.rerank_threshold,
            blend=self.rerank_blend,
            seed_scores=[item.score for item in seeds],
            preserve_seed_margin=self.rerank_preserve_seed_margin,
        )
        return [
            DocumentHit(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                title=item.title,
                locator=item.locator,
                text=item.text,
                score=float(score if score is not None else item.score),
                context=item.context,
                expires_at=item.expires_at,
                source=item.source,
                tags=item.tags,
                metadata=item.metadata,
                score_details=self._reranked_score_details(item.score_details, item.score, score),
            )
            for item, score in ordered
        ]

    @staticmethod
    def _reranked_score_details(
        score_details: dict[str, object] | None,
        semantic_score: float,
        rerank_score: float | None,
    ) -> dict[str, object] | None:
        if score_details is None:
            return None
        threshold = float(score_details.get("threshold") or 0.0)
        final_score = float(rerank_score if rerank_score is not None else semantic_score)
        return build_score_details(
            semantic_score=float(score_details.get("semantic_score") or semantic_score),
            lexical_score=(
                float(score_details["lexical_score"]) if "lexical_score" in score_details else None
            ),
            threshold=threshold,
            final_score=final_score,
            rerank_score=rerank_score,
        )

    def _chunk_document_text(self, text: str, *, chunk_chars: int) -> list[str]:
        attributes: dict[str, object] = {
            "chunk_chars": chunk_chars,
            "text_chars": len(text),
            "chunk_count": 0,
        }
        with self._span("document.chunk", attributes):
            chunks = self._chunk_text(text, chunk_chars=chunk_chars)
            attributes["chunk_count"] = len(chunks)
            return chunks

    @staticmethod
    def _chunk_text(text: str, *, chunk_chars: int) -> list[str]:
        paragraphs = [part.strip() for part in text.split("\n") if part.strip()]
        chunks: list[str] = []
        for paragraph in paragraphs or [text.strip()]:
            while len(paragraph) > chunk_chars:
                split_at = paragraph.rfind(" ", 0, chunk_chars)
                if split_at < 80:
                    split_at = chunk_chars
                chunks.append(paragraph[:split_at].strip())
                paragraph = paragraph[split_at:].strip()
            if paragraph:
                chunks.append(paragraph)
        return chunks

    @staticmethod
    def _records(df: Any) -> list[dict[str, Any]]:
        def clean(value: Any) -> Any:
            if hasattr(value, "item"):
                try:
                    return value.item()
                except Exception:
                    pass
            if value is None:
                return None
            if isinstance(value, float) and value != value:
                return None
            if isinstance(value, (str, int, float, bool)):
                return value
            return str(value)

        return [{str(key): clean(value) for key, value in row.items()} for row in df.to_dict("records")]

    @staticmethod
    def _vector_literal(vec: list[float]) -> str:
        return "(" + ", ".join(f"{value:.8f}" for value in vec) + ")"

    @staticmethod
    def _clean_limit(limit: int) -> int:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return min(limit, 25)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

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
    def _json_dumps(value: object) -> str:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _json_loads(value: object, fallback: object) -> object:
        if not isinstance(value, str) or not value:
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback

    @staticmethod
    def _int_value(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

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

    @staticmethod
    def _memory_vector_id(user_identifier: str, memory_id: str) -> int:
        return vector_id("memory", f"{user_identifier}:{memory_id}")

    @staticmethod
    def _document_vector_id(user_identifier: str, chunk_id: str) -> int:
        return vector_id("chunk", f"{user_identifier}:{chunk_id}")

    @staticmethod
    def _document_text_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _require_user(user_identifier: str) -> None:
        if not user_identifier.strip():
            raise ValueError("user_identifier is required")
