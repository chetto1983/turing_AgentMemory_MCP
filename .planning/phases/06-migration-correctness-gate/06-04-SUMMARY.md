---
phase: 06-migration-correctness-gate
plan: 04
subsystem: testing
tags: [e2e-gate, retrieval-benchmark, arcadedb-migration, gate-artifact, phase7-guard]

# Dependency graph
requires:
  - phase: 06-migration-correctness-gate
    provides: "06-01 scripts/gate_diff.py (build_gate_result/verify_corpus/is_stub_provider/mean_of_runs/compute_verdict engine); 06-02 turing_agentmemory_mcp.gate_guard (validate_gate_result_schema/assert_gate_go); 06-03 baseline/06-gate/{e2e-results.json, real-document-benchmark-run{1,2,3}.json, capture-provider-env.txt} GPU-backed real-provider captures"
  - phase: 03-turingdb-retrieval-baseline
    provides: "baseline/03-turingdb/{e2e-results.json, real-document-benchmark.json, corpus-manifest.json, frozen-questions.json, BASELINE.md} committed yardstick"
provides:
  - "baseline/06-gate/gate-result.json — the committed D-09 machine verdict: GO"
  - "baseline/06-gate/e2e-baseline-corrected.json — the D-05 corrected TuringDB baseline (14/19 true pass, score 7.368)"
  - "baseline/06-gate/GATE.md — the D-09 human-readable gate artifact mirroring BASELINE.md"
  - "tests/test_gate_artifact_schema.py — committed-artifact well-formedness + assert_gate_go(GO) verification tests"
affects: [07-turingdb-removal]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deriving a corrected artifact from a committed capture: call the already-exported pure transform function (scripts.gate_diff.corrected_checks) directly rather than assuming a standalone CLI mode exists for every documented flag combination"
    - "Committed-artifact test asserts against the real repo path (Path(__file__).resolve().parents[1] / 'baseline' / '06-gate' / 'gate-result.json'), not a tmp_path fixture — proves the actual shipped artifact, not a synthetic stand-in"

key-files:
  created:
    - baseline/06-gate/gate-result.json
    - baseline/06-gate/e2e-baseline-corrected.json
    - baseline/06-gate/GATE.md
    - tests/test_gate_artifact_schema.py
  modified: []

key-decisions:
  - "gate_diff.py's --derive-corrected-baseline flag is a store_true modifier consumed only inside the full build_gate_result pipeline, not a standalone single-file transform as the plan's literal CLI example implied — derived e2e-baseline-corrected.json directly via the already-exported scripts.gate_diff.corrected_checks() function instead, recomputing score/verdict with the same formula as e2e_score.py:163-165 (Rule 3 fix, no gate_diff.py changes, out of this plan's file scope)"
  - "Verdict computed honestly by scripts/gate_diff.py over the real N=3 06-03 captures: GO — all three locked aggregate metrics (mrr_at_20, recall_at_1, recall_at_20) clear the epsilon=0.03 band vs the D-01 bug-corrected 7-doc bar, corpus verified zero-drift, provider confirmed non-stub"
  - "Check #19 (restart_preserves_memory_and_document_retrieval) flip (true->false) and check #1's turingdb_->arcadedb_ rename (unmatched, port_ok=null) are both documented, non-regression deviations in GATE.md, not silently absorbed into the aggregate GO verdict"

requirements-completed: [ARC-09]

