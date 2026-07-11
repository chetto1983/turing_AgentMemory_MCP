"""Multi-signal retrieval evidence collection mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-02). Collects per-channel
`RetrievalEvidence` (episode/fact/entity/community-dense, bm25, graph) consumed by
`store_search.py`'s `_search_memory_fused`.
"""

from __future__ import annotations

from typing import Any

from turing_agentmemory_mcp.ids import quote, stable_id
from turing_agentmemory_mcp.models import RetrievalEvidence
from turing_agentmemory_mcp.temporal_graph import canonicalize_entity_name, canonicalize_entity_type


class _EvidenceMixin:
    def _collect_retrieval_evidence(
        self,
        *,
        user_identifier: str,
        query: str,
        candidate_limit: int,
    ) -> tuple[dict[str, list[RetrievalEvidence]], dict[str, str]]:
        channels: dict[str, list[RetrievalEvidence]] = {}
        degraded: dict[str, str] = {}
        query_vector: list[float] | None = None
        try:
            query_vector = self._embed_text(query, operation="memory.search")
        except Exception as exc:
            for channel in ("episode_dense", "fact_dense", "entity_dense"):
                degraded[channel] = type(exc).__name__

        if query_vector is not None:
            for channel, collector in (
                (
                    "episode_dense",
                    lambda: self._episode_dense_evidence(
                        user_identifier, query_vector, candidate_limit
                    ),
                ),
                (
                    "fact_dense",
                    lambda: self._fact_dense_evidence(
                        user_identifier, query_vector, candidate_limit
                    ),
                ),
                (
                    "entity_dense",
                    lambda: self._entity_dense_evidence(
                        user_identifier, query_vector, candidate_limit
                    ),
                ),
            ):
                try:
                    values = collector()
                    if values:
                        channels[channel] = values
                except Exception as exc:
                    degraded[channel] = type(exc).__name__
            try:
                community_values = self._community_dense_evidence(
                    user_identifier, query_vector, candidate_limit
                )
                if community_values:
                    channels["community"] = community_values
            except Exception as exc:
                degraded["community"] = type(exc).__name__

        if self.sparse_index is not None:
            try:
                sparse_values = self._sparse_evidence(
                    user_identifier, query, candidate_limit
                )
                if sparse_values:
                    channels["bm25"] = sparse_values
            except Exception as exc:
                degraded["bm25"] = type(exc).__name__

        if self.memory_extractor is not None:
            try:
                graph_values = self._query_graph_evidence(
                    user_identifier, query, candidate_limit
                )
                if graph_values:
                    channels["graph"] = graph_values
            except Exception as exc:
                degraded["graph"] = type(exc).__name__
        for channel, values in channels.items():
            channels[channel] = sorted(
                values,
                key=lambda item: (
                    -item.raw_score,
                    item.hop,
                    item.source_memory_id,
                    item.evidence_id,
                ),
            )
        return channels, degraded

    def _episode_dense_evidence(
        self,
        user_identifier: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        index_name = self._ensure_tenant_vector_index(
            self.memory_index, user_identifier
        )
        rows = self._records(
            self._query(
                f"VECTOR SEARCH IN {index_name} FOR {limit} "
                f"{self._vector_literal(query_vector)} YIELD ids, score "
                "MATCH (m:Memory) "
                f'WHERE m.vector_id = ids AND m.user_identifier = "{quote(user_identifier)}" '
                'AND m.status = "active" RETURN m.id, score',
                operation="memory.vector_search.fused",
            )
        )
        return [
            RetrievalEvidence(
                source_memory_id=str(row.get("m.id")),
                evidence_id=str(row.get("m.id")),
                evidence_kind="episode",
                raw_score=float(row.get("score") or 0.0),
            )
            for row in rows
            if row.get("m.id")
        ]

    def _fact_dense_evidence(
        self,
        user_identifier: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        index_name = self._ensure_tenant_vector_index(
            self.fact_index, user_identifier
        )
        rows = self._records(
            self._query(
                f"VECTOR SEARCH IN {index_name} FOR {limit} "
                f"{self._vector_literal(query_vector)} YIELD ids, score "
                "MATCH (f:Fact) "
                f'WHERE f.vector_id = ids AND f.user_identifier = "{quote(user_identifier)}" '
                'AND f.status = "active" RETURN f.id, f.source_memory_id, score',
                operation="fact.vector_search",
            )
        )
        return [
            RetrievalEvidence(
                source_memory_id=str(row.get("f.source_memory_id")),
                evidence_id=str(row.get("f.id")),
                evidence_kind="fact",
                raw_score=float(row.get("score") or 0.0),
            )
            for row in rows
            if row.get("f.id") and row.get("f.source_memory_id")
        ]

    def _entity_dense_evidence(
        self,
        user_identifier: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        index_name = self._ensure_tenant_vector_index(
            self.entity_index, user_identifier
        )
        rows = self._records(
            self._query(
                f"VECTOR SEARCH IN {index_name} FOR {limit} "
                f"{self._vector_literal(query_vector)} YIELD ids, score "
                "MATCH (e:Entity) "
                f'WHERE e.vector_id = ids AND e.user_identifier = "{quote(user_identifier)}" '
                'AND e.status = "active" RETURN e.id, score',
                operation="entity.vector_search",
            )
        )
        seeds = {
            str(row.get("e.id")): float(row.get("score") or 0.0)
            for row in rows
            if row.get("e.id")
        }
        return self._expand_entity_evidence(user_identifier, seeds, limit)

    def _sparse_evidence(
        self,
        user_identifier: str,
        query: str,
        limit: int,
    ) -> list[RetrievalEvidence]:
        if self.sparse_index is None:
            return []
        hits = self.sparse_index.search(
            user_identifier=user_identifier,
            query=query,
            limit=limit,
            kinds=["episode", "fact", "entity", "community"],
        )
        fact_ids = [hit.source_id for hit in hits if hit.kind == "fact"]
        fact_sources = self._fact_sources_by_ids(user_identifier, fact_ids)
        community_ids = [hit.source_id for hit in hits if hit.kind == "community"]
        community_sources = self._community_sources_by_ids(
            user_identifier, community_ids
        )
        entity_seeds = {
            hit.source_id: max(hit.score, 1e-12)
            for hit in hits
            if hit.kind == "entity"
        }
        entity_evidence = self._expand_entity_evidence(
            user_identifier, entity_seeds, limit
        )
        values: list[RetrievalEvidence] = []
        for hit in hits:
            if hit.kind == "episode":
                values.append(
                    RetrievalEvidence(
                        hit.source_id,
                        hit.source_id,
                        "episode",
                        hit.score,
                    )
                )
            elif hit.kind == "fact" and hit.source_id in fact_sources:
                values.append(
                    RetrievalEvidence(
                        fact_sources[hit.source_id],
                        hit.source_id,
                        "fact",
                        hit.score,
                    )
                )
            elif hit.kind == "community":
                for source_memory_id in community_sources.get(hit.source_id, ()):
                    values.append(
                        RetrievalEvidence(
                            source_memory_id,
                            hit.source_id,
                            "community",
                            hit.score,
                            metadata={"community_id": hit.source_id},
                        )
                    )
        values.extend(entity_evidence)
        return values[:limit]

    def _community_dense_evidence(
        self,
        user_identifier: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        index_name = self._ensure_tenant_vector_index(
            self.community_index, user_identifier
        )
        rows = self._records(
            self._query(
                f"VECTOR SEARCH IN {index_name} FOR {limit} "
                f"{self._vector_literal(query_vector)} YIELD ids, score "
                "MATCH (c:Community) "
                f'WHERE c.vector_id = ids AND c.user_identifier = "{quote(user_identifier)}" '
                'AND c.status = "active" RETURN c.id, c.source_memory_ids_json, score',
                operation="community.vector_search",
            )
        )
        values: list[RetrievalEvidence] = []
        for row in rows:
            community_id = str(row.get("c.id") or "")
            source_ids = self._json_loads(
                row.get("c.source_memory_ids_json"), []
            )
            if not community_id or not isinstance(source_ids, list):
                continue
            for source_id in source_ids:
                if not isinstance(source_id, str) or not source_id:
                    continue
                values.append(
                    RetrievalEvidence(
                        source_memory_id=source_id,
                        evidence_id=community_id,
                        evidence_kind="community",
                        raw_score=float(row.get("score") or 0.0),
                        metadata={"community_id": community_id},
                    )
                )
                if len(values) >= limit:
                    return values
        return values

    def _query_graph_evidence(
        self,
        user_identifier: str,
        query: str,
        limit: int,
    ) -> list[RetrievalEvidence]:
        if self.memory_extractor is None:
            return []
        extractions = self.memory_extractor.extract_many([query])
        if not isinstance(extractions, tuple) or len(extractions) != 1:
            raise RuntimeError("query memory extractor returned an invalid result count")
        seeds: dict[str, float] = {}
        for entity in extractions[0].entities:
            entity_type = canonicalize_entity_type(entity.label)
            canonical_name = canonicalize_entity_name(entity.text)
            entity_id = stable_id(
                "ent", user_identifier, entity_type, canonical_name
            )
            seeds[entity_id] = max(seeds.get(entity_id, 0.0), entity.score)
        return self._expand_entity_evidence(user_identifier, seeds, limit)

    def _expand_entity_evidence(
        self,
        user_identifier: str,
        entity_scores: dict[str, float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        if not entity_scores:
            return []
        condition = " OR ".join(
            f'e.id = "{quote(entity_id)}"' for entity_id in entity_scores
        )
        queries = (
            (
                "graph.entity_direct_subject",
                "MATCH (e:Entity)-[:SUBJECT_OF]->(f:Fact)-[:SUPPORTED_BY]->(m:Memory) ",
                1,
            ),
            (
                "graph.entity_direct_object",
                "MATCH (e:Entity)-[:OBJECT_OF]->(f:Fact)-[:SUPPORTED_BY]->(m:Memory) ",
                1,
            ),
            (
                "graph.entity_two_hop_subject",
                "MATCH (e:Entity)--(n:Entity)-[:SUBJECT_OF]->(f:Fact)-[:SUPPORTED_BY]->(m:Memory) ",
                2,
            ),
            (
                "graph.entity_two_hop_object",
                "MATCH (e:Entity)--(n:Entity)-[:OBJECT_OF]->(f:Fact)-[:SUPPORTED_BY]->(m:Memory) ",
                2,
            ),
        )
        values: list[RetrievalEvidence] = []
        for operation, prefix, hop in queries:
            rows = self._records(
                self._query(
                    prefix
                    + f'WHERE e.user_identifier = "{quote(user_identifier)}" '
                    + f'AND ({condition}) AND e.status = "active" '
                    + 'AND f.status = "active" AND m.status = "active" '
                    + "RETURN m.id, f.id, f.confidence, e.id",
                    operation=operation,
                )
            )
            for row in rows:
                source_memory_id = str(row.get("m.id") or "")
                evidence_id = str(row.get("f.id") or "")
                entity_id = str(row.get("e.id") or "")
                if not source_memory_id or not evidence_id:
                    continue
                seed_score = entity_scores.get(entity_id, max(entity_scores.values()))
                confidence = float(row.get("f.confidence") or 1.0)
                values.append(
                    RetrievalEvidence(
                        source_memory_id=source_memory_id,
                        evidence_id=evidence_id,
                        evidence_kind="fact",
                        raw_score=seed_score * confidence / hop,
                        hop=hop,
                        metadata={"entity_id": entity_id},
                    )
                )
                if len(values) >= limit:
                    return values
        return values

    def _fact_sources_by_ids(
        self,
        user_identifier: str,
        fact_ids: list[str],
    ) -> dict[str, str]:
        if not fact_ids:
            return {}
        condition = " OR ".join(
            f'f.id = "{quote(fact_id)}"' for fact_id in dict.fromkeys(fact_ids)
        )
        rows = self._records(
            self._query(
                "MATCH (f:Fact) "
                f'WHERE f.user_identifier = "{quote(user_identifier)}" '
                f'AND ({condition}) AND f.status = "active" '
                "RETURN f.id, f.source_memory_id, f.confidence",
                operation="fact.source_lookup",
            )
        )
        return {
            str(row.get("f.id")): str(row.get("f.source_memory_id"))
            for row in rows
            if row.get("f.id") and row.get("f.source_memory_id")
        }

    def _community_sources_by_ids(
        self,
        user_identifier: str,
        community_ids: list[str],
    ) -> dict[str, tuple[str, ...]]:
        if not community_ids:
            return {}
        condition = " OR ".join(
            f'c.id = "{quote(community_id)}"'
            for community_id in dict.fromkeys(community_ids)
        )
        rows = self._records(
            self._query(
                "MATCH (c:Community) "
                f'WHERE c.user_identifier = "{quote(user_identifier)}" '
                f'AND ({condition}) AND c.status = "active" '
                "RETURN c.id, c.source_memory_ids_json",
                operation="community.source_lookup",
            )
        )
        values: dict[str, tuple[str, ...]] = {}
        for row in rows:
            community_id = str(row.get("c.id") or "")
            source_ids = self._json_loads(
                row.get("c.source_memory_ids_json"), []
            )
            if community_id and isinstance(source_ids, list):
                values[community_id] = tuple(
                    source_id
                    for source_id in source_ids
                    if isinstance(source_id, str) and source_id
                )
        return values

    def _memory_rows_for_ids(
        self,
        user_identifier: str,
        memory_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not memory_ids:
            return {}
        condition = " OR ".join(
            f'm.id = "{quote(memory_id)}"'
            for memory_id in dict.fromkeys(memory_ids)
        )
        try:
            rows = self._records(
                self._query(
                    "MATCH (m:Memory) "
                    f'WHERE m.user_identifier = "{quote(user_identifier)}" '
                    f'AND ({condition}) AND m.status = "active" '
                    "RETURN m.id, m.user_identifier, m.kind, m.content, m.session_id, m.role, "
                    "m.created_at, m.updated_at, m.expires_at, m.source, "
                    "m.tags_json, m.metadata_json",
                    operation="memory.source_hydration",
                )
            )
        except Exception as exc:
            if "Unknown label: Memory" not in str(exc):
                raise
            return {}
        return {
            str(row.get("m.id")): row for row in rows if row.get("m.id")
        }
