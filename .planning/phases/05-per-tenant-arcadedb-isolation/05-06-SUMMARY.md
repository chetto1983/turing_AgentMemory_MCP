---
phase: 05-per-tenant-arcadedb-isolation
plan: 06
subsystem: api
tags: [arcadedb, multi-tenant, fastmcp, routing, health, tdd]

requires:
  - phase: 05-per-tenant-arcadedb-isolation
    provides: Exact tenant identity, ready-last provisioning, immutable tenant views, shared dependencies, and bounded router reuse from plans 01-05
provides:
  - Strict production environment assembly for one key-bound TenantRouter
  - Resolve-once routing for every memory tool and foreground document data operation
  - Backward-compatible static store injection with mutually exclusive resolver ownership
  - Layered global health that probes shared router readiness without tenant provisioning
affects: [05-07, 05-08, document-workers, physical-isolation-gate, production-compose]

tech-stack:
  added: []
  patterns:
    - Build one unbootstrapped assembly store solely to freeze shared dependencies
    - Resolve one immutable tenant view at each foreground data-operation boundary
    - Keep global runtime health on StoreResolver.runtime_status without tenant resolution

key-files:
  created:
    - tests/test_tenant_server_routing.py
  modified:
    - src/turing_agentmemory_mcp/server.py
    - src/turing_agentmemory_mcp/server_memory_tools.py
    - src/turing_agentmemory_mcp/server_document_tools.py
    - src/turing_agentmemory_mcp/tenant_router.py
    - compose.yaml
    - .env.example

key-decisions:
  - "Construct shared dependencies from an unbootstrapped base-client store; ARCADEDB_DATABASE remains inert connection configuration and is never bootstrapped or selected for tenant operations."
  - "Wrap direct store injection in StaticStoreResolver and reject simultaneous store/resolver arguments so application assembly has exactly one routing owner."
  - "Resolve once inside each foreground tool span and pass the original user_identifier unchanged to both resolver and tenant-bound store."
  - "Report global health exclusively from resolver/router runtime status; tenant resolution and tenant-local damage remain outside the global probe."

patterns-established:
  - "Production assembly: strict key and finite config parsing, registry initialize, provisioner construct, shared dependency freeze, then bounded router publication."
  - "Foreground boundary: resolver.resolve(exact_identifier).memory once, followed by the unchanged explicit store predicate."

requirements-completed: [ARC-07]

coverage:
  - id: D1
    description: "Production application assembly fails closed on naming/config errors and constructs one bounded key/registry-bound router without bootstrapping the legacy shared database."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_tenant_server_routing.py::test_tenant_router_from_env_requires_explicit_strict_naming_key"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_server_routing.py::test_tenant_router_from_env_rejects_unbounded_or_non_positive_configuration"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_server_routing.py::test_tenant_router_from_env_builds_shared_dependencies_without_bootstrapping_legacy_db"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every memory tool and foreground document text/search/reindex/delete operation resolves exactly once and preserves exact tenant identity into the selected store."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_tenant_server_routing.py::test_each_tenant_tool_resolves_once_and_passes_exact_identifier_to_store"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_server_routing.py::test_case_and_unicode_variants_select_distinct_views_without_transformation"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_server_routing.py::test_invalid_identity_fails_before_foreground_store_action"
        status: pass
    human_judgment: false
  - id: D3
    description: "Static injected stores remain compatible while global health and memory_runtime_status stay non-provisioning and independent of tenant-local failure."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_tenant_server_routing.py::test_create_mcp_app_static_store_bypasses_router_config_and_rejects_ambiguous_injection"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_server_routing.py::test_global_health_uses_non_provisioning_resolver_status"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_server_routing.py::test_memory_runtime_status_uses_global_resolver_without_tenant_resolution"
        status: pass
    human_judgment: false
  - id: D4
    description: "Compose and environment examples expose every finite tenant-routing setting while requiring an operator-generated naming key with no fallback secret."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_tenant_server_routing.py::test_compose_and_env_example_publish_required_router_settings_without_key_fallback"
        status: pass
      - kind: other
        ref: "docker compose config --quiet"
        status: pass
    human_judgment: false

duration: 17min
completed: 2026-07-15
status: complete
---

# Phase 05 Plan 06: Foreground Tenant Router Integration Summary

**FastMCP production assembly now fails closed into one key-bound TenantRouter, and every foreground memory/document data call resolves one immutable tenant store while global health remains non-provisioning.**

## Performance

- **Duration:** 17 min
- **Started:** 2026-07-15T11:52:46Z
- **Completed:** 2026-07-15T12:10:14Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Added strict production router assembly from the naming key, durable registry, ready-last provisioner, frozen shared dependencies, and finite cache/retry configuration.
- Routed all 13 memory operations and 4 foreground document data operations through exactly one immutable tenant view without transforming the explicit user identifier.
- Preserved direct fake/store injection through `StaticStoreResolver`, rejected ambiguous dual injection, and kept public FastMCP contracts green.
- Layered `/health` and `memory_runtime_status` on global resolver readiness without provisioning, enumerating, or inspecting a tenant.
- Documented all tenant environment settings in Compose and `.env.example`, leaving the naming key required and empty with a secure generation command.

## Task Commits

Each behavior task followed an independent RED then GREEN cycle:

