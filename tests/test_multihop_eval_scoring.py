from __future__ import annotations

import pytest

from scripts import multihop_eval_scoring as scoring


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
