"""Proves the Phase-7 entry guard (D-09/D-10) actually fires. Mirrors
tests/test_no_skip_as_green_guard.py's fail-closed discipline: a missing,
malformed, or NO_GO gate-result.json must hard-fail -- never a skip escape
hatch. Deliberately contains no skip marker of any kind (verified by
`bash scripts/check-file-size.sh`-adjacent grep in this plan's verification
step, not by a self-referential assertion, since a string literal proving
its own absence from the same file is a paradox)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from turing_agentmemory_mcp.gate_guard import (
    assert_gate_go,
    load_verdict,
    validate_gate_result_schema,
)

_REQUIRED_FIELDS = {
    "verdict",
    "tolerance",
    "provider_config",
    "corpus_verification",
    "metrics_diff",
    "baseline_bar",
    "e2e_diff",
    "latency",
    "runs",
}


def _well_formed(verdict: str = "GO") -> dict:
    return {field: {} for field in _REQUIRED_FIELDS if field != "verdict"} | {"verdict": verdict}


class TestValidateGateResultSchema:
    def test_accepts_well_formed_go_dict(self) -> None:
        validate_gate_result_schema(_well_formed("GO"))

    def test_accepts_well_formed_no_go_dict(self) -> None:
        validate_gate_result_schema(_well_formed("NO_GO"))

    @pytest.mark.parametrize("missing_field", sorted(_REQUIRED_FIELDS))
    def test_raises_when_a_mandated_field_is_absent(self, missing_field: str) -> None:
        obj = _well_formed("GO")
        del obj[missing_field]
        with pytest.raises((ValueError, AssertionError)):
            validate_gate_result_schema(obj)

    @pytest.mark.parametrize("bad_verdict", ["MAYBE", "", "go", "no_go", "PENDING"])
    def test_raises_when_verdict_is_not_go_or_no_go(self, bad_verdict: str) -> None:
        obj = _well_formed(bad_verdict)
        with pytest.raises((ValueError, AssertionError)):
            validate_gate_result_schema(obj)

    @pytest.mark.parametrize("non_dict", [None, [], "not a dict", 42, ("verdict", "GO")])
    def test_raises_when_top_level_value_is_not_a_dict(self, non_dict: object) -> None:
        with pytest.raises((ValueError, AssertionError)):
            validate_gate_result_schema(non_dict)


class TestAssertGateGo:
    def test_raises_when_file_is_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "gate-result.json"
        with pytest.raises(AssertionError):
            assert_gate_go(missing)

    def test_raises_on_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "gate-result.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(AssertionError):
            assert_gate_go(path)

    def test_raises_when_verdict_is_no_go(self, tmp_path: Path) -> None:
        path = tmp_path / "gate-result.json"
        path.write_text(json.dumps(_well_formed("NO_GO")), encoding="utf-8")
        with pytest.raises(AssertionError):
            assert_gate_go(path)

    def test_passes_when_verdict_is_go(self, tmp_path: Path) -> None:
        path = tmp_path / "gate-result.json"
        path.write_text(json.dumps(_well_formed("GO")), encoding="utf-8")
        assert_gate_go(path)  # must not raise

    def test_rereads_the_file_fresh_on_every_call_no_caching(self, tmp_path: Path) -> None:
        path = tmp_path / "gate-result.json"
        path.write_text(json.dumps(_well_formed("GO")), encoding="utf-8")
        assert_gate_go(path)  # first call: GO, passes

        path.write_text(json.dumps(_well_formed("NO_GO")), encoding="utf-8")
        with pytest.raises(AssertionError):
            assert_gate_go(path)  # second call must see the rewritten NO_GO, not a cached GO

    def test_load_verdict_returns_the_verdict_string(self, tmp_path: Path) -> None:
        path = tmp_path / "gate-result.json"
        path.write_text(json.dumps(_well_formed("GO")), encoding="utf-8")
        assert load_verdict(path) == "GO"
