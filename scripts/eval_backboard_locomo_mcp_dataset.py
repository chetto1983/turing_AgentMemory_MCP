"""Dataset loading, LoCoMo message building, and deterministic metrics helpers.

Split out of `eval_backboard_locomo_mcp.py` per D-08/D-09 so the async
MCP-bridge runner stays under the 600-LOC cap. `call_tool`, `ingest_conversation`,
`evaluate_question`, and `evaluate_conversation` stay in the original module
because `tests/test_backboard_locomo_runner.py` monkeypatches the module-level
`call_tool` global and relies on those functions resolving it via that same
module's namespace at call time. Every symbol this module owns is re-imported
unchanged into `eval_backboard_locomo_mcp.py` so `tests/test_backboard_locomo_runner.py`'s
`runner.<name>` attribute access keeps resolving. Not wired into CI (D-10).
"""

from __future__ import annotations

import argparse
import re
import statistics
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlsplit

from fastmcp.client.transports import StdioTransport

CATEGORY_NAMES = {
    1: "single_hop",
    2: "temporal_reasoning",
    3: "multi_hop",
    4: "open_domain",
    5: "adversarial",
}
COMPARABLE_CUTOFFS = (20, 50, 200)
MAX_INGEST_BATCH = 1024
MAX_SEARCH_CONCURRENCY = 4


class ResumeState(NamedTuple):
    completed_samples: frozenset[str]
    conversations: list[dict[str, Any]]
    results: list[dict[str, Any]]


class QuestionEvaluation(NamedTuple):
    question_index: int
    evidence: list[str]
    retrieved_refs: list[str]
    answer_hit_by_k: dict[int, bool]
    latency_ms: float
    error: str
    row: dict[str, Any] | None


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
    parser.add_argument(
        "--search-concurrency",
        type=int,
        default=1,
        help=f"Independent direct-MCP search workers (1-{MAX_SEARCH_CONCURRENCY}).",
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


def validate_search_concurrency(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_SEARCH_CONCURRENCY
    ):
        raise ValueError(f"search_concurrency must be between 1 and {MAX_SEARCH_CONCURRENCY}")
    return value


def mcp_transport(container: str) -> StdioTransport:
    return StdioTransport(
        command="docker.exe",
        args=[
            "exec",
            "-i",
            container,
            "turing-agentmemory-mcp",
            "serve",
            "--transport",
            "stdio",
        ],
    )


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
            else "mixed"
            if primary_statuses
            else "candidate_limit"
            if candidate_limited
            else ""
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
        raise RuntimeError(
            f"benchmark ingest did not report required entity model: {required_model}"
        )


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
        "search_success_rate": round((total - bucket["search_errors"]) / total, 6)
        if total
        else 0.0,
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 3) if latencies else 0.0,
            "p50": round(statistics.median(latencies), 3) if latencies else 0.0,
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "mrr": round(bucket["reciprocal_rank_sum"] / evidence_total, 6) if evidence_total else 0.0,
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
