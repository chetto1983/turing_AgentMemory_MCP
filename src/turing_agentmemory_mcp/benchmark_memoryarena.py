"""MemoryArena bucket benchmark stage: sample loading, case construction, hit-rate
scoring, and the `_benchmark_memoryarena` pipeline stage itself. Split out of
`benchmark.py` per D-08/D-09 as its own concern (dataset-specific loading/scoring
vs. the generic synthetic-corpus pipeline stages in `benchmark_stages.py`)."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

from turing_agentmemory_mcp.benchmark_schema import (
    MeasuredBatch,
    MemoryArenaCase,
    make_result_row,
    turingdb_version,
)
from turing_agentmemory_mcp.benchmark_stages import _measure_batch
from turing_agentmemory_mcp.memoryarena import answer_marker, load_samples


def _default_memoryarena_configs() -> list[str]:
    return [
        "bundled_shopping",
        "progressive_search",
        "group_travel_planner",
        "formal_reasoning_math",
        "formal_reasoning_phys",
    ]


def _parse_memoryarena_configs(value: str) -> list[str]:
    if value.strip().lower() in {"", "none", "off", "skip"}:
        return []
    if value.strip().lower() == "all":
        return _default_memoryarena_configs()
    return [part.strip() for part in value.split(",") if part.strip()]


def _compact_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


def _memoryarena_background(sample: dict[str, Any], idx: int) -> str:
    backgrounds = sample.get("backgrounds")
    if isinstance(backgrounds, list) and idx < len(backgrounds):
        return _compact_json(backgrounds[idx])
    if isinstance(backgrounds, str):
        return backgrounds
    base_person = sample.get("base_person")
    if isinstance(base_person, dict):
        return _compact_json(base_person)
    return ""


def _memoryarena_cases_from_sample(config: str, sample: dict[str, Any]) -> list[MemoryArenaCase]:
    questions = [str(question) for question in sample.get("questions") or []]
    answers = sample.get("answers") or []
    if not isinstance(answers, list):
        answers = [answers]
    sample_id = str(sample.get("id", "unknown"))
    source_url = str(sample.get("_source_url", ""))
    cases: list[MemoryArenaCase] = []
    for idx, question in enumerate(questions):
        if idx >= len(answers):
            break
        answer = answers[idx]
        cases.append(
            MemoryArenaCase(
                config=config,
                sample_id=sample_id,
                subtask_index=idx,
                question=question,
                answer=answer,
                marker=answer_marker(answer),
                background=_memoryarena_background(sample, idx),
                source_url=source_url,
            )
        )
    return cases


def _load_memoryarena_cases(
    *,
    configs: Sequence[str],
    start_index: int,
    samples_per_config: int,
    cases_per_config: int,
) -> list[MemoryArenaCase]:
    cases: list[MemoryArenaCase] = []
    for config in configs:
        samples = load_samples(config, start_index=start_index, limit=samples_per_config)
        config_cases: list[MemoryArenaCase] = []
        for sample in samples:
            config_cases.extend(_memoryarena_cases_from_sample(config, sample))
            if len(config_cases) >= cases_per_config:
                break
        cases.extend(config_cases[:cases_per_config])
    return cases


def _memoryarena_marker_hit(result: Any, marker: str) -> bool:
    return bool(result) and any(marker and marker in item.content for item in result)


def _memoryarena_marker_hit_rate(batch: MeasuredBatch, cases: Sequence[MemoryArenaCase]) -> float:
    if not cases:
        return 0.0
    hits = sum(
        1
        for case, result in zip(cases, batch.results, strict=False)
        if _memoryarena_marker_hit(result, case.marker)
    )
    return round(hits / len(cases), 4)


def _memoryarena_top1_hit_rate(batch: MeasuredBatch, cases: Sequence[MemoryArenaCase]) -> float:
    if not cases:
        return 0.0
    hits = 0
    for case, result in zip(cases, batch.results, strict=False):
        if result and case.marker and case.marker in result[0].content:
            hits += 1
    return round(hits / len(cases), 4)


def _memoryarena_config_counts(cases: Sequence[MemoryArenaCase]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.config] = counts.get(case.config, 0) + 1
    return counts


def _benchmark_memoryarena(
    store: Any,
    *,
    timestamp: str,
    git_commit: str,
    embedding_model: str,
    rerank_model: str,
    memoryarena_index: int,
    memoryarena_configs: Sequence[str],
    samples_per_config: int,
    cases_per_config: int,
    top_k: int,
) -> list[dict[str, Any]]:
    error_started = time.perf_counter()
    configs = list(memoryarena_configs)
    if not configs:
        return []
    try:
        cases = _load_memoryarena_cases(
            configs=configs,
            start_index=memoryarena_index,
            samples_per_config=samples_per_config,
            cases_per_config=cases_per_config,
        )
        if not cases:
            raise RuntimeError("no MemoryArena cases loaded")
        user = "bench-memoryarena-user"
        store_batch = _measure_batch(
            cases,
            lambda case: store.store_message(
                user_identifier=user,
                session_id=f"memoryarena-{case.config}",
                role="assistant",
                content=case.content,
                memory_id=case.memory_id,
                source="memoryarena-bucket",
                tags=["memoryarena", case.config],
                metadata={
                    "dataset": "memoryarena",
                    "config": case.config,
                    "sample_id": case.sample_id,
                    "subtask_index": case.subtask_index,
                    "source_url": case.source_url,
                    "answer_marker": case.marker,
                },
            ),
            lambda result, case: result.id == case.memory_id,
        )
        search_batch = _measure_batch(
            cases,
            lambda case: store.search_memory(
                user_identifier=user,
                query=case.query,
                limit=top_k,
            ),
            lambda result, case: _memoryarena_marker_hit(result, case.marker),
        )
        marker_hit_rate = _memoryarena_marker_hit_rate(search_batch, cases)
        top1_hit_rate = _memoryarena_top1_hit_rate(search_batch, cases)
        source_urls = sorted({case.source_url for case in cases})
        config_counts = _memoryarena_config_counts(cases)
        return [
            make_result_row(
                timestamp=timestamp,
                git_commit=git_commit,
                turingdb_version=turingdb_version,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                dataset="memoryarena-bucket",
                operation="memoryarena_bucket_store",
                durations_ms=store_batch.durations_ms,
                successes=store_batch.successes,
                notes=(
                    f"configs={','.join(configs)}; cases={len(cases)}; "
                    f"errors={len(store_batch.errors)}"
                ),
                metadata={
                    "configs": configs,
                    "config_counts": config_counts,
                    "samples_per_config": samples_per_config,
                    "cases_per_config": cases_per_config,
                    "source_urls": source_urls,
                    "errors": store_batch.errors[:3],
                },
            ),
            make_result_row(
                timestamp=timestamp,
                git_commit=git_commit,
                turingdb_version=turingdb_version,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                dataset="memoryarena-bucket",
                operation="memoryarena_bucket_retrieval",
                durations_ms=search_batch.durations_ms,
                successes=search_batch.successes,
                notes=(
                    f"top_k={top_k}; marker_hit_rate={marker_hit_rate:.3f}; "
                    f"top1_hit_rate={top1_hit_rate:.3f}; errors={len(search_batch.errors)}"
                ),
                metadata={
                    "top_k": top_k,
                    "marker_hit_rate": marker_hit_rate,
                    "top1_hit_rate": top1_hit_rate,
                    "configs": configs,
                    "config_counts": config_counts,
                    "source_urls": source_urls,
                    "errors": search_batch.errors[:3],
                },
            ),
        ]
    except Exception as exc:
        duration_ms = (time.perf_counter() - error_started) * 1000
        return [
            make_result_row(
                timestamp=timestamp,
                git_commit=git_commit,
                turingdb_version=turingdb_version,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                dataset="memoryarena-bucket",
                operation="memoryarena_bucket_retrieval",
                durations_ms=[duration_ms],
                successes=0,
                notes=f"error={type(exc).__name__}: {str(exc)[:240]}",
                metadata={"configs": configs},
            )
        ]
