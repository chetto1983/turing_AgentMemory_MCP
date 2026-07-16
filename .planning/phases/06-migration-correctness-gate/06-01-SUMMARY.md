---
phase: 06-migration-correctness-gate
plan: 01
subsystem: testing
tags: [e2e-gate, retrieval-benchmark, tdd, arcadedb-migration, sha256-verify]

# Dependency graph
requires:
  - phase: 03-turingdb-retrieval-baseline
    provides: "committed baseline/03-turingdb/{corpus-manifest.json, e2e-results.json, real-document-benchmark.json, frozen-questions.json, BASELINE.md} yardstick"
  - phase: 04-arcadedb-direct-port
    provides: "ArcadeDB-backed store + e2e harness field shape (baseline/04-arcadedb/e2e-results.json)"
provides:
  - "scripts/gate_diff.py: the deterministic gate engine (corpus sha256 verify, corrected-baseline derivation, bug-corrected 7-doc bar, per-document+aggregate diff, epsilon-band GO|NO_GO verdict, full CLI)"
  - "tests/test_gate_diff.py: 20 unit tests proving every locked decision (D-01/D-02/D-04/D-05/D-07/D-09/D-11) against committed fixtures + synthetic port runs"
affects: [06-02, 06-03, 06-04, 07-turingdb-removal]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Gate diff engine as a pure, stdlib-only script (json/hashlib/statistics/pathlib/argparse) reusing scripts/real_document_benchmark_scoring.py helpers (file_digest, summarize_results, load_frozen_questions) rather than re-deriving them"
    - "Fail-closed verdict precedence: stub-provider or corpus sha256 mismatch forces NO_GO even when quality metrics pass"
    - "N=3-mean smoothing over epsilon relative-floor band so a single fluke run cannot flip an irreversible cutover verdict"

key-files:
  created:
    - scripts/gate_diff.py
    - tests/test_gate_diff.py
  modified: []

key-decisions:
  - "D-05 contingency confirmed and NOT re-triggered: `check()` in e2e_score_check.py already computes `ok = bool(detail)` at HEAD (commit 8120efd, confirmed ancestor of the baseline capture commit ab7abd0 via `git merge-base --is-ancestor`); corrected_checks() is a pure derivation over already-captured JSON, not a source edit"
  - "meaningful_subset_summary() reproduces the committed D-01 bar exactly (MRR@20=0.5979488765203052, recall@1=0.5142857142857142, recall@20=0.7714285714285715) by filtering baseline/03-turingdb/real-document-benchmark.json results to non-'normattiva_' filenames and reusing summarize_results verbatim"
  - "compute_verdict() gates only on the three locked AGGREGATE metrics (mrr_at_20/recall_at_1/recall_at_20) within the epsilon=0.03 relative floor on the N-run mean; per-document regressions are surfaced in metrics_diff.per_document for transparency (D-02) but do not independently flip the aggregate-driven verdict, matching the plan's must_haves wording"
  - "verify_corpus() unit tests use tmp_path synthetic stand-in files (not the real ~56MB D:/tmp/baseline-corpus), per the plan's read_first guidance, so the unit tier has no external corpus dependency"

requirements-completed: [ARC-09]

