---
phase: 07-remove-turingdb-dependency-hardening
plan: 08
subsystem: testing
tags: [pytest, ruff, docker-compose, e2e-gate, arcadedb, cut-proof]

# Dependency graph
requires:
  - phase: 07-remove-turingdb-dependency-hardening (07-01..07-07)
    provides: TuringDB removal, dependency hardening oracles, docs/invariant rewrite
provides:
  - Cut-proof: full unit suite green turingdb-free at the CI coverage floor
  - Cut-proof: docker compose config --quiet clean on the ArcadeDB-only stack
  - Cut-proof: grep-gate + DEP-01/DEP-02 compat oracles green; gate_guard reads GO
  - Cut-proof: E2E score gate green (10.0, 19/19) on ArcadeDB alone
  - Human approval of the rewritten CLAUDE.md / .claude/CLAUDE.md invariants and the irreversible TuringDB cut
affects: [08, 09, 10, 11, 12]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified: []

key-decisions:
  - "Task 1 is verification-only (files_modified: []) — no code changes, the gate itself is the deliverable."
  - "Human approved the invariant rewrite and the irreversible TuringDB cut ('approved') after reviewing the automated cut-proof evidence."

patterns-established: []

requirements-completed: []  # ARC-10 intentionally left Pending — the orchestrator owns phase-level REQUIREMENTS.md traceability after this plan returns.

coverage:
  - id: D1
    description: "Full unit suite passes turingdb-free at the CI coverage floor (-m 'not integration and not gpu' --cov-fail-under=78)"
    requirement: "ARC-10"
    verification:
      - kind: unit
        ref: "python -m pytest -m 'not integration and not gpu' --cov=src/turing_agentmemory_mcp --cov-fail-under=78 -q"
        status: pass
    human_judgment: false
  - id: D2
    description: "docker compose config --quiet validates the ArcadeDB-only stack (turingdb + turingdb-volume-init services gone)"
    requirement: "ARC-10"
    verification:
      - kind: integration
        ref: "docker compose config --quiet"
        status: pass
    human_judgment: false
  - id: D3
    description: "No-import grep-gate + DEP-01/DEP-02 compat oracles green; gate_guard still reads GO against the untouched baseline"
    requirement: "ARC-10"
    verification:
      - kind: unit
        ref: "tests/test_no_turingdb_imports.py; -k graspologic_compat; -k fastmcp_compat; gate_guard.assert_gate_go(baseline/06-gate/gate-result.json)"
        status: pass
    human_judgment: false
  - id: D4
    description: "E2E score gate stays green on ArcadeDB alone (score >= 9.8, check_count == 19) — the cut did not regress retrieval correctness"
    requirement: "ARC-10"
    verification:
      - kind: e2e
        ref: "python scripts/e2e_score.py --out e2e-results.json (score 10.0, check_count 19, verdict VALIDATED_10_10)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Human review of the rewritten CLAUDE.md / .claude/CLAUDE.md invariants and confirmation of the irreversible TuringDB removal"
    requirement: "ARC-10"
    verification: []
    human_judgment: true
    rationale: "Irreversible architectural cut (D-04) — confirming invariant text accuracy and authorizing removal is a human judgment call by design, not something a passing test can substitute for."

# Metrics
duration: 20min
completed: 2026-07-16
status: complete
---

# Phase 7 Plan 8: TuringDB Cut-Proof Gate Summary

