from __future__ import annotations

import json

import pytest

from scripts.real_document_benchmark import (
    evidence_rank,
    parse_generated_questions,
    select_passages,
    summarize_results,
)


def test_select_passages_returns_ten_grounded_samples_for_short_text() -> None:
    passages = select_passages("Alpha fact.\n\nBeta fact.", count=10, passage_chars=200)

    assert len(passages) == 10
    assert [item["source_id"] for item in passages] == [f"S{i}" for i in range(1, 11)]
    assert all(item["text"] for item in passages)


def test_parse_generated_questions_requires_exact_grounded_quotes() -> None:
    passages = [
        {"source_id": f"S{index}", "text": f"Section {index} states exact fact {index}."}
        for index in range(1, 11)
    ]
    response = json.dumps(
        {
            "questions": [
                {
                    "source_id": f"S{index}",
                    "question": f"What does section {index} state?",
                    "answer": f"Exact fact {index}.",
                    "evidence_quote": f"exact fact {index}",
                }
                for index in range(1, 11)
            ]
        }
    )

    questions = parse_generated_questions(response, passages, expected_count=10)

    assert len(questions) == 10
    assert questions[0]["evidence_quote"] == "exact fact 1"

    invalid = json.loads(response)
    invalid["questions"][0]["evidence_quote"] = "invented evidence"
    with pytest.raises(ValueError, match="exact substring"):
        parse_generated_questions(json.dumps(invalid), passages, expected_count=10)


def test_evidence_rank_prefers_quote_then_falls_back_to_answer() -> None:
    hits = [
        {"text": "Unrelated content."},
        {"text": "The exact evidence appears here."},
    ]

    assert evidence_rank(hits, evidence_quote="exact evidence", answer="unused") == (2, "quote")
    assert evidence_rank(hits, evidence_quote="missing", answer="unrelated content") == (
        1,
        "answer",
    )
    assert evidence_rank(hits, evidence_quote="missing", answer="absent") == (0, "none")


def test_summarize_results_reports_mrr_and_recall_cutoffs() -> None:
    rows = [
        {"document_id": "a", "evidence_rank": 1, "error": ""},
        {"document_id": "a", "evidence_rank": 5, "error": ""},
        {"document_id": "b", "evidence_rank": 0, "error": ""},
        {"document_id": "b", "evidence_rank": 0, "error": "provider failed"},
    ]

    summary = summarize_results(rows, cutoffs=(1, 3, 5, 10, 20))

    assert summary["question_count"] == 4
    assert summary["search_error_count"] == 1
    assert summary["mrr_at_20"] == pytest.approx(0.3)
    assert summary["recall_at_k"] == {
        "1": 0.25,
        "3": 0.25,
        "5": 0.5,
        "10": 0.5,
        "20": 0.5,
    }
    assert summary["documents"]["a"]["mrr_at_20"] == pytest.approx(0.6)
