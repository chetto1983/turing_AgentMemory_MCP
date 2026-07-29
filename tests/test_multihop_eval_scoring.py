from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import multihop_eval_scoring as scoring
from scripts.real_document_benchmark_scoring import load_frozen_questions

ROOT = Path(__file__).resolve().parents[1]


def test_bridging_set_recall_returns_one_when_all_required_passages_are_found() -> None:
    hits = [
        {"text": "Alpha bridge appears here."},
        {"text": "Beta bridge appears here."},
        {"text": "Gamma bridge appears here."},
    ]

    recall = scoring.bridging_set_recall_at_k(
        hits,
        ["Alpha bridge", "Beta bridge", "Gamma bridge"],
        3,
    )

    assert recall == 1.0


def test_bridging_set_recall_returns_exact_fraction_for_partial_match() -> None:
    hits = [
        {"text": "Alpha bridge appears here."},
        {"text": "Beta bridge appears here."},
    ]

    recall = scoring.bridging_set_recall_at_k(
        hits,
        ["Alpha bridge", "Beta bridge", "Gamma bridge"],
        2,
    )

    assert recall == 2 / 3


def test_bridging_set_recall_returns_zero_when_no_required_passage_is_found() -> None:
    hits = [{"text": "Unrelated passage."}]

    recall = scoring.bridging_set_recall_at_k(
        hits,
        ["Alpha bridge", "Beta bridge", "Gamma bridge"],
        1,
    )

    assert recall == 0.0


def test_bridging_set_recall_excludes_matches_after_top_k() -> None:
    hits = [
        {"text": "Alpha bridge appears here."},
        {"text": "Beta bridge appears here."},
        {"text": "Gamma bridge appears too late."},
    ]

    recall = scoring.bridging_set_recall_at_k(
        hits,
        ["Alpha bridge", "Beta bridge", "Gamma bridge"],
        2,
    )

    assert recall == 2 / 3


def test_bridging_set_recall_deduplicates_required_passages() -> None:
    hits = [{"text": "Alpha bridge appears here."}]

    recall = scoring.bridging_set_recall_at_k(
        hits,
        ["Alpha bridge", "Alpha bridge", "Beta bridge"],
        1,
    )

    assert recall == 1 / 2


def test_bridging_set_recall_credits_two_passages_found_in_one_hit() -> None:
    hits = [{"text": "Alpha bridge connects directly to the Beta bridge."}]

    recall = scoring.bridging_set_recall_at_k(
        hits,
        ["Alpha bridge", "Beta bridge"],
        1,
    )

    assert recall == 1.0


def test_bridging_set_recall_rejects_an_empty_required_set() -> None:
    with pytest.raises(ValueError, match="bridging"):
        scoring.bridging_set_recall_at_k([], [], 10)


def test_bridging_set_recall_uses_canonical_text_normalization() -> None:
    hits = [{"text": "  ALPHA,\nbridge!  "}]

    recall = scoring.bridging_set_recall_at_k(hits, ["alpha bridge"], 1)

    assert recall == 1.0


def test_rejection_filter_accepts_answer_contained_in_one_hit() -> None:
    hits = [
        {"text": "Unrelated passage."},
        {"text": "The final answer is Rome."},
    ]

    assert scoring.single_passage_answerable(
        hits,
        answer="Rome",
        evidence_quote="missing evidence",
    )


def test_rejection_filter_accepts_evidence_contained_in_one_hit() -> None:
    hits = [{"text": "The exact evidence quote appears here."}]

    assert scoring.single_passage_answerable(
        hits,
        answer="missing answer",
        evidence_quote="exact evidence quote",
    )


def test_rejection_filter_rejects_answer_that_only_emerges_across_hits() -> None:
    hits = [
        {"text": "The first hop identifies Alpha."},
        {"text": "The second hop links Beta to the destination."},
    ]

    assert not scoring.single_passage_answerable(
        hits,
        answer="Alpha Beta destination",
        evidence_quote="Alpha links Beta to the destination",
    )