coverage:
  - id: D1
    description: "gate-result.json written with verdict GO, every D-09 field (aggregate + per_document metrics_diff, per-check e2e_diff, latency, tolerance, provider_config, corpus_verification, runs)"
    requirement: ARC-09
    verification:
      - kind: unit
        ref: "tests/test_gate_artifact_schema.py::TestCommittedGateResultWellFormed"
        status: pass
      - kind: unit
        ref: "tests/test_gate_artifact_schema.py::TestCommittedGateVerdictIsGo::test_assert_gate_go_passes_on_the_committed_artifact"
        status: pass
    human_judgment: false
  - id: D2
    description: "e2e-baseline-corrected.json materialized (D-05 derivation, 14/19 true pass, score 7.368) while baseline/03-turingdb/e2e-results.json is left byte-for-byte unchanged"
    requirement: ARC-09
    verification:
      - kind: manual_procedural
        ref: "python -c invocation using scripts.gate_diff.corrected_checks() -> baseline/06-gate/e2e-baseline-corrected.json; git diff --stat confirms baseline/03-turingdb/e2e-results.json untouched"
        status: pass
    human_judgment: false
  - id: D3
    description: "GATE.md authored with all required sections, figures matching gate-result.json exactly, per-document diff present, deviations disclosed, correct per-script repro flags"
    requirement: ARC-09
    verification:
      - kind: other
        ref: "python -c section-presence + GO|NO_GO regex check (task's own <automated> verify command)"
        status: pass
    human_judgment: true
    rationale: "The plan's own <human-check> for Task 2 requires a human read-through confirming honesty of the verdict narration, per-document diff completeness, and disclosed deviations — this is a judgment call about narrative honesty, not something a script can certify."
  - id: D4
    description: "SC#2 backstop: port full-corpus retrieval meets-or-exceeds the bug-corrected 7-doc bar within epsilon on the N=3 mean, and per-query latency does not regress vs the clean-DB baseline"
    requirement: ARC-09
    verification: []
    human_judgment: true
    rationale: "Flagged verification: backstop in the plan's must_haves — requires end-of-phase human-verify per the plan's own <verification> block, even though the automated gate_diff computation already shows GO with comfortable margins (mrr@20 +0.086, recall@1 +0.075, recall@20 +0.084 above baseline; latency 3.3s vs 5.4s baseline)."

# Metrics
duration: 55min
completed: 2026-07-16
status: complete
---

# Phase 6 Plan 4: ARC-09 Gate Verdict Computation Summary

**Ran `scripts/gate_diff.py` over the real N=3 GPU-backed port captures + the committed Phase-3 baseline, producing a committed `GO` verdict in `baseline/06-gate/gate-result.json` — every locked retrieval metric clears its epsilon=0.03 band, the corpus verified zero-drift, the provider confirmed non-stub, and all 5 previously-non-passing e2e checks (including the document_id-length bug sentinel) now genuinely pass — authorizing Phase 7's TuringDB removal.**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-07-16T13:30:00+02:00 (approx)
- **Completed:** 2026-07-16T14:25:00+02:00 (approx)
- **Tasks:** 3 (all `type="execute"`, Task 3 `tdd="true"`)
- **Files modified:** 4 (all new: `gate-result.json`, `e2e-baseline-corrected.json`, `GATE.md`, `tests/test_gate_artifact_schema.py`)

## Accomplishments

