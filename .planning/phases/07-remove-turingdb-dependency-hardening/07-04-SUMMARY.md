---
phase: 07-remove-turingdb-dependency-hardening
plan: 04
subsystem: testing
tags: [pytest, ruff, turingdb-removal, test-fixtures]

# Dependency graph
requires:
  - phase: 07-remove-turingdb-dependency-hardening
    provides: "Plans 07-01/07-02 removed every src-side `from turingdb import ...` (legacy harness cluster, e2e_score.py/e2e_score_stubs.py rewrites)"
provides:
  - "Zero `sys.modules[\"turingdb\"]` stubs anywhere in tests/ (removed from all 31 test/shared-fixture files that carried it)"
  - "Full test suite (861 tests) collects and runs green with turingdb neither installed nor stubbed"
  - "tests/conftest.py confirmed unchanged (never carried the stub)"
affects: [07-05, 07-06, 07-07, 07-08]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Windows-compat import stubs removed once the upstream import chain requiring them is gone, verified by re-running collection rather than trusted from the removal alone"]

key-files:
  created: []
  modified:
    - tests/_arcadedb_physical_isolation_support.py
    - tests/_store_arcadedb_core_shared.py
    - tests/_retrieval_arcadedb_shared.py
    - tests/_documents_arcadedb_shared.py
    - tests/_batch_memory_shared.py
    - tests/test_tenant_binding_enforcement.py
    - tests/test_tenant_telemetry_pseudonymity.py
    - tests/test_document_file_pipe.py
    - tests/test_document_ingest_file.py
    - tests/test_store_entity_processing.py
    - tests/test_store_arcadedb_retrieval.py
    - tests/test_store_arcadedb_rebuild.py
    - tests/test_store_arcadedb_memory.py
    - tests/test_store_arcadedb_documents.py
    - tests/test_runtime_pipeline.py
    - tests/test_stable_id_survives_rebuild.py
    - tests/test_retrieval_filters.py
    - tests/test_observability.py
    - tests/test_fused_memory_search.py
    - tests/test_community_detection.py
    - tests/test_batch_memory_write.py
    - tests/test_batch_memory_dedup.py
    - tests/test_batch_memory.py
    - tests/test_arcadedb_tenant_isolation.py
    - tests/test_utcp_conformance.py
    - tests/test_rerank.py
    - tests/test_backboard_locomo_runner.py
    - tests/test_utcp_manual.py
    - tests/test_server_batch_tool.py
    - tests/test_auth.py
    - tests/test_governance.py
    - tests/test_gliner_provider_extraction.py
    - tests/test_entity_extraction_http.py
    - tests/test_entity_extraction.py

key-decisions:
  - "Left test_gate_diff.py, test_lab.py, test_tenant_server_routing.py, and test_store_arcadedb_core.py untouched: their remaining turingdb/TuringDB mentions are either accurate historical facts (baseline/03-turingdb/ directory, phase-4 port docstrings), live functional data still required by out-of-plan src code (lab.py's REQUIRED_BENCHMARK_FIELDS), or live env vars owned by a later plan (TURINGDB_HOME, renamed in 07-06/07-07) — rewriting any of them here would either misrepresent history or break the test against still-unchanged src code."
  - "Fixed a dangling comment in test_utcp_conformance.py (Rule 1, discovered on touch): it described the just-removed sys.modules stub as 'This shim' and claimed store.py still transitively imports turingdb, which stopped being true once Plans 07-01/07-02 landed."

patterns-established: []

requirements-completed: []  # ARC-10 spans all 8 plans of this phase; marked complete only at phase close (07-08)

coverage:
  - id: D1
    description: "All 31 sys.modules[\"turingdb\"] stub blocks removed from the test tree; tests/conftest.py confirmed unchanged; full suite (861 tests) collects and runs green with turingdb neither installed nor stubbed."
    requirement: "ARC-10"
    verification:
      - kind: unit
        ref: "python -m pytest tests/ --collect-only -q (861 collected, 0 errors)"
        status: pass
      - kind: unit
        ref: "python -m pytest tests/ -m \"not integration and not gpu\" -q (851 passed, 1 pre-existing unrelated skip)"
        status: pass
      - kind: unit
        ref: "grep -rl 'sys.modules\\[.turingdb' tests/ (0 files)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Residual comment/docstring turingdb prose swept in the entity/gliner fixture test files; test_store_arcadedb_core.py's grep-gate literal preserved."
    requirement: "ARC-10"
    verification:
      - kind: unit
        ref: "python -m pytest tests/test_store_arcadedb_core.py tests/test_lab.py -q (19 passed)"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-07-16
