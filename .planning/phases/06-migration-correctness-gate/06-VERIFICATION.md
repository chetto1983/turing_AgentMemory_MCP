---
phase: 06-migration-correctness-gate
verified: 2026-07-16T15:00:00Z
status: passed
score: 16/18 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification:

  - test: "Confirm the GPU-backed real-provider captures (baseline/06-gate/e2e-results.json, real-document-benchmark-run{1,2,3}.json) are genuine measurements from an actual NVIDIA-GPU Docker run against the real granite-embedding/BGE-reranker sidecars and the exact D:/tmp/baseline-corpus, not fabricated/hand-edited JSON."
    expected: "The capture-provider-env.txt narrative (rebuild of stale image, tenant-naming-key generation, MSYS path-conversion workaround) matches what actually happened on the GPU host; the raw JSON files are the direct, unedited output of `docker compose run --rm e2e` and `real_document_benchmark.py`."
    why_human: "This verifier has no GPU/Docker access in this session and cannot re-run the capture. Internal consistency checks (non-stub hostnames, check #13's genuine before/after IndexError-to-pass flip, sha256 corpus verification, N=3 run-to-run variance) all support authenticity, but cannot fully rule out a hand-crafted artifact. The plan itself tags this class of truth `verification: backstop` and the 06-03/06-04 SUMMARYs self-report `human_judgment: true` for exactly this reason."

  - test: "Read baseline/06-gate/GATE.md end-to-end per the plan's own deferred <human-check> (06-04-PLAN.md Task 2): confirm the verdict + rationale are honest (graded against the bug-corrected 7-doc bar, not the deflated full-corpus aggregate), the per-document diff is complete, deviations (GLiNER-on, latency volume-bloat confound, check #19/#1 rename) are disclosed, and reproduction commands use the correct per-script flag names (--out vs --output)."
    expected: "A human reviewer confirms no narrative dishonesty or cherry-picking; this is the phase's own declared checkpoint before Phase 7 (irreversible TuringDB removal) proceeds."
    why_human: "The plan (autonomous: true) declared this as a `<human-check>` inside Task 2's `<verify>` block, deferring it to end-of-phase per the project's human_verify_mode. A prose-honesty judgment call is not something this verifier can certify beyond the cross-references already performed (all GATE.md figures were confirmed byte-identical to gate-result.json in this verification pass)."
---

# Phase 6: Migration-Correctness Gate Verification Report

