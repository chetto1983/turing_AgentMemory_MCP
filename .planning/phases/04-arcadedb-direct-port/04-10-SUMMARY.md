---
phase: 04-arcadedb-direct-port
plan: 10
subsystem: database
tags: [arcadedb, sqlite-fts5, sparse-index, lexical-retrieval, tdd]

# Dependency graph
requires:
  - phase: 04-arcadedb-direct-port
    provides: "04-07's read-side ARC-06 port (store_search.py/store_evidence.py already query only native ArcadeDB channels), 04-04's bootstrap change that stopped initializing the SQLite-FTS5 outbox schema"
provides:
  - "Write-side SQLite-FTS5 outbox fully retired from store_messages, update_memory, delete_memory, and rebuild_communities"
  - "store_rebuild_sparse.py mixin deleted; TuringAgentMemory's MRO no longer references it"
  - "A correctness-bug fix: unhandled SparseSchemaMismatch on a fresh deployment volume with AGENTMEMORY_FUSION_ENABLED=true"
  - "End-to-end proof (write-then-search) that lexical retrieval is unaffected by the outbox's removal"
affects: [phase-05-per-tenant-isolation, phase-07-turingdb-removal]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deliberately un-initialized SparseIndex as a test fixture to prove a code path never touches the legacy outbox (raises SparseSchemaMismatch on first touch if it does)"

key-files:
  created: []
  modified:
    - src/turing_agentmemory_mcp/store_memory_write.py
    - src/turing_agentmemory_mcp/store_memory_read.py
    - src/turing_agentmemory_mcp/store_rebuild.py
    - src/turing_agentmemory_mcp/store.py
    - tests/test_batch_memory_dedup.py
    - tests/test_batch_memory.py
    - tests/test_community_detection.py
    - tests/test_store_arcadedb_memory.py
    - tests/test_store_arcadedb_rebuild.py
    - tests/test_store_arcadedb_retrieval.py
    - tests/_retrieval_arcadedb_shared.py
    - docs/architecture.md
    - CHANGELOG.md
  deleted:
    - src/turing_agentmemory_mcp/store_rebuild_sparse.py

key-decisions:
  - "Disposition confirmed retire-directly (not ensure-then-retire): direct source inspection showed store_evidence.py already fed the bm25 RRF channel exclusively from ArcadeDB's native vector.sparseNeighbors + SEARCH_INDEX (Lucene), and lexical_tokens/lexical_weights were already written unconditionally on every CREATE/UPDATE -- no 'wire the native channel in first' step was needed."
  - "The gap was not merely dead-weight cleanup: store_core.py's bootstrap() stopped calling sparse_index.initialize() in 04-04, so a fresh deployment volume's outbox file has no sparse_meta/sparse_outbox tables. sparse_index.py's _ready_connection() raises SparseSchemaMismatch (uncaught by any of the four write call sites' except (OSError, sqlite3.Error) guards) on first .prepare() call. Retiring these call sites is a correctness fix for a live, unhandled-crash bug under a supported production configuration (AGENTMEMORY_FUSION_ENABLED=true), not just tidying."

patterns-established:
  - "Pattern: prove a retirement with a deliberately un-initialized dependency (never .initialize()'d SparseIndex) rather than mocking the dependency out -- makes the absence of a call site directly falsifiable (SparseSchemaMismatch on first touch)."

requirements-completed: [ARC-06]

coverage:
  - id: D1
    description: "store_messages/update_memory/delete_memory succeed with AGENTMEMORY_FUSION_ENABLED=true even when the SQLite FTS5 outbox file was never initialized -- none of the three write paths touch sparse_index.prepare/commit_batch/replay/discard_prepared anymore"
    requirement: "ARC-06"
    verification:
      - kind: unit
        ref: "tests/test_batch_memory_dedup.py#test_store_messages_succeeds_with_uninitialized_sparse_index_and_populates_lexical_channels"
        status: pass
      - kind: unit
        ref: "tests/test_batch_memory_dedup.py#test_update_and_delete_memory_succeed_with_uninitialized_sparse_index"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_memory_write_and_read_files_no_longer_touch_the_sparse_outbox"
        status: pass
    human_judgment: false
  - id: D2
    description: "rebuild_communities succeeds with an un-initialized SparseIndex and the legacy FTS5 rebuild mixin (store_rebuild_sparse.py) is deleted; store.py's MRO no longer references it"
    requirement: "ARC-06"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_rebuild.py#test_community_rebuild_succeeds_with_uninitialized_sparse_index"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_rebuild.py#test_store_rebuild_sparse_module_deleted_and_mixin_removed_from_mro"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_rebuild.py#test_rebuild_file_contains_no_sparse_outbox_calls"
        status: pass
      - kind: unit
        ref: "tests/test_community_detection.py#test_store_rebuilds_embeds_and_grounds_communities_via_native_lexical_channel"
        status: pass
    human_judgment: false
  - id: D3
    description: "End-to-end write-then-search proves lexical retrieval quality is unaffected by the outbox's removal -- the real write path (store_memory_write.py) and real read path (store_search.py/store_evidence.py) run together against a store built with a deliberately un-initialized SparseIndex"
    requirement: "ARC-06"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_write_then_search_round_trips_lexical_hit_with_uninitialized_sparse_index"
        status: pass
      - kind: integration
        ref: "python -m pytest -q (full suite)"
        status: pass
    human_judgment: false

