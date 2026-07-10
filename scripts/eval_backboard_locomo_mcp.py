"""Run Backboard LoCoMo dataset retrieval evaluation through the MCP stdio bridge.

This runner ingests only raw conversation turns, then scores memory_search
results against the dataset evidence ids. It does not call Backboard APIs or
inject LoCoMo gold answers into memory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


CATEGORY_NAMES = {
    1: "single_hop",
    2: "temporal_reasoning",
    3: "multi_hop",
    4: "open_domain",
    5: "adversarial",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Backboard LoCoMo retrieval through Turing AgentMemory MCP."
    )
    parser.add_argument(
        "--dataset",
        default=r"D:\tmp\Backboard-Locomo-Benchmark\locomo_dataset.json",
        help="Path to Backboard LoCoMo locomo_dataset.json.",
    )
    parser.add_argument(
        "--repo",
        default=r"D:\tmp\Backboard-Locomo-Benchmark",
        help="Path to cached Backboard benchmark repo, used only for git commit metadata.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output JSON path. Defaults to .benchmarks/backboard-locomo-direct-mcp-<timestamp>.json.",
    )
    parser.add_argument("--top-k", type=int, default=10, help="memory_search limit.")
    parser.add_argument("--batch-size", type=int, default=50, help="MCP ingest batch size.")
    parser.add_argument(
        "--scope-prefix",
        default="bench-backboard-locomo-direct-mcp-v1",
        help="Stable user_identifier prefix. Stable values make ingestion idempotent across reruns.",
    )
    parser.add_argument(
        "--container",
        default="turing-agentmemory-mcp-turing-agentmemory-mcp-1",
        help="Running product MCP container name.",
    )
    parser.add_argument(
        "--conversation",
        action="append",
        default=[],
        help="Optional sample_id filter. Repeat to evaluate multiple conversations.",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip ingest and only run searches against an already ingested scope.",
    )
    parser.add_argument(
        "--save-results",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include per-question retrieval details in the JSON output.",
    )
    return parser.parse_args()


def utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def git_commit(repo: Path) -> str:
    if not repo.exists():
        return ""
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def session_number(session_key: str) -> int:
    try:
        return int(session_key.split("_")[1])
    except (IndexError, ValueError):
        return 0


def session_keys(conversation: dict[str, Any]) -> list[str]:
    keys = [
        key
        for key, value in conversation.items()
        if re.fullmatch(r"session_\d+", key) and isinstance(value, list)
    ]
    return sorted(keys, key=session_number)


def turn_content(sample_id: str, session_key: str, session_dt: str, turn: dict[str, Any]) -> str:
    dia_id = str(turn.get("dia_id") or "")
    speaker = str(turn.get("speaker") or "speaker")
    text = str(turn.get("text") or "").strip()
    parts = [
        f"LoCoMo sample {sample_id} evidence {dia_id}.",
        f"{session_key} date/time: {session_dt}.",
        f"{speaker}: {text}",
    ]
    query = turn.get("query")
    if query:
        parts.append(f"Image search query: {query}.")
    caption = turn.get("blip_caption")
    if caption:
        parts.append(f"Image caption: {caption}.")
    img_urls = turn.get("img_url")
    if isinstance(img_urls, list) and img_urls:
        parts.append(f"Image URLs: {' '.join(str(url) for url in img_urls)}")
    return " ".join(part for part in parts if part)


def build_messages(item: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    sample_id = str(item.get("sample_id") or "sample")
    conversation = item["conversation"]
    dia_to_content: dict[str, str] = {}
    messages: list[dict[str, Any]] = []
    for key in session_keys(conversation):
        session_dt = str(conversation.get(f"{key}_date_time") or "")
        for turn_index, turn in enumerate(conversation[key], 1):
            dia_id = str(turn.get("dia_id") or f"{key}:{turn_index}")
            speaker = str(turn.get("speaker") or "speaker")
            content = turn_content(sample_id, key, session_dt, turn)
            dia_to_content[dia_id] = content
            messages.append(
                {
                    "session_id": f"locomo-{sample_id}-{key}",
                    "role": speaker,
                    "content": content,
                    "memory_id": safe_id(f"locomo-{sample_id}-{dia_id}"),
                    "metadata": {
                        "benchmark": "backboard-locomo",
                        "dataset_variant": "turns_only",
                        "sample_id": sample_id,
                        "dia_id": dia_id,
                        "session_key": key,
                        "session_date_time": session_dt,
                        "speaker": speaker,
                    },
                }
            )
    return messages, dia_to_content


def chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def answer_in_hits(answer: Any, hits: list[dict[str, Any]], k: int) -> bool:
    answer_text = normalize_text(answer)
    if len(answer_text) < 2:
        return False
    combined = normalize_text(" ".join(str(hit.get("content") or "") for hit in hits[:k]))
    return answer_text in combined


def result_ref(hit: dict[str, Any]) -> str:
    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    dia_id = metadata.get("dia_id")
    if dia_id:
        return str(dia_id)
    content = str(hit.get("content") or "")
    match = re.search(r"evidence\s+(D\d+:\d+)", content)
    return match.group(1) if match else ""


def compact_hit(hit: dict[str, Any], rank: int) -> dict[str, Any]:
    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    return {
        "rank": rank,
        "id": hit.get("id"),
        "score": hit.get("score"),
        "dia_id": metadata.get("dia_id") or result_ref(hit),
        "sample_id": metadata.get("sample_id"),
        "session_id": hit.get("session_id"),
        "speaker": metadata.get("speaker") or hit.get("role"),
    }


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
) -> dict[str, Any]:
    stored = 0
    started = time.perf_counter()
    for batch in chunks(messages, batch_size):
        result = await call_tool(
            client,
            "memory_store_messages",
            {
                "messages": batch,
                "user_identifier": user_identifier,
                "source": "backboard-locomo",
                "tags": ["benchmark", "backboard", "locomo", "turns-only"],
            },
        )
        stored += len(result or [])
    return {
        "messages": len(messages),
        "stored_results": stored,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def question_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    return [qa for qa in item.get("qa", []) if qa.get("category") != 5]


def init_metric_counts() -> dict[str, Any]:
    return {
        "total": 0,
        "evidence_total": 0,
        "search_errors": 0,
        "latencies_ms": [],
        "evidence_any_hits": Counter(),
        "evidence_all_hits": Counter(),
        "answer_in_content_hits": Counter(),
        "evidence_or_answer_hits": Counter(),
    }


def update_metrics(
    bucket: dict[str, Any],
    *,
    evidence: list[str],
    retrieved_refs: list[str],
    answer_hit_by_k: dict[int, bool],
    ks: list[int],
    latency_ms: float,
    search_error: bool,
) -> None:
    bucket["total"] += 1
    bucket["latencies_ms"].append(latency_ms)
    if search_error:
        bucket["search_errors"] += 1
        return
    evidence_set = set(evidence)
    has_evidence = bool(evidence_set)
    if has_evidence:
        bucket["evidence_total"] += 1
    for k in ks:
        top_refs = set(ref for ref in retrieved_refs[:k] if ref)
        any_hit = has_evidence and bool(evidence_set & top_refs)
        all_hit = has_evidence and evidence_set.issubset(top_refs)
        answer_hit = answer_hit_by_k[k]
        if any_hit:
            bucket["evidence_any_hits"][k] += 1
        if all_hit:
            bucket["evidence_all_hits"][k] += 1
        if answer_hit:
            bucket["answer_in_content_hits"][k] += 1
        if any_hit or (not has_evidence and answer_hit):
            bucket["evidence_or_answer_hits"][k] += 1


def finalize_metrics(bucket: dict[str, Any], ks: list[int]) -> dict[str, Any]:
    total = bucket["total"]
    evidence_total = bucket["evidence_total"]
    latencies = bucket["latencies_ms"]
    out: dict[str, Any] = {
        "total": total,
        "evidence_total": evidence_total,
        "search_errors": bucket["search_errors"],
        "search_success_rate": round((total - bucket["search_errors"]) / total, 6) if total else 0.0,
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 3) if latencies else 0.0,
            "p50": round(statistics.median(latencies), 3) if latencies else 0.0,
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
    }
    for k in ks:
        out[f"evidence_any_at_{k}"] = (
            round(bucket["evidence_any_hits"][k] / evidence_total, 6) if evidence_total else 0.0
        )
        out[f"evidence_all_at_{k}"] = (
            round(bucket["evidence_all_hits"][k] / evidence_total, 6) if evidence_total else 0.0
        )
        out[f"answer_in_content_at_{k}"] = (
            round(bucket["answer_in_content_hits"][k] / total, 6) if total else 0.0
        )
        out[f"evidence_or_answer_at_{k}"] = (
            round(bucket["evidence_or_answer_hits"][k] / total, 6) if total else 0.0
        )
    return out


async def evaluate_conversation(
    client: Client,
    *,
    item: dict[str, Any],
    user_identifier: str,
    top_k: int,
    ks: list[int],
    save_results: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sample_id = str(item.get("sample_id") or "sample")
    qa_items = question_rows(item)
    metrics = init_metric_counts()
    rows: list[dict[str, Any]] = []
    for idx, qa in enumerate(qa_items, 1):
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
        update_metrics(
            metrics,
            evidence=evidence,
            retrieved_refs=retrieved_refs,
            answer_hit_by_k=answer_hit_by_k,
            ks=ks,
            latency_ms=latency_ms,
            search_error=bool(error),
        )
        if save_results:
            rows.append(
                {
                    "sample_id": sample_id,
                    "question_index": idx,
                    "category": category,
                    "question_type": CATEGORY_NAMES.get(category, "unknown"),
                    "question": question,
                    "answer": qa.get("answer"),
                    "evidence": evidence,
                    "retrieved_refs": retrieved_refs,
                    "evidence_any_at_top_k": bool(set(evidence) & set(retrieved_refs)) if evidence else False,
                    "evidence_all_at_top_k": set(evidence).issubset(set(retrieved_refs)) if evidence else False,
                    "answer_in_content_at_top_k": answer_hit_by_k[top_k],
                    "answer_in_content_by_k": {str(k): answer_hit_by_k[k] for k in ks},
                    "latency_ms": round(latency_ms, 3),
                    "error": error,
                    "retrieved": [compact_hit(hit, rank) for rank, hit in enumerate(hits, 1)],
                }
            )
        if idx % 25 == 0 or idx == len(qa_items):
            print(
                f"  searched {sample_id}: {idx}/{len(qa_items)} "
                f"evidence_any@{top_k}="
                f"{metrics['evidence_any_hits'][top_k]}/{max(metrics['evidence_total'], 1)}",
                flush=True,
            )
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
    max_k = max(1, args.top_k)
    ks = [k for k in [1, 3, 5, 10, 20] if k <= max_k]
    if max_k not in ks:
        ks.append(max_k)
    ks = sorted(set(ks))

    os.environ.setdefault("NO_COLOR", "1")
    transport = StdioTransport(
        command="docker.exe",
        args=[
            "exec",
            "-i",
            args.container,
            "turing-agentmemory-mcp",
            "serve",
            "--transport",
            "stdio",
        ],
    )
    all_results: list[dict[str, Any]] = []
    conversations: list[dict[str, Any]] = []
    overall = init_metric_counts()
    by_category: dict[str, dict[str, Any]] = defaultdict(init_metric_counts)
    total_turns = 0
    evaluated_questions = 0
    excluded_questions = 0
    started = time.perf_counter()

    async with Client(transport) as client:
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        required = {"memory_store_messages", "memory_search"}
        missing = sorted(required - tool_names)
        if missing:
            raise RuntimeError(f"MCP server missing required tools: {missing}")

        for conv_index, item in enumerate(data, 1):
            sample_id = str(item.get("sample_id") or f"conversation-{conv_index}")
            user_identifier = f"{args.scope_prefix}-{sample_id}"
            messages, _dia_to_content = build_messages(item)
            total_turns += len(messages)
            evaluated_questions += len(question_rows(item))
            excluded_questions += len(item.get("qa", [])) - len(question_rows(item))
            print(
                f"conversation {conv_index}/{len(data)} {sample_id}: "
                f"{len(messages)} turns, {len(question_rows(item))} eval questions",
                flush=True,
            )
            ingest_info = {"messages": len(messages), "stored_results": 0, "duration_ms": 0.0}
            if not args.skip_ingest:
                ingest_info = await ingest_conversation(
                    client,
                    user_identifier=user_identifier,
                    messages=messages,
                    batch_size=args.batch_size,
                )
                print(
                    f"  ingested {sample_id}: {ingest_info['stored_results']} results "
                    f"in {ingest_info['duration_ms']} ms",
                    flush=True,
                )
            conv_metrics, rows = await evaluate_conversation(
                client,
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
            for row in rows:
                category_name = row["question_type"]
                evidence = row["evidence"]
                retrieved_refs = row["retrieved_refs"]
                answer_by_k = row.get("answer_in_content_by_k") or {}
                answer_hit_by_k = {k: bool(answer_by_k.get(str(k))) for k in ks}
                update_metrics(
                    by_category[category_name],
                    evidence=evidence,
                    retrieved_refs=retrieved_refs,
                    answer_hit_by_k=answer_hit_by_k,
                    ks=ks,
                    latency_ms=row["latency_ms"],
                    search_error=bool(row["error"]),
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
            "scope_prefix": args.scope_prefix,
            "skip_ingest": args.skip_ingest,
        },
        "counts": {
            "conversations": len(data),
            "turns": total_turns,
            "qa_total": sum(len(item.get("qa", [])) for item in data),
            "evaluated_questions": evaluated_questions,
            "excluded_adversarial_questions": excluded_questions,
        },
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
