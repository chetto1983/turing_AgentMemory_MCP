"""Generate and judge LoCoMo answers from a completed direct-MCP retrieval artifact."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ModelResponse(NamedTuple):
    text: str
    input_tokens: int
    output_tokens: int


class JudgeResponse(NamedTuple):
    correct: bool
    reason: str
    input_tokens: int
    output_tokens: int


class Answerer(Protocol):
    model: str

    def answer(self, *, question: str, context: str) -> ModelResponse: ...


class Judge(Protocol):
    model: str

    def judge(
        self,
        *,
        question: str,
        reference_answer: str,
        predicted_answer: str,
    ) -> JudgeResponse: ...


def estimate_tokens(value: str) -> int:
    return max(1, (len(value.encode("utf-8")) + 3) // 4)


def row_key(row: dict[str, object]) -> str:
    return f"{row.get('sample_id')}:{row.get('question_index')}"


def format_context_document(hit: object) -> str:
    if not isinstance(hit, dict):
        raise ValueError("retrieved context row must be an object")
    rank = int(hit.get("rank") or 0)
    evidence = str(hit.get("dia_id") or "")
    content = str(hit.get("content") or "").strip()
    if rank <= 0 or not content:
        raise ValueError("retrieved context row is incomplete")
    return f"[rank={rank} evidence={evidence}] {content}"


def build_context(
    row: dict[str, object],
    *,
    max_context_tokens: int,
) -> tuple[str, int, int]:
    if max_context_tokens <= 0:
        raise ValueError("max_context_tokens must be positive")
    retrieved = row.get("retrieved")
    if not isinstance(retrieved, list):
        raise ValueError("retrieval row has no context")
    selected: list[str] = []
    used = 0
    for hit in retrieved:
        document = format_context_document(hit)
        tokens = estimate_tokens(document)
        if used + tokens > max_context_tokens:
            break
        selected.append(document)
        used += tokens
    return "\n".join(selected), len(selected), used


def pending_rows(
    retrieval_rows: list[dict[str, object]],
    completed_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    completed = {row_key(row) for row in completed_rows}
    return [row for row in retrieval_rows if row_key(row) not in completed]


def limit_rows(rows: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    return rows if limit == 0 else rows[:limit]


def parse_judge_payload(payload: object) -> tuple[bool, str]:
    if not isinstance(payload, dict) or type(payload.get("correct")) is not bool:
        raise ValueError("judge payload correct must be a JSON boolean")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("judge payload reason must be non-empty")
    return payload["correct"], reason.strip()


def evaluate_row(
    row: dict[str, object],
    *,
    answerer: Answerer,
    judge: Judge,
    max_context_tokens: int,
) -> dict[str, object]:
    question = str(row.get("question") or "").strip()
    reference = str(row.get("answer") or "").strip()
    if not question or not reference:
        raise ValueError("retrieval row requires question and reference answer")
    context, context_documents, context_tokens = build_context(
        row, max_context_tokens=max_context_tokens
    )
    answer = answerer.answer(question=question, context=context)
    judgment = judge.judge(
        question=question,
        reference_answer=reference,
        predicted_answer=answer.text,
    )
    return {
        "sample_id": row.get("sample_id"),
        "question_index": row.get("question_index"),
        "category": row.get("category"),
        "question_type": row.get("question_type"),
        "predicted_answer": answer.text,
        "correct": judgment.correct,
        "judge_reason": judgment.reason,
        "answer_model": answerer.model,
        "judge_model": judge.model,
        "usage": {
            "context_documents": context_documents,
            "context_estimated_tokens": context_tokens,
            "answer_input_tokens": answer.input_tokens,
            "answer_output_tokens": answer.output_tokens,
            "judge_input_tokens": judgment.input_tokens,
            "judge_output_tokens": judgment.output_tokens,
        },
    }


class OpenAIChatClient:
    def __init__(
        self, *, base_url: str, api_key: str, model: str, timeout_s: float = 120.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        if not self.base_url or not self.model or self.timeout_s <= 0:
            raise ValueError("OpenAI-compatible client configuration is incomplete")

    def complete(self, *, system: str, user: str, json_mode: bool = False) -> ModelResponse:
        body: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        request = Request(
            self.base_url + "/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"chat provider HTTP {exc.code}") from exc
        except (URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("chat provider unavailable or returned invalid JSON") from exc
        try:
            text = str(payload["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("chat provider returned an invalid response") from exc
        usage = payload.get("usage") if isinstance(payload, dict) else {}
        usage = usage if isinstance(usage, dict) else {}
        return ModelResponse(
            text,
            int(usage.get("prompt_tokens") or estimate_tokens(system + user)),
            int(usage.get("completion_tokens") or estimate_tokens(text)),
        )


class OpenAIAnswerer:
    def __init__(self, client: OpenAIChatClient) -> None:
        self.client = client
        self.model = client.model

    def answer(self, *, question: str, context: str) -> ModelResponse:
        return self.client.complete(
            system=(
                "Answer the question using only the retrieved conversation context. "
                "Return the shortest supported answer, usually one phrase or sentence. "
                "Do not explain, cite evidence ranks, list alternatives, or add plausible details. "
                "For a relative date, resolve it from the dated session when possible; otherwise "
                "preserve the exact relative-time phrase from the context. "
                "If the context is insufficient, answer only: unknown."
            ),
            user=f"Question:\n{question}\n\nRetrieved context:\n{context}",
        )


class OpenAIJudge:
    def __init__(self, client: OpenAIChatClient) -> None:
        self.client = client
        self.model = client.model

    def judge(
        self,
        *,
        question: str,
        reference_answer: str,
        predicted_answer: str,
    ) -> JudgeResponse:
        response = self.client.complete(
            system=(
                "Judge whether the predicted answer is semantically correct relative to the "
                "reference answer. Return JSON with boolean correct and short string reason."
            ),
            user=json.dumps(
                {
                    "question": question,
                    "reference_answer": reference_answer,
                    "predicted_answer": predicted_answer,
                },
                ensure_ascii=False,
            ),
            json_mode=True,
        )
        try:
            correct, reason = parse_judge_payload(json.loads(response.text))
        except json.JSONDecodeError as exc:
            raise RuntimeError("judge returned invalid JSON") from exc
        return JudgeResponse(correct, reason, response.input_tokens, response.output_tokens)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")
    )
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""))
    parser.add_argument("--answer-model", default=os.environ.get("LOCOMO_ANSWER_MODEL", "gpt-5"))
    parser.add_argument("--judge-model", default=os.environ.get("LOCOMO_JUDGE_MODEL", "gpt-5"))
    parser.add_argument("--max-context-tokens", type=int, default=32768)
    parser.add_argument(
        "--limit", type=int, default=0, help="Evaluate only the first N rows; 0 means all."
    )
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    retrieval = json.loads(Path(args.retrieval).read_text(encoding="utf-8"))
    if retrieval.get("contract", {}).get("ingest") != "memory_store_messages":
        raise RuntimeError("retrieval artifact is not a direct-MCP turns-only benchmark")
    rows = limit_rows(
        [row for row in retrieval.get("results", []) if isinstance(row, dict)],
        args.limit,
    )
    output = Path(args.output)
    completed: list[dict[str, object]] = []
    if args.resume and output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        completed = [row for row in previous.get("results", []) if isinstance(row, dict)]
    answerer = OpenAIAnswerer(
        OpenAIChatClient(base_url=args.base_url, api_key=args.api_key, model=args.answer_model)
    )
    judge = OpenAIJudge(
        OpenAIChatClient(base_url=args.base_url, api_key=args.api_key, model=args.judge_model)
    )
    results = list(completed)
    for row in pending_rows(rows, completed):
        results.append(
            evaluate_row(
                row,
                answerer=answerer,
                judge=judge,
                max_context_tokens=args.max_context_tokens,
            )
        )
        correct = sum(1 for result in results if result.get("correct") is True)
        payload = {
            "benchmark": "locomo-direct-mcp-answer-eval",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "retrieval_artifact": str(Path(args.retrieval)),
            "retrieval_ablation_id": retrieval.get("parameters", {}).get("ablation_id"),
            "answer_model": answerer.model,
            "judge_model": judge.model,
            "max_context_tokens": args.max_context_tokens,
            "limit": args.limit,
            "total": len(rows),
            "completed": len(results),
            "correct": correct,
            "accuracy": correct / len(results) if results else 0.0,
            "results": results,
        }
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    correct = sum(1 for result in results if result.get("correct") is True)
    payload = {
        "benchmark": "locomo-direct-mcp-answer-eval",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "retrieval_artifact": str(Path(args.retrieval)),
        "retrieval_ablation_id": retrieval.get("parameters", {}).get("ablation_id"),
        "answer_model": answerer.model,
        "judge_model": judge.model,
        "max_context_tokens": args.max_context_tokens,
        "limit": args.limit,
        "total": len(rows),
        "completed": len(results),
        "correct": correct,
        "accuracy": correct / len(results) if results else 0.0,
        "results": results,
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    main()
