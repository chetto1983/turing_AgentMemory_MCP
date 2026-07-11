"""Memory write-path mixin for TuringAgentMemory: store/batch-store/add-* operations.

Split out of store.py (D-08/D-09, phase 01-01). Cross-mixin calls (`self.get_memory`,
`self.update_memory`, `self._unique_projection_entities`, `self._prepare_sparse_projection`,
`self._refresh_communities_after_batch`, ...) resolve via the TuringAgentMemory MRO at
runtime against the sibling mixins that define them.
"""

from __future__ import annotations

from turing_agentmemory_mcp.ids import cypher_var, quote, stable_id
from turing_agentmemory_mcp.models import MemoryItem
from turing_agentmemory_mcp.temporal_graph import (
    EntityProjection,
    EpisodeContext,
    TemporalProjection,
    plan_temporal_projection,
)

_MISSING = object()


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
        with self._span("memory.store_message", {"user_identifier": user_identifier, "source": source}):
            self._require_user(user_identifier)
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
        with self._span(
            "memory.store_messages",
            {"user_identifier": user_identifier, "source": source, "count": len(messages)},
        ):
            self._require_user(user_identifier)
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
            vector_rows: list[tuple[int, list[float]]] = []
            sparse_batch_id = self._prepare_sparse_projection(
                user_identifier=user_identifier,
                payloads=new_payloads,
                projections=projections,
                entities=entities,
            )
            try:
                for item in self._create_memories_batch(
                    user_identifier=user_identifier,
                    payloads=new_payloads,
                    projections=projections,
                    entities=entities,
                ):
                    item_by_id[item.id] = item
            except Exception as exc:
                if sparse_batch_id is not None and self.sparse_index is not None:
                    try:
                        self.sparse_index.discard_prepared(sparse_batch_id)
                    except Exception as discard_exc:
                        exc.add_note(f"sparse prepared-batch cleanup failed: {discard_exc}")
                raise
            if sparse_batch_id is not None and self.sparse_index is not None:
                self.sparse_index.commit_batch(sparse_batch_id)
                self.sparse_index.replay(batch_id=sparse_batch_id)
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
                self._load_vectors(
                    self._tenant_vector_index(self.memory_index, user_identifier),
                    vector_rows,
                    "memory_batch",
                )
            if entity_vectors:
                self._load_vectors(
                    self._tenant_vector_index(self.entity_index, user_identifier),
                    [
                        (self._entity_vector_id(user_identifier, entity.id), vector)
                        for entity, vector in zip(entities, entity_vectors, strict=True)
                    ],
                    "entity_batch",
                )
            if fact_vectors:
                self._load_vectors(
                    self._tenant_vector_index(self.fact_index, user_identifier),
                    [
                        (self._fact_vector_id(user_identifier, fact.id), vector)
                        for fact, vector in zip(facts, fact_vectors, strict=True)
                    ],
                    "fact_batch",
                )
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
                self._tenant_vector_index(self.memory_index, user_identifier),
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
        projections: list[TemporalProjection] | None = None,
        entities: list[EntityProjection] | None = None,
    ) -> list[MemoryItem]:
        if not payloads:
            return []
        self._ensure_user(user_identifier)
        projections = list(projections or [])
        new_entities = list(entities or [])
        nodes: list[str] = []
        edges: list[str] = []
        items: list[MemoryItem] = []
        for payload in payloads:
            memory_id = str(payload["memory_id"])
            mem_var = cypher_var(memory_id)
            vid = self._memory_vector_id(user_identifier, memory_id)
            created_at = str(payload.get("created_at") or self._now_iso())
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
        new_entity_ids = {entity.id for entity in new_entities}
        all_entity_ids = {
            entity.id
            for projection in projections
            for entity in projection.entities
        }
        existing_entity_ids = all_entity_ids - new_entity_ids
        for entity in new_entities:
            entity_var = cypher_var(entity.id)
            nodes.append(
                f'({entity_var}:Entity {{id: "{quote(entity.id)}", '
                f'vector_id: {self._entity_vector_id(user_identifier, entity.id)}, '
                f'user_identifier: "{quote(user_identifier)}", '
                f'entity_type: "{quote(entity.entity_type)}", '
                f'canonical_name: "{quote(entity.canonical_name)}", '
                f'display_name: "{quote(entity.display_name)}", '
                f'content: "{quote(entity.content)}", confidence: {entity.confidence:.8f}, '
                f'first_observed_at: "{quote(entity.observed_at)}", '
                f'last_observed_at: "{quote(entity.observed_at)}", '
                f'source_memory_id: "{quote(entity.source_memory_id)}", '
                f'schema_version: "{quote(entity.schema_version)}", '
                f'model: "{quote(entity.model)}", '
                f'expires_at: "{quote(entity.expires_at)}", status: "active"}})'
            )
        facts = [fact for projection in projections for fact in projection.facts]
        for fact in facts:
            fact_var = cypher_var(fact.id)
            nodes.append(
                f'({fact_var}:Fact {{id: "{quote(fact.id)}", '
                f'vector_id: {self._fact_vector_id(user_identifier, fact.id)}, '
                f'user_identifier: "{quote(user_identifier)}", '
                f'subject_entity_id: "{quote(fact.subject_entity_id)}", '
                f'predicate: "{quote(fact.predicate)}", '
                f'object_entity_id: "{quote(fact.object_entity_id)}", '
                f'content: "{quote(fact.content)}", confidence: {fact.confidence:.8f}, '
                f'observed_at: "{quote(fact.observed_at)}", '
                f'valid_from: "{quote(fact.valid_from)}", '
                f'valid_to: "{quote(fact.valid_to)}", '
                f'valid_time_precision: "{quote(fact.valid_time_precision)}", '
                f'source_memory_id: "{quote(fact.source_memory_id)}", '
                f'session_id: "{quote(fact.session_id)}", speaker: "{quote(fact.speaker)}", '
                f'source: "{quote(fact.source)}", '
                f'tags_json: "{quote(self._json_dumps(list(fact.tags)))}", '
                f'metadata_json: "{quote(self._json_dumps(fact.metadata))}", '
                f'schema_version: "{quote(fact.schema_version)}", model: "{quote(fact.model)}", '
                f'expires_at: "{quote(fact.expires_at)}", status: "active"}})'
            )
        for projection in projections:
            edges.extend(self._projection_edge_literals(projection.edges))
        match_nodes = ["(u:User)"] + [
            f"({cypher_var(entity_id)}:Entity)" for entity_id in sorted(existing_entity_ids)
        ]
        where_terms = [f'u.identifier = "{quote(user_identifier)}"'] + [
            f'{cypher_var(entity_id)}.id = "{quote(entity_id)}"'
            for entity_id in sorted(existing_entity_ids)
        ]
        self._write(
            "MATCH "
            + ", ".join(match_nodes)
            + " WHERE "
            + " AND ".join(where_terms)
            + " CREATE "
            + ", ".join(nodes + edges)
        )
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
