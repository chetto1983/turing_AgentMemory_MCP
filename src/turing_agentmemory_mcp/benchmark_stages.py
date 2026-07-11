"""Synthetic-corpus benchmark pipeline stages (memory store/search, document
ingest/search, rerank on/off comparison, restart durability) plus the shared
`_measure_batch` timing helper. Split out of `benchmark.py` per D-08/D-09; the
MemoryArena-bucket stage lives separately in `benchmark_memoryarena.py` since it
depends on this module's `_measure_batch`."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from turing_agentmemory_mcp.benchmark_schema import MeasuredBatch, make_result_row, turingdb_version
from turing_agentmemory_mcp.rerank import OpenAICompatibleReranker


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
