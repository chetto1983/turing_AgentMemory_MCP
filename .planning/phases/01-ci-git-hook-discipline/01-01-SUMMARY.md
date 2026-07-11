---
phase: 01-ci-git-hook-discipline
plan: 01
subsystem: infra
tags: [store-decomposition, mixin-facade, python, refactor, tenant-isolation]

# Dependency graph
requires: []
provides:
  - "store.py decomposed into a 34-LOC mixin-composed facade + 9 store_<concern>.py modules, all <=600 LOC"
  - "TuringAgentMemory public class and import path (turing_agentmemory_mcp.store.TuringAgentMemory) unchanged"
  - "Precedent for the mixin-composed-facade pattern other oversized files in this phase can follow"
affects: [ci-git-hook-discipline, arcadedb-port]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Mixin-composed facade: TuringAgentMemory(_MemoryWriteMixin, _MemoryReadMixin, _SearchMixin, _EvidenceMixin, _DocumentMixin, _ChunkingMixin, _RebuildMixin, _UtilsMixin, _StoreCore) — cross-mixin self.<method> calls resolve via MRO at runtime, no mixin imports another mixin's class"

key-files:
  created:
    - src/turing_agentmemory_mcp/store_core.py
    - src/turing_agentmemory_mcp/store_utils.py
    - src/turing_agentmemory_mcp/store_chunking.py
    - src/turing_agentmemory_mcp/store_memory_write.py
    - src/turing_agentmemory_mcp/store_memory_read.py
    - src/turing_agentmemory_mcp/store_search.py
    - src/turing_agentmemory_mcp/store_evidence.py
    - src/turing_agentmemory_mcp/store_documents.py
    - src/turing_agentmemory_mcp/store_rebuild.py
  modified:
    - src/turing_agentmemory_mcp/store.py

key-decisions:
  - "Applied both RESEARCH.md-flagged sub-splits for store_documents.py: moved _rerank_documents/_reranked_score_details to store_search.py, and moved _active_chunk_rows/_document_chunk_batch_query/_document_from_row to store_chunking.py, to clear the 600-LOC cap"
  - "Moved _batch_payload_key/_memory_matches_payload from store_memory_write.py to store_utils.py (RESEARCH sub-split note) to bring store_memory_write.py from 616 to 595 LOC"
  - "Converted _chunk_text from @staticmethod to @classmethod (calling cls._pack_text instead of the concrete TuringAgentMemory class) to avoid a circular import between store_chunking.py and store.py — behavior-identical, Rule 3 auto-fix"

patterns-established:
  - "Mixin-composed facade for size-capped classes with shared instance state: one _StoreCore mixin owns __init__/query/write infra; sibling _<Concern>Mixin classes assume self.<attr> is available via MRO"

requirements-completed: [CI-01]

coverage:
  - id: D1
    description: "store.py (3891 LOC) decomposed into a slim facade (34 LOC) + 9 store_<concern>.py mixin modules, each <=600 LOC"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "python -m pytest -q (362/362 passed, unchanged from pre-split baseline)"
        status: pass
      - kind: other
        ref: "git ls-files 'src/turing_agentmemory_mcp/store*.py' | wc -l line check — all 10 files <=600 LOC (max 610->595 after sub-split)"
        status: pass
    human_judgment: false
  - id: D2
    description: "TuringAgentMemory public import path and API unchanged; tenant scoping (_require_user/user_identifier) preserved verbatim across every moved method"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "from turing_agentmemory_mcp.store import TuringAgentMemory (import smoke, exits 0 with the same turingdb stub pattern existing tests use)"
        status: pass
      - kind: other
        ref: "grep -c '_require_user(user_identifier)' across all store*.py == 11, matches the pre-split count"
        status: pass
    human_judgment: false
  - id: D3
    description: "E2E score gate (scripts/e2e_score.py, VALIDATED_10_10 >= 9.8) confirms retrieval-fusion/rerank/document-chunking call graph is unbroken across the mixin split"
    requirement: "CI-01"
    verification: []
    human_judgment: true
    rationale: "turingdb has no Windows wheel — scripts/e2e_score.py cannot import/run on this Windows dev host (ModuleNotFoundError: No module named 'turingdb'). This is a known environment constraint, not a code gap. The orchestrator's Docker run (docker compose run --rm e2e) is the actual E2E gate for this plan and must be green before the phase closes."

# Metrics
duration: ~30min
completed: 2026-07-11
status: complete
---

# Phase 1 Plan 1: store.py Decomposition Summary

**Split the 3891-LOC `store.py` god-module into a 34-LOC mixin-composed facade plus 9 `store_<concern>.py` sibling modules (`store_core`, `store_utils`, `store_chunking`, `store_memory_write`, `store_memory_read`, `store_search`, `store_evidence`, `store_documents`, `store_rebuild`), all ≤600 LOC, preserving the `TuringAgentMemory` public class, import path, and every method body/signature/tenant-scoping call verbatim.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-07-11T20:00:00Z (approx.)
- **Completed:** 2026-07-11T20:26:10Z
- **Tasks:** 2
- **Files modified:** 10 (1 modified facade + 9 new mixin modules)