status: complete
---

# Phase 07 Plan 04: Remove the 31-file turingdb test stub Summary

**Removed the `sys.modules["turingdb"]` Windows import-compat stub from all 31 test/shared-fixture files, confirmed the 861-test suite collects and passes with turingdb neither installed nor stubbed, and swept residual "TuringDB"-as-sample-text fixture strings in three entity-extraction test files.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-16
- **Tasks:** 2
- **Files modified:** 33 (31 stub removals + 3 prose-sweep files, with 1 file — test_utcp_conformance.py — touched by both tasks)

## Accomplishments
- Deleted the exact 2-line `if "turingdb" not in sys.modules: sys.modules["turingdb"] = ...` block from all 31 files identified in 07-RESEARCH.md's exact-pattern grep, matching the plan's `files_modified` list 1:1 (verified via `diff` against the expected file list — zero scope creep).
- Removed now-unused `sys`/`types` imports left behind by the stub removal (ruff F401 auto-fix, 60 fixes across the 31 files), then re-ran `ruff format`/`ruff check --fix` (import-sort) to clean up the resulting blank-line/import-grouping artifacts.
- Confirmed `tests/conftest.py` untouched (`git diff` empty) — it never carried the stub, only the no-skip-as-green hookwrapper guard.
- Full suite collects clean: 861 tests collected, 0 `ModuleNotFoundError: turingdb`, proving Plans 07-01/07-02 fully cleared every src-side `from turingdb import ...` call site before this plan ran (satisfying the plan's hard sequencing precondition).
- Full suite runs green: 851 passed, 1 pre-existing unrelated skip (`utcp` package not installed on Windows), 10 deselected (integration/gpu).
- Swept "TuringDB" used as literal sample-entity fixture text (not backend-concept prose) in `test_gliner_provider_extraction.py`, `test_entity_extraction_http.py`, `test_entity_extraction.py` — replaced with "ArcadeDB" (identical 8-character length, so all `start`/`end` offset assertions stayed correct without any other edits). All 25 tests across the three files still pass.
- Fixed a dangling explanatory comment in `test_utcp_conformance.py` that Task 1's own stub removal orphaned (it referred to "This shim" — the now-deleted stub — and claimed `store.py` still transitively imports turingdb, which stopped being true after Plans 07-01/07-02).

## Task Commits

Each task was committed atomically:

1. **Task 1: Delete the sys.modules[turingdb] stub from all 31 files** - `e137e0f` (test)
2. **Task 2: Sweep the residual comment-only turingdb mentions in the test tree** - `c5fda7e` (test)

_Note: no plan-metadata commit is separate — the docs/state commit below covers it._

## Files Created/Modified
- 30 of the 31 stub-removal files listed in `key-files.modified` above - stub block + now-unused `sys`/`types` imports removed
- `tests/test_gliner_provider_extraction.py`, `tests/test_entity_extraction_http.py`, `tests/test_entity_extraction.py` - "TuringDB" sample-entity fixture text swept to "ArcadeDB"
- `tests/test_utcp_conformance.py` - both the stub removal (Task 1) and a stale-comment fix (Task 2, Rule 1)

## Decisions Made
- **Scope boundary held to the plan's explicit `<files>` tags, not a blanket tree-wide sweep.** `test_gate_diff.py`'s `TURINGDB_E2E`/`REAL_DOCUMENT_BENCHMARK` constants reference the real, immutable `baseline/03-turingdb/` directory on disk (Phase-3 baseline capture) — renaming these would break the path, not just the prose, and the paired test names (`test_is_stub_provider_true_for_arcadedb_stub_capture` / `test_is_stub_provider_false_for_turingdb_real_sidecar_capture`) are historically accurate, not stale. Left unchanged.
- `test_lab.py`'s `"turingdb_version": "test"` fixture key is still required by `src/turing_agentmemory_mcp/lab.py`'s live `REQUIRED_BENCHMARK_FIELDS` tuple — that src-side rename is Plan 07-06's scope (confirmed via `grep -l lab.py .planning/.../07-0[5-8]-PLAN.md`). Changing the test fixture here without the src rename would break `test_lab.py`. Left unchanged.
- `test_tenant_server_routing.py`'s `monkeypatch.setenv("TURINGDB_HOME", ...)` is a still-live env var read by `server.py`/`document_job_manager.py`; its rename to `BERTONI_HOME` is Plan 07-06/07-07's scope (confirmed the same way). Left unchanged.
- `test_store_arcadedb_core.py` and the "NN-XX: ported from TuringDB to ArcadeDB" docstrings/comments across several of the 31 stub-removal files (`test_store_arcadedb_documents/memory/rebuild/retrieval.py`, `test_batch_memory.py`, `test_runtime_pipeline.py`, `test_store_entity_processing.py`) are accurate historical records of the Phase-4 port and explicitly outside this task's declared `<files>` scope — rewriting them would misrepresent what actually happened (genuinely TuringDB-shaped behavior that was retired) for no functional gain. Left unchanged; not counted as stale prose.
- `test_docker_hardening.py` was confirmed turingdb-prose-free by direct grep (per the plan's own notes, already reconciled by commit `837d178`); treated as verify-only, no edit made.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed a dangling comment orphaned by Task 1's own stub removal**
- **Found during:** Task 2 (residual prose sweep)
- **Issue:** `tests/test_utcp_conformance.py`'s comment block (originally sitting right after the now-deleted stub) said "turingdb has no Windows wheel; utcp.py transitively imports store.py -> turingdb. This shim mirrors..." — "This shim" referred to the stub Task 1 had just deleted from this exact file, and the claim that `store.py` transitively imports `turingdb` is no longer true post-Plans 07-01/07-02.
- **Fix:** Reworded the comment to describe the actual current purpose of the two `importorskip` calls (optional spike deps `utcp`/`utcp_text`, unrelated to turingdb) without any dangling reference.
- **Files modified:** `tests/test_utcp_conformance.py`
- **Verification:** `python -m pytest tests/test_utcp_conformance.py -q` (1 skipped, same as before the edit — utcp not installed on this Windows machine, unrelated to the fix); ruff format/check clean.
- **Committed in:** `c5fda7e` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - dangling comment)
**Impact on plan:** Necessary correctness fix for a comment my own Task 1 edit orphaned; no scope creep beyond the file already being touched in this plan.

## Issues Encountered
- Stub removal via regex left a double-blank-line artifact and unused `sys`/`types` imports in all 31 files. Resolved with `ruff check --select F401 --fix` (60 fixes) + a targeted blank-line collapse + `ruff check --fix`/`ruff format` to re-run isort-style import grouping. Final state is ruff format/check clean across `tests/`.
- Confirmed via `diff` that the 31 changed files in `git status` exactly match the plan's `files_modified` list (Task 1) and the 4 changed files in Task 2 (`test_entity_extraction.py`, `test_entity_extraction_http.py`, `test_gliner_provider_extraction.py`, `test_utcp_conformance.py`) are all deliberate, in-scope edits — no accidental scope creep into unrelated files.
- The plan's Task 2 acceptance criteria implies a fully-clean `grep -rnE "TuringDB|turingdb" tests/` (modulo the one grep-gate literal). This is not achievable within Task 2's own declared 7-file `<files>` scope, because many remaining mentions live in files outside that scope (see Decisions Made above) and are either historically accurate or functionally still required by out-of-plan src code. Documented explicitly rather than silently expanding scope or silently leaving the criterion unmet without explanation.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The test tree is now fully turingdb-stub-free; Plan 07-05's planned "no-import-turingdb" src-wide grep-gate test can be authored without any test-collection interference from a stale stub.
- `TURINGDB_HOME`/`TURINGDB_GRAPH` env var renames (Plans 07-06/07-07) and `lab.py`'s `turingdb_version` field rename (Plan 07-06) remain open work; this plan intentionally left their corresponding test-side references untouched pending those plans.

---
*Phase: 07-remove-turingdb-dependency-hardening*
*Completed: 2026-07-16*

## Self-Check: PASSED

All claimed files verified present on disk; both task commits (`e137e0f`, `c5fda7e`) verified present in git history.
