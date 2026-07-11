---
phase: 01-ci-git-hook-discipline
plan: 07
subsystem: infra
tags: [lefthook, ruff, pytest, git-hooks, ci, pyproject, makefile, windows]

# Dependency graph
requires:
  - phase: 01-ci-git-hook-discipline
    provides: "store.py + 9 other over-cap files decomposed to <=600 LOC (plans 01-01..01-06), repo-wide ruff-format bootstrap clean"
provides:
  - "scripts/check-file-size.sh — 600-LOC cap, no allowlist, MSYS-safe"
  - "lefthook.yml — pre-commit (ruff-format/ruff-check/file-size) + pre-push (compile-smoke/fast-tests/compose-config), installed and exercised via a real git commit"
  - "pyproject.toml dev extra: ruff==0.15.21, lefthook==2.1.10, pytest-cov==7.1.0; slow/integration/gpu pytest markers; [tool.coverage.run] omit for e2e_score*.py"
  - "Makefile hooks target (lefthook install)"
  - "CLAUDE.md store.py 600-LOC exception language removed"
  - "scripts/run-python.sh / scripts/run-fast-tests.sh — Windows-safe interpreter resolver + marker-expression wrapper (see Deviations)"
affects: [ci-workflow, phase-02-onward-all-commits]

# Tech tracking
tech-stack:
  added: ["lefthook==2.1.10 (pip)", "pytest-cov==7.1.0"]
  patterns:
    - "Local git hooks via lefthook.yml, heavy gates (E2E, coverage) stay in CI"
    - "No-allowlist file-size cap scanning ALL tracked *.py via git ls-files"
    - "Windows-safe interpreter resolution via a dedicated wrapper script, not inline shell in lefthook.yml"

key-files:
  created:
    - scripts/check-file-size.sh
    - lefthook.yml
    - scripts/run-python.sh
    - scripts/run-fast-tests.sh
  modified:
    - pyproject.toml
    - Makefile
    - CLAUDE.md

key-decisions:
  - "Wrapped interpreter resolution and the pytest marker expression in scripts/run-python.sh and scripts/run-fast-tests.sh instead of inline lefthook.yml shell — lefthook's Windows command execution does not reliably preserve nested single/double quotes or a root-level `shell:` override (schema rejects it in 2.1.10), verified by direct reproduction"
  - "pip install -e \".[dev]\" cannot complete on this Windows host because the base `dependencies` list pins turingdb==1.35 (no Windows wheel, pre-existing constraint unrelated to this plan) — dev-extra tools were verified via a direct `pip install ruff==... lefthook==... pytest-cov==...` instead, all three pins confirmed via `pip show`"
  - "make hooks could not be exercised in this shell (make is not installed / not on PATH here) — verified the underlying `lefthook install` command directly instead; the Makefile target itself is correct and equivalent"

patterns-established:
  - "Any future lefthook.yml command needing the project interpreter or a quoted multi-word argument should call a wrapper script under scripts/, not inline bash -c or unescaped quotes in the run: value"

requirements-completed: [CI-01, CI-02]

coverage:
  - id: D1
    description: "scripts/check-file-size.sh enforces the 600-LOC cap on ALL tracked *.py with no allowlist, MSYS-safe"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "bash scripts/check-file-size.sh (compliant tree, cap=600)"
        status: pass
      - kind: unit
        ref: "bash scripts/check-file-size.sh 50 (negative self-test — 93 OVER CAP lines, exit 1)"
        status: pass
    human_judgment: false
  - id: D2
    description: "lefthook.yml pre-commit (ruff-format/ruff-check/file-size) wired, installed, and fires on a real git commit"
    requirement: "CI-01"
    verification:
      - kind: integration
        ref: "lefthook run pre-commit --all-files (106 files formatted, checks passed, cap passed)"
        status: pass
      - kind: integration
        ref: "real `git commit` at 3cf333c / 4c71b34 shows the lefthook pre-commit banner firing and file-size passing"
        status: pass
    human_judgment: false
  - id: D3
    description: "lefthook.yml pre-push (compile-smoke/fast-tests/compose-config) wired and green"
    requirement: "CI-02"
    verification:
      - kind: integration
        ref: "lefthook run pre-push --all-files (compile-smoke, compose-config, fast-tests: 362 passed)"
        status: pass
    human_judgment: false
  - id: D4
    description: "pyproject.toml dev pins (lefthook==2.1.10, ruff==0.15.21, pytest-cov==7.1.0), slow/integration/gpu markers, coverage omit"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "pip show lefthook ruff pytest-cov -> 2.1.10 / 0.15.21 / 7.1.0"
        status: pass
      - kind: unit
        ref: "python -c tomllib marker-assertion one-liner from the plan's acceptance criteria"
        status: pass
    human_judgment: false
  - id: D5
    description: "make hooks target added; CLAUDE.md store.py exception removed"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "grep -ri 'large central exception' CLAUDE.md (no match) + grep -ri 'name>_<concern' CLAUDE.md (still matches)"
        status: pass
    human_judgment: false