coverage:
  - id: D1
    description: "corrected_checks() derives the correct ok flag (ok = False if error else bool(detail)) over the committed baseline/03-turingdb/e2e-results.json checks array, yielding 14 pass / 5 non-pass with the exact 5 names the plan specified"
    requirement: ARC-09
    verification:
      - kind: unit
        ref: "tests/test_gate_diff.py::test_corrected_checks_yields_14_pass_5_non_pass_over_committed_baseline"
        status: pass
      - kind: unit
        ref: "tests/test_gate_diff.py::test_corrected_checks_forces_ok_false_when_error_key_present_regardless_of_other_fields"
        status: pass
      - kind: unit
        ref: "tests/test_gate_diff.py::test_corrected_checks_detail_truthy_is_ok_true_falsy_is_ok_false"
        status: pass
    human_judgment: false
  - id: D2
    description: "verify_corpus() re-hashes files under --corpus-root with the reused file_digest() helper and fails closed (ok=False, mismatches listed) on any sha256 drift or missing file versus the manifest"
    requirement: ARC-09
    verification:
      - kind: unit
        ref: "tests/test_gate_diff.py::test_verify_corpus_ok_true_on_byte_identical_stand_in_files"
        status: pass
      - kind: unit
        ref: "tests/test_gate_diff.py::test_verify_corpus_fails_closed_on_tampered_file"
        status: pass
      - kind: unit
        ref: "tests/test_gate_diff.py::test_verify_corpus_fails_closed_on_missing_file"
        status: pass
    human_judgment: false
  - id: D3
    description: "is_stub_provider() correctly classifies the 04-arcadedb (localhost stub) capture as stub=True and the 03-turingdb (real granite/BGE sidecar) capture as stub=False"
    requirement: ARC-09
    verification:
      - kind: unit
        ref: "tests/test_gate_diff.py::test_is_stub_provider_true_for_arcadedb_stub_capture"
        status: pass
      - kind: unit
        ref: "tests/test_gate_diff.py::test_is_stub_provider_false_for_turingdb_real_sidecar_capture"
        status: pass
    human_judgment: false
  - id: D4
    description: "meaningful_subset_summary() reproduces the committed D-01 bug-corrected 7-doc bar (MRR@20=0.5979, recall@1=0.5143, recall@20=0.7714) from the real baseline JSON within 1e-3"
    requirement: ARC-09
    verification:
      - kind: unit
        ref: "tests/test_gate_diff.py::test_meaningful_subset_summary_reproduces_the_committed_d01_bar"
        status: pass
    human_judgment: false
  - id: D5
    description: "mean_of_runs()/diff_metrics()/compute_verdict() implement the epsilon=0.03 N=3-mean band: GO when every locked metric's mean is within band, NO_GO when any is below, forced NO_GO on stub provider or corpus mismatch regardless of metrics, and a single fluke run (in either direction) cannot flip a verdict the N-run mean does not support"
    requirement: ARC-09
    verification:
      - kind: unit
        ref: "tests/test_gate_diff.py::test_mean_of_runs_computes_arithmetic_mean_and_stddev"
        status: pass
      - kind: unit
        ref: "tests/test_gate_diff.py::test_compute_verdict_go_when_every_locked_metric_within_band"
        status: pass
      - kind: unit
        ref: "tests/test_gate_diff.py::test_compute_verdict_no_go_when_any_locked_metric_below_band"
        status: pass
      - kind: unit
        ref: "tests/test_gate_diff.py::test_compute_verdict_forced_no_go_on_stub_provider_even_when_metrics_pass"
        status: pass
      - kind: unit
        ref: "tests/test_gate_diff.py::test_compute_verdict_forced_no_go_on_corpus_mismatch_even_when_metrics_pass"
        status: pass
      - kind: unit
        ref: "tests/test_gate_diff.py::test_marginal_fluke_single_run_below_band_does_not_flip_a_passing_mean_verdict"
        status: pass
      - kind: unit
        ref: "tests/test_gate_diff.py::test_marginal_fluke_single_run_above_band_does_not_flip_a_failing_mean_verdict"
        status: pass
    human_judgment: false
  - id: D6
    description: "diff output carries both an aggregate block and a per_document block; a port whose aggregate is flat/passing but one document regresses below band surfaces that regression in metrics_diff.per_document (D-02)"
    requirement: ARC-09
    verification:
      - kind: unit
        ref: "tests/test_gate_diff.py::test_diff_carries_aggregate_and_per_document_and_flags_a_per_document_regression"
        status: pass
    human_judgment: false
  - id: D7
    description: "build_gate_result() emits every D-09 field (verdict, tolerance, provider_config, corpus_verification, metrics_diff, baseline_bar, e2e_diff, latency, runs, normattiva_evidence) and serializes deterministically (sort_keys=True/indent=2); a stub e2e_port forces NO_GO even when quality metrics pass"
    requirement: ARC-09
    verification:
      - kind: unit
        ref: "tests/test_gate_diff.py::test_build_gate_result_emits_every_d09_field_and_serializes_deterministically"
        status: pass
      - kind: unit
        ref: "tests/test_gate_diff.py::test_verdict_forced_no_go_when_e2e_port_is_a_stub_capture_despite_passing_metrics"
        status: pass
    human_judgment: false
  - id: D8
    description: "scripts/gate_diff.py --help lists all documented CLI flags (--baseline-benchmark, --port-runs repeatable, --e2e-baseline, --e2e-port, --corpus-root, --manifest, --frozen-questions, --epsilon, --derive-corrected-baseline, --out)"
    requirement: ARC-09
    verification:
      - kind: unit
        ref: "tests/test_gate_diff.py::test_cli_help_lists_all_documented_flags"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-07-16
