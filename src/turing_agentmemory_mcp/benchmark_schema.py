"""Result-row schema and shared measurement dataclasses for `benchmark.py`.

Kept as a standalone concern (per D-08/D-09) so both the pipeline-stage runner
(`benchmark_stages.py`) and the MemoryArena runner (`benchmark_memoryarena.py`)
can depend on it without importing from `benchmark.py` itself.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

try:
    from turingdb import __version__ as turingdb_version
except ModuleNotFoundError:
    turingdb_version = "unavailable"

REQUIRED_FIELDS = (
    "timestamp",
    "git_commit",
    "turingdb_version",
    "embedding_model",
    "rerank_model",
    "dataset",
    "operation",
    "count",
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "success_rate",
    "notes",
)


@dataclass
class MeasuredBatch:
    items: list[Any]
    durations_ms: list[float]
    successes: int
    errors: list[str]
    results: list[Any | None]


@dataclass(frozen=True)
class MemoryArenaCase:
    config: str
    sample_id: str
    subtask_index: int
    question: str
    answer: Any
    marker: str
    background: str
    source_url: str

    @property
    def memory_id(self) -> str:
        return f"memoryarena-{self.config}-{self.sample_id}-{self.subtask_index}"

    @property
    def query(self) -> str:
        return f"MemoryArena {self.config} subtask {self.subtask_index}: {self.question}"

    @property
    def content(self) -> str:
        return (
            f"MemoryArena config={self.config} id={self.sample_id} subtask={self.subtask_index}\n"
            f"question: {self.question}\n"
            f"background: {self.background}\n"
            f"answer_marker: {self.marker}\n"
            f"answer_json: {json.dumps(self.answer, ensure_ascii=True, sort_keys=True, default=str)}"
        )


def _percentile(values: Sequence[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return round(ordered[rank - 1], 3)


def make_result_row(
    *,
    timestamp: str,
    git_commit: str,
    turingdb_version: str,
    embedding_model: str,
    rerank_model: str,
    dataset: str,
    operation: str,
    durations_ms: Sequence[float],
    successes: int,
    notes: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    count = len(durations_ms)
    row: dict[str, Any] = {
        "timestamp": timestamp,
        "git_commit": git_commit,
        "turingdb_version": turingdb_version,
        "embedding_model": embedding_model,
        "rerank_model": rerank_model,
        "dataset": dataset,
        "operation": operation,
        "count": count,
        "p50_ms": _percentile(durations_ms, 50),
        "p95_ms": _percentile(durations_ms, 95),
        "p99_ms": _percentile(durations_ms, 99),
        "success_rate": round(successes / count, 4) if count else 0.0,
        "notes": notes,
    }
    if metadata:
        row["metadata"] = metadata
    return row
