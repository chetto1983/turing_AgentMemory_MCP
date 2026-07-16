---
phase: 06-migration-correctness-gate
plan: 02
subsystem: testing
tags: [gate-guard, fail-closed, tdd, ARC-09, phase-7-entry]

# Dependency graph
requires:
  - phase: 06-migration-correctness-gate (plan 01)
    provides: baseline/06-gate/gate-result.json schema conventions (D-09 field names) and compute_verdict() output shape
provides:
  - src/turing_agentmemory_mcp/gate_guard.py -- validate_gate_result_schema(), load_verdict(), assert_gate_go()
  - fail-closed Phase-7 entry contract that a future phase invokes before the irreversible TuringDB removal
affects: [phase-7 (TuringDB removal), any future gate-artifact consumer]

# Tech tracking
tech-stack:
  added: []
  patterns: ["fail-closed guard: read-fresh + schema-validate + explicit-verdict-check, no cache, no pytest.skip escape hatch"]

key-files:
  created:
    - src/turing_agentmemory_mcp/gate_guard.py
    - tests/test_phase7_gate_guard.py
  modified: []

key-decisions:
  - "validate_gate_result_schema raises ValueError (not AssertionError) for schema violations; assert_gate_go wraps that into AssertionError at the load_verdict boundary so callers only need to catch one exception type for the fail-closed contract"
  - "Removed a self-referential 'no pytest.skip in this file' pytest test (paradoxical: the assertion string itself would trip its own check) in favor of the plan's literal grep-based verification step, per the task's stated 'grep-style assertion or reviewer note' allowance"

patterns-established:
  - "Gate-guard module: read fresh on every call (no module-level caching) to defeat tampering-after-first-read; mirrors tenant_registry.py's corrupt-schema-never-auto-repaired posture"

requirements-completed: [ARC-09]

coverage:
  - id: D1
    description: "validate_gate_result_schema(obj) asserts every D-09-mandated field is present and verdict is one of {GO, NO_GO}, raising on any violation"
    requirement: "ARC-09"
    verification:
      - kind: unit
        ref: "tests/test_phase7_gate_guard.py::TestValidateGateResultSchema"
        status: pass
    human_judgment: false
  - id: D2
    description: "assert_gate_go(path) reads gate-result.json fresh every call, validates schema, and refuses (raises AssertionError) unless verdict == 'GO'; fails closed on missing file, malformed JSON, and NO_GO; proven not to cache across calls"
    requirement: "ARC-09"
    verification:
      - kind: unit
        ref: "tests/test_phase7_gate_guard.py::TestAssertGateGo"
        status: pass
    human_judgment: false

# Metrics
duration: 12min
completed: 2026-07-16
status: complete
---

# Phase 06 Plan 02: Phase-7 Gate Guard Summary

**Fail-closed `gate_guard.py` (validate_gate_result_schema / load_verdict / assert_gate_go) that Phase 7 must invoke before the irreversible TuringDB removal — refuses unless the committed `gate-result.json` verdict is exactly `"GO"`, reading the file fresh every call with no `pytest.skip` escape hatch anywhere.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-16T09:39:00Z
- **Completed:** 2026-07-16T09:51:00Z
- **Tasks:** 2 completed
- **Files modified:** 2 (both new)

## Accomplishments
- `validate_gate_result_schema(obj)` — asserts all 9 D-09-mandated fields present and `verdict` is `GO`/`NO_GO`, raising `ValueError` naming the missing field or bad verdict
- `load_verdict(path)` — opens the path fresh (no caching), parses JSON, validates the schema, returns the verdict string; raises `AssertionError` on any missing file, unparseable JSON, or schema violation
- `assert_gate_go(path)` — the Phase-7 entry contract: raises `AssertionError` unless `verdict == "GO"`; proven to re-read fresh on every call (a GO-then-NO_GO rewrite between two calls flips the second call to raise)
- `tests/test_phase7_gate_guard.py` — 27 tmp_path self-tests covering well-formed accept, per-field-missing raise, bad-verdict raise, non-dict raise, missing-file raise, invalid-JSON raise, NO_GO raise, GO pass, and the no-cache proof; zero `pytest.skip` tokens anywhere in the file

## Task Commits

Each task was committed atomically (TDD RED -> GREEN):

1. **Task 1+2 RED: failing tests for D-09 schema validator + D-10 assert_gate_go** - `ad2833d` (test)
2. **Task 1+2 GREEN: implement gate_guard.py** - `3efbb6c` (feat)

_Note: both plan tasks (schema validator, then assert_gate_go) landed as a single cohesive RED->GREEN pair since the module is small (79 LOC) and the two functions share the same read-fresh/fail-closed contract; this matches the plan's own Task 2 action note ("REFACTOR if needed to keep both functions cohesive")._

**Plan metadata:** (this commit, below)

## Files Created/Modified
- `src/turing_agentmemory_mcp/gate_guard.py` - `validate_gate_result_schema`, `load_verdict`, `assert_gate_go`; 79 LOC, stdlib-only (json, pathlib)
- `tests/test_phase7_gate_guard.py` - 27 tmp_path/parametrized self-tests, modeled on `tests/test_no_skip_as_green_guard.py`'s fail-closed shape

## Decisions Made
- `validate_gate_result_schema` raises `ValueError` for schema-shape violations; `assert_gate_go`/`load_verdict` re-wrap that as `AssertionError` so the single documented Phase-7 contract is "catch `AssertionError`, never a silent pass, never a skip"
- Dropped a self-referential "no pytest.skip in this file" pytest test because the assertion literal itself would falsely trip its own check (paradox); the plan explicitly permits a "grep-style assertion or reviewer note" instead — verified manually via `grep -n "pytest.skip" tests/test_phase7_gate_guard.py` (zero matches) as part of this plan's verification, and the module/test docstrings were worded to avoid the literal token too

## Deviations from Plan

None - plan executed exactly as written, with one clarifying adjustment documented above (self-referential skip-check test replaced by the plan's own allowed grep-based verification).

## Issues Encountered
- Initial draft of the self-check test asserted `"pytest.skip" not in source` against its own file, which is inherently paradoxical (the assertion string is itself a match). Resolved by removing the self-referential pytest test and relying on the plan's literal grep verification step instead, and rewording nearby docstrings to avoid the literal token as well.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `gate_guard.assert_gate_go()` is ready for Phase 7 to import and invoke as the hard-block gate before TuringDB removal, once `baseline/06-gate/gate-result.json` is committed with a `GO` verdict
- No blockers; full 872-test suite green (1 pre-existing unrelated skip), ruff format/check clean, file-size cap clean

---
*Phase: 06-migration-correctness-gate*
*Completed: 2026-07-16*

## Self-Check: PASSED

- FOUND: src/turing_agentmemory_mcp/gate_guard.py
- FOUND: tests/test_phase7_gate_guard.py
- FOUND: ad2833d (test commit)
- FOUND: 3efbb6c (feat commit)
