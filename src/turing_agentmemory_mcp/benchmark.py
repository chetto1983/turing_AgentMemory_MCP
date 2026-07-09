from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from turing_agentmemory_mcp.memoryarena import answer_marker, load_samples
from turing_agentmemory_mcp.rerank import OpenAICompatibleReranker

try:
    from turingdb import __version__ as turingdb_version
except ModuleNotFoundError:
    turingdb_version = "unavailable"

ROOT = Path(__file__).resolve().parents[2]

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


def run_benchmarks(
    *,
    out: Path,
    memory_count: int = 40,
    search_count: int = 20,
    document_count: int = 5,
    top_k: int = 5,
    use_external_embed: bool = False,
    use_external_rerank: bool = False,
    keep_home: bool = False,
    memoryarena_index: int = 0,
    memoryarena_configs: Sequence[str] | None = None,
    memoryarena_samples_per_config: int = 1,
    memoryarena_cases_per_config: int = 8,
) -> list[dict[str, Any]]:
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    git_commit = _git_commit()
    home = Path(os.environ.get("TURINGDB_BENCH_HOME", ROOT / ".turingdb" / "benchmark"))
    graph = f"benchmark_agent_memory_{int(time.time())}"
    from turing_agentmemory_mcp.e2e_score import (
        LocalEmbedServer,
        LocalRerankServer,
        TuringDaemon,
    )
    from turing_agentmemory_mcp.store import TuringAgentMemory

    embed_server: Any | None = None
    rerank_server: Any | None = None
    daemon = TuringDaemon(home)
    previous_env = {
        key: os.environ.get(key)
        for key in (
            "EMBED_BASE_URL",
            "EMBED_DIMENSIONS",
            "EMBED_MODEL",
            "RERANK_BASE_URL",
            "RERANK_MODEL",
        )
    }
    rows: list[dict[str, Any]] = []
    store: TuringAgentMemory | None = None

    try:
        if home.exists() and not keep_home:
            shutil.rmtree(home)
        if not use_external_embed:
            embed_server = LocalEmbedServer(dimensions=768)
            embed_server.start()
            os.environ["EMBED_BASE_URL"] = embed_server.base_url
            os.environ["EMBED_DIMENSIONS"] = "768"
            os.environ["EMBED_MODEL"] = "local-embedding"
        if not use_external_rerank:
            rerank_server = LocalRerankServer()
            rerank_server.start()
            os.environ["RERANK_BASE_URL"] = rerank_server.base_url
            os.environ["RERANK_MODEL"] = "local-rerank"

        embedding_model = os.environ.get("EMBED_MODEL", "local-embedding")
        rerank_model = os.environ.get("RERANK_MODEL", "local-rerank")

        daemon.start()
        store = TuringAgentMemory(daemon.client(), turing_home=home, graph=graph)
        store.bootstrap()

        rows.extend(
            _benchmark_memory_store(
                store,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                memory_count=memory_count,
            )
        )
        rows.extend(
            _benchmark_memory_store_batch(
                store,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                memory_count=memory_count,
            )
        )
        rows.extend(
            _benchmark_memory_search(
                store,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                memory_count=memory_count,
                search_count=search_count,
                top_k=top_k,
            )
        )
        rows.extend(
            _benchmark_documents(
                store,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                document_count=document_count,
                search_count=search_count,
                top_k=top_k,
            )
        )
        rows.extend(
            _benchmark_rerank_comparison(
                store,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                memory_count=memory_count,
                search_count=max(8, min(search_count, 16)),
                top_k=top_k,
            )
        )
        rows.extend(
            _benchmark_memoryarena(
                store,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                memoryarena_index=memoryarena_index,
                memoryarena_configs=list(memoryarena_configs or _default_memoryarena_configs()),
                samples_per_config=memoryarena_samples_per_config,
                cases_per_config=memoryarena_cases_per_config,
                top_k=top_k,
            )
        )
        rows.append(
            _benchmark_restart(
                daemon=daemon,
                home=home,
                graph=graph,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
            )
        )
    finally:
        daemon.stop()
        if embed_server is not None:
            embed_server.stop()
        if rerank_server is not None:
            rerank_server.stop()
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    return rows


