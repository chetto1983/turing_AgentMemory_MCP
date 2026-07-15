---
phase: 05-per-tenant-arcadedb-isolation
plan: 03
subsystem: database
tags: [arcadedb, multi-tenant, query-builders, defense-in-depth, tdd]

requires:
  - phase: 04-arcadedb-direct-port
    provides: Bound-parameter ArcadeDB query builders and native rebuild/retrieval paths
  - phase: 05-per-tenant-arcadedb-isolation
    provides: Exact tenant identity and durable pseudonymous tenant registry from plans 01-02
provides:
  - Reflection-backed classification catalog for every public query builder
  - Exact tenant predicates on memory, document, chunk, projection, and community edges
  - Tenant-bound vector-version and staging reads/writes resistant to foreign stable IDs
affects: [05-04, 05-05, 05-06, 05-07, 05-08, tenant-isolation, rebuilds]

tech-stack:
  added: []
  patterns:
    - Explicit public-builder catalog with narrow named schema exemptions
    - Stable resource IDs always paired with an exact bound tenant predicate
    - Both CREATE EDGE endpoint subqueries reassert tenant ownership

key-files:
  created:
    - tests/test_tenant_query_scope.py
  modified:
    - src/turing_agentmemory_mcp/store_memory_queries.py
    - src/turing_agentmemory_mcp/store_documents_queries.py
    - src/turing_agentmemory_mcp/store_rebuild_queries.py
    - src/turing_agentmemory_mcp/store_memory_write.py
    - src/turing_agentmemory_mcp/store_documents.py
    - src/turing_agentmemory_mcp/store_rebuild.py

key-decisions:
  - "Discover public SQL builders from their Statement/DDL contract, then require every discovered callable to be explicitly tenant-scoped or individually schema-exempt."
  - "Persist user_identifier on VectorVersion records so deterministic IDs never become the sole authorization boundary."
  - "Keep User.identifier equality exact while separately scoping every tenant-owned edge endpoint with the same bound user_identifier."

patterns-established:
  - "Query catalog gate: a future public Statement, statement-list, sqlscript, or DDL builder fails until explicitly classified."
  - "Edge endpoint gate: every non-User source and every selected target carries user_identifier = :user_identifier."

requirements-completed: [ARC-07, TEST-05]

coverage:
  - id: D1
    description: "Every public query builder is mechanically classified, with only individually reasoned schema exemptions."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_tenant_query_scope.py::test_all_query_builders_are_classified"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_query_scope.py::test_tenant_scope_exemptions_are_narrow_and_reasoned"
        status: pass
    human_judgment: false
  - id: D2
    description: "Memory, document, chunk, projection, and community edge endpoints bind the same exact tenant."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_tenant_query_scope.py::test_every_edge_endpoint_is_tenant_scoped"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py and tests/test_store_arcadedb_documents.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Stable-ID and rebuild/version operations pair resource identity with explicit tenant scope."
    requirement: TEST-05
    verification:
      - kind: unit
        ref: "tests/test_tenant_query_scope.py::test_stable_resource_ids_are_paired_with_tenant_scope"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_rebuild.py and tests/test_store_arcadedb_retrieval.py"
        status: pass
    human_judgment: false

duration: 11min
completed: 2026-07-15
status: complete
---

# Phase 05 Plan 03: Defense-in-Depth Query Scope Summary

**A reflection-backed builder catalog now enforces exact tenant predicates across stable-ID, edge-endpoint, and rebuild/version query paths.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-07-15T10:37:28Z
- **Completed:** 2026-07-15T10:49:02Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- Cataloged all 44 tenant-data builders and five individually reasoned schema-only exemptions across the four public query modules.
- Scoped both sides of memory, document, chunk, temporal-projection, and community membership edges with the exact operation tenant.
- Persisted and required tenant scope for vector-version pointers and per-record staging updates, closing stable-ID-only rebuild paths.

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Catalog the query surface and expose scope gaps** - `73a9381` (test)
2. **Task 2 (GREEN): Scope memory, document, and projection endpoints** - `b4f21a5` (feat)
3. **Task 3 (GREEN): Scope rebuild/version state and close the catalog** - `7726b31` (feat)
4. **REFACTOR: Apply the repository format gate** - `7e33f9b` (refactor)

## Files Created/Modified

- `tests/test_tenant_query_scope.py` - Explicit catalogs, reflection gate, bound-parameter checks, edge structure checks, and foreign stable-ID defenses.
- `src/turing_agentmemory_mcp/store_memory_queries.py` - Tenant-scoped memory and temporal-projection endpoints.
- `src/turing_agentmemory_mcp/store_documents_queries.py` - Tenant-scoped document and chunk endpoints.
- `src/turing_agentmemory_mcp/store_rebuild_queries.py` - Tenant-owned vector-version, staging, and community membership statements.
- `src/turing_agentmemory_mcp/store_memory_write.py` - Passes the exact operation tenant into projection edge builders.
- `src/turing_agentmemory_mcp/store_documents.py` - Passes the exact operation tenant into chunk edge builders.
- `src/turing_agentmemory_mcp/store_rebuild.py` - Passes the exact operation tenant into version and staging builders.

## Decisions Made

- Builder discovery follows the public `Statement`/statement-list/sqlscript/DDL contract; classification remains explicit so newly added builders fail the catalog gate.
- Vector-version rows now persist `user_identifier` and all version/staging lookups bind it, even though the stable ID already includes tenant material.
- Schema lifecycle statements remain the only exemptions in this query surface; every exemption is named and justified individually.

## TDD Gate Compliance

- **RED:** `73a9381` produced 19 expected tenant-scope failures and 46 passing catalog cases before production changes.
- **GREEN:** `b4f21a5` removed all memory/document/projection failures; `7726b31` removed the remaining rebuild/version/community failures.
- **REFACTOR:** `7e33f9b` applied Ruff normalization with the focused suite remaining green.

## Automated Validation

- `python -m pytest tests/test_tenant_query_scope.py -q` - 65 passed.
- Focused memory/document/rebuild/retrieval suites - 125 passed.
- `python -m pytest -p no:cacheprovider -q` - 626 passed, 9 integration skips allowed locally.
- `python -m ruff format --check src tests scripts` - 143 files formatted.
- `python -m ruff check src tests scripts` - passed.
- `docker compose config --quiet` - passed.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The deterministic E2E entrypoint could not start because the pre-existing `src/turing_agentmemory_mcp/e2e_score.py` still imports the retired `turingdb` package. This is unrelated to 05-03, was already identified as Phase 4 follow-up debt, and is recorded in `deferred-items.md`; no retired backend dependency was reintroduced.

## Known Stubs

None - the modified-file scan found no newly introduced TODO, FIXME, placeholder, unavailable-data path, or runtime rendering stub.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The application-layer defense-in-depth gate is ready for the remaining physical tenant routing and live isolation plans.
- The query surface is green and future public builders fail closed until classified.

## Self-Check: PASSED

- All seven created/modified implementation and test artifacts exist.
- RED, both GREEN, and REFACTOR commits exist in the required order.
- The catalog contains 44 tenant-scoped builders and five narrow schema exemptions.
- Summary and deferred-item tracking artifacts exist on disk.

---
*Phase: 05-per-tenant-arcadedb-isolation*
*Completed: 2026-07-15*