# Metrics
duration: ~35min
completed: 2026-07-14
status: complete
---

# Phase 04 Plan 10: Retire the write-side SQLite-FTS5 outbox (ARC-06 gap closure) Summary

**Removed the last live `sparse_index.prepare/commit_batch/replay/discard_prepared` call sites from `store_messages`, `update_memory`, `delete_memory`, and `rebuild_communities`, deleted the now-orphaned `store_rebuild_sparse.py` mixin, and fixed a real unhandled `SparseSchemaMismatch` crash on fresh deployment volumes with fusion enabled.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-07-14
- **Tasks:** 3 (all TDD, RED→GREEN as tests-that-must-pass-after-the-fix; no separate RED commit was needed since these were regression-proof tests against existing behavior, not new-feature tests)
- **Files modified:** 12 (+1 deleted)

## Accomplishments
- Retired the outbox write path from all four remaining call sites (`store_messages`, `update_memory`, `delete_memory`, `rebuild_communities`) -- `store.py`'s ARC-06 row is now literally true on both the read side (04-07) and the write side (this plan).
- Deleted `store_rebuild_sparse.py` and its `_RebuildSparseMixin` entry from `TuringAgentMemory`'s MRO in `store.py`.
- Fixed a real correctness bug: on a fresh deployment volume (no `sparse_meta`/`sparse_outbox` tables, since `store_core.py`'s `bootstrap()` stopped calling `sparse_index.initialize()` in 04-04), any of the four write paths would previously crash unhandled with `SparseSchemaMismatch` whenever `AGENTMEMORY_FUSION_ENABLED=true` -- a supported, dogfooded production configuration.
- Proved lexical retrieval is unaffected end-to-end: a new test drives `store_message` (write) then `search_memory` (read) together against a store whose `SparseIndex` is deliberately never `.initialize()`'d, and the hit still comes back via ArcadeDB's native `lexical_tokens`/`lexical_weights` sparse-vector channel + Lucene `SEARCH_INDEX`.
- Updated `docs/architecture.md` (dropped the two stale SQLite-FTS5 outbox edges from the System Context diagram) and `CHANGELOG.md` (new `### Removed` entry).
- Full suite went from 501 to 502 passed (net +1: -4 obsolete outbox-dependent tests removed across `test_batch_memory_dedup.py`/`test_batch_memory.py`, +5 new proof tests added across the touched files, +1 renamed test with no net count change).

## Task Commits

Each task was committed atomically:

1. **Task 1: Retire the memory write/read outbox call sites** - `a74b35e` (fix)
2. **Task 2: Retire the community-rebuild outbox call site and delete the orphaned FTS5 mixin** - `b734445` (fix)
3. **Task 3: End-to-end lexical-retrieval-preserved proof, docs/CHANGELOG** - `be5adc6` (test)

_Note: these were TDD-flavored tasks proving retirement of already-planned-for-removal behavior against a real un-initialized dependency, rather than net-new RED/GREEN feature cycles -- each commit bundles the source removal with its proof test, matching this plan's own `<behavior>` framing ("RED before the fix / GREEN after")._

## Files Created/Modified
- `src/turing_agentmemory_mcp/store_memory_write.py` - `store_messages` no longer stages/commits/replays/discards a sparse outbox batch around `_create_memories_batch`
- `src/turing_agentmemory_mcp/store_memory_read.py` - `update_memory`/`delete_memory` no longer stage/commit/replay/discard a sparse outbox batch; unused `SparseDocument`/`SparseMutation` imports removed
- `src/turing_agentmemory_mcp/store_rebuild.py` - `rebuild_communities` no longer stages/commits/replays/discards a sparse outbox batch; unused imports removed; module docstring corrected
- `src/turing_agentmemory_mcp/store_rebuild_sparse.py` - deleted (fully orphaned legacy FTS5 outbox rebuild mixin)
- `src/turing_agentmemory_mcp/store.py` - `_RebuildSparseMixin` import and MRO entry removed
- `tests/test_batch_memory_dedup.py` - 3 obsolete outbox-roundtrip tests replaced with 2 new un-initialized-SparseIndex proof tests
- `tests/test_batch_memory.py` - obsolete `test_rebuild_sparse_projection_replaces_index_from_canonical_graph_documents` deleted with an explanatory superseding comment
- `tests/test_community_detection.py` - `CommunityStore`'s `SparseIndex` is now deliberately never `.initialize()`'d; the grounding test renamed and its outbox-search assertions removed (native `lexical_tokens` assertion kept)
- `tests/test_store_arcadedb_memory.py` - new source-grep gate for the retired outbox call syntax
- `tests/test_store_arcadedb_rebuild.py` - 3 new tests: rebuild-succeeds-with-un-initialized-index, mixin-file-deleted-and-MRO-clean, source-grep gate
- `tests/test_store_arcadedb_retrieval.py` - new end-to-end write-then-search test proving lexical retrieval is unaffected
- `tests/_retrieval_arcadedb_shared.py` - `make_retrieval_store` gained an optional `sparse_index` passthrough (purely additive)
- `docs/architecture.md` - dropped the two stale `Store --> FTS[(SQLite FTS5 projection)]` / `StoreWorker --> FTS` mermaid edges; rewrote the "SQLite FTS5 is a rebuildable read projection" sentence to describe the native sparse-vector + Lucene channels
- `CHANGELOG.md` - new `### Removed` entry under `## Unreleased` documenting the retired write path

## Decisions Made
- Confirmed retire-directly disposition by direct source inspection (not assumption) before touching any code: `store_evidence.py` and `store_search.py` already had zero references to `sparse_index`, so there was no "wire the native channel in first" step -- purely a removal.
- Treated the `SparseSchemaMismatch` crash risk as a genuine correctness bug (T-04-10-01 in the plan's threat register), not just dead-code cleanup, since it's reachable on a fresh volume under a supported configuration.
- Left `server.py`'s `SparseIndex` construction, `AGENTMEMORY_SPARSE_PATH`, `store_core.py`'s `runtime_status()` sparse diagnostic, `sparse_index.py` itself, and the `turingdb` Compose service/dependency untouched -- explicitly out of this plan's scope per the plan's prohibitions.

## Deviations from Plan

None - plan executed exactly as written. All three tasks, their behaviors, actions, and acceptance criteria were followed precisely as specified in `04-10-PLAN.md`.

## Issues Encountered
- The pre-commit `ruff-format` hook reformatted `tests/test_community_detection.py` and `tests/test_store_arcadedb_rebuild.py` on the first Task 2 commit attempt (line-wrapping differences from the plan's suggested edits); resolved by running `ruff format` explicitly and re-staging before committing. No content change, formatting only.

## Verification Results
- `python -m pytest -q` (full suite): **502 passed** (baseline 501 pre-fix; net +1 delta from this plan's own test additions/removals)
- `python -m pytest tests/test_batch_memory_dedup.py tests/test_batch_memory.py tests/test_community_detection.py tests/test_store_arcadedb_memory.py tests/test_store_arcadedb_rebuild.py tests/test_store_arcadedb_retrieval.py -q`: all green
- `python -m ruff check src tests scripts`: All checks passed
- `bash scripts/check-file-size.sh`: all tracked `*.py` files within the 600-LOC cap
- `docker compose config --quiet`: exit 0
- `grep -crnE "sparse_index\.(prepare|commit_batch|replay|discard_prepared)\(" src/turing_agentmemory_mcp/store_memory_write.py src/turing_agentmemory_mcp/store_memory_read.py src/turing_agentmemory_mcp/store_rebuild.py`: 0 across all three files
- `[ ! -f src/turing_agentmemory_mcp/store_rebuild_sparse.py ]`: confirmed true
- REQUIREMENTS.md's ARC-06 row and ROADMAP.md's Phase 4 Success Criterion #3 ("the SQLite-FTS5 outbox prepare/commit/replay path retired") were re-read and confirmed already correctly worded with no `[x]`-vs-reality mismatch remaining -- no text edit was needed, only the code needed to catch up (as the plan anticipated).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 4's one verified gap (04-VERIFICATION.md's "gaps_found" status, Success Criterion #3 partial) is now closed. ARC-06 is fully satisfied on both read and write sides.
- No blockers for subsequent phases. Phase 5 (per-tenant ArcadeDB isolation) and Phase 7 (turingdb service/dependency removal) are unaffected by this plan's scope.
- Recommend the orchestrator re-run `/gsd-verify-work` or the phase verifier against `04-VERIFICATION.md`'s gap to confirm closure before archiving Phase 4.

---
*Phase: 04-arcadedb-direct-port*
*Completed: 2026-07-14*

## Self-Check: PASSED
- FOUND: .planning/phases/04-arcadedb-direct-port/04-10-SUMMARY.md
- FOUND: src/turing_agentmemory_mcp/store_rebuild_sparse.py deleted as claimed
- FOUND: a74b35e (Task 1 commit)
- FOUND: b734445 (Task 2 commit)
- FOUND: be5adc6 (Task 3 commit)
