"""Verifies the COMMITTED baseline/06-gate/gate-result.json artifact (SC#3/D-09/D-10).

Two distinct guarantees, kept separate per the plan's own distinction:

1. Well-formedness (always green, regardless of verdict value) -- the committed
   artifact carries every D-09-mandated field, a recognized verdict, and both the
   aggregate + per_document granularity of metrics_diff (D-02).
2. The committed-verdict gate (green only when verdict == GO) -- calls
   `turing_agentmemory_mcp.gate_guard.assert_gate_go` on the real committed path.
   No `pytest.skip` anywhere in this file: a missing or NO_GO artifact is a hard
   failure that correctly blocks the phase and Phase-7 cutover, matching
   `tests/test_no_skip_as_green_guard.py`'s no-skip-as-green discipline.
"""

from __future__ import annotations

import json
from pathlib import Path

from turing_agentmemory_mcp.gate_guard import assert_gate_go, validate_gate_result_schema

GATE_RESULT_PATH = Path(__file__).resolve().parents[1] / "baseline" / "06-gate" / "gate-result.json"


def _load_committed_gate_result() -> dict:
    return json.loads(GATE_RESULT_PATH.read_text(encoding="utf-8"))


class TestCommittedGateResultWellFormed:
    """Always green regardless of the committed verdict's value."""

    def test_committed_artifact_exists(self) -> None:
        assert GATE_RESULT_PATH.is_file(), f"expected committed gate artifact at {GATE_RESULT_PATH}"

    def test_committed_artifact_passes_schema_validation(self) -> None:
        obj = _load_committed_gate_result()
        validate_gate_result_schema(obj)  # must not raise

    def test_committed_artifact_verdict_is_a_recognized_value(self) -> None:
        obj = _load_committed_gate_result()
        assert obj["verdict"] in {"GO", "NO_GO"}

    def test_metrics_diff_carries_both_aggregate_and_per_document_granularity(self) -> None:
        obj = _load_committed_gate_result()
        assert "aggregate" in obj["metrics_diff"]
        assert "per_document" in obj["metrics_diff"]
        assert obj["metrics_diff"]["aggregate"], "aggregate metrics_diff must not be empty"
        assert obj["metrics_diff"]["per_document"], "per_document metrics_diff must not be empty"

    def test_locked_metrics_present_in_aggregate_diff(self) -> None:
        obj = _load_committed_gate_result()
        aggregate = obj["metrics_diff"]["aggregate"]
        for metric in ("mrr_at_20", "recall_at_1", "recall_at_20"):
            assert metric in aggregate
            assert "within_band" in aggregate[metric]

    def test_corpus_verification_and_provider_config_are_recorded(self) -> None:
        obj = _load_committed_gate_result()
        assert "ok" in obj["corpus_verification"]
        assert isinstance(obj["provider_config"], dict)

    def test_runs_and_tolerance_and_latency_are_recorded(self) -> None:
        obj = _load_committed_gate_result()
        assert obj["runs"] >= 3
        assert obj["tolerance"]["run_count"] == obj["runs"]
        assert "mean" in obj["latency"]


class TestCommittedGateVerdictIsGo:
    """Green only when the committed verdict is GO -- no pytest.skip escape hatch.

    A NO_GO or missing artifact correctly fails this test and blocks the phase.
    """

    def test_assert_gate_go_passes_on_the_committed_artifact(self) -> None:
        assert_gate_go(GATE_RESULT_PATH)  # must not raise
