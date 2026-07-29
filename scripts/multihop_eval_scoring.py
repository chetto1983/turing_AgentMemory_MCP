"""Deterministic measurements for the Phase 07.1 multi-hop retrieval evaluation.

The existing real-document ``_metrics`` contract assumes one relevant passage per question.
D-08 instead measures set-recall over multiple bridging passages, and D-15 aggregates those
per-question measurements without folding question-level regressions into a mean.
"""

from __future__ import annotations

from typing import Any

try:
    from real_document_benchmark_scoring import normalize_text
except ImportError:
    from scripts.real_document_benchmark_scoring import normalize_text

__all__ = [
    "bridging_set_recall_at_k",
    "normalize_text",
    "single_passage_answerable",
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
