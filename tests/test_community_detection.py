from __future__ import annotations

import math
import sys
import types
from pathlib import Path

import pytest

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.community_detection import (
    CommunityEntity,
    CommunityFact,
    NativeLeidenDetector,
    WeightedEntityEdge,
    aggregate_weighted_edges,
    build_community_projection,
)
from turing_agentmemory_mcp.sparse_index import SparseIndex
from turing_agentmemory_mcp.store import TuringAgentMemory


def two_cluster_edges() -> list[WeightedEntityEdge]:
    return [
        WeightedEntityEdge("a", "b", 3.0, ("m1",)),
        WeightedEntityEdge("b", "c", 3.0, ("m1",)),
        WeightedEntityEdge("a", "c", 3.0, ("m2",)),
        WeightedEntityEdge("d", "e", 3.0, ("m3",)),
        WeightedEntityEdge("e", "f", 3.0, ("m3",)),
        WeightedEntityEdge("d", "f", 3.0, ("m4",)),
        WeightedEntityEdge("c", "d", 0.01, ("bridge",)),
    ]


def test_native_leiden_is_deterministic_and_separates_weighted_components() -> None:
    detector = NativeLeidenDetector(seed=42, iterations=2, max_cluster_size=10)

    first = detector.detect("alice", ["a", "b", "c", "d", "e", "f"], two_cluster_edges())
    second = detector.detect(
        "alice",
        ["f", "e", "d", "c", "b", "a"],
        list(reversed(two_cluster_edges())),
    )

    assert first == second
    assert {community.member_ids for community in first.communities} == {
        ("a", "b", "c"),
        ("d", "e", "f"),
    }
    assert first.isolates == ()


def test_isolates_remain_searchable_without_fabricated_community() -> None:
    result = NativeLeidenDetector(seed=7).detect(
        "alice",
        ["a", "b", "isolated"],
        [WeightedEntityEdge("a", "b", 1.0)],
    )

    assert result.isolates == ("isolated",)
    assert all("isolated" not in community.member_ids for community in result.communities)


def test_community_ids_are_tenant_scoped_and_cluster_label_independent() -> None:
    detector = NativeLeidenDetector(seed=42)
    alice = detector.detect("alice", ["a", "b"], [WeightedEntityEdge("a", "b", 1.0)])
    bob = detector.detect("bob", ["a", "b"], [WeightedEntityEdge("a", "b", 1.0)])

    assert alice.communities[0].member_ids == bob.communities[0].member_ids
    assert alice.communities[0].id != bob.communities[0].id


def test_max_cluster_size_is_a_hard_deterministic_bound() -> None:
    nodes = [f"n{index}" for index in range(8)]
    edges = [
        WeightedEntityEdge(left, right, 1.0)
        for index, left in enumerate(nodes)
        for right in nodes[index + 1 :]
    ]

    result = NativeLeidenDetector(seed=42, max_cluster_size=3).detect("alice", nodes, edges)

    assert all(len(community.member_ids) <= 3 for community in result.communities)
    assert sorted(node for community in result.communities for node in community.member_ids) == nodes


def test_aggregate_weighted_edges_merges_direction_and_provenance() -> None:
    aggregated = aggregate_weighted_edges(
        [
            WeightedEntityEdge("b", "a", 0.5, ("m2",)),
            WeightedEntityEdge("a", "b", 1.5, ("m1",)),
            WeightedEntityEdge("a", "a", 9.0, ("self",)),
        ]
    )

    assert aggregated == [WeightedEntityEdge("a", "b", 2.0, ("m1", "m2"))]


@pytest.mark.parametrize("weight", [0.0, -1.0, math.nan, math.inf, True])
def test_weighted_edges_reject_invalid_weights(weight: object) -> None:
    with pytest.raises(ValueError):
        WeightedEntityEdge("a", "b", weight)  # type: ignore[arg-type]


