---
phase: 01-ci-git-hook-discipline
plan: 09
subsystem: infra
tags: [github-actions, ci, ruff, pytest-cov, pip-audit, docker-compose, e2e]

# Dependency graph
requires:
  - phase: 01-07
    provides: lefthook.yml local hook layer (pre-commit ruff/file-size, pre-push compile/fast-tests/compose-config), scripts/check-file-size.sh, scripts/run-python.sh
  - phase: 01-08
    provides: tests/conftest.py no-skip-as-green hookwrapper guard + tests/test_no_skip_as_green_guard.py negative self-test
provides:
  - .github/workflows/ci.yml with the full L-04 job matrix (lint, unit-tests+coverage, compose-validate, supply-chain, dockerized-integration)
  - a measured (not guessed) coverage floor wired as --cov-fail-under=78
  - a GPU-less E2E stub-floor design that asserts a real pass/fail signal (score>=9.4, all 19 checks executed) instead of the script's own unreachable VALIDATED_10_10 exit code
affects: [ci, docker, backend]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "GPU-less CI degrade floor: assert a measured stub-mode floor (score/check-count) rather than the deterministic gate's own strict pass/fail exit code, when that gate's full bar (VALIDATED_10_10) requires hardware unavailable on the runner"
    - "no-skip-as-green CI=true arming convention applied per-job (unit-tests self-test step, whole dockerized-integration job)"

key-files:
  created:
    - .github/workflows/ci.yml
  modified: []

key-decisions:
  - "Coverage floor measured at 78.12% (364 tests, e2e_score.py omitted per existing [tool.coverage.run]); wired as --cov-fail-under=78 (ratchet-safe, not guessed)"
  - "dockerized-integration job does NOT assert docker compose run --rm e2e's own exit code — that script's main() only returns 0 when score>=9.8 AND check_count==19 (VALIDATED_10_10), which the in-process HashingEmbedder stub cannot reach (measured stub baseline: score 9.474, 18/19 passing, all 19 executed). Asserting that exit code as-is would make CI permanently red on every GPU-less run. Instead the job captures stdout JSON and asserts a measured stub floor (score >= 9.4 AND check_count == 19) via jq + awk — a real, regression-catching pass/fail gate that is never a silent skip, per D-05/D-06/CI-08's explicit requirement to avoid both silent-green and permanently-red outcomes"
  - "CI-05 (real-document E2E) satisfied by the deterministic in-process document flow inside scripts/e2e_score.py plus the existing unit-tests job's deterministic document tests (D-10); scripts/real_document_benchmark.py (needs a live paid LLM key + a pre-running MCP server) stays an operator-run tool, intentionally not wired into CI — verified via grep that ci.yml contains no reference to it or to PROVIDER_API_KEY"
  - "Single Python 3.12 across every job (D-11); no matrix"

patterns-established:
  - "GPU-less degrade floor pattern: when a deterministic gate's own internal pass/fail bar is unreachable without hardware the CI runner lacks, parse its JSON output and assert a separately measured, lower floor as the job's real signal — never pass through the tool's own too-strict exit code, and never skip the tier outright"

requirements-completed: [CI-03, CI-04, CI-05, CI-06, CI-08, CI-09]

coverage:
  - id: D1
    description: "CI lint job: ruff==0.15.21 format --check + check + check-file-size.sh, all verified locally"
    requirement: "CI-03"
    verification:
      - kind: other
        ref: "local: ruff format --check / ruff check / bash scripts/check-file-size.sh all exit 0"
        status: pass
    human_judgment: false
  - id: D2
    description: "CI unit-tests job: pytest --cov=src/turing_agentmemory_mcp --cov-fail-under=78 (measured floor, 364 tests) + no-skip-as-green guard self-test armed via CI=true"
    requirement: "CI-04, CI-09"
    verification:
      - kind: unit
        ref: "local: python -m pytest --cov=src/turing_agentmemory_mcp --cov-fail-under=78 -q -> 364 passed, TOTAL 78%"
        status: pass
    human_judgment: false
  - id: D3
    description: "CI compose-validate job: docker compose config --quiet"
    requirement: "CI-06"
    verification:
      - kind: other
        ref: "local: docker compose config --quiet exits 0"
        status: pass
    human_judgment: false
  - id: D4
    description: "CI supply-chain job: pip-audit==2.10.1 against the resolved env"
    requirement: "CI-06"
    verification: []
    human_judgment: true
    rationale: "pip-audit is not installed in the local dev venv (CI-only tool per RESEARCH.md); the pin (2.10.1) matches the locked decision and the step shape mirrors the RESEARCH.md skeleton, but the actual pip-audit run itself could only be verified by a real GitHub Actions run, not locally on this Windows host"
  - id: D5
    description: "CI dockerized-integration job: runs the GPU-less E2E stub floor (docker compose run --rm e2e, score>=9.4, all 19 checks executed) instead of asserting the script's own VALIDATED_10_10 exit code; CI=true arms no-skip-as-green"
    requirement: "CI-05, CI-08"
    verification:
      - kind: e2e
        ref: "local: docker compose run --rm e2e -> score 9.474, check_count 19, verdict FAILED_SCORE_GATE (expected in stub mode); floor-assertion logic (jq/awk control flow) dry-run against the captured JSON confirms PASS at the real baseline and confirms the FAIL path fires on a synthetic low score and a synthetic dropped check_count"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-11