duration: 40min
completed: 2026-07-12
status: complete
---

# Phase 01 Plan 07: Local Git-Hook Layer Summary

**Installed and exercised the lefthook pre-commit/pre-push stack (ruff-format, ruff-check, no-allowlist file-size cap, compile smoke, fast pytest subset, compose-config), pinned the dev-tooling versions, and removed CLAUDE.md's store.py 600-LOC exception now that store.py is decomposed.**

## Performance

- **Duration:** ~40 min (including Windows/lefthook quoting investigation)
- **Started:** 2026-07-11T23:45:00+02:00 (approx, first file read)
- **Completed:** 2026-07-12T00:02:28+02:00
- **Tasks:** 3
- **Files modified:** 7 (2 new beyond the plan's 5 — see Deviations)

## Accomplishments
- `scripts/check-file-size.sh` scans every tracked `*.py` with no allowlist; proven to exit 0 on the compliant tree and exit 1 (93 offenders) at a synthetic 50-LOC cap
- `lefthook.yml` wires pre-commit (ruff-format, ruff-check, file-size) and pre-push (compile-smoke, fast-tests, compose-config); `lefthook install` was run for real and a real `git commit` demonstrably triggered and passed the pre-commit hook
- `pyproject.toml` dev extra now pins `ruff==0.15.21`, `lefthook==2.1.10`, `pytest-cov==7.1.0`; registers `slow`/`integration`/`gpu` pytest markers; adds `[tool.coverage.run] omit = ["*/e2e_score*.py"]` for plan 09
- `Makefile` gained a `hooks` target; `CLAUDE.md` no longer calls `store.py` a 600-LOC exception

## Task Commits

Each task was committed atomically:

1. **Task 1: Create scripts/check-file-size.sh** - `f58f480` (feat)
2. **Task 2: Wire lefthook.yml, pyproject.toml, Makefile** - `3cf333c` (feat)
3. **Task 3: Remove store.py exception from CLAUDE.md** - `4c71b34` (docs)

**Plan metadata:** (this commit, appended after SUMMARY.md)

## Files Created/Modified
- `scripts/check-file-size.sh` - 600-LOC cap, no allowlist, MSYS-safe process-substitution loop
- `lefthook.yml` - pre-commit + pre-push command definitions
- `scripts/run-python.sh` - Windows-safe Python interpreter resolver used by lefthook commands (deviation, see below)
- `scripts/run-fast-tests.sh` - wraps the quoted `-m "not slow and not integration and not gpu"` pytest invocation (deviation, see below)
- `pyproject.toml` - dev extra pins, pytest markers, `[tool.coverage.run] omit`
- `Makefile` - added `hooks` target
- `CLAUDE.md` - removed store.py 600-LOC exception language

## Decisions Made
- The literal plan commands (`python -m ruff format --check {staged_files}`, `python -m pytest -q -m "not slow and not integration and not gpu"`) do not resolve correctly on this host/lefthook combination: bare `python` hits the broken Windows Store shim, and lefthook 2.1.10's Windows command execution does not reliably preserve nested quoting (verified both a root-level `shell: bash` override — rejected by the 2.1.10 schema — and an inline `bash -c '...'` wrapper — corrupted by the outer invocation). Resolved by moving the interpreter-resolution and quoted-marker-expression logic into two small wrapper scripts (`scripts/run-python.sh`, `scripts/run-fast-tests.sh`) that lefthook.yml calls with zero embedded quoting. This is a Rule 3 (blocking-issue) auto-fix per the plan's own environment guidance ("adapt to a working invocation and note the deviation").
- `pip install -e ".[dev]"` cannot complete on this Windows host: the project's base `dependencies` (pre-existing, unrelated to this plan) pin `turingdb==1.35`, which has no Windows wheel. Verified the three dev-tool pins directly via `pip install ruff==0.15.21 lefthook==2.1.10 pytest-cov==7.1.0` (registering the project itself via `pip install -e . --no-deps` first) and confirmed each via `pip show`. This matches the environment's own documented constraint ("turingdb has no Windows wheel — do NOT run scripts/e2e_score.py") and does not affect Linux CI, where the full `pip install -e ".[dev]"` will resolve normally.
- `make` is not installed/on PATH in this Git Bash shell, so `make hooks` itself could not be invoked; ran the target's underlying command (`lefthook install`) directly and confirmed hook files were written to `.git/hooks/pre-commit` and `.git/hooks/pre-push`. The Makefile target is correct and will work on any host with `make` present.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] lefthook.yml commands adapted from bare `python`/inline quoting to wrapper scripts**
- **Found during:** Task 2 verification (`lefthook run pre-commit`/`pre-push`)
- **Issue:** Bare `python -m ...` resolves to the Windows Store app-execution alias (no ruff/pytest installed); a quoted, multi-word `-m "not slow and not integration and not gpu"` marker expression got corrupted by lefthook's Windows command execution, producing a pytest `Wrong expression passed to '-m'` parse error even after resolving the interpreter path correctly. Also tried a root-level `shell: bash` lefthook.yml key — rejected by the 2.1.10 config schema ("No values are allowed") — and an inline `bash -c '...'` wrapper — still corrupted (`unexpected EOF while looking for matching \`'\``).
- **Fix:** Added `scripts/run-python.sh` (resolves `.venv/Scripts/python.exe` → `.venv/bin/python` → `python`, execs the rest of argv) and `scripts/run-fast-tests.sh` (hardcodes the quoted marker expression, calls `run-python.sh`). `lefthook.yml`'s `run:` values now call these with zero embedded quoting.
- **Files modified:** lefthook.yml, scripts/run-python.sh (new), scripts/run-fast-tests.sh (new)
- **Verification:** `lefthook run pre-commit --all-files` (ruff-format 106 files formatted, ruff-check all passed, file-size passed) and `lefthook run pre-push --all-files` (compile-smoke passed, compose-config passed, fast-tests 362 passed) both exit 0; a real `git commit` (3cf333c, 4c71b34) shows the lefthook pre-commit banner firing.
- **Committed in:** 3cf333c (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking — Rule 3), plus two documented pre-existing-environment notes (turingdb Windows wheel, `make` not on PATH) that required an equivalent verification path rather than the literal plan command, per the plan's own environment guidance.
**Impact on plan:** The wrapper scripts are the only files added beyond the plan's five-file list (`scripts/check-file-size.sh`, `lefthook.yml`, `Makefile`, `pyproject.toml`, `CLAUDE.md`). They are minimal, narrowly scoped to making the exact commands the plan specifies (`ruff format --check`, `ruff check`, `pytest -m "..."`) actually resolve on this host and in Linux CI, with no behavior change to what runs. No scope creep beyond the working-invocation requirement stated in the plan's own `<environment>` block.

