"""Run Backboard LoCoMo dataset retrieval evaluation through the MCP stdio bridge.

This runner ingests only raw conversation turns, then scores memory_search
results against the dataset evidence ids. It does not call Backboard APIs or
inject LoCoMo gold answers into memory.

Split by concern per D-08/D-09: dataset loading, LoCoMo message building, and
deterministic metrics helpers live in `eval_backboard_locomo_mcp_dataset.py`.
`call_tool`, `ingest_conversation`, `evaluate_question`, and
`evaluate_conversation` stay here because `tests/test_backboard_locomo_runner.py`
monkeypatches this module's `call_tool` global and relies on those functions
resolving it via this module's own namespace at call time. Every dataset-module
symbol is re-imported unchanged so `tests/test_backboard_locomo_runner.py`'s
`runner.<name>` attribute access keeps resolving. Not wired into CI (D-10).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import defaultdict
from collections.abc import Sequence
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastmcp import Client

try:
    from eval_backboard_locomo_mcp_dataset import (  # noqa: F401 - some re-exported for tests
        CATEGORY_NAMES,
        COMPARABLE_CUTOFFS,
        MAX_INGEST_BATCH,
        QuestionEvaluation,
        ResumeState,
        answer_in_hits,
        build_messages,
        chunks,
        compact_hit,
        estimate_tokens,
        extraction_summary_from_runtime,
        finalize_metrics,
        git_commit,
        init_metric_counts,
        mcp_transport,
        parse_args,
        question_rows,
        require_entity_model,
        result_ref,
        resume_state,
        retrieval_cutoffs,
        retrieval_diagnostics,
        summarize_entity_extraction,
        turn_content,
        update_metrics,
        utc_timestamp,
        validate_batch_size,
        validate_search_concurrency,
    )
except ImportError:  # running as `python scripts/eval_backboard_locomo_mcp.py` directly
    from scripts.eval_backboard_locomo_mcp_dataset import (  # noqa: F401 - some re-exported for tests
        CATEGORY_NAMES,
        COMPARABLE_CUTOFFS,
        MAX_INGEST_BATCH,
        QuestionEvaluation,
        ResumeState,
        answer_in_hits,
        build_messages,
        chunks,
        compact_hit,
        estimate_tokens,
        extraction_summary_from_runtime,
        finalize_metrics,
        git_commit,
        init_metric_counts,
        mcp_transport,
        parse_args,
        question_rows,
        require_entity_model,
        result_ref,
        resume_state,
        retrieval_cutoffs,
        retrieval_diagnostics,
        summarize_entity_extraction,
        turn_content,
        update_metrics,
        utc_timestamp,
        validate_batch_size,
        validate_search_concurrency,
    )


async def call_tool(client: Client, name: str, arguments: dict[str, Any]) -> Any:
    result = await client.call_tool(name, arguments)
    if result.is_error:
        text = "\n".join(getattr(part, "text", str(part)) for part in result.content)
        raise RuntimeError(f"{name} failed: {text}")
    structured = result.structured_content or {}
    if "result" in structured:
        return structured["result"]
    if result.content:
        text = getattr(result.content[0], "text", "")
        if text:
            return json.loads(text)
    return None


async def ingest_conversation(
    client: Client,
    *,
    user_identifier: str,
    messages: list[dict[str, Any]],
    batch_size: int,
    skip_existing: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    stored = 0
    stored_rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    pending_messages = messages
    existing = 0
    if skip_existing:
        pending_messages = []
        for index, message in enumerate(messages, 1):
            current = await call_tool(
                client,
                "memory_get",
                {
                    "memory_id": str(message["memory_id"]),
                    "user_identifier": user_identifier,
                },
            )
            if current is None:
                pending_messages.append(message)
            else:
                existing += 1
            if index % 100 == 0 or index == len(messages):
                print(
                    f"  resume scan: {index}/{len(messages)} existing={existing}",
                    flush=True,
                )
    for batch in chunks(pending_messages, batch_size):
        result = await call_tool(
            client,
            "memory_store_messages",
            {
                "messages": batch,
                "user_identifier": user_identifier,
                "source": "backboard-locomo",
                "tags": ["benchmark", "backboard", "locomo", "turns-only"],
                "refresh_communities": False,
            },
        )
        if not isinstance(result, list):
            raise RuntimeError("memory_store_messages returned a non-list result")
        stored += len(result)
        stored_rows.extend(row for row in result if isinstance(row, dict))
    community = await call_tool(
        client,
        "memory_rebuild_communities",
        {"user_identifier": user_identifier},
    )
    return (
        {
            "messages": len(messages),
            "existing_results": existing,
            "stored_results": stored,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "entity_extraction": summarize_entity_extraction(stored_rows),
            "community": community,
        },
        stored_rows,
    )


async def evaluate_question(
    client: Client,
    *,
    sample_id: str,
    question_index: int,
    qa: dict[str, Any],
    user_identifier: str,
    top_k: int,
    ks: list[int],
    save_result: bool,
) -> QuestionEvaluation:
    category = int(qa.get("category") or 0)
    question = str(qa.get("question") or "")
    evidence = [str(ref) for ref in qa.get("evidence") or []]
    started = time.perf_counter()
    error = ""
    hits: list[dict[str, Any]] = []
    try:
        hits = await call_tool(
            client,
            "memory_search",
            {
                "query": question,
                "user_identifier": user_identifier,
                "limit": top_k,
                "source": "backboard-locomo",
                "tags": ["locomo"],
            },
        )
        hits = hits or []
    except Exception as exc:  # noqa: BLE001 - report per-question MCP failures.
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - started) * 1000
    retrieved_refs = [result_ref(hit) for hit in hits]
    answer_hit_by_k = {k: answer_in_hits(qa.get("answer"), hits, k) for k in ks}
    row = None
    if save_result:
        row = {
            "sample_id": sample_id,
            "question_index": question_index,
            "category": category,
            "question_type": CATEGORY_NAMES.get(category, "unknown"),
            "question": question,
            "answer": qa.get("answer"),
            "evidence": evidence,
            "retrieved_refs": retrieved_refs,
            "evidence_any_at_top_k": bool(set(evidence) & set(retrieved_refs))
            if evidence
            else False,
            "evidence_all_at_top_k": set(evidence).issubset(set(retrieved_refs))
            if evidence
            else False,
            "answer_in_content_at_top_k": answer_hit_by_k[top_k],
            "answer_in_content_by_k": {str(k): answer_hit_by_k[k] for k in ks},
            "latency_ms": round(latency_ms, 3),
            "error": error,
            **retrieval_diagnostics(hits),
            "retrieved": [compact_hit(hit, rank) for rank, hit in enumerate(hits, 1)],
        }
    return QuestionEvaluation(
        question_index=question_index,
        evidence=evidence,
        retrieved_refs=retrieved_refs,
        answer_hit_by_k=answer_hit_by_k,
        latency_ms=latency_ms,
        error=error,
        row=row,
    )


async def evaluate_conversation(
    clients: Sequence[Client],
    *,
    item: dict[str, Any],
    user_identifier: str,
    top_k: int,
    ks: list[int],
    save_results: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not clients:
        raise ValueError("at least one MCP search client is required")
    sample_id = str(item.get("sample_id") or "sample")
    qa_items = question_rows(item)
    metrics = init_metric_counts()
    rows: list[dict[str, Any]] = []
    queue: asyncio.Queue[tuple[int, dict[str, Any]]] = asyncio.Queue()
    for question_index, qa in enumerate(qa_items, 1):
        queue.put_nowait((question_index, qa))
    completed = 0

    async def search_worker(client: Client) -> None:
        nonlocal completed
        while True:
            try:
                question_index, qa = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            evaluation = await evaluate_question(
                client,
                sample_id=sample_id,
                question_index=question_index,
                qa=qa,
                user_identifier=user_identifier,
                top_k=top_k,
                ks=ks,
                save_result=save_results,
            )
            update_metrics(
                metrics,
                evidence=evaluation.evidence,
                retrieved_refs=evaluation.retrieved_refs,
                answer_hit_by_k=evaluation.answer_hit_by_k,
                ks=ks,
                latency_ms=evaluation.latency_ms,
                search_error=bool(evaluation.error),
            )
            if evaluation.row is not None:
                rows.append(evaluation.row)
            completed += 1
            if completed % 25 == 0 or completed == len(qa_items):
                print(
                    f"  searched {sample_id}: {completed}/{len(qa_items)} "
                    f"evidence_any@{top_k}="
                    f"{metrics['evidence_any_hits'][top_k]}/{max(metrics['evidence_total'], 1)}",
                    flush=True,
                )
            queue.task_done()

    await asyncio.gather(*(search_worker(client) for client in clients))
    rows.sort(key=lambda row: int(row["question_index"]))
    return finalize_metrics(metrics, ks), rows


async def run() -> dict[str, Any]:
    args = parse_args()
    dataset_path = Path(args.dataset)
    repo_path = Path(args.repo)
    timestamp = utc_timestamp()
    output_path = Path(args.output) if args.output else Path(".benchmarks") / (
        f"backboard-locomo-direct-mcp-{timestamp}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    if args.conversation:
        wanted = set(args.conversation)
        data = [item for item in data if str(item.get("sample_id")) in wanted]
    max_k = args.top_k
    ks = retrieval_cutoffs(max_k)
    args.batch_size = validate_batch_size(args.batch_size)
    args.search_concurrency = validate_search_concurrency(args.search_concurrency)

    os.environ.setdefault("NO_COLOR", "1")
    resumed = ResumeState(frozenset(), [], [])
    if args.resume and output_path.exists():
        resumed = resume_state(json.loads(output_path.read_text(encoding="utf-8")))
    all_results: list[dict[str, Any]] = list(resumed.results)
    conversations: list[dict[str, Any]] = list(resumed.conversations)
    overall = init_metric_counts()
    by_category: dict[str, dict[str, Any]] = defaultdict(init_metric_counts)
    total_turns = sum(len(build_messages(item)[0]) for item in data)
    evaluated_questions = sum(len(question_rows(item)) for item in data)
    excluded_questions = sum(
        len(item.get("qa", [])) - len(question_rows(item)) for item in data
    )
    started = time.perf_counter()
    runtime_status: dict[str, Any] = {}

    async with AsyncExitStack() as stack:
        clients = [
            await stack.enter_async_context(Client(mcp_transport(args.container)))
            for _ in range(args.search_concurrency)
        ]
        client = clients[0]
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        required = {
            "memory_store_messages",
            "memory_rebuild_communities",
            "memory_get",
            "memory_search",
            "memory_runtime_status",
        }
        missing = sorted(required - tool_names)
        if missing:
            raise RuntimeError(f"MCP server missing required tools: {missing}")
        runtime_status = await call_tool(client, "memory_runtime_status", {}) or {}
        runtime_extraction = extraction_summary_from_runtime(runtime_status)
        require_entity_model(runtime_extraction, args.require_entity_model.strip())

        for conv_index, item in enumerate(data, 1):
            sample_id = str(item.get("sample_id") or f"conversation-{conv_index}")
            if sample_id in resumed.completed_samples:
                print(f"conversation {conv_index}/{len(data)} {sample_id}: resumed", flush=True)
                continue
            user_identifier = f"{args.scope_prefix}-{sample_id}"
            messages, _dia_to_content = build_messages(item)
            print(
                f"conversation {conv_index}/{len(data)} {sample_id}: "
                f"{len(messages)} turns, {len(question_rows(item))} eval questions",
                flush=True,
            )
            ingest_info = {
                "messages": len(messages),
                "existing_results": 0,
                "stored_results": 0,
                "duration_ms": 0.0,
                "entity_extraction": summarize_entity_extraction([]),
            }
            if not args.skip_ingest:
                ingest_info, conversation_entity_rows = await ingest_conversation(
                    client,
                    user_identifier=user_identifier,
                    messages=messages,
                    batch_size=args.batch_size,
                    skip_existing=args.resume,
                )
                del conversation_entity_rows
                print(
                    f"  ingested {sample_id}: {ingest_info['stored_results']} results "
                    f"in {ingest_info['duration_ms']} ms",
                    flush=True,
                )
            conv_metrics, rows = await evaluate_conversation(
                clients,
                item=item,
                user_identifier=user_identifier,
                top_k=max_k,
                ks=ks,
                save_results=True,
            )
            all_results.extend(rows)
            conversations.append(
                {
                    "sample_id": sample_id,
                    "user_identifier": user_identifier,
                    "turns": len(messages),
                    "qa_total": len(item.get("qa", [])),
                    "evaluated_questions": len(question_rows(item)),
                    "excluded_adversarial_questions": len(item.get("qa", [])) - len(question_rows(item)),
                    "ingest": ingest_info,
                    "metrics": conv_metrics,
                }
            )
            checkpoint = {
                "benchmark": "backboard-locomo-direct-mcp",
                "status": "running",
                "ablation_id": args.ablation_id,
                "parameters": {
                    "top_k": max_k,
                    "ks": ks,
                    "search_concurrency": args.search_concurrency,
                },
                "runtime": runtime_status,
                "conversations": conversations,
                "results": all_results,
            }
            output_path.write_text(
                json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
            )
    for row in all_results:
        evidence = row["evidence"]
        retrieved_refs = row["retrieved_refs"]
        answer_by_k = row.get("answer_in_content_by_k") or {}
        answer_hit_by_k = {k: bool(answer_by_k.get(str(k))) for k in ks}
        update_metrics(
            overall,
            evidence=evidence,
            retrieved_refs=retrieved_refs,
            answer_hit_by_k=answer_hit_by_k,
            ks=ks,
            latency_ms=row["latency_ms"],
            search_error=bool(row["error"]),
        )
        update_metrics(
            by_category[str(row["question_type"])],
            evidence=evidence,
            retrieved_refs=retrieved_refs,
            answer_hit_by_k=answer_hit_by_k,
            ks=ks,
            latency_ms=row["latency_ms"],
            search_error=bool(row["error"]),
        )

    payload = {
        "benchmark": "backboard-locomo-direct-mcp",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "dataset_path": str(dataset_path),
        "dataset_repo": "https://github.com/Backboard-io/Backboard-Locomo-Benchmark",
        "dataset_git_commit": git_commit(repo_path),
        "contract": {
            "transport": "MCP stdio through docker exec",
            "mcp_container": args.container,
            "ingest": "memory_store_messages",
            "search": "memory_search",
            "dataset_variant": "turns_only",
            "category_filter": "exclude category 5 adversarial",
            "scoring": (
                "Evidence recall counts a hit when retrieved memory metadata dia_id matches "
                "a LoCoMo gold evidence id. Gold answers are not ingested."
            ),
        },
        "parameters": {
            "top_k": max_k,
            "ks": ks,
            "batch_size": args.batch_size,
            "search_concurrency": args.search_concurrency,
            "scope_prefix": args.scope_prefix,
            "skip_ingest": args.skip_ingest,
            "ablation_id": args.ablation_id,
        },
        "counts": {
            "conversations": len(data),
            "turns": total_turns,
            "qa_total": sum(len(item.get("qa", [])) for item in data),
            "evaluated_questions": evaluated_questions,
            "excluded_adversarial_questions": excluded_questions,
        },
        "entity_extraction": {
            "required_model": args.require_entity_model.strip(),
            **extraction_summary_from_runtime(runtime_status),
        },
        "runtime": runtime_status,
        "metrics": finalize_metrics(overall, ks),
        "by_category": {
            category: finalize_metrics(bucket, ks)
            for category, bucket in sorted(by_category.items())
        },
        "conversations": conversations,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "results": all_results if args.save_results else [],
        "notes": [
            "This is a direct MCP retrieval evaluation, not Backboard's LLM-as-judge answer generation.",
            "Only raw conversation turns were ingested; event_summary, observation, session_summary, and QA gold answers were not ingested.",
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {output_path}", flush=True)
    print(json.dumps({"metrics": payload["metrics"], "counts": payload["counts"]}, indent=2), flush=True)
    return payload


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
