from __future__ import annotations

import pytest

from turing_agentmemory_mcp.search_controls import (
    build_score_details,
    passes_threshold,
    validate_fusion_weights,
    validate_search_query,
    validate_threshold,
)


def test_validate_search_query_rejects_blank_queries() -> None:
    with pytest.raises(ValueError, match="query"):
        validate_search_query("  ")


def test_validate_search_query_trims_non_blank_query() -> None:
    assert validate_search_query("  espresso memory  ") == "espresso memory"


def test_validate_threshold_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="threshold"):
        validate_threshold(1.1)


def test_threshold_filters_scores_below_floor() -> None:
    assert passes_threshold(0.42, 0.4)
    assert not passes_threshold(0.39, 0.4)


def test_build_score_details_includes_semantic_threshold_and_final_score() -> None:
    details = build_score_details(
        semantic_score=0.72,
        lexical_score=0.8,
        threshold=0.4,
        final_score=0.91,
        rerank_score=0.91,
    )

    assert details == {
        "semantic_score": 0.72,
        "lexical_score": 0.8,
        "threshold": 0.4,
        "rerank_score": 0.91,
        "final_score": 0.91,
    }


def test_validate_fusion_weights_returns_stable_float_mapping() -> None:
    assert validate_fusion_weights({"graph": 2, "dense": 1.5}) == {
        "dense": 1.5,
        "graph": 2.0,
    }


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, "1"])
def test_validate_fusion_weights_rejects_non_positive_finite_numbers(value: object) -> None:
    with pytest.raises(ValueError, match="weight"):
        validate_fusion_weights({"dense": value})  # type: ignore[dict-item]


def test_validate_fusion_weights_rejects_non_string_channel() -> None:
    with pytest.raises(ValueError, match="channel"):
        validate_fusion_weights({1: 1.0})  # type: ignore[dict-item]
