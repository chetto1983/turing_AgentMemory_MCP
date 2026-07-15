---
phase: 05-per-tenant-arcadedb-isolation
plan: 04
subsystem: database
tags: [arcadedb, multi-tenant, provisioning, manifest, ready-last, tdd]

requires:
  - phase: 04-arcadedb-direct-port
    provides: Direct ArcadeDB transport and idempotent native schema bootstrap
  - phase: 05-per-tenant-arcadedb-isolation
    provides: Exact pseudonymous tenant identity and durable tenant registry from plans 01-02
provides:
  - Idempotent per-tenant ArcadeDB creation with duplicate-create reconciliation
  - Immutable singleton tenant manifest verified before registry-ready promotion
  - Bounded transient-only lifecycle retries with deterministic failures left untouched
affects: [05-05, 05-06, 05-07, 05-08, tenant-routing, startup-readiness]

tech-stack:
  added: []
  patterns:
    - Registry begin, database reconcile, schema bootstrap, manifest reread, registry ready
    - Immutable client rebinding per opaque tenant database
    - Constant-time digest and key-fingerprint manifest verification

key-files:
  created:
    - src/turing_agentmemory_mcp/tenant_provisioning.py
    - tests/test_tenant_provisioning.py
  modified:
    - src/turing_agentmemory_mcp/arcadedb_client.py
    - src/turing_agentmemory_mcp/arcadedb_schema.py
    - tests/test_arcadedb_client_transport.py
    - tests/test_arcadedb_schema.py

key-decisions:
  - "Promote the tenant registry to ready only after the immutable singleton manifest is durably reread and exactly verified."
  - "Use the durable registry record's created_at as the authoritative manifest timestamp so concurrent contenders converge on the winner's identity."
  - "Retry only classified transient failures; reconcile duplicate create by relisting, while ready/missing and manifest mismatch states fail closed without mutation."

patterns-established:
  - "Ready-last provisioning: registry-ready is the final durable lifecycle boundary and never substitutes for manifest verification."
  - "Race convergence: duplicate database or manifest creation is evidence to reconcile, never evidence of success by itself."

requirements-completed: [ARC-07]

coverage:
  - id: D1
    description: "New, resumed, raced, and fault-interrupted tenant provisioning converges only after durable manifest verification."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_tenant_provisioning.py::test_ready_manifest_is_written_last"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_provisioning.py::test_fault_after_each_boundary_never_serves_and_later_resumes"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_provisioning.py::test_contenders_use_winning_registry_created_at"
        status: pass
    human_judgment: false
  - id: D2
    description: "Lifecycle list/create requests use the exact authenticated server-command transport and preserve bounded retry classifications."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_arcadedb_client_transport.py::test_list_databases_posts_authenticated_server_command"
        status: pass
      - kind: unit
        ref: "tests/test_arcadedb_client_transport.py::test_lifecycle_command_retries_identical_request_then_decodes_success"
        status: pass
      - kind: unit
        ref: "tests/test_arcadedb_client_transport.py::test_lifecycle_transport_failures_preserve_runtime_error_classification"
        status: pass
    human_judgment: false
  - id: D3
    description: "The tenant manifest schema is unique, pseudonymous, immutable by contract, and mismatch states fail without create or drop."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_arcadedb_schema.py::test_bootstrap_creates_immutable_tenant_manifest_contract"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_provisioning.py::test_ready_missing_database_fails_closed_without_create_or_drop"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_provisioning.py::test_ready_manifest_mismatch_fails_once_without_mutation"
        status: pass
    human_judgment: false

duration: 21min
completed: 2026-07-15
status: complete
---

# Phase 05 Plan 04: Ready-Last Tenant Database Provisioning Summary

**Per-tenant ArcadeDB provisioning now reconciles creation races, verifies an immutable pseudonymous manifest, and promotes registry readiness only as the final durable step.**

## Performance

- **Duration:** 21 min
- **Started:** 2026-07-15T10:59:41Z
- **Completed:** 2026-07-15T11:20:07Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Implemented idempotent new/resume provisioning across registry, database lifecycle, schema bootstrap, manifest insertion, manifest reread, and ready promotion.
- Added duplicate-create and duplicate-manifest convergence while keeping ready/missing, malformed, ambiguous, and mismatched states fail closed.
- Added exact authenticated server lifecycle methods plus bounded exponential backoff with jitter for transient failures only.

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Specify the ready-last provisioning state machine and every fault boundary** - `5c91479` (test)
2. **Task 2 (GREEN): Implement database reconciliation, bootstrap, manifest, and bounded retries** - `d8267cd` (feat)

## Files Created/Modified

- `src/turing_agentmemory_mcp/tenant_provisioning.py` - Frozen contracts and the ready-last, retry-bounded tenant provisioner.
- `tests/test_tenant_provisioning.py` - State, race, fault-boundary, retry, and leakage contracts.
- `src/turing_agentmemory_mcp/arcadedb_client.py` - Exact list/create database lifecycle methods.
- `src/turing_agentmemory_mcp/arcadedb_schema.py` - Singleton tenant manifest type, properties, and unique index.
- `tests/test_arcadedb_client_transport.py` - Authenticated request-shape, retry, malformed-response, and classification coverage.
- `tests/test_arcadedb_schema.py` - Immutable manifest schema contract coverage.

## Decisions Made

- Registry `ready` is written only after the manifest insert has been followed by a successful exact reread and verification.
- The registry's durable `created_at` wins concurrent races and is copied into the manifest; a losing contender accepts only the exact stale-transition conflict after confirming the same ready record.
- Digest and key fingerprint comparisons use constant-time comparison; errors expose only opaque database identity and never the raw tenant identifier.
- Retry classification is narrow and finite: transient network, retryable HTTP, MVCC, and unavailable errors retry; deterministic contract and mismatch failures do not.

## TDD Gate Compliance

- **RED:** `5c91479` produced 25 expected `NotImplementedError` failures and one interface-contract pass before production behavior existed.
- **GREEN transport:** the added lifecycle transport tests first produced 11 expected missing-method failures.
- **GREEN:** `d8267cd` removes all focused failures; the final provisioning/transport/schema suite passes 57 tests.
- **REFACTOR:** No separate refactor was needed after the green implementation passed formatting and lint unchanged.

## Automated Validation

- `python -m pytest tests/test_tenant_provisioning.py tests/test_arcadedb_client_transport.py tests/test_arcadedb_schema.py -q` - 57 passed.
- `python -m pytest -p no:cacheprovider -q` - 664 passed, 9 integration skips allowed locally.
- `python -m ruff check src tests scripts` - passed.
- `python -m ruff format --check src tests scripts` - 145 files formatted.
- `scripts/check-file-size.sh` - all tracked Python files within the 600-line cap.
- `docker compose config --quiet` - passed.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Fault injection caught an over-broad race-convergence handler that could absorb a deterministic failure after registry promotion; it was narrowed to the registry's exact stale-transition conflict before the green commit.

## Known Stubs

None - the modified-file scan found no TODO, FIXME, placeholder, `NotImplementedError`, unavailable-data path, or runtime rendering stub.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The ready-last provisioner and immutable manifest contract are ready to be wired into request routing and startup orchestration.
- Future lifecycle code can consume an immutable tenant-bound client only after this provisioner returns.

## Self-Check: PASSED

- All six implementation and test artifacts plus this summary exist on disk.
- RED `5c91479` and GREEN `d8267cd` exist in the required order.
- Focused and full verification gates pass, and the worktree contains only this completion artifact before tracking updates.

---
*Phase: 05-per-tenant-arcadedb-isolation*
*Completed: 2026-07-15*