status: complete
---

# Phase 1 Plan 9: GitHub Actions CI Workflow Summary

**Authored `.github/workflows/ci.yml` with a 5-job L-04 matrix (lint, unit-tests+coverage, compose-validate, supply-chain, dockerized-integration), wiring a measured 78% coverage floor and a GPU-less E2E stub-floor design that asserts a real pass/fail signal instead of the deterministic gate's own unreachable-on-CPU exit code.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-07-11T22:25:09Z
- **Tasks:** 2
- **Files modified:** 1 (`.github/workflows/ci.yml`, new)

## Accomplishments

- Measured the real coverage baseline against the post-decomposition suite: 364 tests, 78.12% covered (`e2e_score.py` omitted per the existing `[tool.coverage.run]` config from plan 07) — not guessed. Verified `--cov-fail-under=78` exits 0 on the current tree.
- Authored `.github/workflows/ci.yml`'s five jobs on `ubuntu-latest`/Python 3.12 (D-11), triggered on `push`/`pull_request` to `master`, with `permissions: contents: read` and a `cancel-in-progress` concurrency group.
- Discovered mid-execution that a naive `docker compose run --rm e2e` step (as literally sketched in RESEARCH.md's skeleton) would make CI **permanently red** on this GPU-less runner: `scripts/e2e_score.py`'s `main()` only returns exit code 0 when `score >= 9.8` and `check_count == 19` (`VALIDATED_10_10`), but the in-process `HashingEmbedder` stub caps out at `score 9.474` / `18 of 19` passing checks (confirmed by two real local `docker compose run --rm e2e` invocations). Redesigned the `dockerized-integration` job to capture the script's JSON stdout and assert a separately measured stub floor (`score >= 9.4` AND `check_count == 19`) via `jq`/`awk` — a real, regression-catching pass/fail gate that is never a silent skip, satisfying D-05/D-06/CI-08's explicit requirement to avoid both silent-green and permanently-red outcomes on a GPU-less runner.
- Verified every job's underlying command locally: `ruff format --check`/`ruff check` (clean), `bash scripts/check-file-size.sh` (clean), `docker compose config --quiet` (valid), `docker compose run --rm e2e` (ran twice, JSON captured and parsed), full `pytest -q` (364 passed).

## Task Commits

1. **Task 1: Measure the coverage floor** — no source commit (measurement recorded here; the chosen floor `78` was wired directly into Task 2's `ci.yml`)
2. **Task 2: Author .github/workflows/ci.yml** — `f2acdfe` (feat)

**Plan metadata:** (this commit, pending)

## Files Created/Modified

- `.github/workflows/ci.yml` - the full L-04 CI job matrix: `lint`, `unit-tests`, `compose-validate`, `supply-chain`, `dockerized-integration`

## Decisions Made

- **Coverage floor = 78** (measured 78.12%, ratchet-safe, `e2e_score.py` excluded per existing `pyproject.toml` `[tool.coverage.run] omit`).
- **GPU-less E2E floor design deviates from RESEARCH.md's literal skeleton**: instead of `run: docker compose run --rm e2e` (whose exit code is the script's own `VALIDATED_10_10` gate — permanently unreachable and thus permanently red on a stub-only runner), the job captures stdout to a file with `|| true`, then asserts `score >= 9.4` and `check_count == 19` via `jq`/`awk`, echoing the raw `score`/`check_count`/`verdict` for visibility. This is the literal GPU-less-degrade-floor mechanism the plan's environment brief called for (see Deviations below).
- **jq for JSON parsing** (not a new Python helper script) — `jq` ships preinstalled on GitHub-hosted `ubuntu-latest` runners, keeping the `dockerized-integration` job free of an `actions/setup-python` step it otherwise wouldn't need.
- Single Python 3.12 across every job (D-11); no version matrix.
- `pip-audit` remains a workflow-only tool (installed in the `supply-chain` step, not added to `pyproject.toml`'s `dev` extra), matching RESEARCH.md's "Standard Stack" note.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Redesigned the dockerized-integration job's pass/fail signal**
- **Found during:** Task 2, local verification of the plan's acceptance criterion "`docker compose run --rm e2e` reaches VALIDATED_10_10"
- **Issue:** Running `docker compose run --rm e2e` locally (twice) confirmed it does **not** and cannot reach `VALIDATED_10_10` on this GPU-less setup — the script's own exit code is 1 (score 9.474, 18/19 checks, `verdict: FAILED_SCORE_GATE`), because the in-process `HashingEmbedder` stub cannot do semantic ranking (this exact caveat was flagged in the plan's `<environment>` block). Wiring the job as `run: docker compose run --rm e2e` per RESEARCH.md's literal skeleton would make the `dockerized-integration` job fail on every single push/PR forever — the opposite of a working CI gate, and a worse outcome than either D-05 (visible stub floor) or D-06 (never silent) intended.
- **Fix:** Rewrote the job's single step into a multi-line script that (a) runs the compose command with `|| true` to survive its non-zero exit, (b) parses the captured JSON with `jq` for `score`/`check_count`/`verdict`, (c) fails the job only if `check_count != 19` (a check was skipped/dropped — the no-skip-as-green concern) or `score < 9.4` (a real regression below the measured stub baseline), and (d) echoes both the raw values and an explicit "this is NOT VALIDATED_10_10" note so a reader never mistakes stub-mode green for a full-provider pass (D-06).
- **Files modified:** `.github/workflows/ci.yml`
- **Verification:** Two local `docker compose run --rm e2e` runs (score 9.474, check_count 19 both times); extracted the step's `run:` script via YAML parse and checked `bash -n` syntax; dry-ran the `jq`/`awk` control flow against the real captured JSON (PASS at baseline) and against synthetic low-score (5.0) and dropped-check-count (18) inputs (both correctly FAIL) using a local jq-equivalent shim (jq itself is not installed in this dev venv but ships on GitHub's `ubuntu-latest` runner image).
- **Committed in:** `f2acdfe` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug: the plan's literal skeleton would have produced a permanently-failing CI job).
**Impact on plan:** Necessary for correctness — the job now actually functions as a real, ratchet-safe gate on a GPU-less runner, matching the plan's own stated intent (D-05/D-06/CI-08 "never silent, never permanently red on GPU-less") more faithfully than the RESEARCH.md skeleton's literal wording. No scope creep — still one file, still the same five jobs, still no `real_document_benchmark.py`/`PROVIDER_API_KEY` reference.

