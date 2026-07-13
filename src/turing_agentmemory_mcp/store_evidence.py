"""Multi-signal retrieval evidence collection mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-02). Collects per-channel
`RetrievalEvidence` (episode/fact/entity/community-dense, bm25, graph) consumed by
`store_search.py`'s `_search_memory_fused`.

Ported to ArcadeDB (04-07, ARC-04/ARC-05/ARC-06): every dense channel reads
native HNSW (`vectorNeighbors`, D-03 over-fetch-then-filter) with NO legacy
synthetic-integer join property -- a record's own `id` (`ids.stable_id()`) is
the sole cross-channel identifier (ARC-08). The lexical/`bm25` channel retires the
SQLite FTS5 outbox read entirely (ARC-06): it now queries BOTH native
ArcadeDB lexical channels the both-channels decision provisions --
`vector.sparseNeighbors` (04-05's shared `sparse_encoder.sparse_vector()`
query-side encoding, byte-identical to the write-side tokenization) AND
`SEARCH_INDEX` (Lucene, escaped via `store_documents_queries.escape_lucene_query`)
-- merging both per record kind (keeping the higher of the two scores per id)
into ONE `bm25`-weighted RRF channel, since `store_core.py`'s `fusion_weights`
schema is out of this plan's scope to extend with new channel keys. The
2-hop entity-to-fact-to-memory traversal runs on the D-05-chosen SQL `MATCH`
surface with a bound `id IN :entity_ids` array param, replacing the retired
string-built `" OR ".join(...)` condition and the invalid-on-ArcadeDB Cypher
`(e:Entity)-[:R]->(f:Fact)` literal shape.
"""

from __future__ import annotations

from typing import Any

from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.models import RetrievalEvidence
from turing_agentmemory_mcp.sparse_encoder import sparse_vector
from turing_agentmemory_mcp.store_retrieval_queries import (
    community_sources_by_ids_statement,
    dense_search_statement,
    entity_traversal_statement,
    fact_sources_by_ids_statement,
    lucene_search_statement,
    memory_rows_by_ids_statement,
    sparse_search_statement,
)
from turing_agentmemory_mcp.temporal_graph import canonicalize_entity_name, canonicalize_entity_type

# (operation, edge_kind, hop) -- direct (hop=1) and via-one-intermediate-entity
# (hop=2, `.both()`) traversals for both SUBJECT_OF and OBJECT_OF, matching the
# retired Cypher shape's 4 separate queries.
_ENTITY_TRAVERSALS: tuple[tuple[str, str, int], ...] = (
    ("graph.entity_direct_subject", "SUBJECT_OF", 1),
    ("graph.entity_direct_object", "OBJECT_OF", 1),
    ("graph.entity_two_hop_subject", "SUBJECT_OF", 2),
    ("graph.entity_two_hop_object", "OBJECT_OF", 2),
)


