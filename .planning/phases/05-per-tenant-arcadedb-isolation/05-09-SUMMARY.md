---
phase: 05-per-tenant-arcadedb-isolation
plan: 09
subsystem: database
tags: [tenant-isolation, hmac, arcadedb, tdd, security]

# Dependency graph
requires:
  - phase: 05-per-tenant-arcadedb-isolation
    provides: TenantRouter/TenantProvisioner/TenantRegistry physical per-tenant ArcadeDB routing (05-05)
provides:
  - "TenantBinding: a keyed, recomputable logical-to-physical tenant binding (tenant_binding.py)"
  - "Instance-bound _StoreCore._require_user that verifies the binding before any client/span/audit activity"
  - "TenantRouter.resolve wiring that constructs and asserts the binding on every routed store"
  - "Adversarial regression proving a tenant-A view rejects tenant B's valid identifier with zero client activity"
affects: [05-10, 05-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Keyed digest binding recomputed via the single existing derive_tenant_database_identity path (no second hashing implementation)"
    - "Per-tenant runtime state (tenant_binding, like client) kept out of the cross-tenant StoreSharedDependencies bundle"

key-files:
  created:
    - src/turing_agentmemory_mcp/tenant_binding.py
    - tests/test_tenant_binding.py
    - tests/_store_arcadedb_core_shared.py
    - tests/test_store_arcadedb_identity.py
  modified:
    - src/turing_agentmemory_mcp/store_core.py
    - src/turing_agentmemory_mcp/tenant_router.py
    - tests/test_tenant_router.py
    - tests/test_store_arcadedb_core.py
    - docs/architecture.md
    - CHANGELOG.md

key-decisions:
  - "TenantBinding.verify() reuses derive_tenant_database_identity verbatim (no local HMAC re-implementation) and compares digests with hmac.compare_digest -- single derivation path, constant-time comparison"
  - "tenant_binding is per-tenant runtime state assigned next to self.client, deliberately excluded from StoreSharedDependencies (that bundle is reused across tenants and would poison the binding)"
  - "Split test_store_arcadedb_core.py into test_store_arcadedb_core.py (seam/bootstrap/health) + test_store_arcadedb_identity.py (tenant-identity/binding) + _store_arcadedb_core_shared.py (shared fixtures) -- the file was already at exactly 600 LOC and Task 2's tenant-binding assertions would have pushed it over the no-allowlist cap (D-08)"

patterns-established:
  - "Fail-closed binding error names only the opaque database_name, never the supplied or bound user_identifier (mirrors _validate_provisioned's existing message style)"

requirements-completed: [ARC-07]

coverage:
  - id: D1
    description: "A routed tenant store rejects a valid-but-foreign user_identifier before any client call, span, or audit event"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_router.py::test_foreign_identifier_rejected_before_client_call"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_identity.py::test_bound_store_rejects_foreign_identifier_via_require_user"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every store constructed by TenantRouter.resolve carries a recomputable keyed TenantBinding derived from the same HMAC-SHA-256 contract used for the database name"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_router.py::test_resolve_binds_logical_tenant_into_store"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_router.py::test_unbound_store_factory_fails_closed"
        status: pass
    human_judgment: false
  - id: D3
    description: "Binding verification recomputes the digest through derive_tenant_database_identity and compares it in constant time; no second hashing path exists"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_binding.py::test_verify_reuses_central_derivation"
        status: pass
      - kind: other
        ref: "python -c \"import hmac,inspect;from turing_agentmemory_mcp import tenant_binding as m;assert 'hmac.new' not in inspect.getsource(m)\""
        status: pass
    human_judgment: false
  - id: D4
    description: "A binding mismatch raises a fail-closed error whose message contains only the opaque database name, never the supplied or bound identifier"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_binding.py::test_foreign_identifier_fails_closed_with_opaque_message"
        status: pass
    human_judgment: false
  - id: D5
    description: "An unbound store (StaticStoreResolver, direct construction) still enforces the central exact validator, so no existing caller loses fail-closed validation"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_identity.py::test_require_user_delegates_to_central_exact_validator"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_identity.py::test_direct_store_rejects_exact_invalid_identity_before_client_activity"
        status: pass
      - kind: integration
        ref: "tests/test_arcadedb_tenant_isolation.py"
        status: pass
    human_judgment: false
  - id: D6
    description: "The tenant-binding contract is documented in architecture.md and CHANGELOG.md in the same change"
    verification:
      - kind: other
        ref: "grep -c TenantBinding docs/architecture.md CHANGELOG.md"
        status: pass
    human_judgment: false

# Metrics
duration: 27min
completed: 2026-07-15
status: complete
---

# Phase 05 Plan 09: Keyed Tenant Binding Contract Summary

**Instance-bound `TenantBinding` (keyed HMAC-SHA-256 digest, reused single derivation path) now verifies every routed store's `user_identifier` before any ArcadeDB client call, span, or audit event, closing verifier gap 1 (ARC-07: physical isolation had no logical counterpart).**

## Performance

- **Duration:** 27 min
- **Started:** 2026-07-15T16:41:19Z
- **Completed:** 2026-07-15T17:05:33Z
- **Tasks:** 3
- **Files modified:** 10 (4 created, 6 modified)

## Accomplishments

- `tenant_binding.py` ships `TenantBinding`/`TenantBindingError`: `verify()` recomputes the digest through the single existing `derive_tenant_database_identity` path and compares it with `hmac.compare_digest`, raising a fail-closed error that names only the opaque `database_name`.
- `_StoreCore._require_user` converted from a static syntax check into an instance method: bound stores enforce the keyed digest via `self.tenant_binding.verify()`; unbound stores (`StaticStoreResolver`, direct construction, the e2e harness) keep delegating to `validate_user_identifier` exactly as before -- no existing caller lost fail-closed validation.
- `TenantRouter.resolve` constructs a `TenantBinding` from the provisioned identity and the provisioner's naming key, passes it into every `store_factory` call, and asserts the returned store carries that exact binding object (mirroring the existing bound-client assertion) -- a factory that drops the binding fails closed with `RuntimeError` naming only the database name.
- Adversarial regression `test_foreign_identifier_rejected_before_client_call` proves a tenant-A view now rejects tenant B's valid `user_identifier` with zero client query/command activity -- the exact reproduction the phase verifier flagged as BLOCKER gap 1.
- `docs/architecture.md`'s Tenant Routing and Provisioning sequence and defense-in-depth list, plus `CHANGELOG.md`'s Added/Changed entries, document the shipped binding contract.

## Task Commits

Each task was committed atomically (TDD tasks have a RED test commit then a GREEN implementation commit):

1. **Task 1: Create the keyed TenantBinding contract** - `e2014ce` (test, RED) then `008621a` (feat, GREEN)
2. **Task 2: Enforce the binding in _StoreCore and wire it through TenantRouter** - `72c3b24` (test, RED) then `27a08ba` (feat, GREEN)
3. **Task 3: Document the tenant binding contract** - `f9d1d1c` (docs)

_TDD RED commits intentionally fail collection/tests until the following GREEN commit lands (verified by running the affected suite between commits)._

## Files Created/Modified

- `src/turing_agentmemory_mcp/tenant_binding.py` - `TenantBinding`/`TenantBindingError`, `TENANT_CORRELATION_KEY`, `verify()`/`correlation()`
- `src/turing_agentmemory_mcp/store_core.py` - `tenant_binding` constructor kwarg + attribute (excluded from `StoreSharedDependencies`); `_require_user` is now an instance method
- `src/turing_agentmemory_mcp/tenant_router.py` - `resolve()` constructs and passes `tenant_binding=`, then asserts the store carries it
- `tests/test_tenant_binding.py` - unit contract: round-trip, opaque-message rejection, validator-first ordering, single-derivation-path reuse, Unicode-lookalike distinctness, correlation
- `tests/test_tenant_router.py` - `test_resolve_binds_logical_tenant_into_store`, `test_foreign_identifier_rejected_before_client_call`, `test_unbound_store_factory_fails_closed`; fakes updated for the new `tenant_binding=` factory kwarg
- `tests/_store_arcadedb_core_shared.py` - new: shared `_StoreCore` seam fixtures (fake ArcadeDB client, stub embedder, `make_store`/`make_full_store`) extracted from `test_store_arcadedb_core.py`
- `tests/test_store_arcadedb_core.py` - slimmed to the seam/bootstrap/health/dead-shim tests; imports fixtures from the new shared module
- `tests/test_store_arcadedb_identity.py` - new: tenant-identity/binding boundary tests moved from `test_store_arcadedb_core.py`, including the rewritten `test_require_user_delegates_to_central_exact_validator` and the new `test_bound_store_rejects_foreign_identifier_via_require_user`
- `docs/architecture.md` - Tenant Routing and Provisioning sequence + defense-in-depth bullets now name `TenantBinding`
- `CHANGELOG.md` - Added entry for `tenant_binding.py`, new Changed section for the instance-bound `_require_user` contract

## Decisions Made

- `TenantBinding.verify()` reuses `derive_tenant_database_identity` verbatim rather than re-deriving a digest locally -- keeps the single HMAC-SHA-256 derivation path (D-03) and lets `verify()` inherit central exact validation for free before any digest compare runs.
- `tenant_binding` is assigned alongside `self.client` in `_StoreCore.__init__`, explicitly outside the `shared_dependencies` conditional block and never added to `StoreSharedDependencies` -- that bundle is reused across tenants and folding in per-tenant binding state would let one tenant's binding leak into another's constructed store.
- Split `test_store_arcadedb_core.py` (exactly 600 LOC before this plan) into three files rather than trimming existing coverage: the file had zero headroom under the no-allowlist 600-LOC cap (D-08) and Task 2 explicitly required growing `test_require_user_delegates_to_central_exact_validator` plus adding a new bound-store test. Shared fixtures moved to `tests/_store_arcadedb_core_shared.py` (matching the existing `_batch_memory_shared.py` convention) rather than duplicating the fake ArcadeDB client across files.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Split test_store_arcadedb_core.py to stay under the 600-LOC cap**
- **Found during:** Task 2 (rewriting `test_require_user_delegates_to_central_exact_validator` and adding a bound-store-rejects test)
- **Issue:** `tests/test_store_arcadedb_core.py` was already at exactly 600 lines before this plan touched it; the plan's required test additions would push it over the no-allowlist cap enforced by `scripts/check-file-size.sh` on every commit (CLAUDE.md: "no file is exempt").
- **Fix:** Extracted shared `_StoreCore` seam fixtures (`FakeArcadeDBClient`, `StubEmbedder`, `TrackingSparseIndex`, `make_store`, `make_full_store`) into a new `tests/_store_arcadedb_core_shared.py` module (matching the established `_batch_memory_shared.py`/`_retrieval_arcadedb_shared.py` convention), moved the tenant-identity/shared-dependency-bundle tests into a new `tests/test_store_arcadedb_identity.py`, and both files now import fixtures from the shared module. `test_store_arcadedb_core.py` dropped to 329 lines, `test_store_arcadedb_identity.py` is 161 lines, and the shared module is 186 lines -- all well under the cap with room for future growth.
- **Files modified:** tests/test_store_arcadedb_core.py, tests/test_store_arcadedb_identity.py (new), tests/_store_arcadedb_core_shared.py (new)
- **Verification:** `bash scripts/check-file-size.sh` exits 0; full affected suite (`test_tenant_router.py`, `test_store_arcadedb_core.py`, `test_store_arcadedb_identity.py`, `test_tenant_binding.py`) passes (57/57)
- **Committed in:** `72c3b24` (Task 2 RED commit, which introduces the split alongside the new failing tests)

### Environment Setup (not a deviation, documented for continuity)

- No `.venv` existed at session start; created one and installed dependencies with `pip install -e . --no-deps` followed by explicit installs of every runtime/dev dependency except `turingdb==1.35`, which has no distribution available on this Windows machine (matches the documented limitation already recorded in 05-07-SUMMARY.md and 05-08-SUMMARY.md, and the `sys.modules["turingdb"]` stub convention already used throughout the test suite). No repository or dependency-pin state was changed to work around this; it is a local-environment limitation, not a product change.

---

**Total deviations:** 1 auto-fixed (1 blocking cap violation)
**Impact on plan:** The file split is a pure test-organization change with zero behavior change to any existing test -- all pre-existing assertions moved verbatim. No scope creep into production code.

## Issues Encountered

None beyond the file-size deviation and environment setup documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ARC-07 verifier gap 1's first two "missing" items are closed: a recomputable keyed digest is bound into every routed store, and it is compared before any query, write, span, or audit.
- Scope note carried into 05-10 (already documented in this plan's objective): this plan makes the guard *correct where it is called*; 05-10 must make the guard *reachable on every public path* (7 methods that currently never call `_require_user`) and enforce call ordering.
- Full repository test suite (766 passed, 11 skipped) and `docker compose config --quiet` both green after this plan.

---
*Phase: 05-per-tenant-arcadedb-isolation*
*Completed: 2026-07-15*

## Self-Check: PASSED

All 10 created/modified files verified present on disk; all 5 task commit hashes (`e2014ce`, `008621a`, `72c3b24`, `27a08ba`, `f9d1d1c`) verified present in `git log --oneline --all`.