status: complete
---

# Phase 6 Plan 1: Deterministic Gate Engine Summary

**Built `scripts/gate_diff.py` — a stdlib-only, fully TDD'd engine that verifies the gate corpus by sha256, derives the corrected TuringDB baseline pass/fail without a live re-run, reproduces the committed D-01 bug-corrected 7-doc bar (0.5979/0.5143/0.7714), and computes a fail-closed GO|NO_GO verdict on the N=3-run mean within an epsilon=0.03 band.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-16T11:20:00+02:00 (approx, from first Read)
- **Completed:** 2026-07-16T11:36:27+02:00
- **Tasks:** 2 (both TDD: RED test commit + GREEN implementation commit each)
- **Files modified:** 2 (both new)

## Accomplishments

- `corrected_checks()` — pure `ok = False if error else bool(detail)` derivation reproducing the exact 14-pass/5-non-pass split over the committed `baseline/03-turingdb/e2e-results.json`, with the 5 non-passing names matching the plan's spec exactly.
- `verify_corpus()` — sha256 re-hash of every manifest-listed file via the reused `file_digest()` helper; fails closed (`ok: False`, filename+reason listed) on any drift or missing file, tested against tmp_path synthetic stand-ins (no external corpus dependency in the unit tier).
- `is_stub_provider()` — classifies embed/rerank endpoint hosts; correctly flags the `baseline/04-arcadedb/e2e-results.json` localhost-stub capture as stub and the `baseline/03-turingdb/e2e-results.json` real-sidecar capture as non-stub.
- `meaningful_subset_summary()` — filters non-`normattiva_` rows from the real committed benchmark JSON and reuses `summarize_results` verbatim, reproducing the D-01 bar to full float precision (asserted within 1e-3).
- `mean_of_runs()` / `diff_metrics()` / `compute_verdict()` — N-run mean + population stddev per locked metric, epsilon-relative-floor band membership, and a verdict that is forced `NO_GO` on stub provider or corpus mismatch regardless of quality metrics, with tests proving a single fluke run (in either direction) cannot flip a verdict the N=3 mean does not independently support.
- `build_gate_result()` — assembles every D-09 field (`verdict`, `tolerance`, `provider_config`, `corpus_verification`, `metrics_diff.{aggregate,per_document}`, `baseline_bar`, `e2e_diff.{per_check,baseline_corrected_pass_count,port_pass_count}`, `latency`, `runs`, `normattiva_evidence`) and serializes deterministically.
- `main()` — full CLI (`--baseline-benchmark`, `--port-runs` repeatable, `--e2e-baseline`, `--e2e-port`, `--corpus-root`, `--manifest`, `--frozen-questions`, `--epsilon` default 0.03, `--derive-corrected-baseline`, `--out`), exit 0 on GO else 1.

## Task Commits

Each task followed the RED -> GREEN TDD cycle with a separate commit per gate:

