from __future__ import annotations

import math
from collections.abc import Mapping


def validate_search_query(query: str) -> str:
    if not isinstance(query, str):
        raise ValueError("query must be a non-empty string")
    trimmed = query.strip()
    if not trimmed:
        raise ValueError("query must be a non-empty string")
    return trimmed


def validate_threshold(threshold: float | int) -> float:
    if isinstance(threshold, bool) or not isinstance(threshold, (float, int)):
        raise ValueError("threshold must be a number between 0 and 1")
    value = float(threshold)
    if value < 0.0 or value > 1.0:
        raise ValueError("threshold must be between 0 and 1")
    return value


def passes_threshold(score: float, threshold: float) -> bool:
    return float(score) >= threshold


def validate_fusion_weights(weights: Mapping[str, object]) -> dict[str, float]:
    if not isinstance(weights, Mapping) or not weights:
        raise ValueError("fusion weights must be a non-empty mapping")
    if any(not isinstance(channel, str) or not channel.strip() for channel in weights):
        raise ValueError("fusion weight channel must be non-empty")
    validated: dict[str, float] = {}
    for channel in sorted(weights):
        raw_weight = weights[channel]
        if isinstance(raw_weight, bool) or not isinstance(raw_weight, (int, float)):
            raise ValueError(f"fusion weight for {channel} must be a positive finite number")
        weight = float(raw_weight)
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError(f"fusion weight for {channel} must be a positive finite number")
        validated[channel] = weight
    return validated


def build_score_details(
    *,
    semantic_score: float,
    threshold: float,
    final_score: float,
    lexical_score: float | None = None,
    rerank_score: float | None = None,
) -> dict[str, float]:
    details = {
        "semantic_score": round(float(semantic_score), 6),
        "threshold": round(float(threshold), 6),
    }
    if lexical_score is not None:
        details["lexical_score"] = round(float(lexical_score), 6)
    if rerank_score is not None:
        details["rerank_score"] = round(float(rerank_score), 6)
    details["final_score"] = round(float(final_score), 6)
    return details
