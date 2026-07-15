---
phase: 05-per-tenant-arcadedb-isolation
plan: 08
subsystem: live-isolation-and-operations
tags: [arcadedb, multi-tenant, physical-isolation, lifecycle-chaos, compose, tdd]

requires:
  - phase: 05-per-tenant-arcadedb-isolation
    provides: Exact identity, ready-last provisioning, immutable routing, and background job resolution from plans 01-07
provides:
  - Live three-tenant physical-plus-predicate isolation proof against pinned ArcadeDB
  - Live first-use, cache eviction, missing-ready, restart, and real-file lifecycle proof
  - Production Compose contract with no shared tenant-data database fallback
  - Operator guidance for naming keys, registry recovery, layered health, and deferred lifecycle boundaries
affects: [06-parity-gate, 07-turingdb-removal, operations, tenant-security]

tech-stack:
  added: []
  patterns:
    - Derive and clean up only fixed fixture-owned opaque database names
    - Prove physical separation with direct database inspection and predicate capture
    - Exercise cache and restart behavior through fresh immutable views over durable tenant databases
    - Keep shell validation scripts LF-normalized across Windows checkouts

key-files:
  created:
    - tests/test_arcadedb_physical_tenant_isolation.py
    - tests/_arcadedb_physical_isolation_support.py
    - tests/_arcadedb_lifecycle_isolation_support.py
    - .gitattributes
  modified:
    - compose.yaml
    - .env.example
    - tests/test_compose_config.py
    - docs/architecture.md
    - docs/configuration.md
    - CHANGELOG.md
    - AGENTS.md
    - CLAUDE.md
    - CONTRIBUTING.md
    - scripts/check-file-size.sh

key-decisions:
  - "Use one module-scoped live environment with a fixed HMAC key and an exact derived cleanup allowlist; never enumerate-and-drop unrelated databases."
  - "Inspect tenant record types and captured query parameters directly so physical database separation and mandatory user_identifier predicates are independently proven."
  - "Treat a ready registry row whose database disappeared as an incident: fail closed and leave it absent rather than silently provisioning an empty replacement."
  - "Use the same production TenantRouter for the real asynchronous file worker and foreground cited search."
  - "Remove ARCADEDB_DATABASE from production Compose because tenant data is selected only through opaque per-tenant routing."

patterns-established:
  - "Live isolation gate: concurrent public workloads, adversarial foreign IDs, direct database inspection, and diagnostic raw-identifier scans all agree before the gate passes."
  - "Lifecycle gate: first use, bounded cache reuse, active references, missing-ready, scoped service restart, and real-file jobs preserve exact tenant binding and durable data."
  - "Operator contract: registry, naming key, manifest, router, and tenant predicates are separate defense layers with explicit recovery and deferred boundaries."

requirements-completed: [ARC-07, TEST-05]

coverage:
  - id: D1
    description: "Concurrent A/B/C memory and document operations land in separate live databases, retain tenant predicates, deny foreign IDs, and expose no raw tenant identifiers in registry or diagnostics."
    requirement: TEST-05
    verification:
      - kind: integration
        ref: "tests/test_arcadedb_physical_tenant_isolation.py::test_physical_three_tenant_database_and_predicate_isolation"
        status: pass
      - kind: integration
        ref: "direct Memory/Document/Chunk/Entity/Fact/Community and TenantManifest inspection"
        status: pass
    human_judgment: false
  - id: D2
    description: "Live first-use races, cache capacity/TTL eviction, active references, missing-ready failure, restart recovery, and real-file background ingestion preserve physical tenant binding and durable data."
    requirement: ARC-07
    verification:
      - kind: integration
        ref: "tests/test_arcadedb_physical_tenant_isolation.py::test_lifecycle_chaos_preserves_tenant_binding_and_durable_data"
        status: pass
      - kind: e2e
        ref: "python scripts/e2e_score.py --out e2e-results.json (Windows retained-dependency shim)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Compose pins ArcadeDB, persists registry state, injects a required naming key, bounds cache/retries, reports layered health, and has no shared tenant-data database fallback."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_compose_config.py::test_product_service_locks_the_physical_tenant_database_contract"
        status: pass
      - kind: integration
        ref: "docker compose config --quiet"
        status: pass
    human_judgment: false

duration: 47min
completed: 2026-07-15
status: complete
---

# Phase 05 Plan 08: Live Physical Tenant Isolation and Operations Summary

**The pinned live ArcadeDB service now proves database-per-tenant isolation, lifecycle durability, and production deployment contracts across foreground and asynchronous document paths.**

## Performance

- **Duration:** 47 min
- **Started:** 2026-07-15T12:48:12Z
- **Completed:** 2026-07-15T13:35:24Z
- **Tasks:** 3
- **Files modified:** 14

