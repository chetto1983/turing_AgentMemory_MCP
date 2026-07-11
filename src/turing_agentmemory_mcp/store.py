"""Canonical TuringDB-backed memory/document store. See docs/architecture.md.

`TuringAgentMemory` is composed from `store_<concern>.py` sibling mixins (D-08/D-09,
phase 01-01 decomposition) behind this thin facade; the import path
`turing_agentmemory_mcp.store.TuringAgentMemory` is unchanged for all consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from turing_agentmemory_mcp.community_detection import (
    CommunityEntity,
    CommunityFact,
    CommunityProjection,
    WeightedEntityEdge,
    build_community_projection,
)
from turing_agentmemory_mcp.hybrid import blend_hybrid_score, lexical_score
from turing_agentmemory_mcp.ids import cypher_var, quote, stable_id
from turing_agentmemory_mcp.models import (
    DocumentHit,
    IngestedDocument,
    MemoryItem,
    RetrievalCandidate,
    RetrievalEvidence,
)
from turing_agentmemory_mcp.rerank import RerankResult, apply_rerank_guard, assemble_rerank_document
from turing_agentmemory_mcp.retrieval_fusion import diversify_fused, fuse_rankings
from turing_agentmemory_mcp.search_controls import (
    build_score_details,
    passes_threshold,
    validate_search_query,
    validate_threshold,
)
from turing_agentmemory_mcp.sparse_index import SparseDocument, SparseMutation
from turing_agentmemory_mcp.store_chunking import _ChunkingMixin
from turing_agentmemory_mcp.store_core import _StoreCore
from turing_agentmemory_mcp.store_memory_read import _MemoryReadMixin
from turing_agentmemory_mcp.store_memory_write import _MemoryWriteMixin
from turing_agentmemory_mcp.store_utils import _UtilsMixin
from turing_agentmemory_mcp.temporal_graph import (
    EntityProjection,
    TemporalProjection,
    canonicalize_entity_name,
    canonicalize_entity_type,
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


class TuringAgentMemory(
    _MemoryWriteMixin,
    _MemoryReadMixin,
    _ChunkingMixin,
    _UtilsMixin,
    _StoreCore,
):
    """Unified memory/document store. See docs/architecture.md.

    NOTE: search/evidence/document/rebuild methods below are extracted into
    store_search.py / store_evidence.py / store_documents.py / store_rebuild.py in
    plan 01-02 of this phase (D-08/D-09) — kept here intact for the 01-01 gate.
    """

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
            if self.fusion_enabled:
                return self._search_memory_fused(
                    user_identifier=user_identifier,
                    query=query,
                    limit=limit,
                    memory_types=memory_types,
                    session_id=session_id,
                    source=source,
                    tags=tags,
                    created_after=created_after_dt,
                    created_before=created_before_dt,
                    updated_after=updated_after_dt,
                    updated_before=updated_before_dt,
                    threshold=threshold,
                    explain=explain,
                )
            literal = self._vector_literal(self._embed_text(query, operation="memory.search"))
            memory_index = self._ensure_tenant_vector_index(
                self.memory_index, user_identifier
            )
            try:
                vector_rows = self._records(
                    self._query(
                        f"VECTOR SEARCH IN {memory_index} FOR {max(limit * 4, limit)} {literal} "
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

    def _search_memory_fused(
        self,
        *,
        user_identifier: str,
        query: str,
        limit: int,
        memory_types: list[str] | None,
        session_id: str,
        source: str,
        tags: list[str] | None,
        created_after: datetime | None,
        created_before: datetime | None,
        updated_after: datetime | None,
        updated_before: datetime | None,
        threshold: float,
        explain: bool,
    ) -> list[MemoryItem]:
        candidate_limit = min(max(limit * 8, 40), 200)
        channels, degraded = self._collect_retrieval_evidence(
            user_identifier=user_identifier,
            query=query,
            candidate_limit=candidate_limit,
        )
        self.runtime_signals.record_degraded_channels(tuple(sorted(degraded)))
        source_ids = list(
            dict.fromkeys(
                evidence.source_memory_id
                for ranking in channels.values()
                for evidence in ranking
                if evidence.source_memory_id
            )
        )
        rows_by_id = self._memory_rows_for_ids(user_identifier, source_ids)
        items_by_id: dict[str, MemoryItem] = {}
        for source_id, row in rows_by_id.items():
            if self._row_is_expired(row, "m.expires_at"):
                continue
            item = self._memory_from_row(row)
            if not self._memory_matches_filters(
                item,
                session_id=session_id,
                memory_types=memory_types,
                source=source,
                tags=tags,
                created_after=created_after,
                created_before=created_before,
                updated_after=updated_after,
                updated_before=updated_before,
            ):
                continue
            items_by_id[source_id] = item

        rankings: dict[str, list[RetrievalCandidate]] = {}
        evidence_by_source: dict[str, list[RetrievalEvidence]] = {}
        for channel in sorted(channels):
            ranking: list[RetrievalCandidate] = []
            seen_sources: set[str] = set()
            for evidence in channels[channel]:
                source_id = evidence.source_memory_id
                item = items_by_id.get(source_id)
                if item is None:
                    continue
                evidence_by_source.setdefault(source_id, []).append(evidence)
                if source_id in seen_sources:
                    continue
                seen_sources.add(source_id)
                ranking.append(
                    RetrievalCandidate(
                        candidate_id=source_id,
                        kind=item.kind,
                        content=item.content,
                        source_memory_id=source_id,
                        raw_score=evidence.raw_score,
                    )
                )
            if ranking:
                rankings[channel] = ranking
        if not rankings:
            return []
        rerank_pool_limit = min(max(limit * 3, limit), candidate_limit)
        fused = diversify_fused(
            fuse_rankings(
                rankings,
                weights=self.fusion_weights,
                channel_caps=candidate_limit,
            ),
            limit=rerank_pool_limit,
            max_per_source=1,
        )
        results: list[MemoryItem] = []
        for fused_candidate in fused:
            if not passes_threshold(fused_candidate.score, threshold):
                continue
            source_id = fused_candidate.candidate.source_memory_id
            item = items_by_id[source_id]
            details: dict[str, object] = {
                "fusion_score": fused_candidate.score,
                "final_score": fused_candidate.score,
                "threshold": threshold,
            }
            if explain:
                evidence = evidence_by_source.get(source_id, [])
                details.update(
                    {
                    "channels": {
                        channel: score.to_dict()
                        for channel, score in fused_candidate.channels.items()
                    },
                    "evidence_ids": sorted(
                        {value.evidence_id for value in evidence if value.evidence_id}
                    ),
                    "max_hop": max((value.hop for value in evidence), default=0),
                    "degraded_channels": sorted(degraded),
                    }
                )
            results.append(
                MemoryItem(
                    id=item.id,
                    user_identifier=item.user_identifier,
                    kind=item.kind,
                    content=item.content,
                    score=fused_candidate.score,
                    session_id=item.session_id,
                    role=item.role,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    expires_at=item.expires_at,
                    source=item.source,
                    tags=item.tags,
                    metadata=item.metadata,
                    score_details=details,
                )
            )
        return self._rerank_memory(query, results)[:limit]

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

    def _rerank_memory(self, query: str, seeds: list[MemoryItem]) -> list[MemoryItem]:
        fused = any(
            item.score_details is not None and "fusion_score" in item.score_details
            for item in seeds
        )
        if len(seeds) < 2:
            return self._annotate_memory_rerank(
                seeds,
                [(item, None) for item in seeds],
                status="not_needed",
                model=str(getattr(self.reranker, "model", "")),
                fused=fused,
            )
        if self.reranker is None:
            return self._annotate_memory_rerank(
                seeds,
                [(item, None) for item in seeds],
                status="disabled",
                model="",
                fused=fused,
            )
        candidates = seeds[: self.rerank_candidate_limit]
        tail = seeds[self.rerank_candidate_limit :]
        documents = [self._memory_rerank_document(item) for item in candidates]
        status = "applied"
        model = str(getattr(self.reranker, "model", ""))
        try:
            with self._span("rerank", {"kind": "memory", "count": len(candidates)}):
                rerank_with_status = getattr(self.reranker, "rerank_with_status", None)
                if callable(rerank_with_status):
                    result = rerank_with_status(query, documents)
                    if not isinstance(result, RerankResult):
                        raise ValueError("reranker returned an invalid status result")
                    scored = result.scores
                    status = result.status
                    model = result.model
                else:
                    scored = self.reranker.rerank(query, documents)
        except Exception:
            scored = []
            status = "provider_error"
        ordered = (
            apply_rerank_guard(
                candidates,
                scored,
                threshold=self.rerank_threshold,
                blend=self.rerank_blend,
                seed_scores=[item.score for item in candidates],
                preserve_seed_margin=self.rerank_preserve_seed_margin,
            )
            if status == "applied"
            else [(item, None) for item in candidates]
        )
        reranked = self._annotate_memory_rerank(
            candidates,
            ordered,
            status=status,
            model=model,
            fused=fused,
        )
        if tail:
            reranked.extend(
                self._annotate_memory_rerank(
                    tail,
                    [(item, None) for item in tail],
                    status="candidate_limit",
                    model=model,
                    fused=fused,
                )
            )
        return reranked

    def _annotate_memory_rerank(
        self,
        seeds: list[MemoryItem],
        ordered: list[tuple[MemoryItem, float | None]],
        *,
        status: str,
        model: str,
        fused: bool,
    ) -> list[MemoryItem]:
        del seeds
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
                score_details=(
                    self._fused_rerank_score_details(
                        item.score_details,
                        fusion_score=item.score,
                        rerank_score=score,
                        status=status,
                        model=model,
                    )
                    if fused
                    else self._reranked_score_details(item.score_details, item.score, score)
                ),
            )
            for item, score in ordered
        ]

    @staticmethod
    def _memory_rerank_document(item: MemoryItem) -> str:
        provenance: dict[str, object] = {
            "memory_id": item.id,
            "kind": item.kind,
            "source": item.source,
            "session_id": item.session_id,
            "role": item.role,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for key in ("path", "locator", "conversation_id", "document_id"):
            if key in item.metadata:
                provenance[key] = item.metadata[key]
        if item.score_details is not None and "evidence_ids" in item.score_details:
            provenance["evidence_ids"] = item.score_details["evidence_ids"]
        return assemble_rerank_document(content=item.content, provenance=provenance)

    @staticmethod
    def _fused_rerank_score_details(
        score_details: dict[str, object] | None,
        *,
        fusion_score: float,
        rerank_score: float | None,
        status: str,
        model: str,
    ) -> dict[str, object]:
        details = dict(score_details or {})
        details.setdefault("fusion_score", fusion_score)
        details["rerank_status"] = status
        details["rerank_model"] = model
        if rerank_score is not None:
            details["rerank_score"] = rerank_score
        details["final_score"] = rerank_score if rerank_score is not None else fusion_score
        return details

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
