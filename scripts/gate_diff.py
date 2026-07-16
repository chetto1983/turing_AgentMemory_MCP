"""Deterministic ARC-09 migration-correctness gate diff engine.

D-05 note: `check()` in `src/turing_agentmemory_mcp/e2e_score_check.py` already
computes `ok = bool(detail)` as of commit `8120efd`, an ancestor of the
baseline capture commit `ab7abd0`. The four false-passing rows recorded in
`baseline/03-turingdb/e2e-results.json` (`detail: false`, `ok: true`) reflect
whatever ran at capture time, not current HEAD; `corrected_checks()` below is
a pure DERIVATION applied to any raw `checks` array -- it is not a source fix
(D-05 is verify+derive, not an edit; see 06-01-PLAN.md's "RESEARCH CRITICAL
FINDING contingency").

Locked tolerance (D-04): epsilon=0.03 relative floor below the D-01
bug-corrected 7-doc bar, evaluated on the mean of N>=3 real-document-benchmark
runs (`mean_of_runs`) -- never a single run, so a marginal fluke cannot flip
an irreversible cutover verdict.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from real_document_benchmark_scoring import (
        file_digest,
        load_frozen_questions,
        summarize_results,
    )
except ImportError:  # running as `python scripts/gate_diff.py` directly
    from scripts.real_document_benchmark_scoring import (
        file_digest,
        load_frozen_questions,
        summarize_results,
    )

DEFAULT_EPSILON = 0.03
LOCKED_METRICS = ("mrr_at_20", "recall_at_1", "recall_at_20")
STUB_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0"}
CHECK_13_NAME = "document_search_retrieves_exact_top1_with_citation_and_neighbor_context"


def corrected_checks(raw_checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-derive each check row's `ok` as `ok = False if error else bool(detail)`.

    Pure transform over already-captured JSON; does not re-run any check.
    """
    corrected: list[dict[str, Any]] = []
    for row in raw_checks:
        new_row = dict(row)
        new_row["ok"] = False if "error" in row else bool(row.get("detail"))
        corrected.append(new_row)
    return corrected