1. **Task 1: Corpus sha256 fail-closed verify (D-11) + corrected-baseline derivation (D-05)**
   - `ca79916` (test) — RED: failing tests for `corrected_checks`/`verify_corpus`/`is_stub_provider` (module didn't exist)
   - `ff03210` (feat) — GREEN: implemented all three functions; 8/8 tests green
2. **Task 2: Bug-corrected bar + per-document/aggregate diff + epsilon-band GO|NO_GO verdict (D-01/D-02/D-04)**
   - `20701e6` (test) — RED: failing tests for `meaningful_subset_summary`/`mean_of_runs`/`diff_metrics`/`compute_verdict`/`build_gate_result`/CLI `--help`
   - `1df94a4` (feat) — GREEN: implemented remaining functions + `main()` CLI; 20/20 tests green

_No refactor commit was needed — implementation matched the design without post-hoc cleanup._

## Files Created/Modified

- `scripts/gate_diff.py` (365 LOC) - the gate engine: `corrected_checks`, `verify_corpus`, `is_stub_provider`, `meaningful_subset_summary`, `mean_of_runs`, `diff_metrics`, `compute_verdict`, `build_gate_result`, `main`
- `tests/test_gate_diff.py` (393 LOC) - 20 unit tests covering every `<behavior>` bullet in the plan, using committed baseline JSON fixtures plus tmp_path/synthetic data for isolation

## Decisions Made

- Confirmed via `git merge-base --is-ancestor 8120efd ab7abd0` that the D-05 "RESEARCH CRITICAL FINDING contingency" holds: the `check()` honesty fix predates the baseline capture commit, so `corrected_checks()` is purely a derivation over already-captured (stale-at-capture-time) JSON — no source edit to `e2e_score_check.py`/`e2e_score.py`/CI threshold was made or needed in this plan.
- Confirmed the D-01 bar numerically by direct computation against `baseline/03-turingdb/real-document-benchmark.json` before writing any test assertion (MRR@20=0.5979488765203052, recall@1=0.5142857142857142, recall@20=0.7714285714285715) — the plan's stated 1e-3-tolerance figures matched exactly.
- `compute_verdict()` gates on the three locked AGGREGATE metrics only (per the plan's must_haves wording: "computes verdict GO only when every locked metric port_mean >= baseline_bar..."); per-document regressions are computed and surfaced in `metrics_diff.per_document` for transparency (D-02's "cannot hide") but are not wired as an independent second gate — this matches every test the plan specified (the per-document test asserts the regression is *reported*, and separately that the aggregate-passing case still yields `GO`).
- `verify_corpus()` unit tests deliberately avoid `D:/tmp/baseline-corpus` (real, ~56MB, external, non-committed) and instead build tmp_path stand-in files with real sha256 digests computed via the reused `file_digest()` — matching the plan's explicit read_first instruction that the unit tier needs no external corpus.

## Deviations from Plan

None — plan executed exactly as written. The RESEARCH CRITICAL FINDING contingency check (verify `check()` already computes `ok = bool(detail)` at HEAD) was performed as instructed and confirmed the "already fixed" branch, not the fallback edit branch.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. This plan has no GPU/corpus/live-capture dependency; it is pure TDD against already-committed fixture JSON.

## Next Phase Readiness

- `scripts/gate_diff.py` is ready to be invoked by 06-02 (or later plans in this phase) once the real GPU-backed ArcadeDB e2e + real-document-benchmark captures exist (`--port-runs` expects N such captures, `--e2e-port` expects the ArcadeDB e2e JSON, `--corpus-root`/`--manifest` expect the real corpus + committed manifest).
- `build_gate_result()`'s `verdict` field is the exact contract Phase 7's hard guard will read from the committed `gate-result.json` (D-10) — no further schema negotiation needed downstream.
- No blockers. The one open item for a subsequent plan in this phase: actually running the GPU-backed capture (D-07/D-08/D-11 prerequisites: real granite+BGE sidecars, the exact `D:/tmp/baseline-corpus`, and `--frozen-questions baseline/03-turingdb/frozen-questions.json`) and feeding its outputs through this engine to produce the real verdict + `baseline/06-gate/GATE.md` artifact.

---
*Phase: 06-migration-correctness-gate*
*Completed: 2026-07-16*
