"""Ingest a real document directory through MCP and score ten grounded queries per file.

Split by concern per D-08/D-09: deterministic scoring and evidence-grounding
helpers live in `real_document_benchmark_scoring.py`. This module owns the CLI
(`main`), the live-MCP upload/ingest/search runner, and `run`. `evidence_rank`,
`normalize_text`, `parse_generated_questions`, `select_evidence`,
`select_passages`, and `summarize_results` are re-imported unchanged so
`tests/test_real_document_benchmark.py`'s import path keeps resolving. Not
wired into CI per D-10.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastmcp import Client

from turing_agentmemory_mcp.document_processing import convert_document_to_markdown

try:
    from real_document_benchmark_scoring import (  # noqa: F401 - some re-exported for tests
        evidence_rank,
        file_digest,
        load_env_file,
        normalize_text,
        parse_generated_questions,
        safe_id,
        select_evidence,
        select_passages,
        summarize_results,
        utc_timestamp,
    )
except ImportError:  # running as `python scripts/real_document_benchmark.py` directly
    from scripts.real_document_benchmark_scoring import (  # noqa: F401 - some re-exported for tests
        evidence_rank,
        file_digest,
        load_env_file,
        normalize_text,
        parse_generated_questions,
        safe_id,
        select_evidence,
        select_passages,
        summarize_results,
        utc_timestamp,
    )

QUESTION_COUNT = 10
DEFAULT_TOP_K = 20
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
    output = Path(args.output) if args.output else Path(".benchmarks") / f"{benchmark_id}.json"
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
