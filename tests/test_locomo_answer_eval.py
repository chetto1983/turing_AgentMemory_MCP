from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "locomo_answer_eval",
    ROOT / "scripts" / "eval_locomo_answers.py",
)
assert SPEC is not None
assert SPEC.loader is not None
answers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(answers)


class RecordingAnswerer:
    model = "answer-model"

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def answer(self, *, question: str, context: str) -> answers.ModelResponse:
        self.calls.append({"question": question, "context": context})
        return answers.ModelResponse("Rome", 12, 2)


class RecordingJudge:
    model = "judge-model"

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def judge(
        self,
        *,
        question: str,
        reference_answer: str,
        predicted_answer: str,
    ) -> answers.JudgeResponse:
        self.calls.append(
            {
                "question": question,
                "reference_answer": reference_answer,
                "predicted_answer": predicted_answer,
            }
        )
        return answers.JudgeResponse(True, "The location matches.", 20, 3)


class RecordingChatClient:
    model = "chat-model"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        *,
        system: str,
        user: str,
        json_mode: bool = False,
    ) -> answers.ModelResponse:
        self.calls.append({"system": system, "user": user, "json_mode": json_mode})
        return answers.ModelResponse("Rome", 10, 1)


def retrieval_row() -> dict[str, object]:
    return {
        "sample_id": "conv-1",
        "question_index": 7,
        "question": "Where does Alice live?",
        "answer": "Rome",
        "retrieved": [
            {"rank": 1, "dia_id": "D1:1", "content": "Alice now lives in Rome."},
            {"rank": 2, "dia_id": "D1:2", "content": "Alice likes hiking."},
        ],
    }


def test_answerer_receives_only_question_and_retrieved_context() -> None:
    answerer = RecordingAnswerer()
    judge = RecordingJudge()

    result = answers.evaluate_row(
        retrieval_row(),
        answerer=answerer,
        judge=judge,
        max_context_tokens=200,
    )

    assert answerer.calls == [
        {
            "question": "Where does Alice live?",
            "context": "[rank=1 evidence=D1:1] Alice now lives in Rome.\n"
            "[rank=2 evidence=D1:2] Alice likes hiking.",
        }
    ]
    assert "reference_answer" not in answerer.calls[0]
    assert judge.calls[0]["reference_answer"] == "Rome"
    assert result["correct"] is True
    assert result["answer_model"] == "answer-model"
    assert result["judge_model"] == "judge-model"
    assert result["usage"]["context_estimated_tokens"] > 0


def test_openai_answerer_requires_short_grounded_temporal_answers() -> None:
    client = RecordingChatClient()
    answerer = answers.OpenAIAnswerer(client)  # type: ignore[arg-type]

    answerer.answer(
        question="When did Alice move?",
        context="[rank=1 evidence=D1:1] Yesterday Alice moved to Rome.",
    )

    system = str(client.calls[0]["system"])
    assert "shortest supported answer" in system
    assert "Do not explain" in system
    assert "relative date" in system


def test_context_budget_keeps_whole_ranked_documents() -> None:
    row = retrieval_row()
    first = answers.format_context_document(row["retrieved"][0])
    budget = answers.estimate_tokens(first)

    context, count, tokens = answers.build_context(row, max_context_tokens=budget)

    assert context == first
    assert count == 1
    assert tokens <= budget


def test_resume_keys_are_stable_and_skip_completed_rows() -> None:
    rows = [retrieval_row(), {**retrieval_row(), "question_index": 8}]
    completed = [{"sample_id": "conv-1", "question_index": 7, "correct": True}]

    pending = answers.pending_rows(rows, completed)

    assert [answers.row_key(row) for row in pending] == ["conv-1:8"]


def test_limit_rows_selects_only_the_requested_prefix() -> None:
    rows = [
        {**retrieval_row(), "question_index": index}
        for index in range(1, 4)
    ]

    assert answers.limit_rows(rows, 2) == rows[:2]
    assert answers.limit_rows(rows, 0) == rows
    with pytest.raises(ValueError, match="non-negative"):
        answers.limit_rows(rows, -1)


@pytest.mark.parametrize("value", ["yes", "1", {}, []])
def test_judge_payload_requires_a_json_boolean(value: object) -> None:
    with pytest.raises(ValueError, match="correct"):
        answers.parse_judge_payload({"correct": value, "reason": "x"})
