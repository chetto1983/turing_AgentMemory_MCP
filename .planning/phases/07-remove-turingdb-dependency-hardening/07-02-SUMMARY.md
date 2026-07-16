---
phase: 07-remove-turingdb-dependency-hardening
plan: 02
subsystem: infra
tags: [turingdb, arcadedb, e2e-harness, pyproject, dependency-removal]

# Dependency graph
requires:
  - phase: 07-remove-turingdb-dependency-hardening
    provides: 07-01 deleted the legacy TuringDB benchmark/eval harness cluster and admin_repair.py, pruning their cli.py subcommands
provides:
  - Zero live `import turingdb` / `from turingdb` sites remaining in src/
  - e2e_score.py / e2e_score_stubs.py stripped of dead TuringDaemon/wait_rest and the turingdb_version field
  - store.py / store_core.py / store_documents.py / store_rebuild.py docstrings and comments reworded to describe ArcadeDB by concept
  - pyproject.toml free of the turingdb dependency, keyword, and TuringDB-worded description
affects: [07-03, 07-04, 07-05]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - src/turing_agentmemory_mcp/e2e_score.py
    - src/turing_agentmemory_mcp/e2e_score_stubs.py
    - src/turing_agentmemory_mcp/store.py
    - src/turing_agentmemory_mcp/store_core.py
    - src/turing_agentmemory_mcp/store_documents.py
    - src/turing_agentmemory_mcp/store_rebuild.py
    - pyproject.toml

key-decisions:
  - "Removed TuringDaemon and wait_rest from e2e_score.py's re-export list too (not just e2e_score_stubs.py's definitions) since they would otherwise raise ImportError once e2e_score_stubs.py no longer defines them -- Rule 3 blocking-issue fix within task scope, matched by the plan's own acceptance grep spanning both files."
  - "Reworded e2e_score.py's and e2e_score_stubs.py's module docstrings to drop references to the already-deleted legacy benchmark.py/agent_quality_eval.py harnesses (removed in 07-01), since those docstring sentences were now dangling references to nonexistent files."

requirements-completed: [ARC-10]

coverage:
  - id: D1
    description: "e2e_score.py and e2e_score_stubs.py import cleanly with no turingdb references; dead TuringDaemon class and wait_rest() helper removed; live stub servers (LocalEmbedServer, LocalRerankServer, free_port, ArcadeE2EBackend, ARCADEDB_E2E_IMAGE) preserved unchanged"
    requirement: ARC-10
    verification:
      - kind: other
        ref: "grep -nE \"import turingdb|from turingdb|turingdb_version|TuringDaemon|wait_rest\" src/turing_agentmemory_mcp/e2e_score.py src/turing_agentmemory_mcp/e2e_score_stubs.py (0 matches)"
        status: pass
      - kind: unit
        ref: "python -c \"import turing_agentmemory_mcp.e2e_score, turing_agentmemory_mcp.e2e_score_stubs\""
        status: pass
      - kind: other
        ref: "python -m ruff check src/turing_agentmemory_mcp/e2e_score.py src/turing_agentmemory_mcp/e2e_score_stubs.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "store.py / store_core.py / store_documents.py / store_rebuild.py carry no TuringDB-worded docstrings or comments; store.py's module docstring reads ArcadeDB-backed; existing store_core grep-gate test stays green"
    requirement: ARC-10
    verification:
      - kind: other
        ref: "grep -riE turingdb src/turing_agentmemory_mcp/store.py src/turing_agentmemory_mcp/store_core.py src/turing_agentmemory_mcp/store_documents.py src/turing_agentmemory_mcp/store_rebuild.py (0 matches)"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py (17 passed)"
        status: pass
    human_judgment: false
  - id: D3
    description: "turingdb==1.35 removed from pyproject.toml dependencies, turingdb keyword removed, description reworded to name ArcadeDB; fastmcp and graspologic-native pins untouched"
    requirement: ARC-10
    verification:
      - kind: other
        ref: "python -c \"import tomllib; ...\" (asserts no turingdb dependency/keyword, ArcadeDB in description)"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-07-16
status: complete
---

# Phase 07 Plan 02: Strip Last Live turingdb Imports from E2E Harness + Store Prose Summary

**Removed the last live `import turingdb`/`from turingdb` sites from `src/` (dead `TuringDaemon`/`wait_rest`/`turingdb_version` in the E2E harness), scrubbed stale TuringDB-worded comments from four already-ported store modules, and dropped the `turingdb==1.35` dependency/keyword/description from `pyproject.toml`.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-07-16T19:06:41Z
- **Completed:** 2026-07-16T19:12:21Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments
- `src/` now has zero live `import turingdb` / `from turingdb` sites — the strict precondition Plan 04 needs to safely delete the 31-file test stub without masking a `ModuleNotFoundError`
- `e2e_score.py` / `e2e_score_stubs.py` E2E harness retains only its live ArcadeDB-backed surface (`LocalEmbedServer`, `LocalRerankServer`, `free_port`, `ArcadeE2EBackend`, `ARCADEDB_E2E_IMAGE`); the `run_e2e()` score/check_count/verdict contract is byte-identical
- `store.py`'s public module docstring now reads "Canonical ArcadeDB-backed memory/document store" instead of TuringDB-backed
- `pyproject.toml` declares no `turingdb` dependency, no `turingdb` keyword, and an ArcadeDB-worded description

