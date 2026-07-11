---
phase: 01-ci-git-hook-discipline
plan: 05
subsystem: testing
tags: [pytest, ruff, file-size-cap, gliner_provider, batch_memory, test-decomposition]

# Dependency graph
requires:
  - phase: 01-ci-git-hook-discipline
    provides: split gliner_provider.py (extraction vs HTTP-plumbing siblings) and the store.py mixin decomposition that the batch_memory tests exercise
provides:
  - "tests/test_gliner_provider.py split into 3 concern-named files (core provider contract + main/signal lifecycle, HTTP plumbing, FastGLiNER2Adapter extraction), all <=600 LOC"
  - "tests/test_batch_memory.py split into 3 scenario-named files (tenant index + rebuild/projection, basic write/document ingestion/chunking, temporal-graph dedup/sparse/delete), all <=600 LOC"
  - "tests/_gliner_provider_shared.py and tests/_batch_memory_shared.py: leading-underscore shared test-support modules (not pytest-collected) holding payload builders and recording fixtures reused across each split's sibling files"
affects: [ci-git-hook-discipline (later plans validating the full 600-LOC no-allowlist cap and running scripts/check-file-size.sh)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Flat test_<concern>.py / test_<scenario>.py sibling split for over-cap test files, matching the existing tests/ naming convention (e.g. tests/test_admin_repair.py)"
    - "Leading-underscore shared test-support module (tests/_<name>_shared.py) for fixtures/payload-builders reused across split siblings — not collected by pytest (no test_ prefix), avoids duplicating divergent copies"

key-files:
  created:
    - tests/_gliner_provider_shared.py
    - tests/test_gliner_provider_http.py
    - tests/test_gliner_provider_extraction.py
    - tests/_batch_memory_shared.py
    - tests/test_batch_memory_write.py
    - tests/test_batch_memory_dedup.py
  modified:
    - tests/test_gliner_provider.py
    - tests/test_batch_memory.py

key-decisions:
  - "gliner_provider split: original file keeps provider extract/memory contract tests plus main()/signal lifecycle tests (10 tests); test_gliner_provider_http.py holds the HTTP-server plumbing tests (9 tests); test_gliner_provider_extraction.py holds the FastGLiNER2Adapter tests (6 tests) — 25 total, matching the pre-split function count"
  - "batch_memory split: original file keeps tenant-index-naming plus sparse/vector rebuild-projection tests (4 tests); test_batch_memory_write.py holds basic batch write/replay/conflicting-id/document-ingestion/chunking/write_many tests (8 tests); test_batch_memory_dedup.py holds temporal-graph projection, entity dedup, extraction-failure, sparse-index, and delete tests (11 tests) — 23 total, matching the pre-split function count"
  - "Shared helpers (extract_payload/memory_payload/memory_result for gliner_provider; CountingBatchEmbedder/RecordingMemoryStore/RecordingDocumentStore/RecordingMemoryExtractor for batch_memory) moved verbatim into new leading-underscore modules rather than duplicated across split siblings, per the plan's shared-fixture instruction"

requirements-completed: [CI-01]

coverage:
  - id: D1
    description: "tests/test_gliner_provider.py (1076 LOC) decomposed into 3 concern-named files, each <=600 LOC, with every test moved verbatim"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "python -m pytest -q tests/test_gliner_provider.py tests/test_gliner_provider_http.py tests/test_gliner_provider_extraction.py"
        status: pass
      - kind: other
        ref: "wc -l on each tracked tests/test_gliner_provider*.py file (max 384 LOC)"
        status: pass
    human_judgment: false
  - id: D2
    description: "tests/test_batch_memory.py (749 LOC) decomposed into 3 scenario-named files, each <=600 LOC, with every test moved verbatim"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "python -m pytest -q tests/test_batch_memory.py tests/test_batch_memory_write.py tests/test_batch_memory_dedup.py"
        status: pass
      - kind: other
        ref: "wc -l on each tracked tests/test_batch_memory*.py file (max 328 LOC)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Full suite stays at the green baseline (362 collected, 362 passed) after both splits, no test lost/duplicated/renamed-away"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "python -m pytest --co -q (362 tests collected) and python -m pytest -q (362 passed)"
        status: pass
    human_judgment: false

# Metrics
duration: 30min
completed: 2026-07-11
status: complete
---

# Phase 1 Plan 5: Decompose test_gliner_provider.py and test_batch_memory.py Summary

**Split the last two over-cap test files (1076 and 749 LOC) into six ≤600-LOC concern/scenario-named siblings plus two leading-underscore shared-fixture modules, with the identical 362-test collected/passing count preserved.**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-07-11
- **Tasks:** 2
- **Files modified:** 8 (2 slimmed originals + 4 new sibling test files + 2 new shared-fixture modules)

## Accomplishments
- `tests/test_gliner_provider.py` (1076 LOC) split into 3 files: the original (provider extract/memory contract + `main()`/signal lifecycle, 384 LOC), `test_gliner_provider_http.py` (HTTP-server plumbing, 370 LOC), and `test_gliner_provider_extraction.py` (FastGLiNER2Adapter extraction tests, 304 LOC)
- `tests/test_batch_memory.py` (749 LOC) split into 3 files: the original (tenant vector index naming + sparse/vector rebuild projection, 146 LOC), `test_batch_memory_write.py` (basic batch write/replay/conflicting-id/document-ingestion/chunking, 183 LOC), and `test_batch_memory_dedup.py` (temporal-graph projection, entity dedup, sparse-index, delete, 328 LOC)
- Shared payload builders (`extract_payload`, `memory_payload`, `memory_result`) and recording fixtures (`CountingBatchEmbedder`, `RecordingMemoryStore`, `RecordingDocumentStore`, `RecordingMemoryExtractor`) extracted verbatim into new `tests/_gliner_provider_shared.py` and `tests/_batch_memory_shared.py` modules (leading-underscore naming keeps them out of pytest collection while remaining importable by sibling test files)
- Full suite unchanged: `python -m pytest --co -q` still collects exactly 362 tests, `python -m pytest -q` reports 362 passed
- `python -m ruff check src tests scripts` clean (import ordering auto-fixed by `ruff check --fix` to merge the new local `_shared` imports into the existing third-party import block)

## Task Commits

Each task was committed atomically:

1. **Task 1: Split tests/test_gliner_provider.py by concern** - `b168547` (test)
2. **Task 2: Split tests/test_batch_memory.py by scenario** - `acea42f` (test)

_Note: no separate plan-metadata commit hash yet — this SUMMARY/STATE/ROADMAP update is committed after this file is written._

## Files Created/Modified
- `tests/_gliner_provider_shared.py` - `extract_payload`/`memory_payload`/`memory_result` builders shared by the 3 gliner_provider test files
- `tests/test_gliner_provider.py` - slimmed to provider extract/memory contract tests + `main()`/signal-handler lifecycle tests (10 test functions)
- `tests/test_gliner_provider_http.py` - HTTP-server plumbing tests (running_server harness, raw-request framing, saturation/worker-cap, error-logging privacy) (9 test functions)
- `tests/test_gliner_provider_extraction.py` - `FastGLiNER2Adapter` entity/relation/classification extraction tests (6 test functions)
- `tests/_batch_memory_shared.py` - `CountingBatchEmbedder`/`RecordingMemoryStore`/`RecordingDocumentStore`/`RecordingMemoryExtractor` shared by the 3 batch_memory test files
- `tests/test_batch_memory.py` - slimmed to tenant vector index naming + sparse/vector rebuild-projection tests (4 test functions)
- `tests/test_batch_memory_write.py` - basic batch write/replay-safety/conflicting-id, document ingestion, `_write_many`, chunking tests (8 test functions)
- `tests/test_batch_memory_dedup.py` - temporal-graph projection, entity dedup, extraction-failure, sparse-index, delete tests (11 test functions)

## Decisions Made
- Grouped `test_gliner_provider.py`'s `main()`/signal-handler lifecycle tests with the core provider-contract tests (both exercise `GLiNERProvider`/`gliner_provider` module state directly, not over HTTP) rather than creating a fourth file — kept the original file well under cap (384 LOC) while avoiding an unnecessary fourth split.
- Named the batch_memory siblings `test_batch_memory_write.py` and `test_batch_memory_dedup.py` per the plan's literal `<verify>` command, and kept the tenant-index/rebuild-projection tests in the original `test_batch_memory.py` rather than inventing a fourth scenario file.
- Used leading-underscore module names (`tests/_gliner_provider_shared.py`, `tests/_batch_memory_shared.py`) for shared fixtures instead of a `conftest.py`, since neither module needs to be a pytest fixture/plugin (plain importable helpers) and no `tests/conftest.py` exists yet in this repo.

## Deviations from Plan

None - plan executed exactly as written. `ruff check --fix` auto-corrected import ordering (merging the new local `_gliner_provider_shared`/`_batch_memory_shared` imports into the existing third-party import block) — this is tooling-applied formatting, not a code/logic deviation, and is captured in the same task commits.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Both previously over-cap test files are now decomposed; combined with the earlier source-module splits (server.py, document_jobs.py, gliner_provider.py, store.py mixins, benchmark.py, e2e_score.py, eval_backboard_locomo_mcp.py, real_document_benchmark.py), CI-01's no-allowlist 600-LOC cap should hold repo-wide.
- Docker E2E (`scripts/e2e_score.py`) intentionally NOT run per this plan's environment constraints (no turingdb install in this environment) — deferred to the orchestrator's post-wave Docker E2E run. Test-file splits carry no runtime-behavior risk (no source module changed), so E2E risk here is minimal.
- Remaining phase work (lefthook.yml, CI workflow, conftest.py no-skip-as-green guard, check-file-size.sh) is independent of this plan and can proceed.

---
*Phase: 01-ci-git-hook-discipline*
*Completed: 2026-07-11*

## Self-Check: PASSED

All created/modified files found on disk; both task commits (`b168547`, `acea42f`) found in git log. `python -m pytest --co -q` collects 362 tests; `python -m pytest -q` reports 362 passed; `python -m ruff check src tests scripts` clean; all tracked `tests/test_gliner_provider*.py` and `tests/test_batch_memory*.py` files ≤600 LOC (max 384).
