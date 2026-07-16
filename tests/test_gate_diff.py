from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts.gate_diff import (
    build_gate_result,
    compute_verdict,
    corrected_checks,
    diff_metrics,
    is_stub_provider,
    main,
    mean_of_runs,
    meaningful_subset_summary,
    verify_corpus,
)

BASELINE_ROOT = Path(__file__).resolve().parents[1] / "baseline"
TURINGDB_E2E = BASELINE_ROOT / "03-turingdb" / "e2e-results.json"
ARCADEDB_E2E = BASELINE_ROOT / "04-arcadedb" / "e2e-results.json"
REAL_DOCUMENT_BENCHMARK = BASELINE_ROOT / "03-turingdb" / "real-document-benchmark.json"

EXPECTED_BAR_MRR_AT_20 = 0.5979
EXPECTED_BAR_RECALL_AT_1 = 0.5143
EXPECTED_BAR_RECALL_AT_20 = 0.7714

EXPECTED_NON_PASSING_NAMES = {
    "document_ingest_text_writes_chunks",
    "document_search_retrieves_exact_top1_with_citation_and_neighbor_context",
    "document_search_hybrid_exact_code_match_explains_lexical_score",
    "document_ingest_text_is_idempotent_for_same_payload",
    "document_reindex_text_replaces_old_chunks_and_metadata",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_corrected_checks_yields_14_pass_5_non_pass_over_committed_baseline() -> None:
    raw = _load_json(TURINGDB_E2E)
    corrected = corrected_checks(raw["checks"])

    passing = [row for row in corrected if row["ok"]]
    non_passing = [row for row in corrected if not row["ok"]]

    assert len(corrected) == 19
    assert len(passing) == 14
    assert len(non_passing) == 5
    assert {row["name"] for row in non_passing} == EXPECTED_NON_PASSING_NAMES


def test_corrected_checks_forces_ok_false_when_error_key_present_regardless_of_other_fields() -> (
    None
):
    raw_checks = [
        {"name": "x", "ok": True, "detail": True, "error": {"type": "Boom", "message": "m"}},
    ]

    corrected = corrected_checks(raw_checks)

    assert corrected[0]["ok"] is False


def test_corrected_checks_detail_truthy_is_ok_true_falsy_is_ok_false() -> None:
    raw_checks = [
        {"name": "truthy-dict", "ok": False, "detail": {"a": 1}},
        {"name": "truthy-bool", "ok": False, "detail": True},
        {"name": "falsy-bool", "ok": True, "detail": False},
        {"name": "falsy-none", "ok": True, "detail": None},
    ]

    corrected = corrected_checks(raw_checks)
    by_name = {row["name"]: row["ok"] for row in corrected}

    assert by_name["truthy-dict"] is True
    assert by_name["truthy-bool"] is True
    assert by_name["falsy-bool"] is False
    assert by_name["falsy-none"] is False


def test_verify_corpus_ok_true_on_byte_identical_stand_in_files(tmp_path: Path) -> None:
    from scripts.real_document_benchmark_scoring import file_digest

    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    doc_a = corpus_root / "alpha.txt"
    doc_b = corpus_root / "beta.txt"
    doc_a.write_bytes(b"alpha stand-in content")
    doc_b.write_bytes(b"beta stand-in content")

    _, sha_a = file_digest(doc_a)
    _, sha_b = file_digest(doc_b)

    manifest_path = tmp_path / "corpus-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "documents": [
                    {"filename": "alpha.txt", "bytes": doc_a.stat().st_size, "sha256": sha_a},
                    {"filename": "beta.txt", "bytes": doc_b.stat().st_size, "sha256": sha_b},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = verify_corpus(corpus_root, manifest_path)

    assert result["ok"] is True
    assert result["mismatches"] == []


def test_verify_corpus_fails_closed_on_tampered_file(tmp_path: Path) -> None:
    from scripts.real_document_benchmark_scoring import file_digest

    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    doc_a = corpus_root / "alpha.txt"
    doc_a.write_bytes(b"alpha stand-in content")
    _, sha_a = file_digest(doc_a)

    manifest_path = tmp_path / "corpus-manifest.json"
    manifest_path.write_text(
        json.dumps({"documents": [{"filename": "alpha.txt", "bytes": 999, "sha256": sha_a}]}),
        encoding="utf-8",
    )

    # tamper after manifest was written
    doc_a.write_bytes(b"TAMPERED content, different bytes")

    result = verify_corpus(corpus_root, manifest_path)

    assert result["ok"] is False
    assert any(m["filename"] == "alpha.txt" for m in result["mismatches"])


def test_verify_corpus_fails_closed_on_missing_file(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()

    manifest_path = tmp_path / "corpus-manifest.json"
    manifest_path.write_text(
        json.dumps({"documents": [{"filename": "ghost.txt", "bytes": 1, "sha256": "deadbeef"}]}),
        encoding="utf-8",
    )

    result = verify_corpus(corpus_root, manifest_path)

    assert result["ok"] is False
    assert any(m["filename"] == "ghost.txt" for m in result["mismatches"])


def test_is_stub_provider_true_for_arcadedb_stub_capture() -> None:
    e2e_json = _load_json(ARCADEDB_E2E)

    assert is_stub_provider(e2e_json) is True


def test_is_stub_provider_false_for_turingdb_real_sidecar_capture() -> None:
    e2e_json = _load_json(TURINGDB_E2E)

    assert is_stub_provider(e2e_json) is False


def _run(
    mrr: float, recall1: float, recall20: float, *, latency_mean: float = 50.0, documents=None
):
    return {
        "summary": {
            "mrr_at_20": mrr,
            "recall_at_k": {"1": recall1, "20": recall20},
            "latency_ms": {"mean": latency_mean},
            "documents": documents or {},
        }
    }


def _doc_summary(mrr: float, recall1: float, recall20: float, *, latency_mean: float = 5.0):
    return {
        "mrr_at_20": mrr,
        "recall_at_k": {"1": recall1, "20": recall20},
        "latency_ms": {"mean": latency_mean},
    }


def test_meaningful_subset_summary_reproduces_the_committed_d01_bar() -> None:
    benchmark_json = _load_json(REAL_DOCUMENT_BENCHMARK)

    summary = meaningful_subset_summary(benchmark_json)

    assert math.isclose(summary["mrr_at_20"], EXPECTED_BAR_MRR_AT_20, abs_tol=1e-3)
    assert math.isclose(summary["recall_at_k"]["1"], EXPECTED_BAR_RECALL_AT_1, abs_tol=1e-3)
    assert math.isclose(summary["recall_at_k"]["20"], EXPECTED_BAR_RECALL_AT_20, abs_tol=1e-3)


def test_mean_of_runs_computes_arithmetic_mean_and_stddev() -> None:
    runs = [_run(0.9, 0.8, 0.9), _run(1.0, 1.0, 1.0), _run(0.8, 0.6, 0.8)]

    result = mean_of_runs(runs)

    assert result["run_count"] == 3
    assert math.isclose(result["metrics"]["mrr_at_20"]["mean"], 0.9, abs_tol=1e-9)
    assert result["metrics"]["mrr_at_20"]["stddev"] > 0.0


def test_compute_verdict_go_when_every_locked_metric_within_band() -> None:
    baseline = {"mrr_at_20": 0.6, "recall_at_1": 0.5, "recall_at_20": 0.77}
    port_mean = mean_of_runs([_run(0.62, 0.55, 0.80)] * 3)

    diff = diff_metrics(baseline, port_mean["metrics"], epsilon=0.03)
    verdict = compute_verdict(aggregate_diff=diff, corpus_ok=True, stub_provider=False)

    assert verdict == "GO"


def test_compute_verdict_no_go_when_any_locked_metric_below_band() -> None:
    baseline = {"mrr_at_20": 0.6, "recall_at_1": 0.5, "recall_at_20": 0.77}
    # recall_at_1 well below baseline*(1-0.03)
    port_mean = mean_of_runs([_run(0.62, 0.30, 0.80)] * 3)

    diff = diff_metrics(baseline, port_mean["metrics"], epsilon=0.03)
    verdict = compute_verdict(aggregate_diff=diff, corpus_ok=True, stub_provider=False)

    assert verdict == "NO_GO"
    assert diff["recall_at_1"]["within_band"] is False


def test_compute_verdict_forced_no_go_on_stub_provider_even_when_metrics_pass() -> None:
    baseline = {"mrr_at_20": 0.6, "recall_at_1": 0.5, "recall_at_20": 0.77}
    port_mean = mean_of_runs([_run(0.9, 0.9, 0.9)] * 3)
    diff = diff_metrics(baseline, port_mean["metrics"], epsilon=0.03)

    verdict = compute_verdict(aggregate_diff=diff, corpus_ok=True, stub_provider=True)

    assert verdict == "NO_GO"


def test_compute_verdict_forced_no_go_on_corpus_mismatch_even_when_metrics_pass() -> None:
    baseline = {"mrr_at_20": 0.6, "recall_at_1": 0.5, "recall_at_20": 0.77}
    port_mean = mean_of_runs([_run(0.9, 0.9, 0.9)] * 3)
    diff = diff_metrics(baseline, port_mean["metrics"], epsilon=0.03)

    verdict = compute_verdict(aggregate_diff=diff, corpus_ok=False, stub_provider=False)

    assert verdict == "NO_GO"


def test_marginal_fluke_single_run_below_band_does_not_flip_a_passing_mean_verdict() -> None:
    baseline = {"mrr_at_20": 1.0, "recall_at_1": 1.0, "recall_at_20": 1.0}
    # third run's mrr_at_20 alone would be below a 0.95 floor, but the N=3 mean is not
    runs = [_run(1.0, 1.0, 1.0), _run(1.0, 1.0, 1.0), _run(0.90, 1.0, 1.0)]

    port_mean = mean_of_runs(runs)
    diff = diff_metrics(baseline, port_mean["metrics"], epsilon=0.05)
    verdict = compute_verdict(aggregate_diff=diff, corpus_ok=True, stub_provider=False)

    assert diff["mrr_at_20"]["within_band"] is True
    assert verdict == "GO"


def test_marginal_fluke_single_run_above_band_does_not_flip_a_failing_mean_verdict() -> None:
    baseline = {"mrr_at_20": 1.0, "recall_at_1": 1.0, "recall_at_20": 1.0}
    # one fluke run above the floor cannot rescue a mean that is genuinely below it
    runs = [_run(0.50, 1.0, 1.0), _run(0.50, 1.0, 1.0), _run(1.0, 1.0, 1.0)]

    port_mean = mean_of_runs(runs)
    diff = diff_metrics(baseline, port_mean["metrics"], epsilon=0.05)
    verdict = compute_verdict(aggregate_diff=diff, corpus_ok=True, stub_provider=False)

    assert diff["mrr_at_20"]["within_band"] is False
    assert verdict == "NO_GO"


def test_diff_carries_aggregate_and_per_document_and_flags_a_per_document_regression() -> None:
    baseline_benchmark = {
        "results": [
            {"document_id": "docA", "filename": "docA.pdf", "evidence_rank": 1, "latency_ms": 5.0},
            {"document_id": "docA", "filename": "docA.pdf", "evidence_rank": 1, "latency_ms": 5.0},
            {
                "document_id": "docB",
                "filename": "normattiva_docB.pdf",
                "evidence_rank": 0,
                "latency_ms": 5.0,
            },
        ]
    }
    # aggregate is flat/passing (1.0 >= 1.0*0.97) in every port run, but docA's own
    # per-document numbers regress hard in every run.
    regressed_doc_run = {
        "summary": {
            "mrr_at_20": 1.0,
            "recall_at_k": {"1": 1.0, "20": 1.0},
            "latency_ms": {"mean": 5.0},
            "documents": {"docA": _doc_summary(0.3, 0.2, 0.3)},
        }
    }
    port_runs = [regressed_doc_run, regressed_doc_run, regressed_doc_run]

    result = build_gate_result(
        baseline_benchmark=baseline_benchmark,
        port_runs=port_runs,
        e2e_baseline=_load_json(TURINGDB_E2E),
        e2e_port=_load_json(TURINGDB_E2E),
        corpus_verification={"ok": True, "mismatches": []},
        epsilon=0.03,
    )

    assert "aggregate" in result["metrics_diff"]
    assert "per_document" in result["metrics_diff"]
    assert result["metrics_diff"]["aggregate"]["mrr_at_20"]["within_band"] is True
    assert result["metrics_diff"]["per_document"]["docA"]["mrr_at_20"]["within_band"] is False
    # D-02: an unchanged/passing aggregate does not hide the per-document regression
    assert result["verdict"] == "GO"


def test_build_gate_result_emits_every_d09_field_and_serializes_deterministically() -> None:
    benchmark_json = _load_json(REAL_DOCUMENT_BENCHMARK)
    port_runs = [_run(0.65, 0.55, 0.80)] * 3

    result = build_gate_result(
        baseline_benchmark=benchmark_json,
        port_runs=port_runs,
        e2e_baseline=_load_json(TURINGDB_E2E),
        e2e_port=_load_json(TURINGDB_E2E),
        corpus_verification={"ok": True, "mismatches": []},
        epsilon=0.03,
    )

    for field in (
        "verdict",
        "tolerance",
        "provider_config",
        "corpus_verification",
        "metrics_diff",
        "baseline_bar",
        "e2e_diff",
        "latency",
        "runs",
        "normattiva_evidence",
    ):
        assert field in result

    assert result["tolerance"] == {"epsilon": 0.03, "band_type": "relative_floor", "run_count": 3}
    assert set(result["metrics_diff"]) == {"aggregate", "per_document"}
    assert {"per_check", "baseline_corrected_pass_count", "port_pass_count"} <= set(
        result["e2e_diff"]
    )
    assert result["e2e_diff"]["baseline_corrected_pass_count"] == 14

    serialized_once = json.dumps(result, indent=2, sort_keys=True)
    serialized_twice = json.dumps(result, indent=2, sort_keys=True)
    assert serialized_once == serialized_twice


def test_verdict_forced_no_go_when_e2e_port_is_a_stub_capture_despite_passing_metrics() -> None:
    benchmark_json = _load_json(REAL_DOCUMENT_BENCHMARK)
    port_runs = [_run(0.9, 0.9, 0.9)] * 3

    result = build_gate_result(
        baseline_benchmark=benchmark_json,
        port_runs=port_runs,
        e2e_baseline=_load_json(TURINGDB_E2E),
        e2e_port=_load_json(ARCADEDB_E2E),  # stub-provider capture
        corpus_verification={"ok": True, "mismatches": []},
        epsilon=0.03,
    )

    assert result["verdict"] == "NO_GO"


def test_cli_help_lists_all_documented_flags(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    for flag in (
        "--baseline-benchmark",
        "--port-runs",
        "--e2e-baseline",
        "--e2e-port",
        "--corpus-root",
        "--manifest",
        "--frozen-questions",
        "--epsilon",
        "--derive-corrected-baseline",
        "--out",
    ):
        assert flag in help_text