## Accomplishments

- Ran concurrent A/B/C memory and document CRUD/search workloads against separate HMAC-derived live databases, including identical collision-prone inputs and tenant-specific canaries.
- Proved every tenant record type and captured query predicate stays exact, while foreign memory/document IDs cannot read, mutate, delete, filter, or leak across databases.
- Proved same-tenant single flight, unrelated-tenant overlap, capacity and TTL cache reuse, usable active evicted references, and fail-closed missing-ready reconciliation.
- Stopped and restarted only the scoped `arcadedb` Compose service, observed real health and operation degradation, then recovered the exact pre-restart record without recreating the database.
- Sent a real Markdown file through the production asynchronous manager/router path to truthful success, canonical chunks, cited scoped search, foreign-tenant absence, and staged-byte removal.
- Locked Compose and public operator guidance to ArcadeDB canonical truth, required keyed tenant naming, durable registry recovery, layered health, and explicit deferred OIDC/rotation/offboarding/reporting/fleet boundaries.

## Task Commits

Each behavior task followed the requested RED then GREEN order:

1. **Task 1 RED: Specify live physical tenant isolation** - `a222bc3` (test)
2. **Task 1 GREEN: Prove live physical tenant isolation** - `9f10f8a` (feat)
3. **Task 2 RED: Specify live tenant lifecycle chaos** - `552e97b` (test)
4. **Task 2 GREEN: Prove live tenant lifecycle isolation** - `39652e7` (test)
5. **Task 3: Lock physical tenant deployment and operator contracts** - `37dd26f` (docs)
6. **Verification fix: Keep shell validation gates LF on Windows** - `a5514ff` (fix)

## Files Created/Modified

- `tests/test_arcadedb_physical_tenant_isolation.py` - Module-scoped live fixture and physical/lifecycle acceptance contracts.
- `tests/_arcadedb_physical_isolation_support.py` - Pinned-service assembly, exact fixture cleanup, concurrent workloads, direct database inspection, predicate capture, and adversarial boundaries.
- `tests/_arcadedb_lifecycle_isolation_support.py` - First-use barriers, deterministic cache clock, missing-ready failure, scoped restart, and real-file worker lifecycle.
- `compose.yaml` / `.env.example` - Removed the shared tenant-data fallback and aligned layered health and tenant configuration truth.
- `tests/test_compose_config.py` - Pinned image, persistent registry, required key, bounded cache/retry, layered health, and no-fallback policy assertions.
- `docs/architecture.md` / `docs/configuration.md` - Implemented routing flow, defense layers, key handling, backup/recovery, health, and deferred operations.
- `AGENTS.md` / `CLAUDE.md` / `CONTRIBUTING.md` / `CHANGELOG.md` - Replaced obsolete canonical-store guidance and recorded ARC-07/TEST-05.
- `.gitattributes` / `scripts/check-file-size.sh` - LF-normalized Bash validation on Windows.

## Decisions Made

- All destructive test operations are confined to the exact opaque names derived from the fixture's fixed tenant list and key. The pre-existing E2E database remains outside that allowlist.
- Live proof uses production `TenantProvisioner`, `TenantRouter`, `TuringAgentMemory`, registry, and document manager; only deterministic provider dependencies replace external model inference.
- Registry-ready plus missing database is deliberately non-recoverable by provisioning. Operators must restore consistent database/registry/key backups rather than hide loss with an empty tenant.
- Production health is global and layered for ArcadeDB, registry, and router state; tenant manifest health remains per-resolve so one damaged tenant does not mark all tenants unhealthy.
- The retained TuringDB-named compatibility settings are documented as transitional and never described as the canonical tenant store.

## TDD Gate Compliance

- **Task 1 RED:** `a222bc3` failed because no live derived databases or workload proof existed.
- **Task 1 GREEN:** `9f10f8a` passed the focused physical isolation test against `arcadedata/arcadedb:26.7.1`.
- **Task 2 RED:** `552e97b` failed on the first absent lifecycle proof field.
- **Task 2 GREEN:** `39652e7` passed both live tests, including the real scoped restart and asynchronous file worker.
- **REFACTOR:** The live harness was split into leading-underscore support siblings before crossing the mandatory 600-line cap; no production behavior was duplicated or weakened.
- **Order:** Each RED commit immediately precedes its corresponding GREEN commit.

## Automated Validation

