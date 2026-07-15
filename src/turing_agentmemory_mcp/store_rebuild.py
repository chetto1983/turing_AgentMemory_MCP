"""Sparse/vector/community projection rebuild mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-02). All projections here are
rebuildable from canonical graph data (invariant #2 / CLAUDE.md), not a second
source of truth.

Ported to ArcadeDB (04-08, ARC-04/ARC-05): `rebuild_vector_projection`/
`rebuild_communities`'s vector step now use the D-07 versioned atomic-swap
flow (`store_rebuild_queries.py`) instead of the retired TuringDB CSV
LOAD-VECTOR/synthetic-integer join-property mechanism -- see that module's
docstring for the full mechanism. `_replace_community_graph` (Task 2) is one
`sqlscript` BEGIN/LET/COMMIT transaction with inline vectors keyed on
`stable_id`, no synthetic-integer join property. `_fact_ids_for_memory`/`_existing_entity_ids`
(live call sites in `store_memory_read.py`/`store_memory_write.py`, per
04-05-SUMMARY.md's heads-up) and `_community_graph_inputs`/
`_active_community_ids`/`_canonical_vector_records` are also ported to
bound-param ArcadeDB SQL here -- they were still Cypher-shaped (a real,
currently-live bug: these are called from already-ported write/read paths).

The legacy SQLite-FTS5 sparse-index outbox rebuild (formerly a sibling
`store_rebuild_sparse.py` mixin) is retired (04-10, ARC-06 gap closure):
`rebuild_communities` no longer stages, commits, replays, or discards an
outbox batch -- lexical retrieval is carried entirely by the native
`lexical_tokens`/`lexical_weights` channel computed below via the shared
`sparse_encoder.sparse_vector()`, unconditionally, and read by
`store_evidence.py`'s native sparse-vector + Lucene channels (04-07).
"""

from __future__ import annotations

from turing_agentmemory_mcp import store_rebuild_queries as rebuild_queries
from turing_agentmemory_mcp.community_detection import (
    CommunityEntity,
    CommunityFact,
    WeightedEntityEdge,
    build_community_projection,
)
from turing_agentmemory_mcp.sparse_encoder import sparse_vector
from turing_agentmemory_mcp.temporal_graph import EntityProjection, TemporalProjection