def verify_corpus(corpus_root: Path, manifest_path: Path) -> dict[str, Any]:
    """Re-hash every file under `corpus_root` against `manifest_path` (D-11).

    Fails closed: any missing file or sha256 drift is reported as a mismatch
    and `ok` is False. Never silently passes on a partial/renamed/tampered corpus.
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    mismatches: list[dict[str, str]] = []
    for entry in manifest.get("documents", []):
        filename = entry["filename"]
        candidate = Path(corpus_root) / filename
        if not candidate.is_file():
            mismatches.append({"filename": filename, "reason": "missing"})
            continue
        _, digest = file_digest(candidate)
        if digest != entry.get("sha256"):
            mismatches.append({"filename": filename, "reason": "sha256_mismatch"})
    return {"ok": not mismatches, "mismatches": mismatches}


def _provider_host(url: Any) -> str | None:
    if not url or not isinstance(url, str):
        return None
    return urlparse(url).hostname


def is_stub_provider(e2e_json: dict[str, Any]) -> bool:
    """True when the capture's embed/rerank endpoints are localhost stubs (D-07).

    A stub-provider capture can never authorize a GO verdict -- see
    `compute_verdict` (Task 2).
    """
    checks = e2e_json.get("checks") or []
    if not checks:
        return True
    detail = checks[0].get("detail")
    if not isinstance(detail, dict):
        return True
    embed_host = _provider_host(detail.get("embedding_base_url"))
    rerank_host = _provider_host(detail.get("rerank_base_url"))
    return embed_host in STUB_HOSTS or rerank_host in STUB_HOSTS


def _locked_metrics(summary: dict[str, Any]) -> dict[str, float]:
    recall = summary.get("recall_at_k") or {}
    return {
        "mrr_at_20": float(summary.get("mrr_at_20") or 0.0),
        "recall_at_1": float(recall.get("1") or 0.0),
        "recall_at_20": float(recall.get("20") or 0.0),
    }


def meaningful_subset_summary(benchmark_json: dict[str, Any]) -> dict[str, Any]:
    """The D-01 bug-corrected 7-doc bar: excludes filenames starting with
    'normattiva_' and recomputes via the reused `summarize_results` weighting.
    """
    rows = [
        row
        for row in benchmark_json.get("results", [])
        if not str(row.get("filename") or "").startswith("normattiva_")
    ]
    return summarize_results(rows)


def mean_of_runs(run_jsons: list[dict[str, Any]]) -> dict[str, Any]:
    """Arithmetic mean + population stddev of the locked metrics, latency, and
    per-document metrics across N port real-document-benchmark run captures
    (D-04). Reads each run's top-level `summary` (full 12-doc corpus).
    """
    if not run_jsons:
        raise ValueError("mean_of_runs requires at least one run")

    per_run_metrics = [_locked_metrics(run["summary"]) for run in run_jsons]
    metrics: dict[str, dict[str, float]] = {
        key: {
            "mean": statistics.fmean(m[key] for m in per_run_metrics),
            "stddev": statistics.pstdev(m[key] for m in per_run_metrics),
        }
        for key in LOCKED_METRICS
    }

    latency_values = [
        float((run["summary"].get("latency_ms") or {}).get("mean") or 0.0) for run in run_jsons
    ]
    latency_ms = {
        "mean": statistics.fmean(latency_values),
        "stddev": statistics.pstdev(latency_values),
    }

    document_ids: set[str] = set()
    for run in run_jsons:
        document_ids.update((run["summary"].get("documents") or {}).keys())

    documents: dict[str, dict[str, dict[str, float]]] = {}
    for doc_id in sorted(document_ids):
        doc_runs = [
            _locked_metrics(run["summary"]["documents"][doc_id])
            for run in run_jsons
            if doc_id in (run["summary"].get("documents") or {})
        ]
        if not doc_runs:
            continue
        documents[doc_id] = {
            key: {
                "mean": statistics.fmean(m[key] for m in doc_runs),
                "stddev": statistics.pstdev(m[key] for m in doc_runs),
            }
            for key in LOCKED_METRICS
        }

    return {
        "run_count": len(run_jsons),
        "metrics": metrics,
        "latency_ms": latency_ms,
        "documents": documents,
    }


def diff_metrics(
    baseline_metrics: dict[str, float],
    port_metrics: dict[str, dict[str, float]],
    *,
    epsilon: float = DEFAULT_EPSILON,
) -> dict[str, dict[str, Any]]:
    """Per-metric {baseline, port_mean, port_stddev, delta, band_floor,
    within_band} for each locked metric (D-02/D-04). `within_band` is True iff
    `port_mean >= baseline * (1 - epsilon)`.
    """
    diff: dict[str, dict[str, Any]] = {}
    for key in LOCKED_METRICS:
        baseline_value = float(baseline_metrics.get(key, 0.0))
        port_stat = port_metrics.get(key) or {"mean": 0.0, "stddev": 0.0}
        port_value = float(port_stat.get("mean", 0.0))
        band_floor = baseline_value * (1 - epsilon)
        diff[key] = {
            "baseline": baseline_value,
            "port_mean": port_value,
            "port_stddev": float(port_stat.get("stddev", 0.0)),
            "delta": port_value - baseline_value,
            "band_floor": band_floor,
            "within_band": port_value >= band_floor,
        }
    return diff


def compute_verdict(
    *,
    aggregate_diff: dict[str, dict[str, Any]],
    corpus_ok: bool,
    stub_provider: bool,
) -> str:
    """GO iff every locked aggregate metric is within band AND the corpus
    verified AND the provider is not a stub (D-01/D-04/D-07/D-11 fail-closed
    precedence: stub/corpus-mismatch forces NO_GO even if metrics pass).
    """
    if stub_provider or not corpus_ok:
        return "NO_GO"
    if all(metric["within_band"] for metric in aggregate_diff.values()):
        return "GO"
    return "NO_GO"


def build_gate_result(
    *,
    baseline_benchmark: dict[str, Any],
    port_runs: list[dict[str, Any]],
    e2e_baseline: dict[str, Any],
    e2e_port: dict[str, Any],
    corpus_verification: dict[str, Any],
    epsilon: float = DEFAULT_EPSILON,
    frozen_questions: dict[str, Any] | None = None,
    derive_corrected_baseline: bool = False,
) -> dict[str, Any]:
    """Assemble the full D-09 gate-result field set."""
    baseline_summary = meaningful_subset_summary(baseline_benchmark)
    baseline_metrics = _locked_metrics(baseline_summary)
    port_mean = mean_of_runs(port_runs)

    aggregate_diff = diff_metrics(baseline_metrics, port_mean["metrics"], epsilon=epsilon)

    per_document_diff: dict[str, dict[str, Any]] = {}
    for doc_id, doc_summary in (baseline_summary.get("documents") or {}).items():
        port_doc = port_mean["documents"].get(doc_id)
        if port_doc is None:
            continue
        per_document_diff[doc_id] = diff_metrics(
            _locked_metrics(doc_summary), port_doc, epsilon=epsilon
        )

    stub_provider = is_stub_provider(e2e_port)
    corrected_baseline_checks = corrected_checks(e2e_baseline.get("checks") or [])
    corrected_port_checks = corrected_checks(e2e_port.get("checks") or [])
    port_by_name = {row["name"]: row for row in corrected_port_checks}

    per_check_diff = [
        {
            "name": baseline_row["name"],
            "baseline_ok": baseline_row["ok"],
            "port_ok": port_by_name[baseline_row["name"]]["ok"]
            if baseline_row["name"] in port_by_name
            else None,
        }
        for baseline_row in corrected_baseline_checks
    ]

    verdict = compute_verdict(
        aggregate_diff=aggregate_diff,
        corpus_ok=bool(corpus_verification.get("ok")),
        stub_provider=stub_provider,
    )

    normattiva_documents = {
        doc_id: doc_metrics
        for doc_id, doc_metrics in (port_mean.get("documents") or {}).items()
        if doc_id.startswith("normattiva_")
    }
    check_13 = port_by_name.get(CHECK_13_NAME)

    provider_config: dict[str, Any] = {}
    port_checks = e2e_port.get("checks") or []
    if port_checks:
        detail = port_checks[0].get("detail")
        if isinstance(detail, dict):
            provider_config = detail

    result: dict[str, Any] = {
        "verdict": verdict,
        "tolerance": {
            "epsilon": epsilon,
            "band_type": "relative_floor",
            "run_count": port_mean["run_count"],
        },
        "provider_config": provider_config,
        "corpus_verification": corpus_verification,
        "baseline_bar": baseline_metrics,
        "metrics_diff": {
            "aggregate": aggregate_diff,
            "per_document": per_document_diff,
        },
        "e2e_diff": {
            "per_check": per_check_diff,
            "baseline_corrected_pass_count": sum(
                1 for row in corrected_baseline_checks if row["ok"]
            ),
            "port_pass_count": sum(1 for row in corrected_port_checks if row["ok"]),
        },
        "latency": port_mean["latency_ms"],
        "runs": port_mean["run_count"],
        "normattiva_evidence": {
            "documents": normattiva_documents,
            "check_13_corrected_ok": check_13["ok"] if check_13 else None,
        },
    }
    if derive_corrected_baseline:
        result["e2e_diff"]["baseline_corrected_checks"] = corrected_baseline_checks
    if frozen_questions is not None:
        result["frozen_questions_count"] = sum(len(rows) for rows in frozen_questions.values())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ARC-09 migration-correctness gate diff engine")
    parser.add_argument("--baseline-benchmark", required=True, type=Path)
    parser.add_argument(
        "--port-runs",
        required=True,
        type=Path,
        action="append",
        help="Path to a port real-document-benchmark.json run; repeat for N runs",
    )
    parser.add_argument("--e2e-baseline", required=True, type=Path)
    parser.add_argument("--e2e-port", required=True, type=Path)
    parser.add_argument("--corpus-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--frozen-questions", type=Path, default=None)
    parser.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    parser.add_argument("--derive-corrected-baseline", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("gate-result.json"))
    args = parser.parse_args(argv)

    baseline_benchmark = json.loads(args.baseline_benchmark.read_text(encoding="utf-8"))
    port_runs = [json.loads(path.read_text(encoding="utf-8")) for path in args.port_runs]
    e2e_baseline = json.loads(args.e2e_baseline.read_text(encoding="utf-8"))
    e2e_port = json.loads(args.e2e_port.read_text(encoding="utf-8"))
    corpus_verification = verify_corpus(args.corpus_root, args.manifest)
    frozen_questions = (
        load_frozen_questions(args.frozen_questions) if args.frozen_questions else None
    )

    result = build_gate_result(
        baseline_benchmark=baseline_benchmark,
        port_runs=port_runs,
        e2e_baseline=e2e_baseline,
        e2e_port=e2e_port,
        corpus_verification=corpus_verification,
        epsilon=args.epsilon,
        frozen_questions=frozen_questions,
        derive_corrected_baseline=args.derive_corrected_baseline,
    )

    args.out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
