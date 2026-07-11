---
phase: 01-ci-git-hook-discipline
plan: 08
subsystem: testing
tags: [pytest, pytester, conftest, no-skip-as-green, tdd]

# Dependency graph
requires:
  - phase: 01-ci-git-hook-discipline (plan 07)
    provides: pyproject.toml pytest markers (slow/integration/gpu registered) and active local git hooks
provides:
  - "tests/conftest.py — a pytest_runtest_makereport hookwrapper that, under CI=true, converts a skipped integration/gpu-marked test into a failure"
  - "tests/test_no_skip_as_green_guard.py — a pytester-based negative self-test proving the guard fires under CI=true and stays inert without it"
affects: [ci-git-hook-discipline (plan 09 — CI workflow arms CI=true for the guard self-test step and the dockerized-integration job)]

# Tech tracking
tech-stack:
  added: []
  patterns: ["pytester-based hookwrapper self-test (isolated subprocess run, no pollution of the real collected suite)"]

key-files:
  created: [tests/conftest.py, tests/test_no_skip_as_green_guard.py]
  modified: []

key-decisions:
  - "Guard code and self-test written verbatim from RESEARCH.md D-03/D-04 (no in-repo analog existed); RED test committed before the guard implementation, matching the plan's TDD task order"

patterns-established:
  - "no-skip-as-green: a central tests/conftest.py hookwrapper (not per-test boilerplate) enforces that CI-required tiers (integration/gpu markers) never pass green via a silent skip"

requirements-completed: [CI-07]

coverage:
  - id: D1
    description: "Under CI=true, a pytest.mark.integration/gpu test that calls pytest.skip() is reported as a failure (not skipped), with a no-skip-as-green message"
    requirement: "CI-07"
    verification:
      - kind: unit
        ref: "tests/test_no_skip_as_green_guard.py#test_ci_guard_converts_a_marked_skip_into_a_failure"
        status: pass
    human_judgment: false
  - id: D2
    description: "Without CI=true, the same marked skip still passes green (guard is inert off-CI)"
    requirement: "CI-07"
    verification:
      - kind: unit
        ref: "tests/test_no_skip_as_green_guard.py#test_without_ci_env_the_same_skip_still_passes_green"
        status: pass
    human_judgment: false
  - id: D3
    description: "Adding tests/conftest.py does not change the full-suite baseline outcome (guard is inert for unmarked tests/normal runs)"
    requirement: "CI-07"
    verification:
      - kind: unit
        ref: "python -m pytest -q (full suite: 362 pre-existing + 2 new guard tests = 364 passed, 0 failed)"
        status: pass
    human_judgment: false

# Metrics
duration: 5min
completed: 2026-07-12
status: complete
---

# Phase 01 Plan 08: No-Skip-As-Green Guard Summary

**A central `tests/conftest.py` `pytest_runtest_makereport` hookwrapper that converts a CI=true skip on an `integration`/`gpu`-marked test into a failure, proven by a `pytester`-based negative self-test (CI-07, D-03/D-04).**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-07-12T00:12Z (approx, first commit)
- **Completed:** 2026-07-12T00:13Z (approx, second commit)
- **Tasks:** 2
- **Files modified:** 2 (both new)

## Accomplishments
- Wrote `tests/test_no_skip_as_green_guard.py` first (RED) — confirmed it fails with `FileNotFoundError` on `tests/conftest.py` before the guard existed, per TDD task order
- Implemented `tests/conftest.py`'s `pytest_runtest_makereport` hookwrapper (GREEN) — a skip on an `integration`/`gpu`-marked test under `CI=true` is now reported as `failed=1` with a `no-skip-as-green:` message; without `CI=true` the same skip still reports `skipped=1`
- Verified the guard is inert for the normal suite: `python -m pytest -q` reports 364 passed (362 pre-existing + 2 new guard self-tests), 0 failed, no new silent skips
- Verified guard robustness: re-running the self-test file itself with the outer process's `CI=true` set still passes (the pytester subprocess correctly isolates its own env via `monkeypatch`)

## Task Commits

Each task was committed atomically (TDD RED then GREEN):

1. **Task 1 (RED): negative self-test** — `b5e993a` (test) — `tests/test_no_skip_as_green_guard.py`, confirmed failing before the guard existed
2. **Task 2 (GREEN): conftest.py guard** — `7f3637b` (feat) — `tests/conftest.py`, self-test now passes, full suite unchanged at 364 passed

**Plan metadata:** pending (this SUMMARY + STATE/ROADMAP commit)

## TDD Gate Compliance

- RED gate: `test(01-08): add negative self-test proving no-skip-as-green guard fires (RED)` — `b5e993a` — verified failing (`FileNotFoundError` on `tests/conftest.py`) before proceeding
- GREEN gate: `feat(01-08): implement no-skip-as-green conftest.py guard (GREEN)` — `7f3637b` — verified passing after conftest.py landed
- No REFACTOR gate needed (guard implemented directly from the RESEARCH-drafted code, no cleanup pass required)

## Files Created/Modified
- `tests/conftest.py` (28 LOC) — the `pytest_runtest_makereport` hookwrapper; `_CI_ENFORCED_MARKERS = {"integration", "gpu"}`; converts a `CI=true` skip on an enforced-marker test to `failed` with a `no-skip-as-green:` longrepr message
- `tests/test_no_skip_as_green_guard.py` (41 LOC) — `pytester`-based negative self-test; two cases (`failed=1` under `CI=true`, `skipped=1` without) using an inline `_PROBE` module and `_REPO_CONFTEST.read_text()` to exercise the real repo conftest in an isolated subprocess

## Decisions Made
- Used the RESEARCH.md D-03/D-04 code verbatim (no in-repo analog existed for a `conftest.py` hookwrapper or `pytester`-based plugin test) — per PATTERNS.md guidance, this is the one genuinely custom piece of code in the phase.

## Deviations from Plan

None — plan executed exactly as written. Both tasks matched their acceptance criteria on the first pass; no auto-fixes were needed.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The guard and its self-test are in place for plan 09 to arm `CI: "true"` in `.github/workflows/ci.yml`'s unit-tests self-test step and the dockerized-integration job (per RESEARCH.md's "No-skip-as-green arming convention").
- Full local suite remains green (364 passed) and ruff-clean across `src tests scripts`; no blockers for the remaining wave-4 plan.

---
*Phase: 01-ci-git-hook-discipline*
*Completed: 2026-07-12*

## Self-Check: PASSED

- FOUND: tests/conftest.py
- FOUND: tests/test_no_skip_as_green_guard.py
- FOUND: b5e993a (RED commit)
- FOUND: 7f3637b (GREEN commit)
