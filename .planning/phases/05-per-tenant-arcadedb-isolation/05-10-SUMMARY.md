---
phase: 05-per-tenant-arcadedb-isolation
plan: 10
subsystem: database
tags: [tenant-isolation, hmac, arcadedb, tdd, security]

# Dependency graph
requires:
  - phase: 05-per-tenant-arcadedb-isolation
    provides: "TenantBinding: a keyed, recomputable logical-to-physical tenant binding; instance-bound _StoreCore._require_user (05-09)"
provides:
  - "Guard-first ordering on the six span-wrapped public store methods (guard runs before span/audit, not inside it)"
  - "The binding-aware guard added to the seven public store methods that previously never called it at all"
  - "A static catalog test (tests/test_tenant_query_scope.py::test_every_public_store_method_requires_user) that fails if a future public method omits the guard"
  - "An 18-method adversarial matrix (tests/test_tenant_binding_enforcement.py) proving foreign-identifier rejection, bound-identifier success, zero pre-guard telemetry, and a background-job-view rejection"
affects: [05-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Guard-first prologue: self._require_user(user_identifier) is the literal first statement of every public store method, placed before any `with self._span(...)` block -- not hidden behind a decorator, so the static catalog test's inspect.getsource() scan can see it"
    - "Explicit literal method-coverage tables (not introspection) in adversarial test parametrization, so a newly added public method cannot silently fall out of coverage"

key-files:
  created:
    - tests/test_tenant_binding_enforcement.py
  modified:
    - src/turing_agentmemory_mcp/store_memory_write.py
    - src/turing_agentmemory_mcp/store_memory_read.py
    - src/turing_agentmemory_mcp/store_documents.py
    - src/turing_agentmemory_mcp/store_search.py
    - tests/test_tenant_query_scope.py
    - CHANGELOG.md

key-decisions:
  - "test_every_public_store_method_requires_user landed as Task 1's RED test (in tests/test_tenant_query_scope.py) rather than deferred to Task 2, because it is the literal formalization of Task 1's own acceptance-criteria audit script -- writing it first let Task 1 follow a genuine RED (7 methods missing)/GREEN (0 missing) cycle instead of a same-commit assert-and-fix"
  - "Task 2's adversarial-matrix tests construct TuringAgentMemory directly (not via tests/_store_arcadedb_core_shared.py's make_full_store) because the bound-identifier success matrix needs a working .embed()/.embed_many() embedder and a real NoopEntityProcessor, neither of which that helper's fixed StubEmbedder/object() stubs provide"
  - "update_memory's bound-identifier success case seeds its target memory_id first via the same bound tenant (store_message with an explicit memory_id) rather than tolerating its legitimate not-found ValueError -- proves a real success path, not just absence of TenantBindingError"

patterns-established:
  - "A rejected foreign identifier on any span-wrapped public store method emits zero InMemorySpanRecorder events and zero audit-sink events (verified for all 6 span-wrapped methods, not just asserted for one representative)"

requirements-completed: [ARC-07, TEST-05]

coverage:
  - id: D1
    description: "Seven previously-unguarded public store methods (add_entity, add_preference, add_fact, update_memory, delete_memory, get_context, delete_document) now call the binding-aware guard as their first statement"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_query_scope.py::test_every_public_store_method_requires_user"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_binding_enforcement.py::test_foreign_identifier_rejected_on_every_public_path"
        status: pass
    human_judgment: false
  - id: D2
    description: "The six span-wrapped public methods (store_message, store_messages, ingest_document_text, reindex_document_text, search_documents, search_memory) run the guard before opening their span, so a rejected foreign identifier emits zero span/audit telemetry"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_binding_enforcement.py::test_foreign_identifier_rejected_before_span_or_audit"
        status: pass
    human_judgment: false
  - id: D3
    description: "The bound (correct) identifier still succeeds on all 18 public methods, proving the guard is not simply refusing everything"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_binding_enforcement.py::test_bound_identifier_succeeds_on_every_public_path"
        status: pass
    human_judgment: false
  - id: D4
    description: "A background document job resolved for tenant B cannot execute against a tenant-A store view"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_binding_enforcement.py::test_background_job_identifier_rejected_by_foreign_view"
        status: pass
    human_judgment: false
  - id: D5
    description: "A static catalog test fails when a future public store method accepting user_identifier omits the guard, so coverage cannot silently regress"
    requirement: "TEST-05"
    verification:
      - kind: unit
        ref: "tests/test_tenant_query_scope.py::test_every_public_store_method_requires_user"
        status: pass
      - kind: other
        ref: "temporary local revert of the add_entity guard, confirmed test failure naming the method, then restored (not committed) -- see plan verification"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-07-15
status: complete
---

# Phase 05 Plan 10: Store-Wide Guard Coverage and Ordering Summary

**Closed the third "missing" item of verifier gap 1 by making the ARC-07 tenant binding guard reachable and ordered on all 18 public store methods (7 previously never called it at all; 6 called it after the span had already opened), and added a static catalog test plus an 18-method adversarial matrix that fail if coverage regresses.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-15T17:04:00Z (approx.)
- **Completed:** 2026-07-15T17:28:45Z
- **Tasks:** 2
- **Files modified:** 7 (1 created, 6 modified)

## Accomplishments

- `add_entity`, `add_preference`, `add_fact` (store_memory_write), `update_memory`, `delete_memory` (store_memory_read), and `get_context`, `delete_document` (store_documents) now call `self._require_user(user_identifier)` as their literal first statement -- previously these seven reached only `_write_memory`'s `_ensure_user`, a database read/create, not a binding validation guard.
- `store_message`, `store_messages` (store_memory_write), `ingest_document_text`, `reindex_document_text`, `search_documents` (store_documents), and `search_memory` (store_search) now call the guard immediately before their `with self._span(...)` block, not inside it -- a rejected foreign identifier now emits zero span/audit telemetry on every one of these six methods (previously it emitted a span for the rejected call).
- `tests/test_tenant_query_scope.py::test_every_public_store_method_requires_user` mechanically enumerates every public method across the five store mixin modules that accept `user_identifier` and asserts `_require_user` appears in its source -- this was written first as the plan's RED test (failed naming exactly the 7 missing methods) and now passes with 0 missing across all 18.
- `tests/test_tenant_binding_enforcement.py` (new, 194 lines) delivers the adversarial matrix the phase verifier demanded: `test_foreign_identifier_rejected_on_every_public_path` (18 parametrized cases, zero client query/command activity on rejection), `test_foreign_identifier_rejected_before_span_or_audit` (6 span-wrapped cases, zero `InMemorySpanRecorder`/audit-sink events), `test_bound_identifier_succeeds_on_every_public_path` (18 cases, proves the guard isn't refusing everything), and `test_background_job_identifier_rejected_by_foreign_view` (mirrors `DocumentIngestManager.process_next`'s `resolver.resolve(job.user_identifier).memory` shape without re-architecting the worker).
- Verified the regression guarantee empirically: temporarily reverted the `add_entity` guard, confirmed `test_every_public_store_method_requires_user` failed naming exactly that method, then restored the source (not committed) -- `git diff --stat` confirmed a clean restore.

## Task Commits

Each task was committed atomically (TDD RED then GREEN):

1. **Task 1: Guard every public store path, before any span** - `c303f4f` (test, RED: static catalog test, 7 methods missing) then `c7dbfc1` (feat, GREEN: guard-first ordering + missing guards, 0 missing)
2. **Task 2: Adversarial binding matrix and anti-regression catalog** - `1838b54` (test: 43 new parametrized/direct test cases, all passing against Task 1's already-guarded surface)

**Plan metadata:** `ba4bcca` (docs: CHANGELOG entry for the guard-coverage gap closure)

## Files Created/Modified

- `src/turing_agentmemory_mcp/store_memory_write.py` - guard-first ordering on `store_message`/`store_messages`; new guards on `add_entity`/`add_preference`/`add_fact`
- `src/turing_agentmemory_mcp/store_memory_read.py` - new guards on `update_memory`/`delete_memory`
- `src/turing_agentmemory_mcp/store_documents.py` - new guards on `get_context`/`delete_document`; guard-first ordering on `ingest_document_text`/`reindex_document_text`/`search_documents`
- `src/turing_agentmemory_mcp/store_search.py` - guard-first ordering on `search_memory`
- `tests/test_tenant_query_scope.py` - new `STORE_MIXIN_MODULES`/`_public_store_methods`/`test_every_public_store_method_requires_user` static catalog (additive; the pre-existing query-builder classification tests are untouched)
- `tests/test_tenant_binding_enforcement.py` - new: 18-method adversarial matrix + background-job-view test
- `CHANGELOG.md` - Changed entry documenting the guard-coverage contract change

## Decisions Made

- `test_every_public_store_method_requires_user` was written as Task 1's own RED test (in `tests/test_tenant_query_scope.py`, which is also where Task 2's plan text calls for it) rather than deferred until Task 2 -- it is the exact formalization of Task 1's acceptance-criteria audit script, so writing it first gave Task 1 a genuine RED (7 missing)/GREEN (0 missing) cycle instead of an assert-and-fix-in-the-same-commit shape.
- Task 2's adversarial-matrix store is constructed directly via `TuringAgentMemory(...)` rather than through `tests/_store_arcadedb_core_shared.py`'s `make_full_store` helper, because the bound-identifier "succeeds" matrix genuinely exercises embedding (`search_memory`, `search_documents`, `ingest_document_text`, `reindex_document_text`, `store_message`, `store_messages`) and entity processing (`ingest_document_text`/`reindex_document_text`), and that helper's fixed `StubEmbedder`/`object()` stubs have no callable `.embed()`/`.process()`. A local `_WorkingEmbedder` (`.embed()`/`.embed_many()`) and the existing `NoopEntityProcessor` were used instead; `FakeArcadeDBClient` itself was reused unchanged.
- `update_memory`'s bound-identifier success case seeds `mem-1` first via `store_message(..., memory_id="mem-1")` on the same bound tenant, rather than accepting its legitimate `ValueError: memory not found` as an acceptable outcome -- the plan's must-have requires proving a genuine success path, not merely the absence of `TenantBindingError`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Corrected a stale test-file path in the plan's own verify command**
- **Found during:** Task 1 verification
- **Issue:** The plan's `<verify>` step names `tests/test_documents_arcadedb.py`, which does not exist; the actual file (confirmed via `ls tests`) is `tests/test_store_arcadedb_documents.py`.
- **Fix:** Ran the corrected file name; no source change needed.
- **Files modified:** none (verification-command substitution only)
- **Verification:** `python -m pytest tests/test_arcadedb_tenant_isolation.py tests/test_store_arcadedb_documents.py -q` -- 17 passed

**2. [Rule 2 - Missing critical functionality] Added the CHANGELOG entry the plan's task list omitted**
- **Found during:** post-Task-2 review against CLAUDE.md
- **Issue:** CLAUDE.md requires "Update `docs/` and `CHANGELOG.md` in the same change when a contract changes." Both tasks changed `_require_user`'s reachability contract (7 newly-guarded methods, 6 reordered), but neither task's file list included `CHANGELOG.md`, and `docs/architecture.md`'s existing Tenant Routing description already stated the target behavior this plan makes true (no doc drift there, verified by re-reading it).
- **Fix:** Added a `### Changed` entry to `CHANGELOG.md`'s Unreleased section, following the same pattern as 05-09's binding-introduction entry.
- **Files modified:** CHANGELOG.md
- **Verification:** N/A (documentation only)
- **Committed in:** `ba4bcca`

---

**Total deviations:** 2 auto-fixed (1 blocking path correction, 1 missing-documentation addition)
**Impact on plan:** Zero behavior or test-coverage change; both deviations are process/documentation corrections.

## Issues Encountered

None beyond the two documented deviations above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ARC-07 verifier gap 1's third and final "missing" item is closed: the read/write/update/delete/document/background adversarial matrix the verifier demanded now exists and passes, alongside the static anti-regression catalog.
- The gap-closure sequence started in 05-09 (correct-where-called) and completed in 05-10 (reachable-and-ordered-everywhere) is done; 05-11 (referenced in this plan's context as the owner of span-attribute sanitization) can proceed against a fully guarded store surface.
- Full repository test suite (810 passed, 11 skipped), `ruff check`, `scripts/check-file-size.sh`, and `docker compose config --quiet` all green after this plan.

---
*Phase: 05-per-tenant-arcadedb-isolation*
*Completed: 2026-07-15*

## Self-Check: PASSED

All 7 created/modified files verified present on disk; all 4 commit hashes
(`c303f4f`, `c7dbfc1`, `1838b54`, `ba4bcca`) verified present in
`git log --oneline --all`.