def test_community_summary_is_deterministic_and_grounded() -> None:
    community = NativeLeidenDetector(seed=42).detect(
        "alice",
        ["a", "b"],
        [WeightedEntityEdge("a", "b", 2.0, ("m1",))],
    ).communities[0]
    entities = {
        "a": CommunityEntity("a", "Alice", "person", 0.98, ("m1", "m2")),
        "b": CommunityEntity("b", "Hiking", "activity", 0.91, ("m1",)),
    }
    facts = [
        CommunityFact(
            "f1",
            "a",
            "prefers",
            "b",
            "Alice prefers Hiking",
            0.89,
            "2026-07-10T10:00:00Z",
            "m1",
        )
    ]

    first = build_community_projection(community, entities, facts)
    second = build_community_projection(community, dict(reversed(entities.items())), list(reversed(facts)))

    assert first == second
    assert first.content == (
        "Entities: Alice (person), Hiking (activity). "
        "Relations: Alice prefers Hiking. "
        "Observed: 2026-07-10T10:00:00Z."
    )
    assert first.source_memory_ids == ("m1", "m2")
    assert first.fact_ids == ("f1",)
    assert first.confidence == pytest.approx((0.98 + 0.91 + 0.89) / 3)


class CommunityEmbedder:
    dimensions = 3

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, text: str) -> list[float]:
        return [float(len(text)), 1.0, 0.0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self.embed(text) for text in texts]


class CommunityStore(TuringAgentMemory):
    def __init__(self, tmp_path: Path) -> None:
        self.community_embedder = CommunityEmbedder()
        self.sparse = SparseIndex(tmp_path / "communities.sqlite3")
        self.sparse.initialize()
        super().__init__(
            client=object(),  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=self.community_embedder,
            reranker=None,
            sparse_index=self.sparse,
            community_detector=NativeLeidenDetector(seed=42, max_cluster_size=10),
        )
        self.replacements: list[object] = []
        self.vector_loads: list[tuple[str, list[tuple[int, list[float]]]]] = []

    def _community_graph_inputs(
        self,
        user_identifier: str,
    ) -> tuple[dict[str, CommunityEntity], list[CommunityFact], dict[str, tuple[str, ...]]]:
        return (
            {
                "a": CommunityEntity("a", "Alice", "person", 0.98, ("m1",)),
                "b": CommunityEntity("b", "Hiking", "activity", 0.91, ("m1",)),
                "isolated": CommunityEntity("isolated", "Tea", "topic", 0.8, ("m2",)),
            },
            [
                CommunityFact(
                    "f1",
                    "a",
                    "prefers",
                    "b",
                    "Alice prefers Hiking",
                    0.89,
                    "2026-07-10T10:00:00Z",
                    "m1",
                )
            ],
            {"m1": ("a", "b"), "m2": ("isolated",)},
        )

    def _replace_community_graph(self, user_identifier: str, projections: list[object]) -> None:
        self.replacements = list(projections)

    def _active_community_ids(self, user_identifier: str) -> set[str]:
        return set()

    def _load_vectors(
        self,
        index_name: str,
        rows: list[tuple[int, list[float]]],
        stem: str,
    ) -> None:
        self.vector_loads.append((index_name, rows))


def test_store_rebuilds_embeds_and_sparse_indexes_grounded_communities(
    tmp_path: Path,
) -> None:
    store = CommunityStore(tmp_path)

    result = store.rebuild_communities(user_identifier="alice")

    assert result["community_count"] == 1
    assert result["isolate_count"] == 1
    assert len(store.replacements) == 1
    projection = store.replacements[0]
    assert projection.member_ids == ("a", "b")
    assert projection.source_memory_ids == ("m1",)
    assert store.community_embedder.calls == [[projection.content]]
    assert [name for name, _ in store.vector_loads] == [store.community_index]
    hits = store.sparse.search(
        user_identifier="alice",
        query="Alice Hiking",
        kinds=["community"],
        limit=10,
    )
    assert [hit.source_id for hit in hits] == [projection.id]


def test_batch_community_refresh_records_degradation_without_failing_ingest(
    tmp_path: Path,
) -> None:
    store = CommunityStore(tmp_path)
    store.community_rebuild_on_batch = True
    store.memory_extractor = object()  # type: ignore[assignment]

    def fail(*, user_identifier: str) -> dict[str, object]:
        raise RuntimeError(f"derived rebuild failed for {user_identifier}")

    store.rebuild_communities = fail  # type: ignore[method-assign]

    store._refresh_communities_after_batch("alice")

    projection = store.runtime_status()["projections"]["community"]
    assert projection["status"] == "degraded"
    assert projection["error_type"] == "RuntimeError"
    assert "alice" not in repr(projection)