**Phase Goal:** Ported stack provably meets-or-exceeds the baseline (hard exit criterion) — the ARC-09 migration-correctness gate that must pass before Phase 7 removes TuringDB.
**Verified:** 2026-07-16T15:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | (Roadmap SC#1) `e2e_score.py`/`real_document_benchmark.py` run against the ArcadeDB-backed stack and are compared against the Phase 3 baseline within a documented tolerance | ✓ VERIFIED | `gate-result.json.tolerance` = `{epsilon:0.03, band_type:"relative_floor", run_count:3}`; captures exist at `baseline/06-gate/{e2e-results.json, real-document-benchmark-run{1,2,3}.json}` |
| 2 | `gate_diff.py` computes the D-01 bug-corrected 7-doc bar live from committed baseline JSON, excluding `normattiva_*` filenames, yielding MRR@20=0.5979/recall@1=0.5143/recall@20=0.7714 | ✓ VERIFIED | `tests/test_gate_diff.py::test_meaningful_subset_summary_reproduces_the_committed_d01_bar` passes; `gate-result.json.baseline_bar` = `{mrr_at_20: 0.5979488765203052, recall_at_1: 0.5142857142857142, recall_at_20: 0.7714285714285715}` (exact match) |
| 3 | `gate_diff.py` reports per-document AND aggregate metric diffs so an unchanged aggregate cannot hide a per-document regression | ✓ VERIFIED | `gate-result.json.metrics_diff` has both `aggregate` and `per_document` (7 documents) keys; `test_diff_carries_aggregate_and_per_document_and_flags_a_per_document_regression` passes |
| 4 | `compute_verdict` returns GO only when every locked metric's N-run mean clears `baseline*(1-0.03)`; below-band on any metric yields NO_GO | ✓ VERIFIED | 7 dedicated unit tests pass (`test_compute_verdict_*`, `test_marginal_fluke_*`); real computation shows all 3 metrics `within_band: true` with margin well above the raw baseline itself |
| 5 | `corrected_checks()` derives the corrected TuringDB baseline (`ok=bool(detail)`) yielding 14 true passes / 5 non-passing of 19, a pure derivation with no live TuringDB re-run | ✓ VERIFIED | Test passes with exact 5 names specified in the plan; `baseline/06-gate/e2e-baseline-corrected.json` independently shows `earned=14, total=19, score=7.368`; original `baseline/03-turingdb/e2e-results.json` confirmed byte-identical (diffed in this verification) |
| 6 | `verify_corpus()` re-hashes every corpus file and fails closed (non-zero exit/raised error) on any sha256 drift | ✓ VERIFIED | Tests pass (byte-identical / tampered / missing cases); real `gate-result.json.corpus_verification` = `{"ok": true, "mismatches": []}` |
| 7 | `is_stub_provider()` flags a stub/degraded provider and forces NO_GO, so a stub run can never emit GO | ✓ VERIFIED | Tests pass against both 03-turingdb (real) and 04-arcadedb (stub) fixtures; real capture's `provider_config` shows sidecar hostnames `agentmemory-embed:8080`/`agentmemory-rerank:8080` (non-127.0.0.1) |
| 8 | `validate_gate_result_schema()` asserts every D-09 field present + verdict in {GO, NO_GO}, raising on any violation | ✓ VERIFIED | `tests/test_phase7_gate_guard.py::TestValidateGateResultSchema` (16 parametrized cases) all pass |
| 9 | `assert_gate_go()` reads fresh every call (no caching), validates schema, refuses unless verdict=='GO'; never `pytest.skip` | ✓ VERIFIED | `TestAssertGateGo` (6 tests incl. no-cache proof) pass; `grep -n "pytest.skip"` over the guard test file returns zero literal occurrences (only prose mentions of the token) |
| 10 | Pre-flight corpus sha256 verify passes with zero drift before any GPU capture proceeds (D-11) | ✓ VERIFIED | `gate-result.json.corpus_verification.ok == true`, `mismatches: []`; 06-03-SUMMARY.md records the same `{"ok": true, "mismatches": []}` result from the live pre-flight |
| 11 | `baseline/06-gate/gate-result.json` is written with a top-level verdict in {GO, NO_GO} and every D-09 field (per-metric diff, per-check diff, per-document diff, latency, tolerance, run count, provider config, corpus verification) | ✓ VERIFIED | File read directly: all 9 required fields present; `tests/test_gate_artifact_schema.py::TestCommittedGateResultWellFormed` (6 tests) pass against the real committed path |
| 12 | The corrected TuringDB baseline is materialized to a NEW file (`e2e-baseline-corrected.json`); the original `baseline/03-turingdb/e2e-results.json` is left intact for provenance | ✓ VERIFIED | `e2e-baseline-corrected.json` exists with corrected `score:7.368`/`verdict:FAILED_SCORE_GATE`; `git diff` on `baseline/03-turingdb/e2e-results.json` shows zero changes in this verification pass |
| 13 | `GATE.md` records the GO/NO-GO verdict + rationale, per-metric/per-check/per-document diff, disclosed deviations, and exact reproduction commands, mirroring `BASELINE.md` | ✓ VERIFIED | All required sections present (`## What This Is`, `## Provider Configuration`, `## Metrics Diff`, `## Reproduction Commands`, `## Verdict`, plus extras); every figure cross-checked against `gate-result.json` and found to match exactly |
| 14 | The raw ArcadeDB-side captures + corrected baseline are force-added under `baseline/06-gate/` (gitignore-bypassed) | ✓ VERIFIED | `git ls-files baseline/06-gate/` lists all 8 expected files; `git status --porcelain` is clean (nothing untracked/modified) |
| 15 | `tests/test_gate_artifact_schema.py` asserts the committed `gate-result.json` is well-formed — always green regardless of verdict value | ✓ VERIFIED | Ran directly: all 6 well-formedness tests pass |
| 16 | (Roadmap SC#3) The comparison result is recorded as the gate artifact that authorizes/blocks Phase-7 cutover | ✓ VERIFIED | `gate-result.json`/`GATE.md` committed; `gate_guard.assert_gate_go` wired to read this exact path; `test_assert_gate_go_passes_on_the_committed_artifact` passes today because the committed verdict is GO |
| 17 | (Roadmap SC#2 / `verification: backstop`) The verdict logic, fed the **real GPU N=3 captures**, correctly returns GO iff the port meets-or-exceeds the bug-corrected bar — i.e., the underlying capture is a genuine, non-stub, real-hardware measurement | ? UNCERTAIN | Computation itself independently re-verified correct (see #2–#7, #11); the *external* GPU/Docker capture that fed it cannot be reproduced or independently attested by this verifier — see Human Verification |
| 18 | (06-04 Task 2 deferred human-check) `GATE.md`'s verdict narration is honest and non-cherry-picked | ? UNCERTAIN | Every figure cross-referenced matches `gate-result.json` exactly (no discrepancy found); the plan itself declares this a deferred `<human-check>` requiring explicit human sign-off before Phase 7 proceeds — see Human Verification |

**Score:** 16/18 truths verified (2 present, human-judgment items — not failures)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/gate_diff.py` | Deterministic gate engine (all documented functions) | ✓ VERIFIED | 365 LOC; `corrected_checks`, `verify_corpus`, `is_stub_provider`, `meaningful_subset_summary`, `mean_of_runs`, `diff_metrics`, `compute_verdict`, `build_gate_result`, `main` all present and covered by tests |
| `tests/test_gate_diff.py` | 20 unit tests | ✓ VERIFIED | 20/20 pass |
| `src/turing_agentmemory_mcp/gate_guard.py` | Fail-closed Phase-7 guard | ✓ VERIFIED | 79 LOC; `validate_gate_result_schema`, `load_verdict`, `assert_gate_go` present |
| `tests/test_phase7_gate_guard.py` | Fail-closed guard tests | ✓ VERIFIED | 27 tests pass, zero `pytest.skip` |
| `baseline/06-gate/gate-result.json` | GO/NO_GO + all D-09 fields | ✓ VERIFIED | verdict: GO; all 9 required fields + extras (`normattiva_evidence`, `frozen_questions_count`) present |
| `baseline/06-gate/e2e-results.json` | 19 checks, non-stub, check #13 ok | ✓ VERIFIED | 19 checks; `check_count:19`; hostnames `agentmemory-embed:8080`/`agentmemory-rerank:8080`; check #13 `ok:true` |
| `baseline/06-gate/real-document-benchmark-run{1,2,3}.json` | q=60 each, 12 docs | ✓ VERIFIED | Each run: `question_count:60`, 12 documents, `mrr_at_20`/`recall_at_k`/`latency_ms` present |
| `baseline/06-gate/e2e-baseline-corrected.json` | 14 corrected passes | ✓ VERIFIED | `earned:14, total:19, score:7.368` |
| `baseline/03-turingdb/e2e-results.json` | Unchanged (provenance) | ✓ VERIFIED | Diffed byte-for-byte against HEAD — no changes |
| `baseline/06-gate/GATE.md` | All required sections, figures matching | ✓ VERIFIED | All sections present; figures match `gate-result.json` exactly |
| `baseline/06-gate/capture-provider-env.txt` | Provider config + repro commands | ✓ VERIFIED | Present, records model IDs, endpoints, env flags, GLiNER-scope decision |
| `tests/test_gate_artifact_schema.py` | Well-formedness + GO assertion on committed artifact | ✓ VERIFIED | 8 tests, all pass; the GO-only test genuinely passes because the committed verdict is GO |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `corpus-manifest.json` sha256 fields | `verify_corpus()` | fail-closed comparison | WIRED | `gate-result.json.corpus_verification.ok == true`, zero mismatches |
| `baseline/03-turingdb/real-document-benchmark.json` | `diff_metrics()` baseline side | `meaningful_subset_summary` | WIRED | `baseline_bar` in `gate-result.json` reproduces the committed bar exactly |
| e2e check #1 detail (embed/rerank URLs) | `is_stub_provider()` | authenticity gate | WIRED | `provider_config` in `gate-result.json` shows non-stub hostnames; `compute_verdict` forced NO_GO logic tested against stub fixtures |
| `real_document_benchmark_scoring.py` helpers | `gate_diff.py` (imported, not re-derived) | `file_digest`/`summarize_results`/`load_frozen_questions` | WIRED | Import block present (`try`/`except` dual-import pattern matching `real_document_benchmark.py`); no hand-rolled hashing found |
| `baseline/06-gate/gate-result.json` verdict | `gate_guard.assert_gate_go` | Phase-7 entry hard-block | WIRED | `tests/test_gate_artifact_schema.py::TestCommittedGateVerdictIsGo` calls `assert_gate_go` on the real committed path and passes |
| 06-03 raw captures | `gate_diff.py --port-runs`/`--e2e-port` | CLI inputs | WIRED | `gate-result.json`'s `runs:3`, `latency`, `metrics_diff` values are traceable to the three run files and the e2e capture |
| `gate-result.json` verdict | `GATE.md` `## Verdict` | cross-reference | WIRED | Both say `GO`; every other figure in `GATE.md` matches `gate-result.json` verbatim |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|--------------|------------|-------------|--------|----------|
| ARC-09 | 06-01, 06-02, 06-03, 06-04 (all 4 plans) | Migration-correctness gate — the ported ArcadeDB code meets-or-exceeds the ARC-01 baseline (HARD exit criterion) | ✓ SATISFIED (pending human sign-off) | `REQUIREMENTS.md` traceability table: `ARC-09 | Phase 6 | Complete`; no orphaned requirements found for Phase 6 |

No orphaned requirements — REQUIREMENTS.md maps exactly one ID (ARC-09) to Phase 6, and all 4 plans declare `requirements: [ARC-09]`.

### Anti-Patterns Found

None. No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers in any of the phase's created files (`scripts/gate_diff.py`, `src/turing_agentmemory_mcp/gate_guard.py`, `tests/test_gate_diff.py`, `tests/test_phase7_gate_guard.py`, `tests/test_gate_artifact_schema.py`). The only occurrences of the literal string `pytest.skip` are in prose/docstrings explaining that the guard has no skip escape hatch — not actual `pytest.skip()` calls (confirmed by grep). All 5 files are well under the 600-LOC cap (max 393 LOC).

### Full-Gate Command Results

- `python -m pytest -q` (full suite): **880 passed, 1 skipped** (the 1 skip is `tests/test_utcp_conformance.py` — pre-existing, unrelated `ModuleNotFoundError: utcp`, not introduced by this phase)
- `python -m pytest tests/test_gate_diff.py tests/test_phase7_gate_guard.py tests/test_gate_artifact_schema.py -v`: **55/55 passed**, including `test_assert_gate_go_passes_on_the_committed_artifact` (green only because the committed verdict is genuinely GO)
- `python -m ruff format --check src tests scripts`: clean (162 files already formatted)
- `python -m ruff check src tests scripts`: all checks passed
- `bash scripts/check-file-size.sh`: clean, all tracked `*.py` files within the 600-LOC cap
- `docker compose config --quiet`: clean (no output, exit 0)
- D-05 git-ancestry claim independently re-verified: `git merge-base --is-ancestor 8120efd ab7abd0` confirms true; `src/turing_agentmemory_mcp/e2e_score_check.py::check()` at HEAD genuinely computes `ok = bool(detail)`
- Frozen-questions count independently re-verified: `baseline/03-turingdb/frozen-questions.json` sums to exactly 60 questions across 12 documents

### Human Verification Required

### 1. GPU-Backed Capture Authenticity

**Test:** Confirm `baseline/06-gate/e2e-results.json` and `real-document-benchmark-run{1,2,3}.json` are genuine, unedited output from an actual NVIDIA-GPU Docker run against the real granite-embedding + BGE-reranker sidecars and the exact `D:/tmp/baseline-corpus` (per `capture-provider-env.txt`'s narrative).
**Expected:** The capture matches the documented reproduction commands and hardware (RTX A2000, 4096 MiB VRAM per `capture-provider-env.txt`); no hand-edited JSON.
**Why human:** This verifier has no GPU/Docker access in this session. All internal-consistency checks pass (non-stub hostnames, the genuine before/after IndexError-to-pass flip on check #13, sha256-verified corpus, plausible N=3 run-to-run variance, D-05 ancestry independently confirmed) — but authenticity of an external hardware capture is not something static analysis can fully certify. The plan itself tags this class of truth `verification: backstop` and both 06-03-SUMMARY.md and 06-04-SUMMARY.md self-report `human_judgment: true` for exactly this reason.

### 2. GATE.md Honest Narration Read-Through (plan-deferred human-check)

**Test:** Read `baseline/06-gate/GATE.md` end-to-end (06-04-PLAN.md Task 2's own declared `<human-check>`): confirm the verdict + rationale are honest (graded against the bug-corrected 7-doc bar, not a flattered/deflated aggregate), the per-document diff is complete, deviations (GLiNER on, latency volume-bloat confound, check #19/#1 rename) are disclosed, and reproduction commands use correct per-script flag names.
**Expected:** No narrative dishonesty or cherry-picking; the document forms the basis for authorizing Phase 7's irreversible TuringDB removal.
**Why human:** 06-04-PLAN.md declared this `<human-check>` inside an `autonomous: true` plan, explicitly deferring it to end-of-phase. This verifier performed the equivalent figure-by-figure cross-reference (every number in `GATE.md` matches `gate-result.json` exactly — no discrepancy found), but the prose-honesty judgment the plan calls for is a human checkpoint by design, not a mechanical one.

### Gaps Summary

No gaps were found. Every code artifact (`gate_diff.py`, `gate_guard.py`, and their three test modules) exists, is substantive, is wired, and its tests pass — both in isolation and as part of the full 880-test suite. Every committed data artifact under `baseline/06-gate/` is git-tracked, internally consistent, and cross-references correctly against `gate-result.json`. The corrected TuringDB baseline was derived without touching the original, honoring D-05's provenance requirement. Lint, format, file-size, and `docker compose config` gates are all clean. Requirements traceability (ARC-09 → Phase 6 → Complete) has no orphans.

The `human_needed` status stems entirely from two items the phase's own plans deliberately flagged as human judgment calls (`verification: backstop` in must_haves, and an explicit deferred `<human-check>` in 06-04's Task 2): confirming the GPU-backed capture is a genuine, non-fabricated measurement, and a prose-honesty read-through of `GATE.md`. Both are exactly the kind of checkpoint this phase's own threat model called for before authorizing Phase 7's irreversible TuringDB removal — the underlying automated computation is sound and this verifier's cross-checks found no contradicting evidence, but final authorization of an irreversible action is properly a human decision here, not this verifier's to make unilaterally.

---

_Verified: 2026-07-16T15:00:00Z_
_Verifier: Claude (gsd-verifier)_