- **Derived the D-05 corrected TuringDB baseline** (`baseline/06-gate/e2e-baseline-corrected.json`): applied `scripts.gate_diff.corrected_checks()` (`ok = False if error else bool(detail)`) to `baseline/03-turingdb/e2e-results.json`'s 19 checks, then recomputed `score`/`verdict` using the same formula as `e2e_score.py`. Result: **14/19 true pass, score 7.368**, matching `BASELINE.md`'s independently-confirmed true count exactly. The original `baseline/03-turingdb/e2e-results.json` is byte-for-byte untouched (confirmed via `git status`/`git diff --stat` — it was never staged or modified).
- **Computed the authoritative gate verdict** (`baseline/06-gate/gate-result.json`, via `scripts/gate_diff.py`'s full pipeline: `--baseline-benchmark`, 3x `--port-runs`, `--e2e-baseline`, `--e2e-port`, `--corpus-root D:/tmp/baseline-corpus`, `--manifest`, `--frozen-questions`, `--epsilon 0.03`, `--derive-corrected-baseline`): **verdict = GO**.
  - Corpus verification: `{"ok": true, "mismatches": []}` — zero drift across all 12 files.
  - Stub-provider check: `False` (non-stub `agentmemory-embed:8080`/`agentmemory-rerank:8080` confirmed).
  - Aggregate metrics (N=3 mean vs the D-01 bug-corrected 7-doc bar): mrr_at_20 0.6843 vs bar 0.5979 (band floor 0.5800) — within band; recall_at_1 0.5889 vs bar 0.5143 (floor 0.4989) — within band; recall_at_20 0.8556 vs bar 0.7714 (floor 0.7483) — within band. All three clear the raw baseline value itself, not merely the 97%-of-baseline floor.
  - Per-document diff: zero regressions across all 7 bug-corrected documents; `normattiva_evidence` confirms all 5 previously-deflated legal PDFs now retrieve non-zero on every locked metric (direct D-03 evidence, independent of the aggregate bar).
  - E2E per-check diff: 5 previously-non-passing checks (#12/13/14/15/16, including the document_id-length `IndexError` bug at #13) flip to genuinely passing (`ok=true, detail=true`) on the port. Check #19 flips true->false (documented, accepted "docker not on PATH inside the e2e container" limitation, not a regression). Check #1 is name-renamed (`turingdb_->arcadedb_`) and reports `port_ok: null` (unmatched by name, not missing — the renamed check itself independently passes).
- **Force-added the raw captures** under `baseline/06-gate/` (`git add -f`) — `e2e-results.json`, `real-document-benchmark-run{1,2,3}.json`, `e2e-baseline-corrected.json`, `gate-result.json`, `capture-provider-env.txt` — per the established gitignored-artifact force-add convention.
- **Authored `baseline/06-gate/GATE.md`** mirroring `BASELINE.md`'s section structure (What This Is, Provider Configuration, Corpus & sha256 Verification, Metrics Diff [aggregate + per-document + normattiva_evidence], E2E Per-Check Diff, Latency, Deviations/Confounds, Reproduction Commands, Verdict), with every figure transcribed verbatim from `gate-result.json`.
- **Added `tests/test_gate_artifact_schema.py`** (8 tests): well-formedness assertions (always green, regardless of verdict) plus a committed-verdict test calling `gate_guard.assert_gate_go` on the real path — green only because the committed verdict is `GO`. No `pytest.skip` anywhere, matching the repo's no-skip-as-green discipline.

## Task Commits

Each task was committed atomically:

1. **Task 1: Derive corrected baseline + compute gate-result.json + force-add raw captures** - `58694a0` (feat)
2. **Task 2: Author GATE.md** - `737efe1` (docs)
3. **Task 3: Committed-artifact verification tests** - `b66e823` (test)

**Plan metadata:** this SUMMARY.md commit (docs), plus the standard STATE.md/ROADMAP.md update commit.

## Files Created/Modified

- `baseline/06-gate/gate-result.json` - the committed D-09 machine verdict (GO), force-added
- `baseline/06-gate/e2e-baseline-corrected.json` - the D-05 corrected TuringDB baseline, force-added
- `baseline/06-gate/GATE.md` - the D-09 human-readable gate artifact
- `baseline/06-gate/e2e-results.json`, `real-document-benchmark-run{1,2,3}.json`, `capture-provider-env.txt` - the 06-03 raw captures, force-added into this plan's commit (were left uncommitted by 06-03 per its own SUMMARY)
- `tests/test_gate_artifact_schema.py` - 8 tests verifying the committed artifact's schema well-formedness and GO verdict

## Decisions Made

- **CLI-contract deviation resolved via the underlying function, not a CLI rewrite**: the plan's literal `gate_diff.py --derive-corrected-baseline <path> --out <path>` invocation does not match `scripts/gate_diff.py`'s actual argparse contract (`--derive-corrected-baseline` is a `store_true` modifier read only inside `build_gate_result`'s full pipeline — confirmed by reading `main()` and cross-checking `tests/test_gate_diff.py::test_cli_help_lists_all_documented_flags`). Rather than modifying `scripts/gate_diff.py` (out of this plan's declared file scope, and risking `06-01`'s existing 20+ test suite), derived `e2e-baseline-corrected.json` directly via the already-exported `corrected_checks()` function, preserving the exact D-05 semantics.
- **Both e2e-results.json and gate-result.json remain the single source of figures for GATE.md** — every number in `GATE.md` is a verbatim transcription from `gate-result.json`, never independently recomputed or restated with different precision, per the prohibition against grading against a flattered/different bar.
- **Check #19's flip and check #1's rename are both documented as non-regressions in GATE.md's Deviations section** rather than silently omitted, per the prohibition against an unchanged-aggregate hiding a per-check flip.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `gate_diff.py --derive-corrected-baseline <path> --out <path>` CLI invocation does not exist as documented**
- **Found during:** Task 1
- **Issue:** The plan's action text specifies a standalone single-file CLI invocation (`--derive-corrected-baseline <input> --out <output>`) for materializing the corrected baseline. Reading `scripts/gate_diff.py`'s actual `main()` shows `--derive-corrected-baseline` is a `store_true` flag consumed only as a modifier within the full `build_gate_result` pipeline (which itself requires `--baseline-benchmark`, `--port-runs`, `--e2e-baseline`, `--e2e-port`, `--corpus-root`, `--manifest` as hard-required arguments) — there is no standalone single-input mode. Running the literal documented command fails immediately with `argparse` "required arguments" errors.
- **Fix:** Called the already-exported `scripts.gate_diff.corrected_checks()` function directly via a `python -c` invocation: loaded `baseline/03-turingdb/e2e-results.json`, applied `corrected_checks()` to its `checks` array, recomputed `score`/`verdict` using the identical formula `e2e_score.py` uses (`round((earned/total)*10.0, 3)`, `VALIDATED_10_10` if `score>=9.8 and total==19` else `FAILED_SCORE_GATE`), and serialized with `json.dumps(..., indent=2, sort_keys=True)` matching the established convention. Result independently matches `BASELINE.md`'s documented "14/19 true pass" figure exactly.
- **Files modified:** `baseline/06-gate/e2e-baseline-corrected.json` (created, not `scripts/gate_diff.py` — kept within this plan's declared file scope)
- **Verification:** `earned=14, total=19, score=7.368, verdict=FAILED_SCORE_GATE` printed and confirmed against `BASELINE.md`'s independent figure; original `baseline/03-turingdb/e2e-results.json` confirmed unchanged via `git status`.
- **Committed in:** `58694a0` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 blocking-issue).
**Impact on plan:** Necessary to complete Task 1 at all (the documented CLI invocation is a no-op/error as written). No scope creep — `scripts/gate_diff.py` was read-only throughout; only the plan's own declared output files were written.

## Issues Encountered

None beyond the CLI-contract mismatch documented above (resolved inline, not blocking).

## User Setup Required

None - no external service configuration required. This plan consumed already-captured data files and ran pure Python computations; no GPU/Docker/live-service access was needed for Task 1-3 (unlike 06-03).

## Next Phase Readiness

- Phase 7 (TuringDB removal) is authorized: `baseline/06-gate/gate-result.json`'s committed `verdict` field is `GO`, and `tests/test_gate_artifact_schema.py::TestCommittedGateVerdictIsGo` proves `gate_guard.assert_gate_go` passes on the real committed path today.
- No blockers. The one open item is the plan's own D4 backstop (SC#2 end-of-phase human-verify) — the automated computation already shows a comfortable GO margin on every locked metric plus a latency improvement, but the plan's `human_judgment: true` classification for that item means a human should still review `GATE.md` end-to-end before Phase 7 is kicked off, per the plan's own verification block.
- The pre-existing, out-of-scope `compose.yaml` healthcheck schema mismatch noted in 06-03's SUMMARY remains untriaged; not a blocker for this plan or Phase 7.

---
*Phase: 06-migration-correctness-gate*
*Completed: 2026-07-16*

## Self-Check: PASSED

- FOUND: baseline/06-gate/gate-result.json
- FOUND: baseline/06-gate/e2e-baseline-corrected.json
- FOUND: baseline/06-gate/GATE.md
- FOUND: tests/test_gate_artifact_schema.py
- FOUND: 58694a0 (Task 1 commit)
- FOUND: 737efe1 (Task 2 commit)
- FOUND: b66e823 (Task 3 commit)