class _RebuildMixin:
    def _fact_ids_for_memory(self, user_identifier: str, memory_id: str) -> list[str]:
        statement, params = rebuild_queries.fact_ids_for_memory_statement(
            user_identifier=user_identifier, memory_id=memory_id
        )
        rows = self._records(self._query(statement, operation="fact.ids_for_memory", params=params))
        return [str(row["id"]) for row in rows if row.get("id")]

    # -- D-07 versioned atomic-swap vector rebuild --------------------------

    def rebuild_vector_projection(self, *, user_identifier: str) -> dict[str, object]:
        """Re-embed active tenant records into recoverable vector indexes.

        Each kind's records are staged into a tenant+version-namespaced
        scratch property/index (never mutating the live, search-queried
        `embedding`/`lexical_tokens`/`lexical_weights` while still
        computing), then atomically swapped in and the scratch schema
        dropped -- see `store_rebuild_queries.py` module docstring (D-07).
        """
        self._require_user(user_identifier)
        canonical = self._canonical_vector_records(user_identifier)
        specifications = (
            ("memory", "Memory", self.memory_index),
            ("document", "Chunk", self.document_index),
            ("entity", "Entity", self.entity_index),
            ("fact", "Fact", self.fact_index),
            ("community", "Community", self.community_index),
        )
        counts: dict[str, int] = {}
        for kind, type_name, base_index_name in specifications:
            records = canonical.get(kind, [])
            counts[kind] = self._rebuild_kind_vectors(
                kind=kind,
                type_name=type_name,
                base_index_name=base_index_name,
                user_identifier=user_identifier,
                records=records,
            )
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

    def _rebuild_kind_vectors(
        self,
        *,
        kind: str,
        type_name: str,
        base_index_name: str,
        user_identifier: str,
        records: list[tuple[str, str]],
    ) -> int:
        if not records:
            return 0
        current_version = self._active_vector_version(kind, user_identifier)
        new_version = current_version + 1
        embedding_property, tokens_property, weights_property = (
            rebuild_queries.staging_property_names(base_index_name, user_identifier, new_version)
        )
        self._ensure_staging_vector_schema(type_name, embedding_property)
        self._ensure_staging_lexical_schema(type_name, tokens_property, weights_property)

        texts = [text for _record_id, text in records]
        vectors = self._embed_many(texts)
        populate_statements = [
            rebuild_queries.stage_vector_statement(
                type_name=type_name,
                staging_embedding_property=embedding_property,
                staging_tokens_property=tokens_property,
                staging_weights_property=weights_property,
                record_id=record_id,
                embedding=vector,
                lexical_tokens=tokens,
                lexical_weights=weights,
                user_identifier=user_identifier,
            )
            for (record_id, text), vector in zip(records, vectors, strict=True)
            for tokens, weights in (sparse_vector(text),)
        ]
        self._write_many(populate_statements)  # POPULATE -- live fields untouched

        swap_statement, swap_params = rebuild_queries.swap_vector_statement(
            type_name=type_name,
            user_identifier=user_identifier,
            staging_embedding_property=embedding_property,
            staging_tokens_property=tokens_property,
            staging_weights_property=weights_property,
        )
        self._write(swap_statement, params=swap_params)  # SWAP -- one bulk field-copy
        self._set_active_vector_version(
            kind, user_identifier, previous_version=current_version, version=new_version
        )

        self._drop_staging_vector_schema(type_name, embedding_property)  # DROP
        self._drop_staging_lexical_schema(type_name, tokens_property, weights_property)
        return len(records)

    def _active_vector_version(self, kind: str, user_identifier: str) -> int:
        self._ensure_vector_version_schema()
        version_id = rebuild_queries.vector_version_id(kind, user_identifier)
        statement, params = rebuild_queries.vector_version_select_statement(
            version_id=version_id,
            user_identifier=user_identifier,
        )
        rows = self._records(self._query(statement, operation="vector_version.read", params=params))
        if not rows:
            return 0
        return int(rows[0].get("version") or 0)

    def _set_active_vector_version(
        self, kind: str, user_identifier: str, *, previous_version: int, version: int
    ) -> None:
        version_id = rebuild_queries.vector_version_id(kind, user_identifier)
        if previous_version == 0:
            statement, params = rebuild_queries.vector_version_create_statement(
                version_id=version_id,
                version=version,
                user_identifier=user_identifier,
            )
        else:
            statement, params = rebuild_queries.vector_version_update_statement(
                version_id=version_id,
                version=version,
                user_identifier=user_identifier,
            )
        self._write(statement, params=params)

    def _ensure_vector_version_schema(self) -> None:
        if getattr(self, "_vector_version_schema_ready", False):
            return
        for statement in rebuild_queries.vector_version_schema_ddl():
            self._idempotent_schema_command(statement)
        self._vector_version_schema_ready = True

    def _ensure_staging_vector_schema(self, type_name: str, property_name: str) -> None:
        for statement in rebuild_queries.staging_vector_schema_ddl(
            type_name, property_name, dimensions=self.dimensions
        ):
            self._idempotent_schema_command(statement)

    def _ensure_staging_lexical_schema(
        self, type_name: str, tokens_property: str, weights_property: str
    ) -> None:
        for statement in rebuild_queries.staging_lexical_schema_ddl(
            type_name, tokens_property, weights_property
        ):
            self._idempotent_schema_command(statement)

    def _drop_staging_vector_schema(self, type_name: str, property_name: str) -> None:
        self._idempotent_schema_command(
            rebuild_queries.drop_staging_vector_index_ddl(type_name, property_name),
            missing_ok=True,
        )
        self._idempotent_schema_command(
            rebuild_queries.drop_staging_property_ddl(type_name, property_name), missing_ok=True
        )

    def _drop_staging_lexical_schema(
        self, type_name: str, tokens_property: str, weights_property: str
    ) -> None:
        for property_name in (tokens_property, weights_property):
            self._idempotent_schema_command(
                rebuild_queries.drop_staging_property_ddl(type_name, property_name),
                missing_ok=True,
            )

    def _idempotent_schema_command(self, statement: str, *, missing_ok: bool = False) -> None:
        # Schema DDL is issued directly via the client, not `_write`/`_write_many`
        # -- matches arcadedb_schema.py's own precedent that schema mutations
        # are not app-data writes and don't belong in a managed transaction.
        try:
            self.client.command(statement)
        except Exception as exc:
            detail = str(exc).lower()
            if "already exists" in detail:
                return
            if missing_ok and ("not found" in detail or "does not exist" in detail):
                return
            raise

    # -- community rebuild ----------------------------------------------------

    def rebuild_communities(self, *, user_identifier: str) -> dict[str, object]:
        self._require_user(user_identifier)
        entities, facts, mentions_by_memory = self._community_graph_inputs(user_identifier)
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
        prepared = [
            {
                "id": projection.id,
                "content": projection.content,
                "member_ids": list(projection.member_ids),
                "member_ids_json": self._json_dumps(list(projection.member_ids)),
                "source_memory_ids_json": self._json_dumps(list(projection.source_memory_ids)),
                "fact_ids_json": self._json_dumps(list(projection.fact_ids)),
                "confidence": projection.confidence,
                "level": projection.level,
                "parent_id": projection.parent_id,
                "edge_weight": projection.edge_weight,
                "embedding": vector,
                "lexical_tokens": tokens,
                "lexical_weights": weights,
            }
            for projection, vector in zip(projections, vectors, strict=True)
            for tokens, weights in (sparse_vector(projection.content),)
        ]
        self._replace_community_graph(user_identifier, prepared, previous_ids)
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
        entity_statement, entity_params = rebuild_queries.community_entities_statement(
            user_identifier=user_identifier
        )
        entity_rows = self._records(
            self._query(
                entity_statement, operation="community.inputs.entities", params=entity_params
            )
        )
        mention_statement, mention_params = rebuild_queries.community_mentions_statement(
            user_identifier=user_identifier
        )
        mention_rows = self._records(
            self._query(
                mention_statement, operation="community.inputs.mentions", params=mention_params
            )
        )
        sources_by_entity: dict[str, set[str]] = {}
        mentions_by_memory_sets: dict[str, set[str]] = {}
        for row in mention_rows:
            memory_id = str(row.get("memory_id") or "")
            if not memory_id:
                continue
            entity_ids = row.get("entity_id") or []
            if not isinstance(entity_ids, list):
                entity_ids = [entity_ids]
            for entity_id in entity_ids:
                entity_id = str(entity_id or "")
                if not entity_id:
                    continue
                sources_by_entity.setdefault(entity_id, set()).add(memory_id)
                mentions_by_memory_sets.setdefault(memory_id, set()).add(entity_id)
        entities = {
            str(row.get("id")): CommunityEntity(
                id=str(row.get("id")),
                display_name=str(row.get("display_name") or ""),
                entity_type=str(row.get("entity_type") or "entity"),
                confidence=float(row.get("confidence") or 0.0),
                source_memory_ids=tuple(
                    sorted(
                        sources_by_entity.get(
                            str(row.get("id")),
                            {str(row.get("source_memory_id") or "")} - {""},
                        )
                    )
                ),
            )
            for row in entity_rows
            if row.get("id") and row.get("display_name")
        }
        fact_statement, fact_params = rebuild_queries.community_facts_statement(
            user_identifier=user_identifier
        )
        fact_rows = self._records(
            self._query(fact_statement, operation="community.inputs.facts", params=fact_params)
        )
        facts = [
            CommunityFact(
                id=str(row.get("id")),
                subject_entity_id=str(row.get("subject_entity_id") or ""),
                predicate=str(row.get("predicate") or ""),
                object_entity_id=str(row.get("object_entity_id") or ""),
                content=str(row.get("content") or ""),
                confidence=float(row.get("confidence") or 0.0),
                observed_at=str(row.get("observed_at") or ""),
                source_memory_id=str(row.get("source_memory_id") or ""),
            )
            for row in fact_rows
            if row.get("id") and row.get("content")
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
        statement, params = rebuild_queries.active_community_ids_statement(
            user_identifier=user_identifier
        )
        rows = self._records(
            self._query(statement, operation="community.active_ids", params=params)
        )
        return {str(row["id"]) for row in rows if row.get("id")}

    def _replace_community_graph(
        self,
        user_identifier: str,
        prepared: list[dict[str, object]],
        existing_ids: set[str],
    ) -> None:
        if not prepared and not existing_ids:
            return
        body, params = rebuild_queries.community_replace_sqlscript(
            user_identifier=user_identifier,
            prepared=prepared,
            existing_ids=existing_ids,
            timestamp=self._now_iso(),
        )
        with self._span(
            "arcadedb.write_batch",
            {"graph": self.graph, "operation": "community.replace"},
        ):
            self.client.sqlscript(body, params=params)

    # -- shared rebuild inputs --------------------------------------------------

    def _canonical_vector_records(
        self,
        user_identifier: str,
    ) -> dict[str, list[tuple[str, str]]]:
        records: dict[str, list[tuple[str, str]]] = {}
        for kind, type_name, text_property in (
            ("memory", "Memory", "content"),
            ("document", "Chunk", "text"),
            ("entity", "Entity", "content"),
            ("fact", "Fact", "content"),
            ("community", "Community", "content"),
        ):
            statement, params = rebuild_queries.canonical_vector_records_statement(
                type_name=type_name, text_property=text_property, user_identifier=user_identifier
            )
            rows = self._records(
                self._query(statement, operation=f"vector.rebuild.{kind}", params=params)
            )
            records[kind] = [
                (str(row["id"]), str(row[text_property]))
                for row in rows
                if row.get("id") and row.get(text_property)
            ]
        return records

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
        statement, params = rebuild_queries.existing_entity_ids_statement(
            user_identifier=user_identifier, entity_ids=entity_ids
        )
        rows = self._records(self._query(statement, operation="entity.exists_batch", params=params))
        return {str(row["id"]) for row in rows if row.get("id")}