def _similarity(row: dict[str, Any]) -> float:
    """Convert `vectorNeighbors`' cosine `distance` (0 = identical) to a
    higher-is-better score -- `_collect_retrieval_evidence` sorts every
    channel by `-raw_score` uniformly, so every channel must share this
    convention (matches `store_documents.py`'s `search_documents` precedent).
    """
    return max(0.0, 1.0 - float(row.get("distance") or 0.0))


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

        # ARC-06: the SQLite FTS5 outbox is never consulted for reads -- both
        # native ArcadeDB lexical channels are unconditionally available (no
        # separate opt-in projection to wire up), unlike the retired
        # `self.sparse_index is not None` gate.
        try:
            lexical_values = self._lexical_evidence(user_identifier, query, candidate_limit)
            if lexical_values:
                channels["bm25"] = lexical_values
        except Exception as exc:
            degraded["bm25"] = type(exc).__name__

        if self.memory_extractor is not None:
            try:
                graph_values = self._query_graph_evidence(user_identifier, query, candidate_limit)
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
        statement, params = dense_search_statement(
            type_name="Memory", embedding=query_vector, k=limit, user_identifier=user_identifier
        )
        rows = self._records(
            self._query(statement, operation="memory.vector_search.fused", params=params)
        )
        return [
            RetrievalEvidence(
                source_memory_id=str(row["id"]),
                evidence_id=str(row["id"]),
                evidence_kind="episode",
                raw_score=_similarity(row),
            )
            for row in rows
            if row.get("id")
        ]

    def _fact_dense_evidence(
        self,
        user_identifier: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        statement, params = dense_search_statement(
            type_name="Fact",
            embedding=query_vector,
            k=limit,
            user_identifier=user_identifier,
            extra_fields=("source_memory_id",),
        )
        rows = self._records(self._query(statement, operation="fact.vector_search", params=params))
        return [
            RetrievalEvidence(
                source_memory_id=str(row["source_memory_id"]),
                evidence_id=str(row["id"]),
                evidence_kind="fact",
                raw_score=_similarity(row),
            )
            for row in rows
            if row.get("id") and row.get("source_memory_id")
        ]

    def _entity_dense_evidence(
        self,
        user_identifier: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        statement, params = dense_search_statement(
            type_name="Entity", embedding=query_vector, k=limit, user_identifier=user_identifier
        )
        rows = self._records(
            self._query(statement, operation="entity.vector_search", params=params)
        )
        seeds = {str(row["id"]): _similarity(row) for row in rows if row.get("id")}
        return self._expand_entity_evidence(user_identifier, seeds, limit)

    def _community_dense_evidence(
        self,
        user_identifier: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        statement, params = dense_search_statement(
            type_name="Community",
            embedding=query_vector,
            k=limit,
            user_identifier=user_identifier,
            extra_fields=("source_memory_ids_json",),
        )
        rows = self._records(
            self._query(statement, operation="community.vector_search", params=params)
        )
        values: list[RetrievalEvidence] = []
        for row in rows:
            community_id = str(row.get("id") or "")
            source_ids = self._json_loads(row.get("source_memory_ids_json"), [])
            if not community_id or not isinstance(source_ids, list):
                continue
            score = _similarity(row)
            for source_id in source_ids:
                if not isinstance(source_id, str) or not source_id:
                    continue
                values.append(
                    RetrievalEvidence(
                        source_memory_id=source_id,
                        evidence_id=community_id,
                        evidence_kind="community",
                        raw_score=score,
                        metadata={"community_id": community_id},
                    )
                )
                if len(values) >= limit:
                    return values
        return values

    def _lexical_evidence(
        self,
        user_identifier: str,
        query: str,
        limit: int,
    ) -> list[RetrievalEvidence]:
        """BOTH-channels lexical evidence (user decision, 04-EXECUTION-STATE.md):
        merges native `vector.sparseNeighbors` and native `SEARCH_INDEX` per
        record kind into ONE `bm25` RRF channel (keeping the higher of the two
        scores per id when a record matches both channels)."""
        tokens, weights = sparse_vector(query)
        values: list[RetrievalEvidence] = []
        episode_scores = self._merged_lexical_scores(
            "Memory",
            tokens=tokens,
            weights=weights,
            query=query,
            user_identifier=user_identifier,
            limit=limit,
        )
        for memory_id, (_row, score) in episode_scores.items():
            values.append(
                RetrievalEvidence(
                    source_memory_id=memory_id,
                    evidence_id=memory_id,
                    evidence_kind="episode",
                    raw_score=score,
                )
            )
        fact_scores = self._merged_lexical_scores(
            "Fact",
            tokens=tokens,
            weights=weights,
            query=query,
            user_identifier=user_identifier,
            limit=limit,
            extra_fields=("source_memory_id",),
        )
        for fact_id, (row, score) in fact_scores.items():
            source_memory_id = str(row.get("source_memory_id") or "")
            if not source_memory_id:
                continue
            values.append(
                RetrievalEvidence(
                    source_memory_id=source_memory_id,
                    evidence_id=fact_id,
                    evidence_kind="fact",
                    raw_score=score,
                )
            )
        entity_scores = self._merged_lexical_scores(
            "Entity",
            tokens=tokens,
            weights=weights,
            query=query,
            user_identifier=user_identifier,
            limit=limit,
        )
        entity_seeds = {
            entity_id: max(score, 1e-12) for entity_id, (_row, score) in entity_scores.items()
        }
        values.extend(self._expand_entity_evidence(user_identifier, entity_seeds, limit))
        community_scores = self._merged_lexical_scores(
            "Community",
            tokens=tokens,
            weights=weights,
            query=query,
            user_identifier=user_identifier,
            limit=limit,
            extra_fields=("source_memory_ids_json",),
        )
        community_sources = self._community_sources_by_ids(user_identifier, list(community_scores))
        for community_id, (_row, score) in community_scores.items():
            for source_memory_id in community_sources.get(community_id, ()):
                values.append(
                    RetrievalEvidence(
                        source_memory_id=source_memory_id,
                        evidence_id=community_id,
                        evidence_kind="community",
                        raw_score=score,
                        metadata={"community_id": community_id},
                    )
                )
        return values[:limit]

    def _merged_lexical_scores(
        self,
        type_name: str,
        *,
        tokens: list[int],
        weights: list[float],
        query: str,
        user_identifier: str,
        limit: int,
        extra_fields: tuple[str, ...] = (),
    ) -> dict[str, tuple[dict[str, Any], float]]:
        """Run BOTH native lexical channels for `type_name`, merged by `id`
        keeping the row/score pair with the higher score."""
        merged: dict[str, tuple[dict[str, Any], float]] = {}
        kind = type_name.lower()
        if tokens:
            statement, params = sparse_search_statement(
                type_name=type_name,
                tokens=tokens,
                weights=weights,
                k=limit,
                user_identifier=user_identifier,
                extra_fields=extra_fields,
            )
            rows = self._records(
                self._query(statement, operation=f"{kind}.lexical_search.sparse", params=params)
            )
            self._merge_lexical_rows(merged, rows)
        statement, params = lucene_search_statement(
            type_name=type_name,
            query=query,
            limit=limit,
            user_identifier=user_identifier,
            extra_fields=extra_fields,
        )
        rows = self._records(
            self._query(statement, operation=f"{kind}.lexical_search.lucene", params=params)
        )
        self._merge_lexical_rows(merged, rows)
        return merged

    @staticmethod
    def _merge_lexical_rows(
        merged: dict[str, tuple[dict[str, Any], float]],
        rows: list[dict[str, Any]],
    ) -> None:
        for row in rows:
            row_id = str(row.get("id") or "")
            if not row_id:
                continue
            score = float(row.get("score") or 0.0)
            existing = merged.get(row_id)
            if existing is None or score > existing[1]:
                merged[row_id] = (row, score)

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
            entity_id = stable_id("ent", user_identifier, entity_type, canonical_name)
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
        entity_ids = list(entity_scores)
        values: list[RetrievalEvidence] = []
        for operation, edge_kind, hop in _ENTITY_TRAVERSALS:
            statement, params = entity_traversal_statement(
                edge_kind=edge_kind,
                hop=hop,
                entity_ids=entity_ids,
                user_identifier=user_identifier,
            )
            rows = self._records(self._query(statement, operation=operation, params=params))
            for row in rows:
                source_memory_id = str(row.get("memory_id") or "")
                evidence_id = str(row.get("fact_id") or "")
                entity_id = str(row.get("entity_id") or "")
                if not source_memory_id or not evidence_id:
                    continue
                seed_score = entity_scores.get(entity_id, max(entity_scores.values()))
                confidence = float(row.get("confidence") or 1.0)
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
        statement, params = fact_sources_by_ids_statement(
            fact_ids=list(dict.fromkeys(fact_ids)), user_identifier=user_identifier
        )
        rows = self._records(self._query(statement, operation="fact.source_lookup", params=params))
        return {
            str(row.get("id")): str(row.get("source_memory_id"))
            for row in rows
            if row.get("id") and row.get("source_memory_id")
        }

    def _community_sources_by_ids(
        self,
        user_identifier: str,
        community_ids: list[str],
    ) -> dict[str, tuple[str, ...]]:
        if not community_ids:
            return {}
        statement, params = community_sources_by_ids_statement(
            community_ids=list(dict.fromkeys(community_ids)), user_identifier=user_identifier
        )
        rows = self._records(
            self._query(statement, operation="community.source_lookup", params=params)
        )
        values: dict[str, tuple[str, ...]] = {}
        for row in rows:
            community_id = str(row.get("id") or "")
            source_ids = self._json_loads(row.get("source_memory_ids_json"), [])
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
        statement, params = memory_rows_by_ids_statement(
            memory_ids=list(dict.fromkeys(memory_ids)), user_identifier=user_identifier
        )
        rows = self._records(
            self._query(statement, operation="memory.source_hydration", params=params)
        )
        return {str(row.get("id")): row for row in rows if row.get("id")}
