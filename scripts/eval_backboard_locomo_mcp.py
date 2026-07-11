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
from typing import Any, NamedTuple
from urllib.parse import urlsplit

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

CATEGORY_NAMES = {
    1: "single_hop",
    2: "temporal_reasoning",
    3: "multi_hop",
    4: "open_domain",
    5: "adversarial",
}
COMPARABLE_CUTOFFS = (20, 50, 200)
MAX_INGEST_BATCH = 50


class ResumeState(NamedTuple):
    completed_samples: frozenset[str]
    conversations: list[dict[str, Any]]
    results: list[dict[str, Any]]


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
    parser.add_argument("--top-k", type=int, default=200, help="memory_search limit (max 200).")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=MAX_INGEST_BATCH,
        help=f"MCP ingest batch size (max {MAX_INGEST_BATCH}).",
    )
    parser.add_argument(
        "--scope-prefix",
        default="bench-backboard-locomo-fused-v2",
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
        "--require-entity-model",
        default="lion-ai/gliner2-base-v1-onnx",
        help="Fail ingest unless memory_store_messages reports this entity model. Set empty to disable.",
    )
    parser.add_argument(
        "--save-results",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include per-question retrieval details in the JSON output.",
    )
    parser.add_argument(
        "--ablation-id",
        default="fused-full",
        help="Stable identity for the retrieval configuration under test.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume completed conversations from the output checkpoint.",
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
        references: list[str] = []
        for value in img_urls:
            url = str(value)
            if url.casefold().startswith("data:"):
                media_type = url[5:].split(";", 1)[0] or "media"
                references.append(f"[embedded {media_type} omitted]")
            else:
                parsed = urlsplit(url)
                if parsed.scheme in {"http", "https"} and parsed.hostname:
                    filename = parsed.path.rstrip("/").rsplit("/", 1)[-1]
                    references.append(
                        f"{parsed.hostname}/{filename}" if filename else parsed.hostname
                    )
                else:
                    references.append(url.split("?", 1)[0][:256])
        parts.append(f"Image URLs: {' '.join(dict.fromkeys(references))}")
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


def estimate_tokens(value: str) -> int:
    return max(1, (len(value.encode("utf-8")) + 3) // 4)


def retrieval_cutoffs(top_k: int) -> list[int]:
    if top_k <= 0 or top_k > 200:
        raise ValueError("top_k must be between 1 and 200")
    return sorted({k for k in (1, 3, 5, 10, *COMPARABLE_CUTOFFS, top_k) if k <= top_k})


def validate_batch_size(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_INGEST_BATCH:
        raise ValueError(f"batch_size must be between 1 and {MAX_INGEST_BATCH}")
    return value


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
    content = str(hit.get("content") or "")
    return {
        "rank": rank,
        "id": hit.get("id"),
        "score": hit.get("score"),
        "dia_id": metadata.get("dia_id") or result_ref(hit),
        "sample_id": metadata.get("sample_id"),
        "session_id": hit.get("session_id"),
        "speaker": metadata.get("speaker") or hit.get("role"),
        "content": content,
        "estimated_tokens": estimate_tokens(content),
    }


def retrieval_diagnostics(hits: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: set[str] = set()
    models: set[str] = set()
    channels: set[str] = set()
    for hit in hits:
        details = hit.get("score_details")
        if not isinstance(details, dict):
            continue
        status = details.get("rerank_status")
        if isinstance(status, str) and status:
            statuses.add(status)
        model = details.get("rerank_model")
        if isinstance(model, str) and model:
            models.add(model)
        hit_channels = details.get("channels")
        if isinstance(hit_channels, dict):
            channels.update(str(name) for name in hit_channels)
    candidate_limited = "candidate_limit" in statuses
    primary_statuses = statuses - {"candidate_limit"}
    return {
        "rerank_status": (
            next(iter(primary_statuses))
            if len(primary_statuses) == 1
            else "mixed" if primary_statuses else "candidate_limit" if candidate_limited else ""
        ),
        "rerank_model": next(iter(models)) if len(models) == 1 else "mixed" if models else "",
        "rerank_candidate_limited": candidate_limited,
        "retrieval_channels": sorted(channels),
    }


def summarize_entity_extraction(rows: list[dict[str, Any]]) -> dict[str, Any]:
    annotated_memories = 0
    entities = 0
    models: set[str] = set()
    for row in rows:
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            continue
        extraction = metadata.get("entity_extraction")
        if not isinstance(extraction, dict):
            continue
        annotated_memories += 1
        model = extraction.get("model")
        if isinstance(model, str) and model.strip():
            models.add(model.strip())
        count = extraction.get("entity_count")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            entities += count
    return {
        "annotated_memories": annotated_memories,
        "entities": entities,
        "models": sorted(models),
    }


def require_entity_model(summary: dict[str, Any], required_model: str) -> None:
    if not required_model:
        return
    models = summary.get("models")
    if not isinstance(models, list) or required_model not in models:
        raise RuntimeError(f"benchmark ingest did not report required entity model: {required_model}")


def extraction_summary_from_runtime(runtime: object) -> dict[str, Any]:
    if not isinstance(runtime, dict):
        return {"annotated_memories": 0, "entities": 0, "models": [], "schema_version": ""}
    stages = runtime.get("stages")
    extraction = stages.get("extraction") if isinstance(stages, dict) else None
    identity = extraction.get("identity") if isinstance(extraction, dict) else None
    model = identity.get("model") if isinstance(identity, dict) else None
    schema = identity.get("schema_version") if isinstance(identity, dict) else None
    return {
        "annotated_memories": 0,
        "entities": 0,
        "models": [model] if isinstance(model, str) and model else [],
        "schema_version": schema if isinstance(schema, str) else "",
    }


def resume_state(payload: object) -> ResumeState:
    if not isinstance(payload, dict):
        return ResumeState(frozenset(), [], [])
    conversations = [row for row in payload.get("conversations", []) if isinstance(row, dict)]
    results = [row for row in payload.get("results", []) if isinstance(row, dict)]
    completed = frozenset(
        str(row.get("sample_id")) for row in conversations if row.get("sample_id")
    )
    return ResumeState(completed, conversations, results)


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
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    stored = 0
    stored_rows: list[dict[str, Any]] = []
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
            "stored_results": stored,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "entity_extraction": summarize_entity_extraction(stored_rows),
            "community": community,
        },
        stored_rows,
    )


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
        "reciprocal_rank_sum": 0.0,
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
        first_rank = next(
            (rank for rank, ref in enumerate(retrieved_refs, 1) if ref in evidence_set),
            None,
        )
        if first_rank is not None:
            bucket["reciprocal_rank_sum"] += 1.0 / first_rank
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
        "mrr": round(bucket["reciprocal_rank_sum"] / evidence_total, 6)
        if evidence_total
        else 0.0,
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
                    **retrieval_diagnostics(hits),
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
    max_k = args.top_k
    ks = retrieval_cutoffs(max_k)
    args.batch_size = validate_batch_size(args.batch_size)

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

    async with Client(transport) as client:
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        required = {
            "memory_store_messages",
            "memory_rebuild_communities",
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
                )
                del conversation_entity_rows
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
            checkpoint = {
                "benchmark": "backboard-locomo-direct-mcp",
                "status": "running",
                "ablation_id": args.ablation_id,
                "parameters": {"top_k": max_k, "ks": ks},
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