def default_output_path() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / ".benchmarks" / f"benchmark-{stamp}.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=default_output_path())
    parser.add_argument("--memory-count", type=int, default=40)
    parser.add_argument("--search-count", type=int, default=20)
    parser.add_argument("--document-count", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--use-external-embed", action="store_true")
    parser.add_argument("--use-external-rerank", action="store_true")
    parser.add_argument("--keep-home", action="store_true")
    parser.add_argument("--memoryarena-index", type=int, default=0)
    parser.add_argument(
        "--memoryarena-configs",
        default=",".join(_default_memoryarena_configs()),
        help="Comma-separated MemoryArena configs, or 'none' to skip.",
    )
    parser.add_argument("--memoryarena-samples-per-config", type=int, default=1)
    parser.add_argument("--memoryarena-cases-per-config", type=int, default=8)
    args = parser.parse_args()
    memoryarena_configs = _parse_memoryarena_configs(args.memoryarena_configs)
    rows = run_benchmarks(
        out=args.out,
        memory_count=args.memory_count,
        search_count=args.search_count,
        document_count=args.document_count,
        top_k=args.top_k,
        use_external_embed=args.use_external_embed,
        use_external_rerank=args.use_external_rerank,
        keep_home=args.keep_home,
        memoryarena_index=args.memoryarena_index,
        memoryarena_configs=memoryarena_configs,
        memoryarena_samples_per_config=args.memoryarena_samples_per_config,
        memoryarena_cases_per_config=args.memoryarena_cases_per_config,
    )
    print(json.dumps({"out": str(args.out), "result_count": len(rows)}, sort_keys=True))
    return 0


def _benchmark_memory_store(
    store: Any,
    *,
    timestamp: str,
    git_commit: str,
    embedding_model: str,
    rerank_model: str,
    memory_count: int,
) -> list[dict[str, Any]]:
    user = "bench-memory-user"
    items = list(range(memory_count))
    wall_start = time.perf_counter()
    batch = _measure_batch(
        items,
        lambda idx: store.store_message(
            user_identifier=user,
            session_id=f"session-{idx % 4}",
            role="user",
            content=_memory_content(idx),
            memory_id=f"bench-memory-{idx}",
        ),
        lambda result, _idx: result.user_identifier == user,
    )
    wall_ms = (time.perf_counter() - wall_start) * 1000
    throughput = memory_count / (wall_ms / 1000) if wall_ms else 0.0
    return [
        make_result_row(
            timestamp=timestamp,
            git_commit=git_commit,
            turingdb_version=turingdb_version,
            embedding_model=embedding_model,
            rerank_model=rerank_model,
            dataset=f"synthetic-memory-{memory_count}",
            operation="memory_store_message",
            durations_ms=batch.durations_ms,
            successes=batch.successes,
            notes=f"throughput_per_second={throughput:.2f}; errors={len(batch.errors)}",
            metadata={"throughput_per_second": round(throughput, 3), "errors": batch.errors[:3]},
        )
    ]


def _benchmark_memory_store_batch(
    store: Any,
    *,
    timestamp: str,
    git_commit: str,
    embedding_model: str,
    rerank_model: str,
    memory_count: int,
    batch_size: int = 10,
) -> list[dict[str, Any]]:
    user = "bench-memory-batch-user"
    batches = [
        list(range(start, min(start + batch_size, memory_count)))
        for start in range(0, memory_count, batch_size)
    ]
    wall_start = time.perf_counter()
    batch = _measure_batch(
        batches,
        lambda ids: store.store_messages(
            user_identifier=user,
            source="benchmark-batch",
            tags=["batch"],
            metadata={"benchmark": "memory_store_messages"},
            messages=[
                {
                    "session_id": f"batch-session-{idx % 4}",
                    "role": "user",
                    "content": _memory_batch_content(idx),
                    "memory_id": f"bench-memory-batch-{idx}",
                }
                for idx in ids
            ],
        ),
        lambda result, ids: len(result) == len(ids)
        and all(item.user_identifier == user for item in result),
    )
    wall_ms = (time.perf_counter() - wall_start) * 1000
    throughput = memory_count / (wall_ms / 1000) if wall_ms else 0.0
    return [
        make_result_row(
            timestamp=timestamp,
            git_commit=git_commit,
            turingdb_version=turingdb_version,
            embedding_model=embedding_model,
            rerank_model=rerank_model,
            dataset=f"synthetic-memory-batch-{memory_count}",
            operation="memory_store_messages_batch",
            durations_ms=batch.durations_ms,
            successes=batch.successes,
            notes=(
                f"messages={memory_count}; batch_size={batch_size}; "
                f"throughput_per_second={throughput:.2f}; errors={len(batch.errors)}"
            ),
            metadata={
                "messages": memory_count,
                "batch_size": batch_size,
                "throughput_per_second": round(throughput, 3),
                "errors": batch.errors[:3],
            },
        )
    ]


def _benchmark_memory_search(
    store: Any,
    *,
    timestamp: str,
    git_commit: str,
    embedding_model: str,
    rerank_model: str,
    memory_count: int,
    search_count: int,
    top_k: int,
) -> list[dict[str, Any]]:
    user = "bench-memory-user"
    queries = list(range(search_count))
    batch = _measure_batch(
        queries,
        lambda idx: store.search_memory(
            user_identifier=user,
            query=_memory_query(idx, memory_count),
            limit=top_k,
        ),
        lambda result, _idx: bool(result) and all(item.user_identifier == user for item in result),
    )
    top1_hits = _top1_memory_hits(batch, memory_count)
    return [
        make_result_row(
            timestamp=timestamp,
            git_commit=git_commit,
            turingdb_version=turingdb_version,
            embedding_model=embedding_model,
            rerank_model=rerank_model,
            dataset=f"synthetic-memory-{memory_count}",
            operation="memory_search_top_k",
            durations_ms=batch.durations_ms,
            successes=batch.successes,
            notes=f"top_k={top_k}; top1_expected_rate={top1_hits:.3f}; errors={len(batch.errors)}",
            metadata={"top_k": top_k, "top1_expected_rate": top1_hits, "errors": batch.errors[:3]},
        )
    ]


def _benchmark_documents(
    store: Any,
    *,
    timestamp: str,
    git_commit: str,
    embedding_model: str,
    rerank_model: str,
    document_count: int,
    search_count: int,
    top_k: int,
) -> list[dict[str, Any]]:
    user = "bench-document-user"
    sections = 8
    doc_ids = [f"bench-doc-{idx}" for idx in range(document_count)]
    ingest_batch = _measure_batch(
        doc_ids,
        lambda doc_id: store.ingest_document_text(
            user_identifier=user,
            document_id=doc_id,
            title=f"Benchmark Manual {doc_id}",
            text=_document_text(doc_id, sections=sections),
        ),
        lambda result, _doc_id: result.chunk_count >= sections,
    )
    chunk_total = sum(result.chunk_count for result in ingest_batch.results if result is not None)
    search_items = list(range(search_count))
    search_batch = _measure_batch(
        search_items,
        lambda idx: store.search_documents(
            user_identifier=user,
            query=_document_query(doc_ids[idx % len(doc_ids)], idx),
            limit=top_k,
        ),
        lambda result, _idx: bool(result)
        and bool(result[0].chunk_id)
        and bool(result[0].locator)
        and result[0].context is not None,
    )
    citation_rate = _citation_hit_rate(search_batch)
    return [
        make_result_row(
            timestamp=timestamp,
            git_commit=git_commit,
            turingdb_version=turingdb_version,
            embedding_model=embedding_model,
            rerank_model=rerank_model,
            dataset=f"synthetic-documents-{document_count}",
            operation="document_ingest_text",
            durations_ms=ingest_batch.durations_ms,
            successes=ingest_batch.successes,
            notes=f"chunk_total={chunk_total}; errors={len(ingest_batch.errors)}",
            metadata={
                "chunk_total": chunk_total,
                "avg_chunks_per_document": round(chunk_total / document_count, 3),
                "errors": ingest_batch.errors[:3],
            },
        ),
        make_result_row(
            timestamp=timestamp,
            git_commit=git_commit,
            turingdb_version=turingdb_version,
            embedding_model=embedding_model,
            rerank_model=rerank_model,
            dataset=f"synthetic-documents-{document_count}",
            operation="document_search_with_citations",
            durations_ms=search_batch.durations_ms,
            successes=search_batch.successes,
            notes=f"top_k={top_k}; citation_rate={citation_rate:.3f}; errors={len(search_batch.errors)}",
            metadata={"top_k": top_k, "citation_rate": citation_rate, "errors": search_batch.errors[:3]},
        ),
    ]


def _benchmark_rerank_comparison(
    store: Any,
    *,
    timestamp: str,
    git_commit: str,
    embedding_model: str,
    rerank_model: str,
    memory_count: int,
    search_count: int,
    top_k: int,
) -> list[dict[str, Any]]:
    user = "bench-memory-user"
    queries = list(range(search_count))
    original_reranker = store.reranker
    try:
        store.reranker = None
        off_batch = _measure_batch(
            queries,
            lambda idx: store.search_memory(
                user_identifier=user,
                query=_memory_query(idx, memory_count),
                limit=top_k,
            ),
            lambda result, _idx: bool(result),
        )
        store.reranker = OpenAICompatibleReranker.from_env()
        on_batch = _measure_batch(
            queries,
            lambda idx: store.search_memory(
                user_identifier=user,
                query=_memory_query(idx, memory_count),
                limit=top_k,
            ),
            lambda result, _idx: bool(result),
        )
    finally:
        store.reranker = original_reranker

    off_top1 = _top1_memory_hits(off_batch, memory_count)
    on_top1 = _top1_memory_hits(on_batch, memory_count)
    return [
        make_result_row(
            timestamp=timestamp,
            git_commit=git_commit,
            turingdb_version=turingdb_version,
            embedding_model=embedding_model,
            rerank_model="off",
            dataset=f"synthetic-memory-{memory_count}",
            operation="memory_search_rerank_off",
            durations_ms=off_batch.durations_ms,
            successes=off_batch.successes,
            notes=f"top_k={top_k}; top1_expected_rate={off_top1:.3f}; rerank_disabled=true",
            metadata={"top_k": top_k, "top1_expected_rate": off_top1},
        ),
        make_result_row(
            timestamp=timestamp,
            git_commit=git_commit,
            turingdb_version=turingdb_version,
            embedding_model=embedding_model,
            rerank_model=rerank_model,
            dataset=f"synthetic-memory-{memory_count}",
            operation="memory_search_rerank_on",
            durations_ms=on_batch.durations_ms,
            successes=on_batch.successes,
            notes=(
                f"top_k={top_k}; top1_expected_rate={on_top1:.3f}; "
                f"RERANK_BASE_URL={os.environ.get('RERANK_BASE_URL', '')}"
            ),
            metadata={
                "top_k": top_k,
                "top1_expected_rate": on_top1,
                "rerank_base_url": os.environ.get("RERANK_BASE_URL", ""),
            },
        ),
    ]


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


def _benchmark_restart(
    *,
    daemon: Any,
    home: Path,
    graph: str,
    timestamp: str,
    git_commit: str,
    embedding_model: str,
    rerank_model: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    cleanup = daemon.stop()
    restarted = daemon.__class__(home)
    try:
        restarted.start()
        from turing_agentmemory_mcp.store import TuringAgentMemory

        store = TuringAgentMemory(restarted.client(), turing_home=home, graph=graph)
        store.load_graph_after_restart()
        memory = store.search_memory(
            user_identifier="bench-memory-user",
            query=_memory_query(0, 1),
            limit=1,
        )
        docs = store.search_documents(
            user_identifier="bench-document-user",
            query=_document_query("bench-doc-0", 0),
            limit=1,
        )
        success = bool(memory) and bool(docs) and docs[0].document_id == "bench-doc-0"
        duration_ms = (time.perf_counter() - started) * 1000
        return make_result_row(
            timestamp=timestamp,
            git_commit=git_commit,
            turingdb_version=turingdb_version,
            embedding_model=embedding_model,
            rerank_model=rerank_model,
            dataset="synthetic-memory-and-documents",
            operation="restart_durability_retrieval",
            durations_ms=[duration_ms],
            successes=1 if success else 0,
            notes=f"cleanup_returncode={cleanup.get('returncode')}; retrieved_memory={bool(memory)}",
            metadata={
                "retrieved_document": docs[0].document_id if docs else "",
                "retrieved_memory": bool(memory),
                "restart_cleanup": cleanup,
            },
        )
    finally:
        restarted.stop()


def _measure_batch(
    items: Sequence[Any],
    fn: Callable[[Any], Any],
    ok: Callable[[Any, Any], bool],
) -> MeasuredBatch:
    durations_ms: list[float] = []
    successes = 0
    errors: list[str] = []
    results: list[Any | None] = []
    for item in items:
        started = time.perf_counter()
        result: Any | None = None
        try:
            result = fn(item)
            if ok(result, item):
                successes += 1
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {str(exc)[:240]}")
        finally:
            durations_ms.append(round((time.perf_counter() - started) * 1000, 3))
            results.append(result)
    return MeasuredBatch(
        items=list(items),
        durations_ms=durations_ms,
        successes=successes,
        errors=errors,
        results=results,
    )


def _memory_content(idx: int) -> str:
    topic = idx % 7
    return (
        f"benchmark memory marker=mem-{idx} topic=topic-{topic} "
        f"stores TuringDB retrieval preference for latency lane {idx % 5}"
    )


def _memory_batch_content(idx: int) -> str:
    topic = idx % 7
    return (
        f"benchmark batch memory marker=batch-mem-{idx} topic=topic-{topic} "
        f"stores TuringDB batch retrieval preference for latency lane {idx % 5}"
    )


def _memory_query(idx: int, memory_count: int) -> str:
    memory_idx = idx % max(memory_count, 1)
    return f"TuringDB retrieval marker mem-{memory_idx} topic-{memory_idx % 7}"


def _document_text(doc_id: str, *, sections: int) -> str:
    rows = []
    for idx in range(sections):
        rows.append(
            f"{doc_id} section {idx} calibration token {doc_id}-token-{idx} "
            "requires guard interlock verification, blue key reset, and citation-ready "
            f"neighbor context for benchmark retrieval lane {idx}."
        )
    return "\n".join(rows)


def _document_query(doc_id: str, idx: int) -> str:
    section = idx % 4
    return f"{doc_id} token {doc_id}-token-{section} guard interlock citation"


def _top1_memory_hits(batch: MeasuredBatch, memory_count: int) -> float:
    if not batch.results:
        return 0.0
    hits = 0
    for item, result in zip(batch.items, batch.results, strict=False):
        if not result:
            continue
        expected = f"marker=mem-{int(item) % max(memory_count, 1)}"
        if expected in result[0].content:
            hits += 1
    return round(hits / len(batch.results), 4)


def _citation_hit_rate(batch: MeasuredBatch) -> float:
    if not batch.results:
        return 0.0
    hits = 0
    for result in batch.results:
        if result and result[0].chunk_id and result[0].locator:
            hits += 1
    return round(hits / len(batch.results), 4)


def _percentile(values: Sequence[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return round(ordered[rank - 1], 3)


def _git_commit() -> str:
    configured = os.environ.get("BENCHMARK_GIT_COMMIT") or os.environ.get("GIT_COMMIT")
    if configured:
        return configured
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.stdout.strip()
    except Exception:
        return _git_head_commit()


def _git_head_commit() -> str:
    head = ROOT / ".git" / "HEAD"
    try:
        value = head.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if value.startswith("ref:"):
        ref_path = value.split(":", 1)[1].strip()
        try:
            value = (ROOT / ".git" / ref_path).read_text(encoding="utf-8").strip()
        except OSError:
            return "unknown"
    return value[:7] if value else "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
