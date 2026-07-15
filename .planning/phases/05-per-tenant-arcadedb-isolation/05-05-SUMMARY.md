---
phase: 05-per-tenant-arcadedb-isolation
plan: 05
subsystem: database
tags: [arcadedb, multi-tenant, routing, single-flight, lru, tdd]

requires:
  - phase: 05-per-tenant-arcadedb-isolation
    provides: Exact tenant identity, pseudonymous registry, query-scope audit, and ready-last provisioning from plans 01-04
provides:
  - Immutable tenant store views permanently bound to one provisioned ArcadeDB database
  - Per-database single-flight provisioning with bounded idle-TTL and LRU reuse
  - Frozen shared store dependencies with fresh tenant-local runtime and bootstrap state
  - Pseudonymous non-provisioning router diagnostics and central exact validation
affects: [05-06, 05-07, 05-08, server-routing, document-workers, layered-health]

tech-stack:
  added: []
  patterns:
    - One Future leader per opaque database name with provisioning and waiting outside the RLock
    - Frozen shared dependency bundle plus fresh tenant-local client, RuntimeSignals, and schema latch
    - Cache eviction as reference removal only, never client mutation or database lifecycle action

key-files:
  created:
    - src/turing_agentmemory_mcp/tenant_router.py
    - tests/test_tenant_router.py
  modified:
    - src/turing_agentmemory_mcp/store_core.py
    - tests/test_store_arcadedb_core.py

key-decisions:
  - "Use an opaque-database-keyed Future map under a narrow RLock, while provisioning, store construction, and waiter blocking all occur outside the lock."
  - "Share exact provider, extraction, community, observer, redactor, audit, and immutable configuration objects through a frozen bundle while allocating fresh tenant runtime and bootstrap state."
  - "Treat cache eviction as local dereferencing only; active views retain valid database-bound clients and later resolution may construct a new view."

patterns-established:
  - "Tenant resolution: exact validate, derive opaque identity, join or lead single flight, provision/build outside lock, publish bounded cache entry."
  - "Layered diagnostics: global router readiness is content-free and tenant_status derives an opaque key without provisioning."

requirements-completed: [ARC-07]

coverage:
  - id: D1
    description: "Same-tenant callers share one immutable view/outcome while different tenants provision concurrently without a global lifecycle lock."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_tenant_router.py::test_same_tenant_callers_share_one_attempt_and_one_immutable_view"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_router.py::test_different_tenants_provision_concurrently"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_router.py::test_leader_exception_fans_out_and_clears_exact_inflight_for_retry"
        status: pass
    human_judgment: false
  - id: D2
    description: "Bounded LRU and idle-TTL reuse evicts references only, preserving active view usability and permanently bound clients."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_tenant_router.py::test_capacity_lru_eviction_only_removes_cache_reference"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_router.py::test_idle_ttl_uses_injected_monotonic_clock_and_recreates_expired_view"
        status: pass
    human_judgment: false
  - id: D3
    description: "Store dependencies are shared by identity while client, RuntimeSignals, and schema bootstrap state remain tenant-local."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py::test_shared_dependency_bundle_reuses_dependencies_but_not_tenant_runtime_state"
        status: pass
    human_judgment: false
  - id: D4
    description: "Router, static resolver, and direct store entry points share exact validation order and diagnostics remain pseudonymous and non-provisioning."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_tenant_router.py::test_diagnostics_are_pseudonymous_non_provisioning_and_tenant_local"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_router.py::test_resolvers_reject_invalid_identity_before_provision_build_or_store_activity"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py::test_require_user_delegates_to_central_exact_validator"
        status: pass
    human_judgment: false

duration: 17min
completed: 2026-07-15
status: complete
---

# Phase 05 Plan 05: Immutable Tenant Store Router Summary

**Opaque per-database single flight now publishes immutable tenant-bound stores through bounded TTL/LRU reuse while sharing heavyweight dependencies without sharing runtime state.**

## Performance

