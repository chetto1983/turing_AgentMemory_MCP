---
phase: 03-turingdb-retrieval-baseline
plan: 01
subsystem: testing
tags: [tdd, benchmark, retrieval, real-document-benchmark, json-loader]

# Dependency graph
requires: []
provides:
  - "load_frozen_questions(path) -> dict[str, list[dict[str, str]]] in scripts/real_document_benchmark_scoring.py"
  - "resolve_questions(frozen, filename, *, generate) -> tuple[list, dict] in scripts/real_document_benchmark_scoring.py"
  - "--frozen-questions CLI flag + additive call-site branch in scripts/real_document_benchmark.py"
affects: [03-turingdb-retrieval-baseline, ARC-09-migration-correctness-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Zero-arg generate closure with default-parameter loop-variable capture (avoids ruff B023) passed into resolve_questions"

key-files:
  created: []
  modified:
    - scripts/real_document_benchmark_scoring.py
    - scripts/real_document_benchmark.py
    - tests/test_real_document_benchmark.py

key-decisions:
  - "Wrapped the entire per-file generate closure (select_passages + generator.generate) in a single asyncio.to_thread(resolve_questions, ...) call, per the plan's designed minimal-diff shape, rather than keeping select_passages on the main thread as before -- both are pure/fast so behavior is unchanged for the non-frozen path"
  - "Used a nested def with default-parameter capture (_path=path, _converted=converted) instead of a lambda to satisfy ruff's B023 loop-closure rule while keeping the diff to real_document_benchmark.py minimal (587/600 LOC)"

patterns-established:
  - "Validate-and-raise-ValueError convention (mirrors parse_generated_questions/select_passages) applied verbatim to load_frozen_questions"

requirements-completed: [ARC-01]

coverage:
  - id: D1
    description: "load_frozen_questions parses a valid frozen-questions file into a questions_by_document mapping"
    requirement: "ARC-01"
    verification:
      - kind: unit
        ref: "tests/test_real_document_benchmark.py#test_load_frozen_questions_round_trips"
        status: pass
    human_judgment: false
  - id: D2
    description: "load_frozen_questions raises ValueError on malformed/empty/wrong-shape frozen files (fails loud, never silent)"
    requirement: "ARC-01"
    verification:
      - kind: unit
        ref: "tests/test_real_document_benchmark.py#test_load_frozen_questions_rejects_malformed"
        status: pass
    human_judgment: false
  - id: D3
    description: "resolve_questions returns frozen questions without invoking generate() when a frozen set is loaded; falls back to generate() when frozen is None"
    requirement: "ARC-01"
    verification:
      - kind: unit
        ref: "tests/test_real_document_benchmark.py#test_resolve_questions_skips_generation_when_frozen"
        status: pass
    human_judgment: false
  - id: D4
    description: "real_document_benchmark.py accepts --frozen-questions and every tracked *.py stays at or under 600 LOC"
    requirement: "ARC-01"
    verification:
      - kind: unit
        ref: "bash scripts/check-file-size.sh"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-07-13
status: complete
---

# Phase 3 Plan 01: Frozen-Questions Loader (D-08) Summary

**Added `load_frozen_questions` + `resolve_questions` to `real_document_benchmark_scoring.py` via strict RED-GREEN TDD, wired an additive `--frozen-questions` CLI flag into `real_document_benchmark.py` so Phase 6 can replay this phase's exact generated questions without regenerating them.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-13T11:55:00Z (approx.)
- **Completed:** 2026-07-13T12:19:21Z
- **Tasks:** 2 (RED, GREEN)
- **Files modified:** 3

## Accomplishments
- `load_frozen_questions(path)` loads and schema-validates a frozen-questions JSON file, raising a descriptive `ValueError` on any missing key, empty mapping, or wrong-shape row (fails loud, never silent — the T-03-01 tampering mitigation).
- `resolve_questions(frozen, filename, *, generate)` returns the frozen rows for `filename` (with a `{"frozen": True, ...}` usage marker) without ever invoking `generate` when a frozen set is loaded; falls back to `generate()` unmodified when `frozen is None`.
- `real_document_benchmark.py` gained an additive `--frozen-questions` flag; the per-file loop now calls `resolve_questions(frozen, path.name, generate=...)` instead of unconditionally calling `select_passages` + `generator.generate`, so passage selection and the LLM call are deferred inside the closure and never run in frozen mode.
- Non-frozen (baseline) generation/scoring path is behaviorally unchanged — `generate()` still performs the identical `select_passages` + `generator.generate` sequence when no frozen set is supplied.

## Task Commits

Each task was committed atomically per the TDD RED/GREEN gate sequence:

1. **Task 1 (RED): Failing tests + interface stubs** - `9faa981` (test)
2. **Task 2 (GREEN): Implement load_frozen_questions + resolve_questions** - `9bd1551` (feat)

**Plan metadata:** (this commit, to follow)

## Files Created/Modified
- `scripts/real_document_benchmark_scoring.py` - Added `load_frozen_questions` + `resolve_questions` (schema validation, frozen/generate branch) and a `Callable` import.
- `scripts/real_document_benchmark.py` - Re-exported the two new functions in both try/except import blocks, added `--frozen-questions` argparse flag, replaced the unconditional per-file passage-selection + generation block with a `resolve_questions` call wrapping a deferred `generate` closure.
- `tests/test_real_document_benchmark.py` - Added `test_load_frozen_questions_round_trips`, `test_load_frozen_questions_rejects_malformed`, `test_resolve_questions_skips_generation_when_frozen`.

## Decisions Made
- Matched the plan's exact designed function bodies (from `03-PATTERNS.md`) for `load_frozen_questions` rather than inventing alternate validation logic.
- Used a nested `def generate(_path=path, _converted=converted)` closure (default-parameter capture) instead of a `lambda`, both to satisfy ruff's `B023` loop-variable-capture rule and to keep the call-site diff net-neutral on LOC (587/600 vs the 582/600 starting point, well under the no-allowlist 600-LOC cap).

## Deviations from Plan

None - plan executed exactly as written. The plan's `<action>` steps for both tasks were followed verbatim (stub interfaces + failing tests in Task 1; minimal fill-in bodies + green run + LOC/ruff checks in Task 2).

## Issues Encountered

None. `.venv` is not present in this checkout (system `python 3.13.3` on PATH was used per CLAUDE.md's Windows guidance, falling back from the documented `.venv\Scripts\python` since no venv exists); all commands ran identically. No blockers.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `load_frozen_questions` + `resolve_questions` are ready for plans 03-02/03-03 to produce and consume `baseline/03-turingdb/frozen-questions.json`.
- Full repo gate confirmed green after this plan: `python -m pytest -q` → 375 passed, 1 skipped; `python -m ruff check src tests scripts` → clean; `bash scripts/check-file-size.sh` → no file over 600 LOC; `docker compose config --quiet` → valid.
- No blockers for Phase 3's remaining plans (baseline capture, artifact commit).

---
*Phase: 03-turingdb-retrieval-baseline*
*Completed: 2026-07-13*

## Self-Check: PASSED

All created/modified files and both task commits (9faa981, 9bd1551) verified present on disk / in git log.