**Full CI-equivalent gate (unit suite, compose validation, grep-gate + DEP oracles, gate_guard GO, and a live ArcadeDB E2E run scoring 10.0/19-of-19) proved the TuringDB cut correct and tenant-isolated; human approved the rewritten invariants and the irreversible removal.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-16
- **Tasks:** 2/2 completed (Task 1 automated cut-proof; Task 2 human-verify checkpoint, approved)
- **Files modified:** 0 (verification + checkpoint only, per plan's `files_modified: []`)

## Accomplishments

- Ran the full CI-equivalent pre-commit + test gate in CI order and confirmed every stage green turingdb-free:
  - `ruff format --check src tests scripts` — clean (153 files)
  - `ruff check src tests scripts` — all checks passed
  - `bash scripts/check-file-size.sh` — every tracked `*.py` file within the 600-LOC cap
  - `pytest -m "not integration and not gpu" --cov=src/turing_agentmemory_mcp --cov-fail-under=78 -q` — 856 passed, 1 skipped (pre-existing utcp optional-dep skip), coverage 87.22% (well over the 78% floor)
  - `docker compose config --quiet` — exit 0; 7 services, no `turingdb` / `turingdb-volume-init`
- Confirmed all three phase oracles green: `tests/test_no_turingdb_imports.py` (grep-gate), `-k graspologic_compat` (DEP-01), `-k fastmcp_compat` (DEP-02)
- Confirmed `gate_guard.assert_gate_go(baseline/06-gate/gate-result.json)` still returns GO — the Phase 6 migration-correctness baseline is untouched
- Ran the E2E score gate live against the running ArcadeDB compose service: score 10.0, check_count 19, verdict `VALIDATED_10_10` — retrieval correctness fully preserved on ArcadeDB alone, turingdb-free
- Human reviewed the rewritten invariants (CLAUDE.md `## Invariants`, `.claude/CLAUDE.md` Constraints) confirming ArcadeDB as sole canonical backend, the MVCC HTTP-503 `ConcurrentModificationException` handling, native `LSM_VECTOR`+Lucene ACID-consistency, one-DB-per-tenant + `TenantBinding` invariants, and the reconfirmed (not weakened) `user_identifier` fail-closed scope + stable/deterministic-ID invariants — responded **"approved"**, finalizing the irreversible TuringDB removal

## Task Commits

Task 1 (automated cut-proof) made no file changes per its `files_modified: []` scope — it is a pure verification task; no per-task commit exists for it. Task 2 (checkpoint:human-verify) is a review gate with no code changes; approval is recorded here.

**Plan metadata:** see the `docs(07-08): complete cut-proof plan (approved)` commit accompanying this SUMMARY.

## Files Created/Modified

None — this plan is verification + a human-review checkpoint only, exactly as scoped (`files_modified: []`).

## Decisions Made

- Task 1's cut-proof gate is treated as the deliverable itself: a fully green CI-equivalent run (lint, file-size, unit suite at coverage floor, compose validation, all three oracles, gate_guard GO, live E2E score) is the evidence, not a code artifact.
- Human approval text was the literal word "approved" against the presented evidence and invariant text, satisfying the plan's `resume-signal` contract.

## Deviations from Plan

None — plan executed exactly as written. Both tasks (automated cut-proof, then the blocking human-verify checkpoint) completed in order with no auto-fixes required.

## Issues Encountered

None during this plan's own execution. Three pre-existing, non-blocking follow-ups were surfaced (not fixed here, out of this plan's scope) for the orchestrator/owner to route to future quick-tasks or Phase 14:

1. **Stale TuringDB references remain in `.claude/CLAUDE.md`'s auto-generated STACK block** (Key Dependencies / Platform Requirements sections list `turingdb`, TuringDB-era env vars, and CUDA/GPU sidecar language predating the 07-06/07-07 invariant rewrite). This block is machine-regenerated, not hand-edited — resolve via `/gsd-map-codebase` re-run rather than manual patching.
2. **An orphan `turingdb` container was observed still running** on the local Docker host (stale from a prior compose stack before the 07-03/07-06 service removal from `compose.yaml`). `docker compose config --quiet` correctly shows no `turingdb` service defined; the running container is leftover local state, not a config regression. Clear locally with `docker compose up -d --remove-orphans`.
3. **A pre-existing ARIA accessibility lint finding at `frontend/index.html:84`** was noted during the review pass; unrelated to the TuringDB cut and out of this plan's scope — left for a future frontend/Lab-focused quick-task.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- The TuringDB removal is now human-approved and irreversible per this plan's gate. Phases 8–12 (which depend only on Phase 7 per STATE.md's Roadmap Evolution notes) are unblocked to build on the ArcadeDB-only stack.
- ARC-10 is intentionally left **Pending** in REQUIREMENTS.md by this plan — the orchestrator owns marking it complete and phase-level `phase.complete` / VERIFICATION.md / ROADMAP checkbox finalization after this SUMMARY is reviewed, per this plan's explicit continuation scope.
- The three non-blocking follow-ups above (stale STACK block text, orphan container, pre-existing a11y lint) do not block phase completion but should be tracked.

---
*Phase: 07-remove-turingdb-dependency-hardening*
*Completed: 2026-07-16*

## Self-Check: PASSED

- FOUND: `.planning/phases/07-remove-turingdb-dependency-hardening/07-08-SUMMARY.md`
- Sanity re-verify: `.venv/Scripts/python -m pytest tests/test_no_turingdb_imports.py -q` passed (1 passed) at continuation start.
