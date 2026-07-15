"""Memory write-path mixin for TuringAgentMemory: store/batch-store/add-* operations.

Split out of store.py (D-08/D-09, phase 01-01). Cross-mixin calls (`self.get_memory`,
`self.update_memory`, `self._unique_projection_entities`,
`self._refresh_communities_after_batch`, ...) resolve via the TuringAgentMemory MRO at
runtime against the sibling mixins that define them.

Ported to ArcadeDB (04-05, ARC-04/ARC-05/ARC-08): every CREATE is a bound-param
ArcadeDB SQL statement built in `store_memory_queries.py`, the dense `embedding`
and both lexical channels (`lexical_tokens`/`lexical_weights`, the user's
both-channels decision) are inline record properties, and `stable_id()` is the
sole identifier -- the legacy synthetic-integer join property and the separate
CSV vector-load step are both retired (ARC-05). A whole batch (memories + entities + facts + edges)
runs inside ONE managed transaction via `store_core.py`'s `_write_many` (D-08),
so existing-entity lookups no longer need an explicit MATCH: a
`CREATE EDGE ... FROM (SELECT ...)` finds both already-committed rows and rows
created earlier in the SAME batch (read-your-writes, spike-confirmed A5).
"""

from __future__ import annotations

from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.models import MemoryItem
from turing_agentmemory_mcp.sparse_encoder import sparse_vector
from turing_agentmemory_mcp.store_memory_queries import (
    entity_create_statement,
    fact_create_statement,
    memory_create_statement,
    memory_edge_statement,
    projection_edge_statements,
)
from turing_agentmemory_mcp.temporal_graph import (
    EntityProjection,
    EpisodeContext,
    TemporalProjection,
    plan_temporal_projection,
)


