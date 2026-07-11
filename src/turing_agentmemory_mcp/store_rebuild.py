"""Sparse/vector/community projection rebuild mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-02). All projections here are
rebuildable from canonical graph data (invariant #2 / CLAUDE.md), not a second
source of truth.
"""

from __future__ import annotations

from typing import Any

from turing_agentmemory_mcp.community_detection import (
    CommunityEntity,
    CommunityFact,
    CommunityProjection,
    WeightedEntityEdge,
    build_community_projection,
)
from turing_agentmemory_mcp.ids import cypher_var, quote
from turing_agentmemory_mcp.sparse_index import SparseDocument, SparseMutation
from turing_agentmemory_mcp.temporal_graph import EntityProjection, TemporalProjection


class _RebuildMixin:
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
        payload_by_memory_id = {
            str(payload["memory_id"]): payload for payload in payloads
        }
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

    def _fact_ids_for_memory(self, user_identifier: str, memory_id: str) -> list[str]:
        try:
            rows = self._records(
                self._query(
                    "MATCH (f:Fact) "
                    f'WHERE f.user_identifier = "{quote(user_identifier)}" '
                    f'AND f.source_memory_id = "{quote(memory_id)}" AND f.status = "active" '
                    "RETURN f.id",
                    operation="fact.ids_for_memory",
                )
            )
        except Exception as exc:
            if "Unknown label: Fact" not in str(exc):
                raise
            return []
        return [str(row.get("f.id")) for row in rows if row.get("f.id")]

    def rebuild_sparse_projection(self) -> dict[str, object]:
        if self.sparse_index is None:
            raise RuntimeError("sparse projection is not configured")
        documents = self._canonical_sparse_documents()
        self.sparse_index.rebuild(documents)
        return self.sparse_index.status()

    def rebuild_vector_projection(self, *, user_identifier: str) -> dict[str, object]:
        """Re-embed active tenant records into recoverable vector indexes."""
        self._require_user(user_identifier)
        canonical = self._canonical_vector_records(user_identifier)
        specifications = (
            ("memory", self.memory_index, self._memory_vector_id),
            ("document", self.document_index, self._document_vector_id),
            ("entity", self.entity_index, self._entity_vector_id),
            ("fact", self.fact_index, self._fact_vector_id),
            ("community", self.community_index, self._community_vector_id),
        )
        counts: dict[str, int] = {}
        for kind, base_index_name, id_factory in specifications:
            records = canonical.get(kind, [])
            index_name = self._ensure_tenant_vector_index(
                base_index_name, user_identifier
            )
            vectors = self._embed_many([content for _source_id, content in records])
            if vectors:
                self._load_vectors(
                    index_name,
                    [
                        (id_factory(user_identifier, source_id), vector)
                        for (source_id, _content), vector in zip(records, vectors, strict=True)
                    ],
                    f"{kind}_rebuild",
                )
            counts[kind] = len(records)
        result: dict[str, object] = {
            "user_identifier": user_identifier,
            "counts": counts,
            "total": sum(counts.values()),
            "dimensions": self.dimensions,
            "model": getattr(self.embedder, "model", type(self.embedder).__name__),
        }
        self._audit(
            operation="vector_projection.rebuild",
            user_identifier=user_identifier,
            resource_type="vector_projection",
            resource_id=user_identifier,
            details={"counts": counts, "total": result["total"]},
        )
        return result

    def rebuild_communities(self, *, user_identifier: str) -> dict[str, object]:
        self._require_user(user_identifier)
        entities, facts, mentions_by_memory = self._community_graph_inputs(
            user_identifier
        )
        edges = [
            WeightedEntityEdge(
                fact.subject_entity_id,
                fact.object_entity_id,
                max(fact.confidence, 1e-12),
                (fact.source_memory_id,) if fact.source_memory_id else (),
            )
            for fact in facts
            if fact.subject_entity_id in entities
            and fact.object_entity_id in entities
            and fact.subject_entity_id != fact.object_entity_id
        ]
        for memory_id, member_ids in mentions_by_memory.items():
            unique = tuple(sorted(set(member_ids)))
            for index, source_id in enumerate(unique):
                for target_id in unique[index + 1 :]:
                    edges.append(
                        WeightedEntityEdge(
                            source_id,
                            target_id,
                            0.25,
                            (memory_id,),
                        )
                    )
        detection = self.community_detector.detect(
            user_identifier,
            list(entities),
            edges,
        )
        projections = [
            build_community_projection(community, entities, facts)
            for community in detection.communities
        ]
        vectors = self._embed_many([projection.content for projection in projections])
        previous_ids = self._active_community_ids(user_identifier)
        sparse_batch_id = None
        if self.sparse_index is not None:
            mutations: list[SparseMutation] = [
                SparseMutation.delete(
                    self._sparse_doc_key(user_identifier, "community", community_id)
                )
                for community_id in sorted(previous_ids)
            ]
            mutations.extend(
                SparseMutation.upsert(
                    SparseDocument(
                        doc_key=self._sparse_doc_key(
                            user_identifier, "community", projection.id
                        ),
                        user_identifier=user_identifier,
                        source_id=projection.id,
                        kind="community",
                        content=projection.content,
                        created_at=self._now_iso(),
                    )
                )
                for projection in projections
            )
            if mutations:
                sparse_batch_id = self.sparse_index.prepare(mutations)
        try:
            self._replace_community_graph(user_identifier, projections)
        except Exception as exc:
            if sparse_batch_id is not None and self.sparse_index is not None:
                try:
                    self.sparse_index.discard_prepared(sparse_batch_id)
                except Exception as discard_exc:
                    exc.add_note(f"sparse community cleanup failed: {discard_exc}")
            raise
        if sparse_batch_id is not None and self.sparse_index is not None:
            self.sparse_index.commit_batch(sparse_batch_id)
            self.sparse_index.replay(batch_id=sparse_batch_id)
        if vectors:
            self._load_vectors(
                self._tenant_vector_index(self.community_index, user_identifier),
                [
                    (
                        self._community_vector_id(user_identifier, projection.id),
                        vector,
                    )
                    for projection, vector in zip(projections, vectors, strict=True)
                ],
                "community_batch",
            )
        result = {
            "user_identifier": user_identifier,
            "community_count": len(projections),
            "isolate_count": len(detection.isolates),
            "community_ids": [projection.id for projection in projections],
            "backend": detection.backend,
            "seed": detection.seed,
            "resolution": detection.resolution,
        }
        self.runtime_signals.record_projection(
            "community", success=True, item_count=len(projections)
        )
        return result

    def _refresh_communities_after_batch(self, user_identifier: str) -> None:
        if not self.community_rebuild_on_batch or self.memory_extractor is None:
            return
        try:
            self.rebuild_communities(user_identifier=user_identifier)
        except Exception as exc:
            self.runtime_signals.record_projection(
                "community", success=False, error_type=type(exc).__name__
            )

    def _community_graph_inputs(
        self,
        user_identifier: str,
    ) -> tuple[
        dict[str, CommunityEntity],
        list[CommunityFact],
        dict[str, tuple[str, ...]],
    ]:
        entity_rows = self._records(
            self._query(
                "MATCH (e:Entity) "
                f'WHERE e.user_identifier = "{quote(user_identifier)}" AND e.status = "active" '
                "RETURN e.id, e.display_name, e.entity_type, e.confidence, e.source_memory_id",
                operation="community.inputs.entities",
            )
        )
        mention_rows = self._records(
            self._query(
                "MATCH (m:Memory)-[:MENTIONS]->(e:Entity) "
                f'WHERE m.user_identifier = "{quote(user_identifier)}" '
                'AND m.status = "active" AND e.status = "active" RETURN m.id, e.id',
                operation="community.inputs.mentions",
            )
        )
        sources_by_entity: dict[str, set[str]] = {}
        mentions_by_memory_sets: dict[str, set[str]] = {}
        for row in mention_rows:
            memory_id = str(row.get("m.id") or "")
            entity_id = str(row.get("e.id") or "")
            if not memory_id or not entity_id:
                continue
            sources_by_entity.setdefault(entity_id, set()).add(memory_id)
            mentions_by_memory_sets.setdefault(memory_id, set()).add(entity_id)
        entities = {
            str(row.get("e.id")): CommunityEntity(
                id=str(row.get("e.id")),
                display_name=str(row.get("e.display_name") or ""),
                entity_type=str(row.get("e.entity_type") or "entity"),
                confidence=float(row.get("e.confidence") or 0.0),
                source_memory_ids=tuple(
                    sorted(
                        sources_by_entity.get(
                            str(row.get("e.id")),
                            {str(row.get("e.source_memory_id") or "")}
                            - {""},
                        )
                    )
                ),
            )
            for row in entity_rows
            if row.get("e.id") and row.get("e.display_name")
        }
        fact_rows = self._records(
            self._query(
                "MATCH (f:Fact) "
                f'WHERE f.user_identifier = "{quote(user_identifier)}" AND f.status = "active" '
                "RETURN f.id, f.subject_entity_id, f.predicate, f.object_entity_id, f.content, "
                "f.confidence, f.observed_at, f.source_memory_id",
                operation="community.inputs.facts",
            )
        )
        facts = [
            CommunityFact(
                id=str(row.get("f.id")),
                subject_entity_id=str(row.get("f.subject_entity_id") or ""),
                predicate=str(row.get("f.predicate") or ""),
                object_entity_id=str(row.get("f.object_entity_id") or ""),
                content=str(row.get("f.content") or ""),
                confidence=float(row.get("f.confidence") or 0.0),
                observed_at=str(row.get("f.observed_at") or ""),
                source_memory_id=str(row.get("f.source_memory_id") or ""),
            )
            for row in fact_rows
            if row.get("f.id") and row.get("f.content")
        ]
        return (
            entities,
            facts,
            {
                memory_id: tuple(sorted(entity_ids))
                for memory_id, entity_ids in mentions_by_memory_sets.items()
            },
        )

    def _active_community_ids(self, user_identifier: str) -> set[str]:
        try:
            rows = self._records(
                self._query(
                    "MATCH (c:Community) "
                    f'WHERE c.user_identifier = "{quote(user_identifier)}" '
                    'AND c.status = "active" RETURN c.id',
                    operation="community.active_ids",
                )
            )
        except Exception as exc:
            if "Unknown label: Community" not in str(exc):
                raise
            return set()
        return {str(row.get("c.id")) for row in rows if row.get("c.id")}

    def _replace_community_graph(
        self,
        user_identifier: str,
        projections: list[CommunityProjection],
    ) -> None:
        existing_ids = self._active_community_ids(user_identifier)
        timestamp = self._now_iso()
        queries = [
            f'MATCH (c:Community) WHERE c.id = "{quote(community_id)}" '
            f'AND c.user_identifier = "{quote(user_identifier)}" '
            f'SET c.status = "stale", c.updated_at = "{quote(timestamp)}"'
            for community_id in sorted(existing_ids)
        ]
        for projection in projections:
            if projection.id in existing_ids:
                queries.append(
                    f'MATCH (c:Community) WHERE c.id = "{quote(projection.id)}" '
                    f'AND c.user_identifier = "{quote(user_identifier)}" '
                    f'SET c.vector_id = {self._community_vector_id(user_identifier, projection.id)}, '
                    f'c.content = "{quote(projection.content)}", '
                    f'c.member_ids_json = "{quote(self._json_dumps(list(projection.member_ids)))}", '
                    f'c.source_memory_ids_json = "{quote(self._json_dumps(list(projection.source_memory_ids)))}", '
                    f'c.fact_ids_json = "{quote(self._json_dumps(list(projection.fact_ids)))}", '
                    f'c.confidence = {projection.confidence:.8f}, c.level = {projection.level}, '
                    f'c.parent_id = "{quote(projection.parent_id)}", '
                    f'c.edge_weight = {projection.edge_weight:.8f}, '
                    f'c.updated_at = "{quote(timestamp)}", c.status = "active"'
                )
                continue
            member_vars = [cypher_var(member_id) for member_id in projection.member_ids]
            community_var = cypher_var(projection.id)
            match_nodes = ", ".join(
                f"({variable}:Entity)" for variable in member_vars
            )
            where_terms = " AND ".join(
                f'{variable}.id = "{quote(member_id)}"'
                for variable, member_id in zip(
                    member_vars, projection.member_ids, strict=True
                )
            )
            node = (
                f'({community_var}:Community {{id: "{quote(projection.id)}", '
                f'vector_id: {self._community_vector_id(user_identifier, projection.id)}, '
                f'user_identifier: "{quote(user_identifier)}", content: "{quote(projection.content)}", '
                f'member_ids_json: "{quote(self._json_dumps(list(projection.member_ids)))}", '
                f'source_memory_ids_json: "{quote(self._json_dumps(list(projection.source_memory_ids)))}", '
                f'fact_ids_json: "{quote(self._json_dumps(list(projection.fact_ids)))}", '
                f'confidence: {projection.confidence:.8f}, level: {projection.level}, '
                f'parent_id: "{quote(projection.parent_id)}", edge_weight: {projection.edge_weight:.8f}, '
                f'created_at: "{quote(timestamp)}", updated_at: "{quote(timestamp)}", status: "active"}})'
            )
            edges = [
                f"({variable})-[:IN_COMMUNITY]->({community_var})"
                for variable in member_vars
            ]
            queries.append(
                f"MATCH {match_nodes} WHERE {where_terms} CREATE "
                + ", ".join([node, *edges])
            )
        self._write_many(queries)

    def _canonical_sparse_documents(self) -> list[SparseDocument]:
        documents: list[SparseDocument] = []
        memory_rows = self._sparse_rebuild_rows(
            "Memory",
            "MATCH (m:Memory) WHERE m.status = \"active\" "
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
                    row.get(f"{variable}.observed_at")
                    or row.get(f"{variable}.created_at")
                    or ""
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

    def _canonical_vector_records(
        self,
        user_identifier: str,
    ) -> dict[str, list[tuple[str, str]]]:
        records: dict[str, list[tuple[str, str]]] = {}
        for kind, label, variable, status, text_property in (
            ("memory", "Memory", "m", "active", "content"),
            ("document", "Chunk", "c", "active", "text"),
            ("entity", "Entity", "e", "active", "content"),
            ("fact", "Fact", "f", "active", "content"),
            ("community", "Community", "c", "active", "content"),
        ):
            rows = self._sparse_rebuild_rows(
                label,
                f"MATCH ({variable}:{label}) "
                f'WHERE {variable}.user_identifier = "{quote(user_identifier)}" '
                f'AND {variable}.status = "{status}" '
                f"RETURN {variable}.id, {variable}.{text_property}",
                f"vector.rebuild.{kind}",
            )
            records[kind] = [
                (
                    str(row[f"{variable}.id"]),
                    str(row[f"{variable}.{text_property}"]),
                )
                for row in rows
                if row.get(f"{variable}.id")
                and row.get(f"{variable}.{text_property}")
            ]
        return records

    def _sparse_rebuild_rows(
        self,
        label: str,
        query: str,
        operation: str,
    ) -> list[dict[str, Any]]:
        try:
            return self._records(self._query(query, operation=operation))
        except Exception as exc:
            if f"Unknown label: {label}" not in str(exc):
                raise
            return []

    def _unique_projection_entities(
        self,
        *,
        user_identifier: str,
        projections: list[TemporalProjection],
    ) -> list[EntityProjection]:
        by_id: dict[str, EntityProjection] = {}
        for projection in projections:
            for entity in projection.entities:
                previous = by_id.get(entity.id)
                if previous is None or entity.confidence > previous.confidence:
                    by_id[entity.id] = entity
        existing = self._existing_entity_ids(user_identifier, list(by_id))
        return [entity for entity_id, entity in by_id.items() if entity_id not in existing]

    def _existing_entity_ids(self, user_identifier: str, entity_ids: list[str]) -> set[str]:
        if not entity_ids:
            return set()
        conditions = " OR ".join(f'e.id = "{quote(entity_id)}"' for entity_id in entity_ids)
        try:
            rows = self._records(
                self._query(
                    "MATCH (e:Entity) "
                    f'WHERE e.user_identifier = "{quote(user_identifier)}" AND ({conditions}) '
                    "RETURN e.id",
                    operation="entity.exists_batch",
                )
            )
        except Exception as exc:
            if "Unknown label: Entity" not in str(exc):
                raise
            return set()
        return {str(row.get("e.id") or "") for row in rows if row.get("e.id")}
