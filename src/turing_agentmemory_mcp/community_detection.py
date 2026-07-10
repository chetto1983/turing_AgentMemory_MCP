"""Deterministic weighted Leiden communities and grounded summaries."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .ids import stable_id


@dataclass(frozen=True, slots=True)
class WeightedEntityEdge:
    source_id: str
    target_id: str
    weight: float
    source_memory_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("weighted edge source_id must be non-empty")
        if not isinstance(self.target_id, str) or not self.target_id.strip():
            raise ValueError("weighted edge target_id must be non-empty")
        if (
            isinstance(self.weight, bool)
            or not isinstance(self.weight, (int, float))
            or not math.isfinite(float(self.weight))
            or float(self.weight) <= 0
        ):
            raise ValueError("weighted edge weight must be a positive finite number")
        if any(
            not isinstance(source_id, str) or not source_id.strip()
            for source_id in self.source_memory_ids
        ):
            raise ValueError("weighted edge source memory IDs must be non-empty")


@dataclass(frozen=True, slots=True)
class DetectedCommunity:
    id: str
    user_identifier: str
    member_ids: tuple[str, ...]
    level: int
    parent_id: str = ""
    edge_weight: float = 0.0
    source_memory_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CommunityDetection:
    communities: tuple[DetectedCommunity, ...]
    isolates: tuple[str, ...]
    backend: str
    seed: int
    resolution: float


@dataclass(frozen=True, slots=True)
class CommunityEntity:
    id: str
    display_name: str
    entity_type: str
    confidence: float
    source_memory_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CommunityFact:
    id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    content: str
    confidence: float
    observed_at: str
    source_memory_id: str


@dataclass(frozen=True, slots=True)
class CommunityProjection:
    id: str
    user_identifier: str
    member_ids: tuple[str, ...]
    content: str
    source_memory_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    confidence: float
    level: int
    parent_id: str
    edge_weight: float


@dataclass(frozen=True, slots=True)
class NativeLeidenDetector:
    seed: int = 42
    resolution: float = 1.0
    randomness: float = 0.001
    iterations: int = 2
    max_cluster_size: int = 100
    backend: Callable[..., Sequence[Any]] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("Leiden seed must be a non-negative integer")
        for name in ("resolution", "randomness"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise ValueError(f"Leiden {name} must be a positive finite number")
        for name in ("iterations", "max_cluster_size"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"Leiden {name} must be a positive integer")

    def detect(
        self,
        user_identifier: str,
        node_ids: Sequence[str],
        edges: Sequence[WeightedEntityEdge],
    ) -> CommunityDetection:
        if not isinstance(user_identifier, str) or not user_identifier.strip():
            raise ValueError("community user_identifier must be non-empty")
        nodes = tuple(sorted(set(node_ids)))
        if any(not isinstance(node, str) or not node.strip() for node in nodes):
            raise ValueError("community node IDs must be non-empty strings")
        aggregated = aggregate_weighted_edges(edges)
        node_set = set(nodes)
        if any(
            edge.source_id not in node_set or edge.target_id not in node_set
            for edge in aggregated
        ):
            raise ValueError("community edge endpoint is not in node_ids")
        connected = {
            endpoint
            for edge in aggregated
            for endpoint in (edge.source_id, edge.target_id)
        }
        isolates = tuple(sorted(node_set - connected))
        if not aggregated:
            return CommunityDetection(
                communities=(),
                isolates=isolates,
                backend="graspologic-native",
                seed=self.seed,
                resolution=self.resolution,
            )
        backend = self.backend or _native_hierarchical_leiden
        records = backend(
            [(edge.source_id, edge.target_id, float(edge.weight)) for edge in aggregated],
            resolution=float(self.resolution),
            randomness=float(self.randomness),
            iterations=self.iterations,
            max_cluster_size=self.max_cluster_size,
            seed=self.seed,
        )
        grouped: dict[tuple[int, str], set[str]] = {}
        for record in records:
            if not bool(record.is_final_cluster):
                continue
            node = str(record.node)
            if node not in connected:
                raise ValueError("Leiden backend returned an unknown node")
            grouped.setdefault((int(record.level), str(record.cluster)), set()).add(node)
        assigned = set().union(*grouped.values()) if grouped else set()
        if assigned != connected:
            raise ValueError("Leiden backend did not assign every connected node")

        final_groups: list[tuple[int, tuple[str, ...]]] = []
        for (level, _), members in grouped.items():
            ordered = tuple(sorted(members))
            if len(ordered) <= self.max_cluster_size:
                final_groups.append((level, ordered))
                continue
            for offset in range(0, len(ordered), self.max_cluster_size):
                final_groups.append(
                    (level + 1, ordered[offset : offset + self.max_cluster_size])
                )
        final_groups.sort(key=lambda item: item[1])
        communities = tuple(
            self._community_from_members(
                user_identifier,
                members,
                level,
                aggregated,
            )
            for level, members in final_groups
        )
        return CommunityDetection(
            communities=communities,
            isolates=isolates,
            backend="graspologic-native",
            seed=self.seed,
            resolution=self.resolution,
        )

    @staticmethod
    def _community_from_members(
        user_identifier: str,
        members: tuple[str, ...],
        level: int,
        edges: Sequence[WeightedEntityEdge],
    ) -> DetectedCommunity:
        member_set = set(members)
        internal_edges = [
            edge
            for edge in edges
            if edge.source_id in member_set and edge.target_id in member_set
        ]
        source_memory_ids = tuple(
            sorted(
                {
                    source_id
                    for edge in internal_edges
                    for source_id in edge.source_memory_ids
                }
            )
        )
        return DetectedCommunity(
            id=stable_id("community", user_identifier, *members),
            user_identifier=user_identifier,
            member_ids=members,
            level=level,
            edge_weight=sum(edge.weight for edge in internal_edges),
            source_memory_ids=source_memory_ids,
        )


def aggregate_weighted_edges(
    edges: Sequence[WeightedEntityEdge],
) -> list[WeightedEntityEdge]:
    weights: dict[tuple[str, str], float] = {}
    sources: dict[tuple[str, str], set[str]] = {}
    for edge in edges:
        if not isinstance(edge, WeightedEntityEdge):
            raise ValueError("community edge must be a WeightedEntityEdge")
        if edge.source_id == edge.target_id:
            continue
        key = tuple(sorted((edge.source_id, edge.target_id)))
        weights[key] = weights.get(key, 0.0) + float(edge.weight)
        sources.setdefault(key, set()).update(edge.source_memory_ids)
    return [
        WeightedEntityEdge(
            source_id=source,
            target_id=target,
            weight=weights[(source, target)],
            source_memory_ids=tuple(sorted(sources[(source, target)])),
        )
        for source, target in sorted(weights)
    ]


def build_community_projection(
    community: DetectedCommunity,
    entities: dict[str, CommunityEntity],
    facts: Sequence[CommunityFact],
    *,
    max_entities: int = 12,
    max_facts: int = 20,
) -> CommunityProjection:
    if max_entities <= 0 or max_facts <= 0:
        raise ValueError("community summary limits must be positive")
    missing = [member for member in community.member_ids if member not in entities]
    if missing:
        raise ValueError("community summary is missing member entities")
    ranked_entities = sorted(
        (entities[member] for member in community.member_ids),
        key=lambda entity: (-entity.confidence, entity.display_name.casefold(), entity.id),
    )[:max_entities]
    member_set = set(community.member_ids)
    ranked_facts = sorted(
        (
            fact
            for fact in facts
            if fact.subject_entity_id in member_set and fact.object_entity_id in member_set
        ),
        key=lambda fact: (-fact.confidence, fact.observed_at, fact.id),
    )[:max_facts]
    entity_text = ", ".join(
        f"{entity.display_name} ({entity.entity_type})" for entity in ranked_entities
    )
    parts = [f"Entities: {entity_text}."]
    if ranked_facts:
        parts.append(
            "Relations: " + "; ".join(fact.content for fact in ranked_facts) + "."
        )
        observed = sorted(
            {fact.observed_at for fact in ranked_facts if fact.observed_at}
        )
        if len(observed) == 1:
            parts.append(f"Observed: {observed[0]}.")
        elif observed:
            parts.append(f"Observed: {observed[0]} to {observed[-1]}.")
    source_memory_ids = tuple(
        sorted(
            {
                *community.source_memory_ids,
                *(source_id for entity in ranked_entities for source_id in entity.source_memory_ids),
                *(fact.source_memory_id for fact in ranked_facts if fact.source_memory_id),
            }
        )
    )
    confidences = [entity.confidence for entity in ranked_entities] + [
        fact.confidence for fact in ranked_facts
    ]
    return CommunityProjection(
        id=community.id,
        user_identifier=community.user_identifier,
        member_ids=community.member_ids,
        content=" ".join(parts),
        source_memory_ids=source_memory_ids,
        fact_ids=tuple(sorted(fact.id for fact in ranked_facts)),
        confidence=sum(confidences) / len(confidences) if confidences else 0.0,
        level=community.level,
        parent_id=community.parent_id,
        edge_weight=community.edge_weight,
    )


def _native_hierarchical_leiden(edges: list[tuple[str, str, float]], **kwargs: object) -> Sequence[Any]:
    try:
        from graspologic_native import hierarchical_leiden
    except ImportError as exc:
        raise RuntimeError(
            "graspologic-native==1.3.1 is required for community detection"
        ) from exc
    return hierarchical_leiden(edges, **kwargs)
