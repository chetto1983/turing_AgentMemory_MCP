from __future__ import annotations

import json

import pytest

from scripts.real_document_benchmark import (
    evidence_rank,
    normalize_text,
    parse_generated_questions,
    select_evidence,
    select_passages,
    summarize_results,
)


def test_select_passages_returns_ten_grounded_samples_for_short_text() -> None:
    passages = select_passages("Alpha fact.\n\nBeta fact.", count=10, passage_chars=200)

    assert len(passages) == 10
    assert [item["source_id"] for item in passages] == [f"S{i}" for i in range(1, 11)]
    assert all(item["text"] for item in passages)


def test_parse_generated_questions_derives_exact_evidence() -> None:
    passages = [
        {"source_id": f"S{index}", "text": f"Section {index} states exact fact number {index}."}
        for index in range(1, 11)
    ]
    response = json.dumps(
        {
            "questions": [
                {
                    "source_id": f"S{index}",
                    "question": f"What does section {index} state?",
                    "answer": f"exact fact number {index}",
                }
                for index in range(1, 11)
            ]
        }
    )

    questions = parse_generated_questions(response, passages, expected_count=10)

    assert len(questions) == 10
    for index, question in enumerate(questions, 1):
        evidence = question["evidence_quote"]
        assert evidence in passages[index - 1]["text"]
        assert normalize_text(f"exact fact number {index}") in normalize_text(evidence)


def test_parse_generated_questions_rejects_paraphrased_answers() -> None:
    passages = [
        {"source_id": f"S{index}", "text": f"Section {index} states exact fact number {index}."}
        for index in range(1, 11)
    ]
    payload = {
        "questions": [
            {
                "source_id": f"S{index}",
                "question": f"What does section {index} state?",
                "answer": f"exact fact number {index}",
            }
            for index in range(1, 11)
        ]
    }
    payload["questions"][0]["answer"] = "completely unrelated invented paraphrase"

    with pytest.raises(ValueError, match="weak token overlap"):
        parse_generated_questions(json.dumps(payload), passages, expected_count=10)


def test_select_evidence_returns_exact_substring_with_punctuation() -> None:
    passage = "First sentence here. The capital is Rome, founded long ago! Third one."

    evidence = select_evidence(
        passage,
        question="Which city is the capital?",
        answer="the capital is Rome",
    )

    assert evidence in passage
    assert evidence == "The capital is Rome, founded long ago!"


def test_select_evidence_handles_unicode() -> None:
    passage = "Информация раздела. Столица страны — Москва, очень большой город. Конец."

    evidence = select_evidence(
        passage,
        question="Какая столица?",
        answer="столица страны — Москва",
    )

    assert evidence in passage
    assert "Москва" in evidence


def test_select_evidence_handles_spreadsheet_rows() -> None:
    passage = (
        "| Region | Orders | Revenue |\n"
        "| North | 120 | 45000 |\n"
        "| South | 305 | 98200 |\n"
        "| West | 87 | 21000 |"
    )

    evidence = select_evidence(
        passage,
        question="How many orders did the South region record?",
        answer="South 305 98200",
    )

    assert evidence in passage
    assert evidence == "| South | 305 | 98200 |"


def test_select_evidence_grounds_repeated_short_source() -> None:
    passage = "The service level target is ninety five percent uptime each month."

    for _ in range(3):
        evidence = select_evidence(
            passage,
            question="What is the uptime target?",
            answer="ninety five percent uptime",
        )
        assert evidence in passage
        assert normalize_text("ninety five percent uptime") in normalize_text(evidence)


def test_select_evidence_rejects_no_overlap() -> None:
    passage = "The service level target is ninety five percent uptime each month."

    with pytest.raises(ValueError, match="weak token overlap"):
        select_evidence(
            passage,
            question="What is the mascot?",
            answer="a purple dragon named zephyr",
        )


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
