---
phase: 01-ci-git-hook-discipline
plan: 03
subsystem: infra
tags: [refactor, file-size-cap, e2e-gate, benchmark, ci]

# Dependency graph
requires: []
provides:
  - "e2e_score.py decomposed into e2e_score.py (facade) + e2e_score_stubs.py + e2e_score_scenarios.py, all <=600 LOC"
  - "benchmark.py decomposed into benchmark.py (facade) + benchmark_schema.py + benchmark_stages.py + benchmark_memoryarena.py, all <=600 LOC"
  - "Preserved public import paths: turing_agentmemory_mcp.e2e_score.main/run_e2e, turing_agentmemory_mcp.benchmark.main/REQUIRED_FIELDS/make_result_row/_git_commit"
affects: [01-ci-git-hook-discipline other plans that turn on the file-size pre-commit hook]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Facade + concern siblings for oversized CLI/test-tooling modules (mirrors store.py mixin-composed-facade pattern from 01-01/01-02)"
    - "Schema-first split to break potential circular imports (benchmark_schema.py has zero dependents among its own siblings)"

key-files:
  created:
    - src/turing_agentmemory_mcp/e2e_score_stubs.py
    - src/turing_agentmemory_mcp/e2e_score_scenarios.py
    - src/turing_agentmemory_mcp/benchmark_schema.py
    - src/turing_agentmemory_mcp/benchmark_stages.py
    - src/turing_agentmemory_mcp/benchmark_memoryarena.py
  modified:
    - src/turing_agentmemory_mcp/e2e_score.py
    - src/turing_agentmemory_mcp/benchmark.py

key-decisions:
  - "_git_commit/_git_head_commit stay literally in benchmark.py (not moved) because tests/test_benchmark.py monkeypatches `benchmark.ROOT` directly; a sibling module's own `ROOT` global would not see that patch"
  - "benchmark_schema.py holds only dataclasses/constants (no dependents among its own siblings) so benchmark_stages.py and benchmark_memoryarena.py can both depend on it without a benchmark.py <-> sibling import cycle"
  - "e2e_score.py facade re-exports LocalEmbedServer/LocalRerankServer/TuringDaemon from e2e_score_stubs.py (noqa F401) because benchmark.py and potentially other future callers import them via the e2e_score module path, not the stubs module directly"

patterns-established:
  - "Facade module keeps only the entrypoint (main/CLI), any monkeypatch-sensitive module-level globals, and thin orchestration; concern siblings hold everything else"

requirements-completed: [CI-01]

coverage:
  - id: D1
    description: "e2e_score.py split into facade + stubs + scenarios siblings, all <=600 LOC, `main` import path preserved"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "py_compile src/turing_agentmemory_mcp/e2e_score.py src/turing_agentmemory_mcp/e2e_score_stubs.py src/turing_agentmemory_mcp/e2e_score_scenarios.py"
        status: pass
      - kind: unit
        ref: "python -m pytest -q (362 passed, unchanged baseline)"
        status: pass
    human_judgment: false
  - id: D2
    description: "benchmark.py split into facade + schema + stages + memoryarena siblings, all <=600 LOC, public helpers preserved"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "tests/test_benchmark.py (5 passed, includes monkeypatch of benchmark.ROOT and benchmark.subprocess)"
        status: pass
      - kind: unit
        ref: "python -c \"from turing_agentmemory_mcp.benchmark import main, REQUIRED_FIELDS, make_result_row, _git_commit\""
        status: pass
    human_judgment: false
  - id: D3
    description: "E2E score gate (scripts/e2e_score.py, VALIDATED_10_10) stays green after the split"
    requirement: "CI-01"
    verification: []
    human_judgment: true
    rationale: "turingdb has no Windows wheel; scripts/e2e_score.py cannot run/import on this host (ModuleNotFoundError: turingdb per the environment constraint). Verified structurally instead (main export present, py_compile clean); the real functional run is deferred to the orchestrator's Docker-based wave verification (docker compose run --rm e2e)."

# Metrics
duration: 35min
completed: 2026-07-11
status: complete
---

# Phase 01 Plan 03: Decompose benchmark.py and e2e_score.py Summary

**Split the two remaining over-cap `src/` tooling modules — `benchmark.py` (1044 LOC) and `e2e_score.py` (873 LOC) — into 5 new `<=600`-LOC concern siblings behind unchanged facades, preserving every public import path the E2E gate, CLI scripts, and test suite depend on.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 2
- **Files modified:** 2 (facades rewritten)
- **Files created:** 5 (concern siblings)

## Accomplishments