## Task Commits

Each task was committed atomically:

1. **Task 1: Prune vestigial turingdb imports + dead TuringDaemon from the E2E harness** - `1b9f04b` (fix)
2. **Task 2: Scrub stale TuringDB comments/docstrings from the ported store modules** - `27657c2` (docs)
3. **Task 3: Remove turingdb from pyproject.toml (dependency, keyword, description)** - `d80d381` (chore)

**Plan metadata:** pending (docs: complete plan)

## Files Created/Modified
- `src/turing_agentmemory_mcp/e2e_score.py` - dropped `turingdb_version` import/field; module docstring no longer references deleted legacy harnesses; import list no longer re-exports `TuringDaemon`/`wait_rest`
- `src/turing_agentmemory_mcp/e2e_score_stubs.py` - deleted `TuringDaemon` class, `wait_rest()` helper, and the `from turingdb import TuringDB` import; module docstring and `ArcadeE2EBackend` docstring reworded to drop the retired-daemon contrast
- `src/turing_agentmemory_mcp/store.py` - module docstring: "TuringDB-backed" → "ArcadeDB-backed"
- `src/turing_agentmemory_mcp/store_core.py` - module docstring and `reconnect()` docstring reworded to describe ArcadeDB's single managed transaction / reachability re-probe by concept, dropping the TuringDB contrast
- `src/turing_agentmemory_mcp/store_documents.py` - module docstring and an inline `_write_many` comment reworded to describe the single managed transaction, dropping "TuringDB-shaped byte-budget batch splitter" / "TuringDB's submit-before-match visibility gap" framing
- `src/turing_agentmemory_mcp/store_rebuild.py` - module docstring reworded to describe the D-07 versioned atomic swap on ArcadeDB's native `LSM_VECTOR`, dropping "retired TuringDB CSV" framing
- `pyproject.toml` - removed `"turingdb==1.35"` from dependencies, removed `"turingdb"` from keywords, reworded description to name ArcadeDB

## Decisions Made
- Removed `TuringDaemon`/`wait_rest` from `e2e_score.py`'s re-export import list, not just their definitions in `e2e_score_stubs.py` — leaving the import would raise `ImportError` at module load. This is within Task 1's scope: the plan's own acceptance grep (`grep -nE "...TuringDaemon|wait_rest" e2e_score.py e2e_score_stubs.py`) spans both files, confirming the plan author intended both sites cleaned.
- Updated both harness module docstrings to stop referencing `benchmark.py`/`agent_quality_eval.py` (both already deleted in 07-01) rather than leave dangling references to nonexistent files.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed TuringDaemon/wait_rest from e2e_score.py's import statement**
- **Found during:** Task 1 (Prune vestigial turingdb imports + dead TuringDaemon from the E2E harness)
- **Issue:** e2e_score.py imported `TuringDaemon` and `wait_rest` from `e2e_score_stubs` for re-export (`# noqa: F401 - preserved public import path`). Removing those names from `e2e_score_stubs.py` per the task action would leave a dangling import in e2e_score.py, breaking module import at load time.
- **Fix:** Removed `TuringDaemon` and `wait_rest` from the `from turing_agentmemory_mcp.e2e_score_stubs import (...)` block in e2e_score.py, and updated the module docstring's re-export description accordingly.
- **Files modified:** src/turing_agentmemory_mcp/e2e_score.py
- **Verification:** `python -c "import turing_agentmemory_mcp.e2e_score, turing_agentmemory_mcp.e2e_score_stubs"` exits 0; plan's own acceptance grep (spanning both files) returns 0 matches.
- **Committed in:** 1b9f04b (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary to keep the module importable after Task 1's own instructed deletions; no scope creep — the plan's acceptance criteria already covered both files.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `src/` is now fully free of live `turingdb` imports, satisfying the strict precondition for Plan 04 (deleting the 31-file test stub).
- `lab.py`'s `turingdb_version` field and TuringDB-labeled architecture diagram nodes remain (out of scope for this plan; already tracked by 07-04/07-06).
- Full gate green: `ruff format --check`, `ruff check`, `check-file-size.sh`, and `tests/test_store_arcadedb_core.py` all pass.

---
*Phase: 07-remove-turingdb-dependency-hardening*
*Completed: 2026-07-16*

## Self-Check: PASSED

All 8 files listed in this summary's key-files/frontmatter exist on disk, and all 3 task commit hashes (1b9f04b, 27657c2, d80d381) resolve in `git log --oneline --all`.