def test_rejection_filter_does_not_delegate_to_set_recall(monkeypatch) -> None:
    def unexpected_metric_call(*args, **kwargs) -> float:
        raise AssertionError("the rejection filter must not call the set-recall metric")

    monkeypatch.setattr(
        scoring,
        "bridging_set_recall_at_k",
        unexpected_metric_call,
    )

    assert scoring.single_passage_answerable(
        [{"text": "The answer is Rome."}],
        answer="Rome",
        evidence_quote="",
    )


def test_multihop_required_keys_define_a_new_bridging_passage_schema() -> None:
    assert scoring.MULTIHOP_REQUIRED_KEYS == {
        "source_id",
        "question",
        "answer",
        "bridging_passages",
    }


def test_load_multihop_questions_accepts_valid_rows(tmp_path) -> None:
    rows = [
        {
            "source_id": "Q1",
            "question": "Which destination follows from both bridges?",
            "answer": "Rome",
            "bridging_passages": [
                "Alpha identifies the relevant route.",
                "The relevant route terminates in Rome.",
            ],
        }
    ]
    path = tmp_path / "multihop-questions.json"
    path.write_text(json.dumps(rows), encoding="utf-8")

    assert scoring.load_multihop_questions(path) == rows


def test_load_multihop_questions_names_row_missing_bridging_passages(tmp_path) -> None:
    rows = [
        {
            "source_id": "Q1",
            "question": "Which destination follows from both bridges?",
            "answer": "Rome",
            "evidence_quote": "The old single-passage field is not the new schema.",
        }
    ]
    path = tmp_path / "missing-bridges.json"
    path.write_text(json.dumps(rows), encoding="utf-8")

    with pytest.raises(ValueError, match=r"row 0.*bridging_passages"):
        scoring.load_multihop_questions(path)


def test_load_multihop_questions_rejects_one_passage_row_by_index(tmp_path) -> None:
    rows = [
        {
            "source_id": "Q1",
            "question": "Which destination follows from both bridges?",
            "answer": "Rome",
            "bridging_passages": ["Only one passage exists."],
        }
    ]
    path = tmp_path / "one-bridge.json"
    path.write_text(json.dumps(rows), encoding="utf-8")

    with pytest.raises(ValueError, match=r"row 0.*at least 2"):
        scoring.load_multihop_questions(path)


def test_load_multihop_questions_requires_a_list_of_strings(tmp_path) -> None:
    rows = [
        {
            "source_id": "Q1",
            "question": "Which destination follows from both bridges?",
            "answer": "Rome",
            "bridging_passages": ["First passage.", 2],
        }
    ]
    path = tmp_path / "invalid-bridge-type.json"
    path.write_text(json.dumps(rows), encoding="utf-8")

    with pytest.raises(ValueError, match=r"row 0.*list\[str\]"):
        scoring.load_multihop_questions(path)


def test_existing_phase6_frozen_questions_contract_still_loads() -> None:
    path = ROOT / "baseline" / "03-turingdb" / "frozen-questions.json"

    loaded = load_frozen_questions(path)

    assert loaded
    assert all("evidence_quote" in row for rows in loaded.values() for row in rows)


def test_summarize_multihop_results_reports_means_improvements_and_regressions() -> None:
    per_question_by_arm = {
        "fused_base": [0.0, 1.0, 0.0],
        "entity_boost": [0.5, 1.0, 0.0],
        "fused_graph": [1.0, 0.5, 1.0],
    }

    summary = scoring.summarize_multihop_results(
        per_question_by_arm,
        baseline_arm="fused_base",
    )

    assert summary == {
        "fused_base": {
            "mean_set_recall_at_k": 1 / 3,
            "improved": 0,
            "regressed": 0,
        },
        "entity_boost": {
            "mean_set_recall_at_k": 0.5,
            "improved": 1,
            "regressed": 0,
        },
        "fused_graph": {
            "mean_set_recall_at_k": 2.5 / 3,
            "improved": 2,
            "regressed": 1,
        },
    }


def test_summarize_multihop_results_rejects_misaligned_question_counts() -> None:
    with pytest.raises(ValueError, match="same questions"):
        scoring.summarize_multihop_results(
            {
                "fused_base": [0.0, 1.0],
                "fused_graph": [1.0],
            },
            baseline_arm="fused_base",
        )