- `e2e_score.py` (873 LOC) → `e2e_score.py` facade (153 LOC) + `e2e_score_stubs.py` (208 LOC, stub embed/rerank HTTP servers + `TuringDaemon`) + `e2e_score_scenarios.py` (554 LOC, `payload`/`check` helpers + the full `run_mcp_checks` scenario runner)
- `benchmark.py` (1044 LOC) → `benchmark.py` facade (288 LOC) + `benchmark_schema.py` (117 LOC, dataclasses/`REQUIRED_FIELDS`/`make_result_row`) + `benchmark_stages.py` (453 LOC, synthetic-corpus pipeline stages + `_measure_batch`) + `benchmark_memoryarena.py` (263 LOC, MemoryArena-bucket loading/scoring stage)
- `from turing_agentmemory_mcp.e2e_score import main` (the E2E gate's entrypoint, consumed by `scripts/e2e_score.py`) preserved unchanged
- `from turing_agentmemory_mcp.benchmark import main, REQUIRED_FIELDS, make_result_row, _git_commit` (consumed by `scripts/benchmark.py`, `agent_quality_eval.py`, `tests/test_benchmark.py`) preserved unchanged
- Zero scoring/threshold/scenario-content changes — every moved function body is a verbatim cut-and-paste

## Task Commits

1. **Task 1: Split e2e_score.py (preserve `main` export)** - `7543ebc` (refactor)
2. **Task 2: Split benchmark.py (preserve public helpers)** - `c7ee4ed` (refactor)

## Files Created/Modified

- `src/turing_agentmemory_mcp/e2e_score_stubs.py` - `free_port`, `wait_rest`, `LocalEmbedServer`, `LocalRerankServer`, `TuringDaemon` (stub HTTP servers + local TuringDB daemon wrapper)
- `src/turing_agentmemory_mcp/e2e_score_scenarios.py` - `payload`, `check`, `run_mcp_checks` (the full async MCP scenario-check runner, 19 checks)
- `src/turing_agentmemory_mcp/e2e_score.py` - slim facade: `ROOT`, `run_e2e`, `main`; re-exports `LocalEmbedServer`/`LocalRerankServer`/`TuringDaemon`
- `src/turing_agentmemory_mcp/benchmark_schema.py` - `REQUIRED_FIELDS`, `MeasuredBatch`, `MemoryArenaCase`, `_percentile`, `make_result_row`, `turingdb_version` (try/except import)
- `src/turing_agentmemory_mcp/benchmark_stages.py` - `_measure_batch` + synthetic-corpus stages: `_benchmark_memory_store`, `_benchmark_memory_store_batch`, `_benchmark_memory_search`, `_benchmark_documents`, `_benchmark_rerank_comparison`, `_benchmark_restart`
- `src/turing_agentmemory_mcp/benchmark_memoryarena.py` - MemoryArena case loading/scoring helpers + `_benchmark_memoryarena` stage
- `src/turing_agentmemory_mcp/benchmark.py` - slim facade: `ROOT`, `run_benchmarks` (corpus runner), `default_output_path`, `main`, `_git_commit`, `_git_head_commit`; re-exports `REQUIRED_FIELDS`/`make_result_row` and the memoryarena config helpers

## Decisions Made

- **`_git_commit`/`_git_head_commit` stay in `benchmark.py`, not moved to a sibling.** `tests/test_benchmark.py::test_git_commit_can_come_from_git_head_without_git_binary` does `monkeypatch.setattr(benchmark, "ROOT", tmp_path)` and expects `_git_commit()`'s body to see the patched value. Patching a module attribute only affects code that reads the *same module's* global namespace — a sibling module doing `from turing_agentmemory_mcp.benchmark import ROOT` would bind its own copy at import time and the monkeypatch would silently stop working. Kept both functions and `ROOT` collocated to preserve this test's correctness (not a deviation — this is exactly what "preserve public import paths / no behavior change" requires).
- **`benchmark_schema.py` has zero dependents among its own new siblings**, specifically to avoid a `benchmark_stages.py` <-> `benchmark_memoryarena.py` <-> `benchmark.py` import cycle: `benchmark_memoryarena.py` imports `_measure_batch` from `benchmark_stages.py`, and both import shared dataclasses/`make_result_row` from `benchmark_schema.py`, which imports from neither.
- **`monkeypatch.setattr(benchmark.subprocess, "run", ...)` still works post-split** because `subprocess` is a singleton module object cached in `sys.modules` — any module that does `import subprocess` shares the exact same object, so patching `subprocess.run` via the `benchmark` module's reference patches it everywhere. Verified this holds by running `tests/test_benchmark.py` directly (all 5 tests pass).

## Deviations from Plan

None - plan executed exactly as written. The `<threat_model>` register's two threats (T-03-01: `e2e_score.main` export drop; T-03-02: benchmark public-helper import break) were both mitigated as specified: `main` re-verified present in the facade, and an import-smoke check (`from turing_agentmemory_mcp.benchmark import main, REQUIRED_FIELDS, make_result_row, _git_commit`) was run and passed.

## Issues Encountered

None. The split was mechanical (cut-and-paste of existing method/function bodies into new files, no call-site rewrites) per the plan's mixin/facade guidance carried over from the `store.py` decomposition pattern (01-01/01-02).

**E2E gate note:** `scripts/e2e_score.py` (the deterministic 10/10 E2E score gate) cannot be run or imported on this Windows host — `turingdb` has no Windows wheel, so `from turingdb import TuringDB` at the top of `e2e_score_stubs.py`/`e2e_score.py` fails with `ModuleNotFoundError: turingdb`, a known environment constraint (not a regression from this split). Verified structurally instead: `py_compile` of all three e2e_score files exits 0, and `def main` is confirmed present in the facade at the same import path `scripts/e2e_score.py` already uses. The real functional E2E run (VALIDATED_10_10, score >= 9.8) is **deferred to the orchestrator's Docker-based wave verification** (`docker compose run --rm e2e`).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Both `benchmark.py` and `e2e_score.py` are now under the 600-LOC cap, clearing the way for the file-size pre-commit hook (D-08) to be turned on without these two files blocking it.
- `python -m pytest -q` stays at 362 passed; `python -m ruff check src tests scripts` stays clean.
- Outstanding for other plans in this phase: the orchestrator must still run `docker compose run --rm e2e` to get the real functional VALIDATED_10_10 confirmation for this split (not runnable on this Windows host).

---
*Phase: 01-ci-git-hook-discipline*
*Completed: 2026-07-11*

## Self-Check: PASSED

All 5 created files verified present on disk; both task commits (`7543ebc`, `c7ee4ed`) verified present in `git log`.