- `python -m pytest tests/test_arcadedb_physical_tenant_isolation.py -q` - 2 passed in 40.74s.
- `python -m pytest -q` - 765 passed, 1 intentional local guard skip, 1 optional ffmpeg warning in 99.30s.
- `python -m ruff check src tests scripts` - passed.
- `python -m ruff format --check src tests scripts` - 151 files formatted.
- `docker compose config --quiet` - passed.
- `bash scripts/check-file-size.sh` - all tracked Python files within the 600-line cap.
- ArcadeDB-backed `scripts/e2e_score.py` through the documented Windows retained-dependency shim - 19/19 checks, score 10.0, `VALIDATED_10_10`.
- Post-fixture database inventory - only the dedicated `e2e_agent_memory` database remained.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Split the live harness before the 600-line hard gate**
- **Found during:** Task 1 GREEN and Task 2 GREEN design.
- **Issue:** Keeping all live setup, workload, inspection, restart, and document lifecycle code in the requested public test module would exceed the repository's mandatory 600-line cap.
- **Fix:** Kept the fixture and acceptance tests in the requested module and extracted implementation-only helpers into two established leading-underscore test support siblings.
- **Files modified:** `tests/test_arcadedb_physical_tenant_isolation.py`, `tests/_arcadedb_physical_isolation_support.py`, `tests/_arcadedb_lifecycle_isolation_support.py`
- **Verification:** Both live tests pass and every tracked Python file remains under 600 lines.
- **Committed in:** `9f10f8a`, `39652e7`

**2. [Rule 2 - Missing Critical] Corrected stale canonical-store guidance**
- **Found during:** Task 3 operator contract review.
- **Issue:** Repository guidance still described TuringDB restart, batch, and canonical-store invariants that are false for the implemented ArcadeDB port.
- **Fix:** Updated architecture, configuration, contributor/agent guidance, and changelog to the implemented ArcadeDB database-per-tenant truth and retained only explicitly transitional compatibility names.
- **Files modified:** `docs/architecture.md`, `docs/configuration.md`, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `.env.example`
- **Verification:** Policy tests, documentation keyword audit, full suite, and Compose config pass.
- **Committed in:** `37dd26f`

**3. [Rule 3 - Blocking] Made the mandated Bash file-size gate executable on Windows**
- **Found during:** Task 3 full verification.
- **Issue:** Git stored the script as LF but checked it out as CRLF because no attributes policy existed; Bash rejected `set -o pipefail\r` before checking any file.
- **Fix:** Added `*.sh text eol=lf` and normalized `scripts/check-file-size.sh`.
- **Files modified:** `.gitattributes`, `scripts/check-file-size.sh`
- **Verification:** `git ls-files --eol` reports `w/lf`, and the mandated script passes without a filter or wrapper.
- **Committed in:** `a5514ff`

---

**Total deviations:** 3 auto-fixed (1 file-size blocker, 1 critical documentation correction, 1 cross-platform validation blocker).
**Impact on plan:** All fixes were required to execute or truthfully document the requested live isolation gate; none broadened production tenant lifecycle capabilities.

## Issues Encountered

- This Windows Python cannot install the retained `turingdb==1.35` package because no compatible distribution exists. The final E2E used the Phase-4-documented in-memory import shim only for the retained version/re-export seam; all 19 product checks ran against the real pinned ArcadeDB service and the repository was not changed to hide the platform condition.
- The full suite emits one `pydub` warning because optional ffmpeg/avconv is absent; the real Markdown document path and every required test still pass.

## Authentication Gates

None.

## Known Stubs

No product or committed test stub replaces ArcadeDB. The live harness uses deterministic embed/rerank/extraction dependencies, and the Windows-only transient `turingdb` import shim is documented above.

## User Setup Required

Production operators must inject one stable strict-base64 `AGENTMEMORY_TENANT_NAMING_KEY` containing at least 32 decoded bytes, preserve it with registry/database backups, and override the development ArcadeDB password for non-loopback deployment.

## Next Phase Readiness

- Phase 5's ARC-07 and TEST-05 implementation and live gates are complete.
- Phase 6 can compare correctness/retrieval quality against the frozen Phase 3 baseline without changing the database-per-tenant or predicate contracts.
- Rotation/migration, offboarding/delete, OIDC identity binding, cross-tenant reporting, and fleet-wide schema rollout remain explicitly deferred.

## Self-Check: PASSED

- All 14 implementation, test, deployment, documentation, and gate artifacts plus this summary exist on disk.
- RED/GREEN commits `a222bc3`/`9f10f8a` and `552e97b`/`39652e7` exist in the required order.
- Focused live, full pytest, Ruff, format, Compose, file-size, and 19-check E2E gates pass with fresh evidence.
- Fixture teardown leaves no derived Phase 05-08 tenant databases behind.

---
*Phase: 05-per-tenant-arcadedb-isolation*
*Completed: 2026-07-15*