1. **Task 1 RED: Specify strict router assembly, static injection, health, and deployment config** - `be8e6db` (test)
2. **Task 1 GREEN: Assemble the production router and layered global health** - `afa2ef7` (feat)
3. **Task 2 RED: Specify exhaustive resolve-once foreground routing** - `1a03f44` (test)
4. **Task 2 GREEN: Route foreground tools through tenant-bound stores** - `67c4529` (feat)

## Files Created/Modified

- `tests/test_tenant_server_routing.py` - Strict config, assembly, static injection, health, 17-operation resolve-once, exact identity, invalid-boundary, and deployment tests.
- `src/turing_agentmemory_mcp/server.py` - Unbootstrapped shared dependency assembly, `tenant_router_from_env`, resolver ownership, and layered health.
- `src/turing_agentmemory_mcp/server_memory_tools.py` - Resolver contract for all memory operations and global runtime status.
- `src/turing_agentmemory_mcp/server_document_tools.py` - Resolver contract for foreground document text, reindex, delete, and search operations.
- `src/turing_agentmemory_mcp/tenant_router.py` - Global runtime-status protocol and static-store delegation.
- `compose.yaml` - Required naming key plus finite registry/cache/provisioning settings for the MCP service.
- `.env.example` - Operator generation guidance and documented router defaults.

## Decisions Made

- Kept `store_from_env` as an explicitly non-routing compatibility constructor while ensuring the no-argument production app path exclusively creates `TenantRouter`.
- Built shared dependencies from one store instance without invoking `bootstrap`; tenant provisioners replace the base client with the derived opaque database before any tenant schema/data operation.
- Kept upload/job-control tools on their existing stores in this foreground plan; plan 05-07 owns exact-identity upload persistence and per-job background resolver integration.
- Used the actual Phase 05-05 `TenantStoreView.memory` field rather than the plan prose's stale `.store` label.

## TDD Gate Compliance

- **Task 1 RED:** `be8e6db` produced 10 expected failures for the missing router factory, resolver app seam, layered health, and environment documentation.
- **Task 1 GREEN:** `afa2ef7` made the 17 assembly/runtime tests pass without bootstrapping the legacy database.
- **Task 2 RED:** `1a03f44` produced 25 expected failures because registrars still invoked the resolver as a singleton store; the already-correct global runtime-status test passed and was preserved.
- **Task 2 GREEN:** `67c4529` made all 36 routing tests and the 45-test focused server/document suite pass.
- **REFACTOR:** No separate refactor commit was needed; GREEN was formatted, Ruff-clean, and well below the 600-line cap.
- **Order:** Each `test(05-06)` commit immediately precedes its corresponding `feat(05-06)` commit.

## Automated Validation

- `python -m pytest tests/test_tenant_server_routing.py tests/test_runtime_pipeline.py -q` - 17 passed after Task 1.
- `python -m pytest tests/test_tenant_server_routing.py tests/test_server_batch_tool.py tests/test_document_ingest_file.py tests/test_document_file_pipe.py -q` - 45 passed after Task 2.
- `python -m pytest -p no:cacheprovider -q` - 729 passed, 9 integration skips allowed locally.
- `python -m ruff check src tests scripts` - passed.
- `python -m ruff format --check src tests scripts` - 148 files formatted.
- `docker compose config --quiet` - passed.
- CRLF-normalized `scripts/check-file-size.sh` content - all tracked Python files within the 600-line cap.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added global runtime status to the static resolver contract**
- **Found during:** Task 1 (layered global health)
- **Issue:** Phase 05-05 shipped `StaticStoreResolver.resolve` but not the plan-required `runtime_status` delegation, so injected stores could not participate in the same non-provisioning health/status path as production routing.
- **Fix:** Extended `StoreResolver` with global runtime status and made `StaticStoreResolver` delegate to the injected store with a content-free ready fallback.
- **Files modified:** `src/turing_agentmemory_mcp/tenant_router.py`
- **Verification:** Static injection, `/health`, and `memory_runtime_status` tests pass.
- **Committed in:** `afa2ef7`

---

**Total deviations:** 1 auto-fixed (1 missing critical functionality).
**Impact on plan:** The fix completes the planned compatibility contract without changing tenant routing, public tool schemas, or tenant data behavior.

## Issues Encountered

- The tracked shell script is checked out with CRLF and this Bash binary rejects `set -o pipefail\r`; piping the same script content through carriage-return removal produced the passing file-size result without changing the repository script.

## Known Stubs

None - the touched-file scan found no TODO, FIXME, placeholder, `NotImplementedError`, or incomplete runtime path introduced by this plan.

## User Setup Required

- Production operators must set a stable base64 `AGENTMEMORY_TENANT_NAMING_KEY` containing at least 32 random bytes. `.env.example` includes a standard-library generation command; there is deliberately no default.
- Registry/cache/provisioning values have finite defaults and may be overridden through the documented environment names.

## Next Phase Readiness

- Plan 05-07 can route upload ownership, durable job persistence, and document workers through the same exact resolver boundary.
- Plan 05-08 can exercise the assembled production router in the live A/B/C physical-isolation and lifecycle-chaos gate.
- No blockers remain from foreground integration.

## Self-Check: PASSED

- All seven implementation/test/config artifacts and this summary exist on disk.
- Task 1 RED/GREEN commits `be8e6db`/`afa2ef7` and Task 2 RED/GREEN commits `1a03f44`/`67c4529` exist in the required order.
- Focused, full-suite, Ruff, format, Compose, file-size, and coverage-classifier gates pass; all four deliverables are deterministically auto-covered.

---
*Phase: 05-per-tenant-arcadedb-isolation*
*Completed: 2026-07-15*
