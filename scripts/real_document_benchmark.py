"""Ingest a real document directory through MCP and score ten grounded queries per file."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import statistics
import time
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastmcp import Client

from turing_agentmemory_mcp.document_processing import convert_document_to_markdown

QUESTION_COUNT = 10
DEFAULT_TOP_K = 20
DEFAULT_CUTOFFS = (1, 3, 5, 10, 20)
MIN_EVIDENCE_CHARS = 12
MAX_EVIDENCE_CHARS = 320
MIN_ANSWER_COVERAGE = 0.5
_UNIT_PATTERN = re.compile(r".+?(?:[.!?。！？]+|$)", re.UNICODE)
SUPPORTED_SUFFIXES = {
    ".docx",
    ".epub",
    ".html",
    ".htm",
    ".md",
    ".pdf",
    ".pptx",
    ".txt",
    ".url",
    ".xlsx",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=r"D:\turing_AgentMemory_MCP\test")
    parser.add_argument("--mcp-url", default="http://127.0.0.1:8095/mcp/")
    parser.add_argument("--output", default="")
    parser.add_argument("--scope", default="")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--search-concurrency", type=int, default=4)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--chunk-bytes", type=int, default=512 << 10)
    parser.add_argument("--question-count", type=int, default=QUESTION_COUNT)
    parser.add_argument("--passage-chars", type=int, default=1400)
    parser.add_argument(
        "--question-model",
        default="inclusionai/ling-2.6-flash",
    )
    parser.add_argument(
        "--question-url",
        default="https://openrouter.ai/api/v1/chat/completions",
    )
    parser.add_argument("--question-api-key-env", default="PROVIDER_API_KEY")
    parser.add_argument("--env-file", default=".env")
    return parser.parse_args()


def utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def safe_id(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", ascii_value).strip("-._").lower()
    return clean or "document"


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = "".join(" " if unicodedata.category(char).startswith("C") else char for char in text)
    return re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).strip()


def normalized_tokens(value: object) -> list[str]:
    normalized = normalize_text(value)
    return normalized.split(" ") if normalized else []


def source_units(text: str) -> list[tuple[int, int]]:
    """Return exact (start, end) spans for each sentence or table row in ``text``.

    Lines are split first so spreadsheet/markdown-table rows stay whole; each line
    is then split on sentence-ending punctuation. Spans index the original string
    verbatim so any selected slice is guaranteed to be an exact source substring.
    """

    units: list[tuple[int, int]] = []
    for line_match in re.finditer(r"[^\n]+", text):
        line = line_match.group()
        base = line_match.start()
        for segment in _UNIT_PATTERN.finditer(line):
            raw = segment.group()
            lead = len(raw) - len(raw.lstrip())
            trail = len(raw) - len(raw.rstrip())
            start = base + segment.start() + lead
            end = base + segment.end() - trail
            if end > start:
                units.append((start, end))
    return units


def select_evidence(passage: str, *, question: str, answer: str) -> str:
    """Deterministically pick the exact source span that grounds a generated answer.

    Scores every contiguous window of source units by token overlap with the answer
    (weighted) and the question, prefers the shortest highest-scoring window, and
    rejects paraphrases whose answer overlap is too weak to serve as retrieval gold.
    """

    units = source_units(passage)
    if not units:
        raise ValueError("source passage has no usable text for evidence grounding")
    unit_tokens = [set(normalized_tokens(passage[start:end])) for start, end in units]
    answer_all = normalized_tokens(answer)
    question_all = normalized_tokens(question)
    answer_set = {token for token in answer_all if len(token) >= 2} or set(answer_all)
    question_set = {token for token in question_all if len(token) >= 2}

    # Rank by answer coverage first, then the tightest span, then question overlap
    # as a tie-breaker only, so incidental question words never widen the evidence.
    best_key: tuple[int, int, int, int] | None = None
    best: tuple[int, int, int, int] | None = None
    for i in range(len(units)):
        span_tokens: set[str] = set()
        for j in range(i, len(units)):
            span_tokens |= unit_tokens[j]
            start = units[i][0]
            end = units[j][1]
            length = end - start
            if j > i and length > MAX_EVIDENCE_CHARS:
                break
            if len(normalize_text(passage[start:end])) < MIN_EVIDENCE_CHARS:
                continue
            answer_hits = len(answer_set & span_tokens)
            question_hits = len(question_set & span_tokens)
            key = (answer_hits, -length, question_hits, -start)
            if best_key is None or key > best_key:
                best_key = key
                best = (start, end, answer_hits, question_hits)

    if best is None:
        raise ValueError("no contiguous source span met the minimum evidence length")
    start, end, answer_hits, question_hits = best
    if answer_set:
        coverage = answer_hits / len(answer_set)
        if answer_hits < 1 or coverage < MIN_ANSWER_COVERAGE:
            raise ValueError("selected evidence has weak token overlap with the generated answer")
    elif question_hits < 2:
        raise ValueError("selected evidence has weak token overlap with the generated question")

    evidence = passage[start:end].strip()
    if normalize_text(evidence) not in normalize_text(passage):
        raise ValueError("derived evidence is not an exact substring of its source passage")
    return evidence


def file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            total += len(chunk)
    return total, digest.hexdigest()


def select_passages(text: str, *, count: int, passage_chars: int) -> list[dict[str, str]]:
    if count < 1 or passage_chars < 200:
        raise ValueError("passage selection requires a positive count and at least 200 chars")
    clean = "".join(
        " " if unicodedata.category(char).startswith("C") and char not in "\n\t" else char
        for char in text
    ).strip()
    if not clean:
        raise ValueError("document conversion produced no question source text")
    max_start = max(0, len(clean) - passage_chars)
    passages: list[dict[str, str]] = []
    for index in range(count):
        start = round(max_start * index / max(1, count - 1)) if max_start else 0
        if start:
            boundary = clean.find("\n", start, min(len(clean), start + 160))
            if boundary >= 0:
                start = boundary + 1
        excerpt = clean[start : start + passage_chars].strip()
        if not excerpt:
            excerpt = clean[:passage_chars]
        passages.append({"source_id": f"S{index + 1}", "text": excerpt})
    return passages


def _json_object_from_text(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("question model returned no JSON object")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("question model JSON must be an object")
    return payload


def parse_generated_questions(
    response: str,
    passages: list[dict[str, str]],
    *,
    expected_count: int,
) -> list[dict[str, str]]:
    payload = _json_object_from_text(response)
    rows = payload.get("questions")
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise ValueError(f"question model must return exactly {expected_count} questions")
    passage_by_id = {item["source_id"]: item["text"] for item in passages}
    questions: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each generated question must be an object")
        source_id = str(row.get("source_id") or "").strip()
        question = str(row.get("question") or "").strip()
        answer = str(row.get("answer") or "").strip()
        if source_id not in passage_by_id:
            raise ValueError(f"unknown question source_id {source_id}")
        if not question or not answer:
            raise ValueError("generated question fields must be non-empty")
        normalized_question = normalize_text(question)
        if normalized_question in seen:
            raise ValueError("generated questions must be distinct")
        evidence = select_evidence(
            passage_by_id[source_id],
            question=question,
            answer=answer,
        )
        seen.add(normalized_question)
        questions.append(
            {
                "source_id": source_id,
                "question": question,
                "answer": answer,
                "evidence_quote": evidence,
            }
        )
    return questions


class QuestionGenerator:
    def __init__(self, *, url: str, api_key: str, model: str, timeout_s: float = 180.0) -> None:
        if not url or not api_key or not model:
            raise ValueError("question provider URL, API key, and model are required")
        self.url = url
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def generate(
        self,
        *,
        filename: str,
        passages: list[dict[str, str]],
        count: int,
    ) -> tuple[list[dict[str, str]], dict[str, int]]:
        system = (
            "Create a grounded document-retrieval evaluation. Return only one JSON object "
            'with key "questions". Produce exactly one question for each labeled source. '
            "Every row must contain source_id, question, and answer. The answer must be a short, "
            "specific value that is stated in that source, phrased using the source's own wording "
            "so it can be located verbatim in the text. Questions must be distinct, natural, "
            "specific, and answerable without saying 'the passage'. Use the source language. Avoid "
            "asking for personal names, contact details, account identifiers, or other personal "
            "data; for tabular customer material ask about schema or operational concepts instead. "
            "Do not use outside knowledge."
        )
        user = json.dumps(
            {"filename": filename, "required_count": count, "sources": passages},
            ensure_ascii=False,
        )
        last_error = ""
        for attempt in range(1, 4):
            body = {
                "model": self.model,
                "temperature": 0.2,
                "max_tokens": 5000,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            request = Request(
                self.url,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/chetto1983/turing_AgentMemory_MCP",
                    "X-OpenRouter-Title": "Turing AgentMemory real document benchmark",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout_s) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                content = str(payload["choices"][0]["message"]["content"])
                questions = parse_generated_questions(content, passages, expected_count=count)
                usage = payload.get("usage") if isinstance(payload, dict) else {}
                usage = usage if isinstance(usage, dict) else {}
                return questions, {
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                    "attempt": attempt,
                }
            except HTTPError as exc:
                last_error = f"question provider HTTP {exc.code}"
            except (URLError, OSError, TimeoutError, KeyError, IndexError, TypeError) as exc:
                last_error = f"question provider unavailable: {type(exc).__name__}"
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
            if attempt < 3:
                time.sleep(2 ** (attempt - 1))
        raise RuntimeError(last_error or "question generation failed")


def tool_payload(result: Any) -> Any:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and set(structured) == {"result"}:
        return structured["result"]
    if structured is not None:
        return structured
    data = getattr(result, "data", None)
    if data is not None:
        return data
    text = "".join(getattr(item, "text", "") for item in getattr(result, "content", []))
    return json.loads(text)


async def upload_document(
    client: Client,
    document: dict[str, Any],
    *,
    user_identifier: str,
    chunk_bytes: int,
    benchmark_id: str,
) -> dict[str, Any]:
    path = Path(document["path"])
    started = tool_payload(
        await client.call_tool(
            "document_upload_begin",
            {
                "filename": path.name,
                "total_bytes": document["bytes"],
                "sha256": document["sha256"],
                "title": document["title"],
                "user_identifier": user_identifier,
                "document_id": document["document_id"],
                "source": "real-directory-benchmark",
                "tags": ["real-directory-benchmark", path.suffix.lower().lstrip(".")],
                "metadata": {
                    "benchmark_id": benchmark_id,
                    "source_filename": path.name,
                },
            },
        )
    )
    upload_id = str(started["upload_id"])
    transfer_bytes = min(chunk_bytes, int(started.get("chunk_bytes") or chunk_bytes))
    try:
        with path.open("rb") as handle:
            sequence = 0
            while chunk := handle.read(transfer_bytes):
                await client.call_tool(
                    "document_upload_chunk",
                    {
                        "upload_id": upload_id,
                        "sequence": sequence,
                        "content_base64": base64.b64encode(chunk).decode("ascii"),
                        "user_identifier": user_identifier,
                    },
                )
                sequence += 1
        return tool_payload(
            await client.call_tool(
                "document_upload_commit",
                {"upload_id": upload_id, "user_identifier": user_identifier},
            )
        )
    except BaseException:
        try:
            await client.call_tool(
                "document_upload_abort",
                {"upload_id": upload_id, "user_identifier": user_identifier},
            )
        except BaseException:
            pass
        raise


async def wait_for_jobs(
    client: Client,
    documents: list[dict[str, Any]],
    *,
    user_identifier: str,
    poll_seconds: float,
    checkpoint: Any,
) -> None:
    pending = {str(document["job"]["job_id"]): document for document in documents}
    previous: dict[str, tuple[object, ...]] = {}
    while pending:
        for job_id, document in list(pending.items()):
            status = tool_payload(
                await client.call_tool(
                    "document_ingest_status",
                    {"job_id": job_id, "user_identifier": user_identifier},
                )
            )
            document["job"] = status
            snapshot = (
                status["status"],
                status["stage"],
                status["progress_current"],
                status["progress_total"],
                status["attempt"],
            )
            if previous.get(job_id) != snapshot:
                print(
                    "BENCHMARK_CADENCE "
                    + json.dumps(
                        {
                            "file": document["filename"],
                            "status": status["status"],
                            "stage": status["stage"],
                            "progress": [
                                status["progress_current"],
                                status["progress_total"],
                            ],
                            "attempt": status["attempt"],
                            "error_code": status["error_code"],
                        },
                        ensure_ascii=True,
                    ),
                    flush=True,
                )
                previous[job_id] = snapshot
                checkpoint()
            if status["status"] in {"succeeded", "failed", "canceled"}:
                pending.pop(job_id)
        if pending:
            await asyncio.sleep(poll_seconds)


def evidence_rank(
    hits: list[dict[str, Any]],
    *,
    evidence_quote: str,
    answer: str,
) -> tuple[int, str]:
    quote = normalize_text(evidence_quote)
    answer_text = normalize_text(answer)
    for rank, hit in enumerate(hits, 1):
        text = normalize_text(hit.get("text"))
        if quote and quote in text:
            return rank, "quote"
    if len(answer_text) >= 5:
        for rank, hit in enumerate(hits, 1):
            if answer_text in normalize_text(hit.get("text")):
                return rank, "answer"
    return 0, "none"


def _metrics(rows: list[dict[str, Any]], cutoffs: tuple[int, ...]) -> dict[str, Any]:
    count = len(rows)
    ranks = [int(row.get("evidence_rank") or 0) for row in rows]
    return {
        "question_count": count,
        "search_error_count": sum(bool(row.get("error")) for row in rows),
        "mrr_at_20": (
            sum((1.0 / rank) if 0 < rank <= 20 else 0.0 for rank in ranks) / count
            if count
            else 0.0
        ),
        "recall_at_k": {
            str(cutoff): (
                sum(0 < rank <= cutoff for rank in ranks) / count if count else 0.0
            )
            for cutoff in cutoffs
        },
        "latency_ms": {
            "mean": statistics.fmean(
                float(row.get("latency_ms") or 0.0) for row in rows
            )
            if rows
            else 0.0,
            "max": max((float(row.get("latency_ms") or 0.0) for row in rows), default=0.0),
        },
    }


def summarize_results(
    rows: list[dict[str, Any]],
    *,
    cutoffs: tuple[int, ...] = DEFAULT_CUTOFFS,
) -> dict[str, Any]:
    by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_document[str(row.get("document_id") or "unknown")].append(row)
    return {
        **_metrics(rows, cutoffs),
        "documents": {
            document_id: _metrics(document_rows, cutoffs)
            for document_id, document_rows in sorted(by_document.items())
        },
    }


async def search_questions(
    *,
    mcp_url: str,
    user_identifier: str,
    documents: list[dict[str, Any]],
    top_k: int,
    concurrency: int,
    checkpoint: Any,
) -> list[dict[str, Any]]:
    queue: asyncio.Queue[tuple[dict[str, Any], int, dict[str, str]] | None] = asyncio.Queue()
    for document in documents:
        for question_index, question in enumerate(document["questions"], 1):
            queue.put_nowait((document, question_index, question))
    for _ in range(concurrency):
        queue.put_nowait(None)
    rows: list[dict[str, Any]] = []

    async def worker(worker_index: int) -> None:
        async with Client(mcp_url, timeout=1800) as client:
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    document, question_index, question = item
                    started = time.perf_counter()
                    error = ""
                    hits: list[dict[str, Any]] = []
                    try:
                        payload = tool_payload(
                            await client.call_tool(
                                "document_search",
                                {
                                    "query": question["question"],
                                    "user_identifier": user_identifier,
                                    "document_id": document["document_id"],
                                    "limit": top_k,
                                    "explain": True,
                                },
                            )
                        )
                        hits = [hit for hit in payload if isinstance(hit, dict)]
                    except Exception as exc:
                        error = f"{type(exc).__name__}: document search failed"
                    latency_ms = (time.perf_counter() - started) * 1000
                    rank, match_kind = evidence_rank(
                        hits,
                        evidence_quote=question["evidence_quote"],
                        answer=question["answer"],
                    )
                    row = {
                        "filename": document["filename"],
                        "document_id": document["document_id"],
                        "question_index": question_index,
                        **question,
                        "evidence_rank": rank,
                        "match_kind": match_kind,
                        "latency_ms": latency_ms,
                        "error": error,
                        "retrieved": [
                            {
                                "rank": hit_rank,
                                "chunk_id": hit.get("chunk_id"),
                                "locator": hit.get("locator"),
                                "score": hit.get("score"),
                                "text_preview": str(hit.get("text") or "")[:240],
                            }
                            for hit_rank, hit in enumerate(hits[:5], 1)
                        ],
                    }
                    rows.append(row)
                    print(
                        "BENCHMARK_SEARCH "
                        + json.dumps(
                            {
                                "worker": worker_index,
                                "file": document["filename"],
                                "question": question_index,
                                "rank": rank,
                                "latency_ms": round(latency_ms, 1),
                                "error": error,
                            },
                            ensure_ascii=True,
                        ),
                        flush=True,
                    )
                    checkpoint(rows)
                finally:
                    queue.task_done()

    await asyncio.gather(*(worker(index + 1) for index in range(concurrency)))
    return sorted(rows, key=lambda row: (str(row["filename"]), int(row["question_index"])))


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.top_k <= 200:
        raise ValueError("top-k must be between 1 and 200")
    if not 1 <= args.search_concurrency <= 8:
        raise ValueError("search concurrency must be between 1 and 8")
    if args.poll_seconds <= 0 or args.chunk_bytes <= 0:
        raise ValueError("poll and chunk sizes must be positive")

    root = Path(args.root).expanduser().resolve(strict=True)
    files = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    if not files:
        raise ValueError(f"no supported files found under {root}")
    timestamp = utc_timestamp()
    benchmark_id = f"real-documents-direct-mcp-{timestamp}"
    scope = args.scope.strip() or benchmark_id
    output = (
        Path(args.output)
        if args.output
        else Path(".benchmarks") / f"{benchmark_id}.json"
    )
    api_key = os.environ.get(args.question_api_key_env, "").strip()
    generator = QuestionGenerator(
        url=args.question_url,
        api_key=api_key,
        model=args.question_model,
    )
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "benchmark_id": benchmark_id,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "root": str(root),
        "user_identifier": scope,
        "mcp_url": args.mcp_url,
        "question_model": args.question_model,
        "question_count_per_file": args.question_count,
        "top_k": args.top_k,
        "search_concurrency": args.search_concurrency,
        "privacy_note": (
            "Source content is sent to the configured embedding provider and sampled passages "
            "are sent to the configured question model. This local artifact may contain source "
            "evidence and is excluded from Git."
        ),
        "documents": [],
        "results": [],
        "summary": {},
    }

    def checkpoint(rows: list[dict[str, Any]] | None = None) -> None:
        if rows is not None:
            artifact["results"] = rows
            artifact["summary"] = summarize_results(rows)
        atomic_json_write(output, artifact)

    print(f"BENCHMARK_DISCOVERED files={len(files)} scope={scope}", flush=True)
    for path in files:
        started = time.perf_counter()
        converted = await asyncio.to_thread(convert_document_to_markdown, path)
        passages = select_passages(
            converted.text,
            count=args.question_count,
            passage_chars=args.passage_chars,
        )
        questions, usage = await asyncio.to_thread(
            generator.generate,
            filename=path.name,
            passages=passages,
            count=args.question_count,
        )
        total_bytes, sha256 = file_digest(path)
        document = {
            "path": str(path),
            "filename": path.name,
            "title": path.stem,
            "suffix": path.suffix.lower(),
            "bytes": total_bytes,
            "sha256": sha256,
            "document_id": f"{safe_id(path.stem)}-{sha256[:12]}",
            "conversion": {
                "converter": converted.metadata.get("converter"),
                "chars": len(converted.text),
                "page_count": converted.metadata.get("page_count"),
                "seconds": time.perf_counter() - started,
            },
            "question_usage": usage,
            "questions": questions,
            "job": {},
        }
        artifact["documents"].append(document)
        checkpoint()
        print(
            "BENCHMARK_QUESTIONS "
            + json.dumps(
                {
                    "file": path.name,
                    "questions": len(questions),
                    "conversion_chars": len(converted.text),
                    "seconds": round(float(document["conversion"]["seconds"]), 3),
                },
                ensure_ascii=True,
            ),
            flush=True,
        )

    async with Client(args.mcp_url, timeout=1800) as client:
        for document in artifact["documents"]:
            started = time.perf_counter()
            job = await upload_document(
                client,
                document,
                user_identifier=scope,
                chunk_bytes=args.chunk_bytes,
                benchmark_id=benchmark_id,
            )
            document["job"] = job
            document["enqueue_seconds"] = time.perf_counter() - started
            checkpoint()
            print(
                "BENCHMARK_ENQUEUED "
                + json.dumps(
                    {
                        "file": document["filename"],
                        "job_id": job["job_id"],
                        "status": job["status"],
                        "seconds": round(float(document["enqueue_seconds"]), 3),
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
        await wait_for_jobs(
            client,
            artifact["documents"],
            user_identifier=scope,
            poll_seconds=args.poll_seconds,
            checkpoint=checkpoint,
        )

    failed = [
        document
        for document in artifact["documents"]
        if document["job"].get("status") != "succeeded"
    ]
    if failed:
        checkpoint()
        names = ", ".join(str(document["filename"]) for document in failed)
        raise RuntimeError(f"document ingestion failed for: {names}")

    results = await search_questions(
        mcp_url=args.mcp_url,
        user_identifier=scope,
        documents=artifact["documents"],
        top_k=args.top_k,
        concurrency=args.search_concurrency,
        checkpoint=checkpoint,
    )
    artifact["results"] = results
    artifact["summary"] = summarize_results(results)
    artifact["completed_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    checkpoint(results)
    print("BENCHMARK_COMPLETE " + json.dumps(artifact["summary"], sort_keys=True), flush=True)
    print(f"BENCHMARK_OUTPUT {output.resolve()}", flush=True)
    return artifact


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))
    try:
        asyncio.run(run(args))
    except (ValueError, RuntimeError) as exc:
        print(f"BENCHMARK_FAILED {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