## Issues Encountered
- lefthook's Windows shell handling (cmd.exe-style tokenization, not a real POSIX shell) does not preserve nested quotes reliably — resolved as above by removing all nested quoting from `lefthook.yml` itself.
- None of the other issues (turingdb wheel, `make` absence) blocked verification; each has a direct command-line equivalent that was run and confirmed.

## User Setup Required
None beyond the plan's own documented `lefthook install` / `make hooks` step (already run in this session; future clones on a host with `make` can use either).

## Next Phase Readiness
- The local hook stack is live: every subsequent commit in this repo runs `ruff format --check`, `ruff check`, and the file-size cap; every push runs compile smoke, the fast pytest subset, and `docker compose config --quiet`.
- `pyproject.toml`'s `slow`/`integration`/`gpu` markers and `[tool.coverage.run] omit` are in place for plan 08 (no-skip-as-green conftest guard) and plan 09 (coverage floor) to build on directly — no further pyproject.toml edits should be needed from those plans per this plan's "single owner of pyproject.toml for the infra waves" scope.
- Full gate confirmed green: `pytest -q` → 362 passed; `ruff check src tests scripts` → clean; `bash scripts/check-file-size.sh` → 0 violations; `docker compose config --quiet` → valid.

---
*Phase: 01-ci-git-hook-discipline*
*Completed: 2026-07-12*

## Self-Check: PASSED

All claimed files found (scripts/check-file-size.sh, lefthook.yml, scripts/run-python.sh,
scripts/run-fast-tests.sh, pyproject.toml, Makefile, CLAUDE.md, this SUMMARY.md) and all
claimed commit hashes (f58f480, 3cf333c, 4c71b34) verified present in `git log --oneline --all`.