## Issues Encountered

- Local dev venv lacks `jq` (Windows Git Bash) — could not execute the `dockerized-integration` step's exact `run:` script end-to-end as a single shell invocation locally. Mitigated by extracting the script, checking `bash -n` syntax, and dry-running the control-flow logic (score/check_count assertions) against the real captured E2E JSON with a local jq-equivalent shim, confirming both the PASS path (real baseline) and both FAIL paths (synthetic regression, synthetic dropped check). `jq` is preinstalled on GitHub-hosted `ubuntu-latest` runners, so the actual CI run is expected to execute this script as-is; this is a local-verification gap, not an unverified design.
- `pip-audit==2.10.1` is not installed in the local dev venv (by design — CI-only tool per RESEARCH.md's Standard Stack), so the `supply-chain` job's actual `pip-audit` invocation could not be run locally; the pin and step shape were verified against RESEARCH.md's confirmed-current PyPI version instead. Flagged as `human_judgment: true` in the coverage block above.

## Next Phase Readiness

- Phase 01 (ci-git-hook-discipline) is now fully executed: all 9 plans complete. Local hooks (lefthook), the file-size cap, ruff format bootstrap, no-skip-as-green guard, and the GitHub Actions CI matrix are all wired.
- The CI workflow has never actually run on GitHub Actions (no push/PR has triggered it yet) — the `supply-chain` job's `pip-audit` step and the `dockerized-integration` job's `jq`-based floor assertion are verified as far as is possible on this local Windows host; a real GitHub Actions run (on the next push) is the first live confirmation of the full workflow end-to-end.
- No blockers for downstream phases. The guardrails this phase installs (hooks + CI) now protect every subsequent phase's changes.

---
*Phase: 01-ci-git-hook-discipline*
*Completed: 2026-07-11*

## Self-Check: PASSED

- FOUND: `.github/workflows/ci.yml`
- FOUND: `.planning/phases/01-ci-git-hook-discipline/01-09-SUMMARY.md`
- FOUND: commit `f2acdfe`