class _MemoryWriteMixin:
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
        self._require_user(user_identifier)
        with self._span(
            "memory.store_message", {"user_identifier": user_identifier, "source": source}
        ):
            if self.memory_extractor is not None:
                return self.store_messages(
                    user_identifier=user_identifier,
                    messages=[
                        {
                            "memory_id": memory_id or "",
                            "session_id": session_id,
                            "role": role,
                            "content": content,
                            "source": source,
                            "tags": tags,
                            "metadata": metadata,
                            "expires_at": expires_at,
                        }
                    ],
                    _audit_operation="memory.store_message",
                )[0]
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
        refresh_communities: bool = True,
        _audit_operation: str = "memory.store_messages",
    ) -> list[MemoryItem]:
        self._require_user(user_identifier)
        with self._span(
            "memory.store_messages",
            {"user_identifier": user_identifier, "source": source, "count": len(messages)},
        ):
            if not isinstance(refresh_communities, bool):
                raise ValueError("refresh_communities must be a boolean")
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
                    message.get("metadata")
                    if isinstance(message.get("metadata"), dict)
                    else metadata or {}
                )
                item_expires_at = str(
                    message.get("expires_at") if "expires_at" in message else expires_at
                )
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
            if self.memory_extractor is not None:
                for payload in unique_payloads:
                    existing_item = existing_by_id[str(payload["memory_id"])]
                    if existing_item is not None and not self._memory_matches_payload(
                        existing_item,
                        payload,
                    ):
                        raise ValueError(
                            f"immutable temporal episode cannot be changed: {payload['memory_id']}"
                        )
            needs_embedding = [
                payload
                for payload in unique_payloads
                if existing_by_id[str(payload["memory_id"])] is None
                or existing_by_id[str(payload["memory_id"])].content != str(payload["content"])
            ]
            new_payloads = [
                payload
                for payload in unique_payloads
                if existing_by_id[str(payload["memory_id"])] is None
            ]
            for payload in new_payloads:
                payload["created_at"] = self._now_iso()
            projections = self._plan_memory_projections(
                user_identifier=user_identifier,
                payloads=new_payloads,
            )
            entities = self._unique_projection_entities(
                user_identifier=user_identifier,
                projections=projections,
            )
            facts = [fact for projection in projections for fact in projection.facts]
            embedding_texts = (
                [str(payload["content"]) for payload in needs_embedding]
                + [entity.content for entity in entities]
                + [fact.content for fact in facts]
            )
            vectors = self._embed_many(embedding_texts)
            raw_end = len(needs_embedding)
            entity_end = raw_end + len(entities)
            raw_vectors = vectors[:raw_end]
            entity_vectors = vectors[raw_end:entity_end]
            fact_vectors = vectors[entity_end:]
            vector_by_id = {
                str(payload["memory_id"]): vector
                for payload, vector in zip(needs_embedding, raw_vectors, strict=True)
            }

            item_by_id: dict[str, MemoryItem] = {}
            for item in self._create_memories_batch(
                user_identifier=user_identifier,
                payloads=new_payloads,
                projections=projections,
                entities=entities,
                vector_by_id=vector_by_id,
                entity_vectors=entity_vectors,
                fact_vectors=fact_vectors,
            ):
                item_by_id[item.id] = item
            for payload in unique_payloads:
                memory_id = str(payload["memory_id"])
                if memory_id in item_by_id:
                    continue
                existing_item = existing_by_id[memory_id]
                if existing_item is not None and self._memory_matches_payload(
                    existing_item,
                    payload,
                ):
                    item_by_id[memory_id] = existing_item
                    continue
                # An existing memory whose content changed (dedup-safe replay
                # already excluded via `_memory_matches_payload` above) -- the
                # new vector was pre-computed alongside the batch (`vector_by_id`)
                # so `update_memory` can inline it in the same UPDATE statement,
                # not a separate vector-load step (ARC-05, no CSV loader remains).
                item = self.update_memory(
                    user_identifier=user_identifier,
                    memory_id=memory_id,
                    content=str(payload["content"]),
                    kind="message",
                    session_id=str(payload["session_id"]),
                    role=str(payload["role"]),
                    source=str(payload["source"]),
                    tags=payload["tags"],  # type: ignore[arg-type]
                    metadata=payload["metadata"],  # type: ignore[arg-type]
                    expires_at=str(payload["expires_at"]),
                    vector=vector_by_id.get(memory_id),
                )
                item_by_id[memory_id] = item
            if new_payloads and refresh_communities:
                self._refresh_communities_after_batch(user_identifier)
            items = [item_by_id[str(payload["memory_id"])] for payload in prepared]
            self._audit(
                operation=_audit_operation,
                user_identifier=user_identifier,
                resource_type="memory",
                resource_id=items[0].id if _audit_operation == "memory.store_message" else "",
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
        self._require_user(user_identifier)
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
        self._require_user(user_identifier)
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
        self._require_user(user_identifier)
        content = f"{subject} {predicate} {object_value}. {context}".strip()
        memory_id = stable_id("fact", user_identifier, subject, predicate, object_value)
        return self._write_memory(
            user_identifier=user_identifier,
            memory_id=memory_id,
            kind="fact",
            content=content,
            role="system",
        )

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
    ) -> MemoryItem:
        self._ensure_user(user_identifier)
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
            )
        created_at = self._now_iso()
        clean_tags = self._clean_tags(tags)
        clean_metadata = dict(metadata or {})
        embedding = self._embed_text(content, operation="memory.store")
        lexical_tokens, lexical_weights = sparse_vector(content)
        statement = memory_create_statement(
            memory_id=memory_id,
            user_identifier=user_identifier,
            kind=kind,
            content=content,
            session_id=session_id,
            role=role,
            source=source,
            tags_json=self._json_dumps(clean_tags),
            metadata_json=self._json_dumps(clean_metadata),
            created_at=created_at,
            updated_at=created_at,
            expires_at=expires_at,
            embedding=embedding,
            lexical_tokens=lexical_tokens,
            lexical_weights=lexical_weights,
        )
        edge_statement = memory_edge_statement(user_identifier=user_identifier, memory_id=memory_id)
        self._write_many([statement, edge_statement])
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
        projections: list[TemporalProjection] | None = None,
        entities: list[EntityProjection] | None = None,
        vector_by_id: dict[str, list[float]] | None = None,
        entity_vectors: list[list[float]] | None = None,
        fact_vectors: list[list[float]] | None = None,
    ) -> list[MemoryItem]:
        if not payloads:
            return []
        self._ensure_user(user_identifier)
        projections = list(projections or [])
        new_entities = list(entities or [])
        vector_by_id = vector_by_id or {}
        entity_vectors = list(entity_vectors or [])
        fact_vectors = list(fact_vectors or [])

        statements: list[tuple[str, dict[str, object]]] = []
        items: list[MemoryItem] = []
        for payload in payloads:
            memory_id = str(payload["memory_id"])
            created_at = str(payload.get("created_at") or self._now_iso())
            content = str(payload["content"])
            session_id = str(payload["session_id"])
            role = str(payload["role"])
            source = str(payload["source"])
            expires_at = str(payload.get("expires_at") or "")
            clean_tags = self._clean_tags(payload.get("tags"))  # type: ignore[arg-type]
            clean_metadata = dict(
                payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            )
            embedding = vector_by_id.get(memory_id) or []
            lexical_tokens, lexical_weights = sparse_vector(content)
            statements.append(
                memory_create_statement(
                    memory_id=memory_id,
                    user_identifier=user_identifier,
                    kind="message",
                    content=content,
                    session_id=session_id,
                    role=role,
                    source=source,
                    tags_json=self._json_dumps(clean_tags),
                    metadata_json=self._json_dumps(clean_metadata),
                    created_at=created_at,
                    updated_at=created_at,
                    expires_at=expires_at,
                    embedding=embedding,
                    lexical_tokens=lexical_tokens,
                    lexical_weights=lexical_weights,
                )
            )
            statements.append(
                memory_edge_statement(user_identifier=user_identifier, memory_id=memory_id)
            )
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

        # ArcadeDB edges are `CREATE EDGE ... FROM (SELECT ...) TO (SELECT ...)`
        # subqueries (unlike the retired Cypher CREATE literal), so entities
        # already committed in an earlier call and entities created moments
        # ago in THIS same transaction both resolve identically -- no separate
        # "which entities already exist" MATCH is needed (04-04 read-your-writes).
        for entity, vector in zip(new_entities, entity_vectors, strict=True):
            lexical_tokens, lexical_weights = sparse_vector(entity.content)
            statements.append(
                entity_create_statement(
                    entity,
                    embedding=vector,
                    lexical_tokens=lexical_tokens,
                    lexical_weights=lexical_weights,
                )
            )

        facts = [fact for projection in projections for fact in projection.facts]
        for fact, vector in zip(facts, fact_vectors, strict=True):
            lexical_tokens, lexical_weights = sparse_vector(fact.content)
            statements.append(
                fact_create_statement(
                    fact,
                    tags_json=self._json_dumps(list(fact.tags)),
                    metadata_json=self._json_dumps(fact.metadata),
                    embedding=vector,
                    lexical_tokens=lexical_tokens,
                    lexical_weights=lexical_weights,
                )
            )

        for projection in projections:
            statements.extend(
                projection_edge_statements(
                    projection.edges,
                    user_identifier=user_identifier,
                )
            )

        self._write_many(statements)
        return items

    def _plan_memory_projections(
        self,
        *,
        user_identifier: str,
        payloads: list[dict[str, object]],
    ) -> list[TemporalProjection]:
        if not payloads or self.memory_extractor is None:
            return []
        texts = [str(payload["content"]) for payload in payloads]
        extractions = self.memory_extractor.extract_many(texts)
        if not isinstance(extractions, tuple) or len(extractions) != len(payloads):
            count = len(extractions) if isinstance(extractions, tuple) else 0
            raise RuntimeError(
                f"memory extractor returned {count} results for {len(payloads)} inputs"
            )
        return [
            plan_temporal_projection(
                EpisodeContext(
                    user_identifier=user_identifier,
                    memory_id=str(payload["memory_id"]),
                    content=str(payload["content"]),
                    session_id=str(payload["session_id"]),
                    role=str(payload["role"]),
                    observed_at=str(payload["created_at"]),
                    source=str(payload["source"]),
                    tags=tuple(payload["tags"]),  # type: ignore[arg-type]
                    metadata=dict(payload["metadata"]),  # type: ignore[arg-type]
                    expires_at=str(payload["expires_at"]),
                ),
                extraction,
            )
            for payload, extraction in zip(payloads, extractions, strict=True)
        ]