## Accomplishments
- Extracted `_StoreCore` (init/bootstrap/query-write infra), `_UtilsMixin` (ID/vector/datetime/text helpers), `_ChunkingMixin` (text chunking + chunk/document row helpers), `_MemoryWriteMixin` (store/batch-store/add-*), and `_MemoryReadMixin` (get/list/update/delete) — landed and gated (pytest 362/362, ruff clean) before starting the second half
- Extracted `_SearchMixin` (search + rerank pipeline), `_EvidenceMixin` (multi-signal retrieval evidence collection), `_DocumentMixin` (document ingest/search/lifecycle), and `_RebuildMixin` (sparse/vector/community projection rebuild); reduced `store.py` to a 34-LOC facade composing all 9 mixins via MRO
- Applied 3 sub-splits (2 flagged by RESEARCH.md, 1 discovered during measurement) to bring `store_documents.py` (would have been ~715 LOC) and `store_memory_write.py` (616 LOC) under the 600-LOC cap without touching behavior
- Verified `TuringAgentMemory.__mro__` resolves correctly (11 classes: 9 mixins + `TuringAgentMemory` + `object`) and every one of the 11 `_require_user(user_identifier)` call sites survived the split verbatim

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract leaf + write/read mixins (store_utils, store_chunking, store_core, store_memory_write, store_memory_read)** - `43f3335` (feat)
2. **Task 2: Extract retrieval mixins (store_search, store_evidence, store_documents, store_rebuild) and slim the facade** - `a32e5ef` (feat)

_Note: no TDD tasks in this plan (pure behavior-preserving refactor); no separate plan-metadata commit convention departure — the two task commits above are the full history for this plan._

## Files Created/Modified
- `src/turing_agentmemory_mcp/store_core.py` (424 LOC) - `_StoreCore` mixin: `__init__`, `bootstrap`, `load_graph_after_restart`, `runtime_status`, low-level `_ensure_*`/`_query`/`_write`/`_write_many`/`_load_vectors`/`_records`/`_span`/`_audit`/`_now_iso`/`_json_*`/`_require_user`/`_ensure_user` infra
- `src/turing_agentmemory_mcp/store_utils.py` (248 LOC) - `_UtilsMixin`: value/ID/vector/datetime helpers, text redaction/entity-metadata merge, `_batch_payload_key`/`_memory_matches_payload` (moved here from store_memory_write.py to clear the cap)
- `src/turing_agentmemory_mcp/store_chunking.py` (181 LOC) - `_ChunkingMixin`: `_chunk_document_text`/`_chunk_text`/`_pack_text`/`_chunk_context` plus `_active_chunk_rows`/`_document_chunk_batch_query`/`_document_from_row` (moved here from store_documents.py to clear the cap)
- `src/turing_agentmemory_mcp/store_memory_write.py` (595 LOC) - `_MemoryWriteMixin`: `store_message`, `store_messages`, `add_entity`, `add_preference`, `add_fact`, `_write_memory`, `_create_memories_batch`, `_plan_memory_projections`
- `src/turing_agentmemory_mcp/store_memory_read.py` (407 LOC) - `_MemoryReadMixin`: `get_memory`, `list_memories`, `update_memory`, `delete_memory`, row/filter helpers
- `src/turing_agentmemory_mcp/store_search.py` (517 LOC) - `_SearchMixin`: `search_memory`, `_search_memory_fused`, `_rerank_memory`, `_annotate_memory_rerank`, `_memory_rerank_document`, `_fused_rerank_score_details`, plus `_rerank_documents`/`_reranked_score_details` (moved here from store_documents.py to clear the cap)
- `src/turing_agentmemory_mcp/store_evidence.py` (468 LOC) - `_EvidenceMixin`: `_collect_retrieval_evidence` + per-channel dense/sparse/graph evidence collectors
- `src/turing_agentmemory_mcp/store_documents.py` (591 LOC) - `_DocumentMixin`: `get_context`, `ingest_document_text`, `get_document`, `reindex_document_text`, `delete_document`, `search_documents`, document/chunk graph helpers, `_DocumentChunkGraphUnit` dataclass
- `src/turing_agentmemory_mcp/store_rebuild.py` (586 LOC) - `_RebuildMixin`: `rebuild_sparse_projection`, `rebuild_vector_projection`, `rebuild_communities`, projection helpers
- `src/turing_agentmemory_mcp/store.py` (34 LOC) - slim facade: `class TuringAgentMemory(_MemoryWriteMixin, _MemoryReadMixin, _SearchMixin, _EvidenceMixin, _DocumentMixin, _ChunkingMixin, _RebuildMixin, _UtilsMixin, _StoreCore)`, import path unchanged

