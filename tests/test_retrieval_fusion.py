from __future__ import annotations

import math

import pytest

from turing_agentmemory_mcp.models import RetrievalCandidate
from turing_agentmemory_mcp.retrieval_fusion import diversify_fused, fuse_rankings


def candidate(
    candidate_id: str,
    *,
    raw_score: float,
    source_memory_id: str = "",
    evidence_source_ids: tuple[str, ...] = (),
) -> RetrievalCandidate:
    return RetrievalCandidate(
        candidate_id=candidate_id,
        kind="episode",
        content=f"content {candidate_id}",
        source_memory_id=source_memory_id or candidate_id,
        evidence_source_ids=evidence_source_ids,
        raw_score=raw_score,
    )


def test_rrf_uses_rank_not_incomparable_raw_score_magnitude() -> None:
    fused = fuse_rankings(
        {
            "dense": [candidate("a", raw_score=0.01), candidate("b", raw_score=0.99)],
            "bm25": [candidate("a", raw_score=0.000001), candidate("b", raw_score=1000.0)],
        },
        weights={"dense": 1.0, "bm25": 1.0},
        rank_constant=60,
    )

    assert [item.candidate.candidate_id for item in fused] == ["a", "b"]
    assert fused[0].score == pytest.approx(2 / 61)
    assert fused[1].score == pytest.approx(2 / 62)
    assert fused[0].channels["dense"].raw_score == 0.01
    assert fused[0].channels["bm25"].raw_score == 0.000001


def test_rrf_applies_weights_and_reports_complete_contributions() -> None:
    fused = fuse_rankings(
        {
            "dense": [candidate("a", raw_score=0.8)],
            "graph": [candidate("a", raw_score=7.5)],
        },
        weights={"dense": 2.0, "graph": 0.5},
        rank_constant=10,
    )

    result = fused[0]
    assert result.score == pytest.approx(2.5 / 11)
    assert result.best_rank == 1
    assert result.channels["dense"].rank == 1
    assert result.channels["dense"].weight == 2.0
    assert result.channels["dense"].contribution == pytest.approx(2.0 / 11)
    assert result.channels["graph"].contribution == pytest.approx(0.5 / 11)
    assert result.to_dict()["channels"] == {
        "dense": {
            "rank": 1,
            "raw_score": 0.8,
            "weight": 2.0,
            "contribution": pytest.approx(2.0 / 11),
        },
        "graph": {
            "rank": 1,
            "raw_score": 7.5,
            "weight": 0.5,
            "contribution": pytest.approx(0.5 / 11),
        },
    }


def test_missing_channels_do_not_renormalize_scores() -> None:
    fused = fuse_rankings(
        {"dense": [candidate("a", raw_score=0.8)]},
        weights={"dense": 2.0, "bm25": 8.0},
        rank_constant=10,
    )

    assert fused[0].score == pytest.approx(2.0 / 11)
    assert set(fused[0].channels) == {"dense"}


def test_duplicate_ids_within_channel_count_once_at_first_unique_rank() -> None:
    fused = fuse_rankings(
        {
            "dense": [
                candidate("a", raw_score=0.9),
                candidate("a", raw_score=0.8),
                candidate("b", raw_score=0.7),
            ]
        },
        weights={"dense": 1.0},
        rank_constant=10,
    )

    assert [item.candidate.candidate_id for item in fused] == ["a", "b"]
    assert fused[0].channels["dense"].rank == 1
    assert fused[1].channels["dense"].rank == 2


def test_channel_caps_apply_after_deduplication() -> None:
    fused = fuse_rankings(
        {
            "dense": [
                candidate("a", raw_score=0.9),
                candidate("a", raw_score=0.8),
                candidate("b", raw_score=0.7),
                candidate("c", raw_score=0.6),
            ],
            "graph": [candidate("c", raw_score=3.0)],
        },
        weights={"dense": 1.0, "graph": 1.0},
        channel_caps={"dense": 2, "graph": 1},
    )

    by_id = {item.candidate.candidate_id: item for item in fused}
    assert set(by_id) == {"a", "b", "c"}
    assert "dense" not in by_id["c"].channels
    assert "graph" in by_id["c"].channels


def test_ties_are_deterministic_by_best_rank_then_candidate_id() -> None:
    fused = fuse_rankings(
        {
            "dense": [candidate("b", raw_score=0.8)],
            "bm25": [candidate("a", raw_score=4.0)],
        },
        weights={"dense": 1.0, "bm25": 1.0},
    )

    assert [item.candidate.candidate_id for item in fused] == ["a", "b"]


def test_diversity_caps_repeated_source_but_preserves_multihop_evidence() -> None:
    fused = fuse_rankings(
        {
            "dense": [
                candidate("fact-1", raw_score=0.9, source_memory_id="episode-1"),
                candidate(
                    "fact-2",
                    raw_score=0.8,
                    source_memory_id="episode-1",
                    evidence_source_ids=("episode-1", "episode-3"),
                ),
                candidate("episode-2", raw_score=0.7, source_memory_id="episode-2"),
            ]
        },
        weights={"dense": 1.0},
    )

    diversified = diversify_fused(fused, limit=2, max_per_source=1)

    assert [item.candidate.candidate_id for item in diversified] == ["fact-1", "episode-2"]
    assert fused[1].candidate.evidence_source_ids == ("episode-1", "episode-3")


@pytest.mark.parametrize(
    "weights",
    [
        {"dense": 0.0},
        {"dense": -1.0},
        {"dense": math.nan},
        {"dense": math.inf},
        {},
    ],
)
def test_rrf_rejects_invalid_weights(weights: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        fuse_rankings(
            {"dense": [candidate("a", raw_score=0.8)]},
            weights=weights,
        )


def test_rrf_rejects_conflicting_candidate_identity_across_channels() -> None:
    dense = candidate("same", raw_score=0.8)
    conflicting = RetrievalCandidate(
        candidate_id="same",
        kind="fact",
        content="different",
        source_memory_id="other-source",
        raw_score=4.0,
    )

    with pytest.raises(ValueError, match="conflicting candidate"):
        fuse_rankings(
            {"dense": [dense], "bm25": [conflicting]},
            weights={"dense": 1.0, "bm25": 1.0},
        )


def test_rrf_rejects_conflicting_duplicate_identity_inside_channel() -> None:
    first = candidate("same", raw_score=0.8)
    conflicting = RetrievalCandidate(
        candidate_id="same",
        kind="fact",
        content="different",
        source_memory_id="other-source",
        raw_score=0.7,
    )

    with pytest.raises(ValueError, match="conflicting candidate"):
        fuse_rankings(
            {"dense": [first, conflicting]},
            weights={"dense": 1.0},
        )
