---
phase: 05-per-tenant-arcadedb-isolation
plan: 02
subsystem: database-security
tags: [python, sqlite, tenant-isolation, lifecycle, fail-closed]

# Dependency graph
requires:
  - phase: 05-per-tenant-arcadedb-isolation
    plan: 01
    provides: "Opaque tenant database names, full digests, naming versions, and non-secret key fingerprints"
provides:
  - "Durable pseudonymous SQLite inventory for tenant database lifecycle state"
  - "Immutable deployment binding to registry schema, naming version, and naming-key fingerprint"
  - "Idempotent provisioning registration and atomic provisioning-to-ready promotion"
  - "Fail-closed reopen behavior for malformed, corrupt, missing, or incompatible registries"
affects: [05-04-tenant-provisioning, 05-05-tenant-router, 05-08-isolation-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Connection-per-operation SQLite with finite busy timeout, WAL, FULL synchronous writes, and short BEGIN IMMEDIATE transactions"
    - "Ready evidence: provisioning inserts are idempotent, ready promotion is compare-and-set, and ready rows are never demoted"

key-files:
  created:
    - src/turing_agentmemory_mcp/tenant_registry.py
    - tests/test_tenant_registry.py
  modified: []

key-decisions:
  - "A registry file is created only when the path is truly absent; an existing empty or malformed SQLite file is evidence of corruption and fails closed without schema repair."
  - "An idempotent begin_provisioning call returns the winner's durable record unchanged, preserving its authoritative created_at across later contenders and never demoting ready."
  - "Runtime status exposes only content-free configuration readiness—schema version, naming version, and non-secret key fingerprint—with no tenant inventory."

patterns-established:
  - "Registry metadata and tenant lifecycle rows are validated on reopen before any provisioning write can occur."
  - "Opaque database name and full digest form a one-to-one identity through name coherence plus a unique digest constraint."

requirements-completed: [ARC-07]

coverage:
  - id: D1
    description: "Registry initialization durably binds schema version, naming version, and key fingerprint, while matching reopen preserves opaque lifecycle rows"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_registry.py#test_initialize_reopen_preserves_versioned_registry_records"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_registry.py#test_reopen_rejects_immutable_metadata_drift_before_writes"
        status: pass
    human_judgment: false
  - id: D2
    description: "Provisioning registration is identity-safe and idempotent, while ready promotion is an atomic provisioning-only transition"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_registry.py#test_begin_provisioning_is_idempotent_and_never_demotes_ready"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_registry.py#test_begin_provisioning_rejects_database_name_digest_mismatches"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_registry.py#test_mark_ready_is_an_atomic_provisioning_only_transition"
        status: pass
    human_judgment: false
  - id: D3
    description: "Concurrent connection-per-operation writers retain complete rows and reach ready without lost updates or shared-connection state"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_registry.py#test_concurrent_writers_preserve_complete_ready_rows"
        status: pass
    human_judgment: false
  - id: D4
    description: "Raw tenant identifiers never enter registry APIs, serialized records, or SQLite bytes, and corrupt schema, metadata, state, identity, or file content fails closed"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_registry.py#test_registry_never_persists_raw_user_identifier"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_registry.py#test_missing_schema_or_metadata_fails_closed_without_repair"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_registry.py#test_corrupt_metadata_or_tenant_rows_fail_closed"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_registry.py#test_non_sqlite_registry_bytes_fail_closed_without_replacement"
        status: pass
    human_judgment: false

# Metrics
duration: 10min
completed: 2026-07-15
status: complete
---

# Phase 05 Plan 02: Durable Pseudonymous Tenant Registry Summary

**A WAL-backed SQLite registry now preserves opaque tenant provisioning and ready evidence across restart while rejecting naming drift, corrupt state, and raw-identity persistence.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-15T10:19:15Z
- **Completed:** 2026-07-15T10:29:11Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added an immutable, versioned registry metadata binding so changing the naming version or naming-key fingerprint fails before tenant rows can be written.
- Added idempotent opaque provisioning records and an atomic compare-and-set promotion to ready, retaining the durable winner's creation timestamp and preventing ready demotion.
- Added fail-closed validation for missing/malformed schemas, metadata drift, invalid states, name/digest mismatch, and non-SQLite bytes without destructive repair.
- Proved restart persistence, concurrent writers, pseudonymous-only storage, and lifecycle transitions through 17 focused tests and the 561-test repository suite.

## Task Commits

Each TDD gate was committed atomically:

1. **Task 1 (RED): Specify registry persistence, metadata binding, and lifecycle transitions** - `c7d6a67` (test)
2. **Task 2 (GREEN): Implement transactional SQLite registry with fail-closed reopen** - `a029886` (feat)

No REFACTOR commit was needed; the GREEN implementation is a focused 346-line standard-library module with no shared connection or unnecessary abstraction.

## Files Created/Modified

- `src/turing_agentmemory_mcp/tenant_registry.py` - Frozen lifecycle records, immutable metadata binding, short SQLite transactions, idempotent provisioning, ready promotion, validation, and content-free status.
- `tests/test_tenant_registry.py` - Reopen, drift, transition, concurrency, corruption, schema-loss, API-surface, and raw-byte leakage coverage.

## Decisions Made

- Used a singleton metadata row inside the same registry transaction as schema creation, binding schema version, naming version, key fingerprint, and registry creation time permanently.
- Treated an existing file without the exact registry schema as corrupt rather than interpreting it as a new registry, so startup never disguises lost ready evidence.
- Made duplicate provisioning a no-op for the same name/digest and preserved the existing record unchanged; a name/digest conflict raises without writing.
- Kept runtime status tenant-content-free while returning the non-secret fingerprint needed to diagnose configuration binding.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Persisted the progress value returned by the GSD state updater**
- **Found during:** Plan close-out
- **Issue:** `state.update-progress` returned 28/34 completed and 82%, but left the prior 31% frontmatter value and 79% rendered progress line in `STATE.md`.
- **Fix:** Updated both stale progress fields to the handler's returned 82% value after all plan summaries were present.
- **Files modified:** `.planning/STATE.md`
- **Verification:** `STATE.md` reports Plan 3 of 8, 28 completed plans, and 82% consistently.
- **Committed in:** Final plan metadata commit.

---

**Total deviations:** 1 auto-fixed (1 blocking close-out state-sync issue).
**Impact on plan:** Planning metadata now matches the GSD handler result; production scope and behavior are unchanged.

## Issues Encountered

- The unqualified `bash` command resolves to Windows' WSL launcher in this shell and rejects the checkout's CRLF script at `set -euo pipefail`. The repository's installed Git Bash executed the same tracked `scripts/check-file-size.sh` successfully with no file changes; all tracked Python files are within the 600-line cap.

## Verification Results

- `python -m pytest tests/test_tenant_registry.py -q`: **17 passed**.
- `python -m pytest -p no:cacheprovider -q`: **561 passed, 9 skipped** (existing local integration/GPU skip policy; no new skips).
- `python -m ruff check src tests scripts`: **All checks passed**.
- `python -m ruff format --check src tests scripts`: **142 files already formatted**.
- Git Bash execution of `scripts/check-file-size.sh`: **all tracked `*.py` files within the 600-LOC cap**.
- `docker compose config --quiet`: **exit 0**.
- `rg "user_identifier" src/turing_agentmemory_mcp/tenant_registry.py`: **no matches**.
- Stub scan (`NotImplementedError|TODO|FIXME|placeholder|coming soon|not available`): **no matches in changed files**.
- Git log order: `c7d6a67` (RED) precedes `a029886` (GREEN).

## TDD Gate Compliance

| Gate | Commit | Result |
|------|--------|--------|
| RED | `c7d6a67` | Focused behavior tests reached the public registry stubs and failed on `NotImplementedError` before production behavior existed |
| GREEN | `a029886` | 17 focused tests and the full repository validation gate passed |
| REFACTOR | Not needed | Minimal implementation remained green without a cleanup change |

## User Setup Required

None - this plan adds no external service or environment configuration.

## Next Phase Readiness

- Plan 05-03 can continue the independent defense-in-depth query-scope audit.
- Plan 05-04 can consume the registry's durable `created_at`, provisioning/ready distinction, metadata binding, and fail-closed missing-ready evidence.
- No implementation blocker remains.

---
*Phase: 05-per-tenant-arcadedb-isolation*
*Completed: 2026-07-15*

## Self-Check: PASSED

- FOUND: `.planning/phases/05-per-tenant-arcadedb-isolation/05-02-SUMMARY.md`
- FOUND: `src/turing_agentmemory_mcp/tenant_registry.py`
- FOUND: `tests/test_tenant_registry.py`
- FOUND: `c7d6a67` (RED commit)
- FOUND: `a029886` (GREEN commit)
- VERIFIED ORDER: `c7d6a67` before `a029886`
