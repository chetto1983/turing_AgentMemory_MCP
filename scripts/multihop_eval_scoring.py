"""Deterministic measurements for the Phase 07.1 multi-hop retrieval evaluation.

The existing real-document ``_metrics`` contract assumes one relevant passage per question.
D-08 instead measures set-recall over multiple bridging passages, and D-15 aggregates those
per-question measurements without folding question-level regressions into a mean.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

try:
    from real_document_benchmark_scoring import normalize_text
except ImportError:
    from scripts.real_document_benchmark_scoring import normalize_text

MULTIHOP_REQUIRED_KEYS = frozenset(
    {
        "source_id",
        "question",
        "answer",
        "bridging_passages",
    }
)

__all__ = [
    "MULTIHOP_REQUIRED_KEYS",
    "bridging_set_recall_at_k",
    "load_multihop_questions",
    "normalize_text",
    "single_passage_answerable",
    "summarize_multihop_results",
]


def bridging_set_recall_at_k(
    hits: list[dict[str, Any]],
    bridging_passages: list[str],
    k: int,
) -> float:
    required = {normalize_text(passage) for passage in bridging_passages}
    required.discard("")
    if not required:
        raise ValueError("bridging_passages must contain at least one passage")

    normalized_hits = [normalize_text(hit.get("text")) for hit in hits[: max(k, 0)]]
    found = sum(any(passage in hit_text for hit_text in normalized_hits) for passage in required)
    return found / len(required)


def single_passage_answerable(
    hits: list[dict[str, Any]],
    answer: str,
    evidence_quote: str,
) -> bool:
    normalized_answer = normalize_text(answer)
    normalized_evidence = normalize_text(evidence_quote)
    for hit in hits:
        hit_text = normalize_text(hit.get("text"))
        if normalized_answer and normalized_answer in hit_text:
            return True
        if normalized_evidence and normalized_evidence in hit_text:
            return True
    return False


def load_multihop_questions(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("multi-hop questions must be a JSON array")

    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"multi-hop question row {index} must be an object")
        missing = MULTIHOP_REQUIRED_KEYS - row.keys()
        if missing:
            missing_keys = ", ".join(sorted(missing))
            raise ValueError(
                f"multi-hop question row {index} missing required keys: {missing_keys}"
            )

        bridging_passages = row["bridging_passages"]
        if not isinstance(bridging_passages, list) or not all(
            isinstance(passage, str) for passage in bridging_passages
        ):
            raise ValueError(
                f"multi-hop question row {index} bridging_passages must be a list[str]"
            )
        if len(bridging_passages) < 2:
            raise ValueError(
                f"multi-hop question row {index} bridging_passages must contain at least 2 entries"
            )

    return payload


def summarize_multihop_results(
    per_question_by_arm: dict[str, list[float]],
    *,
    baseline_arm: str,
) -> dict[str, dict[str, float | int]]:
    if baseline_arm not in per_question_by_arm:
        raise ValueError(f"unknown baseline arm: {baseline_arm}")

    baseline_values = per_question_by_arm[baseline_arm]
    if not baseline_values:
        raise ValueError("multi-hop results must contain at least one question")
    if any(len(values) != len(baseline_values) for values in per_question_by_arm.values()):
        raise ValueError("all arms must measure the same questions")

    return {
        arm: {
            "mean_set_recall_at_k": statistics.fmean(values),
            "improved": sum(
                value > baseline for value, baseline in zip(values, baseline_values, strict=True)
            ),
            "regressed": sum(
                value < baseline for value, baseline in zip(values, baseline_values, strict=True)
            ),
        }
        for arm, values in sorted(per_question_by_arm.items())
    }
