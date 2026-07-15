---
phase: 05-per-tenant-arcadedb-isolation
plan: 07
subsystem: document-ingestion
tags: [arcadedb, multi-tenant, document-jobs, uploads, worker-routing, tdd]

requires:
  - phase: 05-per-tenant-arcadedb-isolation
    provides: Exact identity validation, immutable tenant views, and foreground StoreResolver routing from plans 01-06
provides:
  - Exact unchanged tenant ownership for upload sessions, durable jobs, and idempotency keys
  - Per-claimed-job StoreResolver routing with no tenant-store cache in the worker
  - Concurrent A/B/C document-job separation and independent post-failure resolution
  - One resolver instance shared by foreground MCP tools and production background workers
affects: [05-08, document-workers, upload-security, physical-isolation-gate]

tech-stack:
  added: []
  patterns:
    - Validate exact tenant identity before filesystem, session, idempotency, or SQLite ownership work
    - Retain a shared resolver while resolving one immutable tenant view per claimed durable job
    - Adapt legacy injected stores through StaticStoreResolver without caching a tenant store in the manager

key-files:
  created: []
  modified:
    - src/turing_agentmemory_mcp/document_jobs.py
    - src/turing_agentmemory_mcp/file_upload.py
    - src/turing_agentmemory_mcp/document_job_manager.py
    - src/turing_agentmemory_mcp/server.py
    - tests/test_document_jobs.py
    - tests/test_document_file_pipe.py
    - tests/test_document_job_manager.py
    - tests/test_document_ingest_file.py

key-decisions:
  - "Validate at every public job/upload boundary and preserve the returned exact identifier unchanged in durable rows, session ownership, and idempotency material."
  - "Return the same non-enumerating upload_id-is-unknown error for absent and foreign upload sessions."
  - "Construct or adapt one shared StoreResolver when the manager is assembled, then resolve the persisted job identity exactly once for each claim."
  - "Use the application active_resolver for production document workers so foreground and background operations share one routing authority."

patterns-established:
  - "Durable document ownership: exact validation precedes all lookup and mutation, while foreign valid identities observe absence only."
  - "Background routing: claim job, resolve persisted exact tenant once, retain that immutable view for the job, and never cache its memory store in _run."

requirements-completed: [ARC-07, TEST-05]

coverage:
  - id: D1
    description: "Upload sessions, durable job rows, ownership checks, and idempotency keys reject invalid identities before mutation and preserve valid case/Unicode identities unchanged."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_document_jobs.py::test_enqueue_rejects_invalid_exact_identity_before_creating_a_row"
        status: pass
      - kind: unit
        ref: "tests/test_document_jobs.py::test_job_rows_and_idempotency_preserve_case_and_unicode_exactly"
        status: pass
      - kind: unit
        ref: "tests/test_document_file_pipe.py::test_upload_operations_reject_invalid_owner_before_mutation"
        status: pass
      - kind: unit
        ref: "tests/test_document_file_pipe.py::test_upload_ownership_is_exact_and_non_enumerating"
        status: pass
    human_judgment: false
  - id: D2
    description: "Concurrent exact A/B/C document jobs resolve once per claim and reach only their corresponding tenant-bound recording store, including after a tenant failure."
    requirement: TEST-05
    verification:
      - kind: unit
        ref: "tests/test_document_job_manager.py::test_concurrent_jobs_resolve_once_into_only_their_exact_tenant_store"
        status: pass
      - kind: unit
        ref: "tests/test_document_job_manager.py::test_tenant_failure_does_not_reuse_or_reset_the_next_tenant_store"
        status: pass
    human_judgment: false
  - id: D3
    description: "Production foreground tools and background document workers consume the same StoreResolver while legacy injected stores remain compatible through StaticStoreResolver."
    requirement: ARC-07
    verification:
      - kind: unit
        ref: "tests/test_document_ingest_file.py::test_production_app_gives_document_worker_the_foreground_resolver"
        status: pass
      - kind: integration
        ref: "python -m pytest tests/test_document_job_manager.py tests/test_document_ingest_file.py tests/test_document_jobs.py tests/test_document_file_pipe.py -q"
        status: pass
    human_judgment: false

duration: 19min
completed: 2026-07-15
status: complete
---

# Phase 05 Plan 07: Exact Document Ownership and Per-Job Tenant Routing Summary

**Durable uploads and jobs now preserve exact tenant identity, while every claimed background job resolves one immutable tenant store through the same resolver as foreground MCP tools.**

## Performance

- **Duration:** 19 min
- **Started:** 2026-07-15T12:19:22Z
- **Completed:** 2026-07-15T12:38:20Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Replaced every upload/job `user_identifier.strip()` transformation with the central exact validator before session, filesystem, idempotency, SQLite lookup, or mutation work.
- Preserved valid identifiers code-point-for-code-point and made case/composed/decomposed Unicode variants distinct durable owners and idempotency domains.
- Made foreign upload sessions indistinguishable from absent sessions while retaining tenant-scoped absence/denial for job get, cancel, and retry.
- Replaced the worker's process-global memory cache with one shared resolver and exactly one `resolve(job.user_identifier)` call per claimed job.
- Proved concurrent A/B/C routing, independent resolution after tenant failure, legacy static-store injection, and production foreground/background resolver identity.

## Task Commits

Each behavior task followed an independent RED then GREEN cycle:

1. **Task 1 RED: Specify exact durable job and upload ownership** - `88e6686` (test)
2. **Task 1 GREEN: Enforce central exact identity at ownership boundaries** - `0b78acd` (feat)
3. **Task 2 RED: Specify concurrent per-job resolver routing** - `c966e93` (test)
4. **Task 2 GREEN: Resolve one tenant store for every claimed job** - `fcaed99` (feat)

## Files Created/Modified

- `src/turing_agentmemory_mcp/document_jobs.py` - Exact validation for enqueue, idempotency, get, cancel, retry, and tenant row ownership.
- `src/turing_agentmemory_mcp/file_upload.py` - Exact session ownership validation and non-enumerating foreign upload handling.
- `src/turing_agentmemory_mcp/document_job_manager.py` - Shared resolver adaptation, pre-staging identity validation, per-claim resolution, and cache-free worker loop.
- `src/turing_agentmemory_mcp/server.py` - Production worker factory now returns the same active resolver used by foreground tools.
- `tests/test_document_jobs.py` - Invalid-before-row, exact case/Unicode idempotency, and mutation-boundary coverage.
- `tests/test_document_file_pipe.py` - Invalid-before-staging/session mutation and non-enumerating exact upload ownership coverage.
- `tests/test_document_job_manager.py` - Concurrent A/B/C routing, independent tenant failure, and pre-source validation coverage.
- `tests/test_document_ingest_file.py` - Production foreground/background resolver identity coverage.

## Decisions Made

- The manager retains only the resolver capability; it never retains a resolved `TuringAgentMemory` or chooses a tenant from mutable process context.
- Resolver construction/adaptation occurs once during manager assembly. Actual tenant selection occurs only from each persisted claimed job identifier.
- Resolution failure is translated through the existing safe `document_indexing_unavailable` retry path without exposing raw exception text.
- Foreign upload ownership uses the same `upload_id is unknown` response as an absent ID, preventing resource enumeration.

## TDD Gate Compliance

- **Task 1 RED:** `88e6686` captured expected failures for silent whitespace/control/surrogate transformation, mutation under trimmed ownership, and foreign upload enumeration.
- **Task 1 GREEN:** `0b78acd` made the focused job/upload suite pass 30 tests.
- **Task 2 RED:** `c966e93` produced four expected failures for validation order, resolver-as-store misuse, poisoned later routing, and the production legacy-store factory.
- **Task 2 GREEN:** `fcaed99` made all 40 focused document job/upload/manager/MCP tests pass.
- **REFACTOR:** No behavior-preserving source cleanup was needed after GREEN; Ruff formatting produced no content diff.
- **Order:** Each `test(05-07)` commit immediately precedes its corresponding `feat(05-07)` commit.

## Automated Validation

- `python -m pytest tests/test_document_job_manager.py tests/test_document_ingest_file.py tests/test_document_jobs.py tests/test_document_file_pipe.py -q` - 40 passed.
- `python -m pytest -p no:cacheprovider -q` - 754 passed, 9 integration skips allowed locally.
- `python -m ruff check src tests scripts` - passed.
- `python -m ruff format --check src tests scripts` - 148 files formatted.
- `docker compose config --quiet` - passed.
- CRLF-normalized `scripts/check-file-size.sh` content - all tracked Python files within the 600-line cap.
- Identity-transform grep across job, upload, and manager modules - no matches.
- ArcadeDB-backed `scripts/e2e_score.py` with local stub providers - 19/19 checks, score 10.0, `VALIDATED_10_10`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Bound production workers to the foreground resolver**
- **Found during:** Task 2 (production resolver integration test)
- **Issue:** `create_mcp_app` still passed `store_from_env` to the default document manager, which would construct a legacy shared database-bound store and bypass the active tenant router.
- **Fix:** Pass a factory returning `active_resolver`, giving foreground tools and background jobs exactly one routing authority.
- **Files modified:** `src/turing_agentmemory_mcp/server.py`, `tests/test_document_ingest_file.py`
- **Verification:** `test_production_app_gives_document_worker_the_foreground_resolver` and the full suite pass.
- **Committed in:** `fcaed99`

---

**Total deviations:** 1 auto-fixed (1 missing critical functionality).
**Impact on plan:** The fix is required for D-12 tenant isolation and closes the intended production integration seam without changing public MCP schemas.

## Issues Encountered

- The tracked file-size script is checked out with CRLF and this Bash rejects `set -o pipefail\r`; piping identical content through carriage-return removal produced the passing gate without changing the script.
- The system Python lacks the declared retained `turingdb==1.35` package used only for legacy E2E metadata. The ArcadeDB-backed harness ran with an in-memory `turingdb_version=1.35` shim, changed no repository/dependency state, and passed 19/19 checks.

## Authentication Gates

None.

## Known Stubs

None - the touched-file scan found no TODO, FIXME, placeholder, `NotImplementedError`, unavailable-data path, or incomplete runtime branch.

## User Setup Required

None - no new external service or configuration is required.

## Next Phase Readiness

- Plan 05-08 can run the live physical A/B/C isolation and lifecycle-chaos gate with both foreground and durable background paths on the same exact resolver boundary.
- No blocker remains from document upload, ownership, idempotency, or worker routing.

## Self-Check: PASSED

- All eight implementation/test artifacts and this summary exist on disk.
- Task 1 RED/GREEN commits `88e6686`/`0b78acd` and Task 2 RED/GREEN commits `c966e93`/`fcaed99` exist in the required order.
- Focused, full-suite, Ruff, format, Compose, file-size, identity-grep, E2E, and coverage-classifier gates pass.

---
*Phase: 05-per-tenant-arcadedb-isolation*
*Completed: 2026-07-15*
