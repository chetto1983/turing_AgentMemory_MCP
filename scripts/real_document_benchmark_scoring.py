"""Deterministic scoring and evidence-grounding helpers for real_document_benchmark.py.

Split out per D-08/D-09 so the CLI/live-MCP runner in `real_document_benchmark.py`
stays under the 600-LOC cap. `evidence_rank`, `normalize_text`,
`parse_generated_questions`, `select_evidence`, `select_passages`, and
`summarize_results` are re-imported unchanged into `real_document_benchmark.py`
so `tests/test_real_document_benchmark.py`'s import path keeps resolving.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_CUTOFFS = (1, 3, 5, 10, 20)
MIN_EVIDENCE_CHARS = 12
MAX_EVIDENCE_CHARS = 320
MIN_ANSWER_COVERAGE = 0.5
_UNIT_PATTERN = re.compile(r".+?(?:[.!?。！？]+|$)", re.UNICODE)


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
            sum((1.0 / rank) if 0 < rank <= 20 else 0.0 for rank in ranks) / count if count else 0.0
        ),
        "recall_at_k": {
            str(cutoff): (sum(0 < rank <= cutoff for rank in ranks) / count if count else 0.0)
            for cutoff in cutoffs
        },
        "latency_ms": {
            "mean": statistics.fmean(float(row.get("latency_ms") or 0.0) for row in rows)
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