- **Duration:** 17 min
- **Started:** 2026-07-15T11:29:06Z
- **Completed:** 2026-07-15T11:46:07Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added a resolver protocol, static injection adapter, immutable tenant view, and router whose per-key Future leaders provision unrelated tenants concurrently.
- Added capacity-bounded LRU and monotonic idle-TTL reuse with deterministic eviction, exception fan-out/cleanup, and active-reference safety.
- Split heavyweight store dependencies/configuration into a frozen shared bundle while keeping the client, RuntimeSignals, schema latch, manifest, and readiness tenant-local.
- Unified router, static-resolver, and direct-store identity rejection through the exact central validator before cache, provisioning, store, or client activity.

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Specify immutable tenant views, per-key single flight, and bounded cache behavior** - `763fcee` (test)
2. **Task 2 (GREEN): Implement shared dependency assembly and concurrency-safe tenant routing** - `ceb2f78` (feat)

## Files Created/Modified

- `src/turing_agentmemory_mcp/tenant_router.py` - Immutable views, resolver/static adapter, opaque-key single flight, bounded cache, and layered diagnostics.
- `src/turing_agentmemory_mcp/store_core.py` - Frozen shared dependency/config bundle, tenant-local construction seam, and central exact validator delegation.
- `tests/test_tenant_router.py` - Barrier/event-driven concurrency, failure fan-out, LRU/TTL, eviction, diagnostics, and identity-boundary coverage.
- `tests/test_store_arcadedb_core.py` - Direct-store validation order and shared-versus-local store state regression coverage.

## Decisions Made

- The router lock protects only the OrderedDict and in-flight Future map; no provisioner, factory, or Future wait runs while it is held.
- Cache and in-flight keys are complete opaque database names. Raw identifiers exist only at the validated request/predicate boundary and are absent from views and diagnostics.
- A tenant store is accepted only when provisioned identity, manifest database, client database, and constructed store client all agree exactly.
- Static injection uses the same frozen view contract and exact validator but never invokes naming, provisioning, or cache behavior.

## TDD Gate Compliance

- **RED:** `763fcee` committed the complete router/store contract while resolution and diagnostics failed with the intended `NotImplementedError`; direct-store tests also exposed the old whitespace-only validation and missing shared dependency seam.
- **GREEN:** `ceb2f78` implemented the minimal router and store-construction behavior; the focused suite passes 46 tests.
- **REFACTOR:** No separate refactor commit was needed; GREEN was formatted, Ruff-clean, and exactly at or below the 600-line cap.
- **Order:** `763fcee` precedes `ceb2f78` in Git history.

## Automated Validation

- `python -m pytest tests/test_tenant_router.py tests/test_store_arcadedb_core.py -q` - 46 passed.
- `python -m pytest -p no:cacheprovider -q` - 693 passed, 9 integration skips allowed locally.
- `python -m ruff check src tests scripts` - passed.
- `python -m ruff format --check src tests scripts` - 147 files formatted.
- CRLF-normalized `scripts/check-file-size.sh` content - all tracked Python files within the 600-line cap.
- `docker compose config --quiet` - passed.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The tracked shell script is checked out with CRLF and this Bash binary rejects `set -o pipefail\r`; piping identical script content through carriage-return removal produced the passing file-size result without changing the repository script.

## Known Stubs

None - the modified-file scan found no TODO, FIXME, placeholder, `NotImplementedError`, unavailable-data path, or runtime rendering stub.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Foreground MCP tools can now resolve one immutable tenant-bound store per operation through the shared resolver seam.
- Background document routing can consume the same resolver without retaining a process-global store.
- Live A/B/C isolation remains scheduled for plan 05-08 after foreground and background integration.

## Self-Check: PASSED

- All four implementation/test artifacts and this summary exist on disk.
- RED `763fcee` and GREEN `ceb2f78` exist in the required order.
- Focused, full-suite, Ruff, file-size, Compose, and coverage-classifier gates pass.

---
*Phase: 05-per-tenant-arcadedb-isolation*
*Completed: 2026-07-15*