## Decisions Made
- Used the mixin-composed-facade pattern exactly as specified in RESEARCH.md/PATTERNS.md — mechanical cut-and-paste, no reimplementation, no signature changes
- Sequenced as two gated tasks (leaf/write/read mixins first, then retrieval mixins + facade slimming) so `store.py` stayed importable and green after every extraction, per the plan's "never leave store.py in a non-importing state" constraint
- Converted `_chunk_text` from `@staticmethod` to `@classmethod` (Rule 3 auto-fix, see Deviations) rather than leaving a hardcoded reference to the concrete `TuringAgentMemory` class inside `store_chunking.py`, which would have created a circular import (`store_chunking.py` → `store.py` → `store_chunking.py`)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Circular-import-safe `_chunk_text` staticmethod→classmethod conversion**
- **Found during:** Task 1 (extracting `store_chunking.py`)
- **Issue:** The original `_chunk_text` staticmethod called `TuringAgentMemory._pack_text(...)` by referencing the concrete class name directly. Moved verbatim into `store_chunking.py`, this would import `store.py` from inside a module `store.py` itself imports — a circular import that breaks the facade.
- **Fix:** Converted `_chunk_text` to a `@classmethod` and changed the internal call to `cls._pack_text(...)`. Since `_chunk_document_text` already invokes it as `self._chunk_text(...)`, `cls` resolves to `TuringAgentMemory` at runtime via the same MRO mechanism every other mixin relies on — behavior is identical, only the import-cycle hazard is removed.
- **Files modified:** `src/turing_agentmemory_mcp/store_chunking.py`
- **Verification:** `python -m pytest -q` (362/362, including all document-ingest/chunking tests) plus the import smoke test both pass.
- **Committed in:** `43f3335` (Task 1 commit)

**2. [Rule 3 - Blocking] Two additional sub-splits beyond RESEARCH.md's flagged one**
- **Found during:** Task 2, after measuring real `wc -l` output (RESEARCH.md's line estimates were explicitly caveated as ±30-50 LOC, "the file-size script is the authoritative check")
- **Issue:** `store_documents.py` measured at 610 LOC (over cap) even after applying RESEARCH.md's flagged `_rerank_documents`/`_reranked_score_details` → `store_search.py` sub-split (which alone was insufficient); `store_memory_write.py` measured at 616 LOC before any sub-split.
- **Fix:** Moved `_document_from_row` (18 LOC) from `store_documents.py` into `store_chunking.py` (grouped with the other document/chunk row-fetch helpers already relocated there in Task 1), bringing `store_documents.py` to 591 LOC. Moved `_batch_payload_key`/`_memory_matches_payload` from `store_memory_write.py` into `store_utils.py` (both are pure payload-comparison helpers with no write-orchestration logic), bringing `store_memory_write.py` to 595 LOC.
- **Files modified:** `src/turing_agentmemory_mcp/store_documents.py`, `src/turing_agentmemory_mcp/store_chunking.py`, `src/turing_agentmemory_mcp/store_memory_write.py`, `src/turing_agentmemory_mcp/store_utils.py`
- **Verification:** `wc -l` confirms all 10 `store*.py` files ≤600 LOC (max 595); `python -m pytest -q` 362/362; `python -m ruff check src tests scripts` clean.
- **Committed in:** `a32e5ef` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 — blocking issues discovered mid-extraction, both required to clear the 600-LOC cap / avoid a circular import). No scope creep — every change stayed within the plan's "cut real method bodies, do not reimplement" boundary.

## Issues Encountered
- The plan's acceptance criteria specify `python scripts/e2e_score.py --out e2e-results.json` (VALIDATED_10_10, score ≥9.8) as part of the behavior-preservation gate run after each extraction. Per this Windows dev host's known environment constraint (`turingdb` ships no Windows wheel — `ModuleNotFoundError: No module named 'turingdb'`), that command cannot run locally. Substituted the locally-runnable subset of the gate after each extraction and again at the end: `python -m pytest -q` (stayed 362/362 throughout), `python -m ruff check src tests scripts` (clean), the `wc -l`/`git ls-files` file-size check, and an import smoke test using the same `sys.modules["turingdb"] = types.SimpleNamespace(...)` stub pattern the existing test suite already uses in ~15 test files. The real E2E score gate is deferred to the orchestrator's Docker run (`docker compose run --rm e2e`), which must pass before this phase is considered fully verified.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `store.py` and all 9 new `store_<concern>.py` siblings are ≤600 LOC, satisfying the file-size precondition this phase's `check-file-size.sh` hook depends on (for `store.py`; the other 9 flagged over-cap files from RESEARCH.md — `benchmark.py`, `e2e_score.py`, `server.py`, `document_jobs.py`, `gliner_provider.py`, and 4 test/script files — are separate plans in this phase's wave)
- The mixin-composed-facade pattern established here (`_<Concern>Mixin` classes in sibling files, composed by a thin facade class, cross-mixin calls resolved via MRO) is now a concrete precedent other oversized-file splits in this phase can follow
- **Blocker for phase completion:** the orchestrator MUST run `docker compose run --rm e2e` (or equivalent) against this split before the phase's lefthook/CI gates are turned on — the local Windows dev environment cannot execute `scripts/e2e_score.py` directly, so this plan's local gate (pytest + ruff + file-size + import smoke) is real but partial

---
*Phase: 01-ci-git-hook-discipline*
*Completed: 2026-07-11*

## Self-Check: PASSED

All 10 `store*.py` files verified present on disk; both task commits (`43f3335`, `a32e5ef`) verified present in git history.
