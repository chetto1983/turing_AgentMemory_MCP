---
phase: 05-per-tenant-arcadedb-isolation
verified: 2026-07-15T14:12:00Z
status: gaps_found
score: 8/10 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "A resolved tenant store enforces agreement between its physical database binding and every explicit user_identifier before any database or telemetry activity."
    status: failed
    reason: "TenantRouter binds only the ArcadeDB client. The store retains no tenant-identity binding, and _require_user validates syntax only, so a tenant-A view accepts tenant B's valid identifier and executes B-scoped operations inside A's physical database."
    artifacts:
      - path: "src/turing_agentmemory_mcp/tenant_router.py"
        issue: "The store factory receives the tenant client and shared dependencies, but not the exact tenant identifier or a verifiable tenant digest."
      - path: "src/turing_agentmemory_mcp/store_core.py"
        issue: "_require_user is static and accepts every syntactically valid identifier without comparing it to the bound client/manifest identity."
      - path: "tests/test_tenant_router.py"
        issue: "No adversarial test invokes one tenant view with another valid tenant identifier and asserts zero client activity."
    missing:
      - "Bind the exact identifier or a recomputable keyed digest into every routed tenant store."
      - "Compare the supplied identifier with that binding before spans, audits, queries, or writes, and fail closed on mismatch."
      - "Add read/write/update/delete/document/background adversarial binding tests."
  - truth: "Logs, spans, audits, status, registry, manifests, errors, and diagnostics expose opaque tenant correlation only, never raw user_identifier values."
    status: failed
    reason: "Store spans forward raw user_identifier attributes and _audit explicitly serializes the raw identifier. The live leakage test does not inspect recorder events and configures a no-op audit sink, so the leak is outside its asserted surface."
    artifacts:
      - path: "src/turing_agentmemory_mcp/store_core.py"
        issue: "_span forwards attributes unchanged and _audit records user_identifier verbatim."
      - path: "src/turing_agentmemory_mcp/store_memory_write.py"
        issue: "Memory spans pass raw user_identifier attributes to the shared recorder."
      - path: "src/turing_agentmemory_mcp/store_documents.py"
        issue: "Document spans pass raw user_identifier attributes to the shared recorder."
      - path: "tests/_arcadedb_physical_isolation_support.py"
        issue: "The diagnostic scan includes caplog/errors/reprs/status but not InMemorySpanRecorder events, and the audit sink is NoopAuditSink."
    missing:
      - "Sanitize span and audit attributes centrally, replacing raw identity with the opaque bound database name or omitting tenant identity."
      - "Capture and serialize real span/audit events in leakage tests and assert no exact tenant identifier appears."
---

# Phase 5: Per-Tenant ArcadeDB Isolation Verification Report

**Phase Goal:** Each tenant gets a physically isolated ArcadeDB database while app-layer
`user_identifier` scoping remains mandatory on every query as defense in depth.

**Verified:** 2026-07-15T14:12:00Z
**Status:** gaps_found
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

The ten rows below merge the three roadmap success criteria with all 41 PLAN-frontmatter
truths. Closely repeated plan truths are grouped without dropping their stricter details.

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Exact identifiers are preserved, invalid identities fail before mutation, and deterministic opaque database names use the full keyed HMAC-SHA-256 contract with no fallback key. | VERIFIED | `tenant_identity.py`; 40 behavior tests; known-vector, Unicode distinction, invalid-input, key, and leakage tests exist and passed in the execution gate. |
| 2 | The durable registry is pseudonymous, metadata-bound, concurrent, reopen-safe, and distinguishes resumable provisioning from ready data-loss evidence. | VERIFIED | `tenant_registry.py` uses connection-per-operation, `BEGIN IMMEDIATE`, WAL/FULL sync, validated metadata, and provisioning-to-ready CAS; registry tests cover reopen, corruption, transitions, concurrency, and raw-byte leakage. |
| 3 | Every applicable query builder explicitly binds `user_identifier`, scopes both tenant-owned edge endpoints, pairs stable IDs with tenant scope, and fails catalog classification for future bypasses. | VERIFIED | `tests/test_tenant_query_scope.py` classifies 44 tenant builders and five narrow schema exemptions. Independent spot-check `test_all_query_builders_are_classified` passed. |
| 4 | First use creates/reconciles an opaque database, bootstraps schema, writes and rereads the manifest ready-last, bounds transient retries, resumes interruptions, and fails closed for ready/missing or mismatched state. | VERIFIED | `tenant_provisioning.py` orders registry, lifecycle, bootstrap, manifest reread, and ready promotion. Independent `test_ready_missing_database_fails_closed_without_create_or_drop` passed. |
| 5 | A routed store enforces agreement among the exact tenant identifier, manifest, and permanently bound physical database before all operations. | FAILED | `TenantRouter.resolve()` constructs the store without an identifier binding (`tenant_router.py:122`); `_StoreCore._require_user()` only calls the syntax validator (`store_core.py:468`). A diagnostic accepted two different valid tenants through the same guard. |
| 6 | Router single-flight/cache behavior is concurrent, tenant-local, bounded by LRU/TTL, eviction-safe, and shares heavyweight dependencies without sharing client/runtime/bootstrap state. | VERIFIED | `tenant_router.py`, `StoreSharedDependencies`, barrier-driven router tests, and store-state identity tests. Independent different-tenant concurrency spot-check passed. |
| 7 | Foreground tools, uploads, durable jobs, and background workers preserve exact identity, resolve once through the same resolver, and do not cache a tenant store across jobs. | VERIFIED | Resolver calls are present at all memory/document boundaries; `DocumentIngestManager` resolves `job.user_identifier` per claim; exact ownership and concurrent A/B/C tests cover job/upload separation. |
| 8 | Live concurrent A/B/C operations, foreign stable-ID attempts, first-use races, cache reuse, missing-ready failure, restart recovery, and a real asynchronous file remain physically and logically isolated. | VERIFIED | Live test module and helpers inspect tenant databases directly. Final execution evidence: 2 live tests passed; full suite 765 passed with one intentional local skip; deterministic E2E 19/19, score 10.0, `VALIDATED_10_10`. |
| 9 | Tenant observability and operational diagnostics are pseudonymous and never retain raw identifiers. | FAILED | `_span` forwards raw attributes and `_audit` records raw `user_identifier` (`store_core.py:372-394`). A no-write diagnostic confirmed both the audit event and span recorder retained the exact raw value. |
| 10 | Production assembly, Compose policy, layered health, documentation, and CI skip policy enforce required naming/registry/cache/retry configuration without a shared tenant-data fallback. | VERIFIED | `server.py`, `compose.yaml`, `.env.example`, Compose tests, architecture/configuration/changelog content, and successful Compose validation. `ARCADEDB_DATABASE` is absent from the production tenant-data route. |

**Score:** 8/10 must-haves verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact group | Expected | Status | Details |
|---|---|---|---|
| Identity and registry | Exact keyed identity plus durable pseudonymous lifecycle control | VERIFIED | 4/4 declared artifacts exist and are substantive. |
| Query defense | Catalog plus memory/document/rebuild scoped builders | VERIFIED | 4/4 declared artifacts exist; catalog and structural tests exercise emitted SQL and params. |
| Provisioning | Lifecycle transport, idempotent schema, manifest, and provisioner | VERIFIED | 4/4 declared artifacts exist and are wired through the provisioner. |
| Routing and store construction | Immutable views, bounded router, and tenant-local store state | PARTIAL | All 4 artifacts exist and client binding works, but the exact logical tenant is not bound into the store. |
| Foreground/background integration | Server resolvers, document ownership, and per-job routing | VERIFIED | 7/7 declared artifacts exist and are wired into production assembly. |
| Live/operations | Live isolation gate and public operator contracts | PARTIAL | All 4 artifacts are substantive. `CHANGELOG.md` contains ARC-07/TEST-05 under different wording than the plan's literal `Per-tenant ArcadeDB` pattern. The live leakage harness omits actual observer/audit event contents. |

Artifact tooling reported 26/27 literal checks green; manual inspection resolves the sole literal
false negative in `CHANGELOG.md`. Artifact existence is not the cause of the failed verdict.

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| Exact identifier | Opaque database identity | Central validation plus unchanged UTF-8 HMAC input | WIRED | `derive_tenant_database_identity` calls the central validator. |
| Registry lifecycle | Durable ready evidence | Transactional provisioning insert and CAS ready promotion | WIRED | Explicit transactions and legal-state validation are present. |
| Store call sites | Scoped query builders | Exact method argument passed into memory/document/rebuild builders | WIRED | Grep and catalog tests confirm call sites and bound params. |
| Provisioner | Registry, schema, and manifest | Ready-last reconciliation | WIRED | Database lifecycle, bootstrap, manifest reread, and `mark_ready` are ordered in `_provision_once`/`_finish`. |
| Router | Provisioner and store factory | Per-database `Future` and immutable client | PARTIAL | The client is wired; the exact identifier is not passed into the store factory. This is gap 1. |
| Server tools | Tenant view | One `resolver.resolve(user_identifier)` per operation | WIRED | Memory and foreground document registrars resolve once and pass the same argument onward. |
| Claimed job | Tenant view | `resolver.resolve(job.user_identifier)` | WIRED | Worker routing occurs per claimed job; no worker-local tenant-store cache remains. |
| Store telemetry | Pseudonymous diagnostics | Central span/audit choke points | NOT_WIRED | Raw identifiers flow into shared telemetry instead of opaque database correlation. This is gap 2. |
| Live gate | Router and physical databases | Production router plus direct per-database inspection | WIRED | Pinned live fixture and exact cleanup allowlist are present. |
| Compose contract | Production router configuration | Required key, registry path, finite cache/retries, no shared fallback | WIRED | Compose policy tests and `docker compose config --quiet` passed. |

### Data-Flow Trace (Level 4)

No frontend or dynamically rendered artifact is in Phase 5 scope. Backend data flow was traced
instead from MCP/job identity -> resolver -> provisioner/manifest -> tenant client -> scoped SQL.
The trace is complete for the normal path but fails at the adversarial logical-to-physical binding
edge described in gap 1.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Future query builders remain classified | `python -m pytest -p no:cacheprovider -q tests/test_tenant_query_scope.py::test_all_query_builders_are_classified` | 1 passed in 0.13s | PASS |
| Ready registry plus missing database fails closed | `python -m pytest -p no:cacheprovider -q tests/test_tenant_provisioning.py::test_ready_missing_database_fails_closed_without_create_or_drop` | 1 passed in 0.14s | PASS |
| Different tenants provision concurrently | `python -m pytest -p no:cacheprovider -q tests/test_tenant_router.py::test_different_tenants_provision_concurrently` | 1 passed in 0.20s | PASS |
| Logical tenant binding and telemetry leakage diagnostic | In-process call of `_require_user`, `_audit`, and `_span` with exact A/B identifiers | Both distinct tenants accepted; audit and span retained raw A | FAIL |

The prior regression gate also passed 113 tests with two expected skips. No source changed between
that gate and this verification.

### Probe Execution

No phase PLAN/SUMMARY declares a `probe-*.sh` contract, and Phase 5 is not a migration/tooling
probe phase. The live ArcadeDB integration tests and deterministic E2E command are the applicable
runtime gates; both were executed during the final wave.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|---|---|---|---|---|
| ARC-07 | 05-01 through 05-08 | One physical ArcadeDB database per tenant with mandatory app-layer scoping | BLOCKED | Physical creation and SQL predicates exist, but a routed store does not enforce that the explicit tenant matches its physical client/manifest binding. Raw telemetry also contradicts the phase's operational isolation contract. |
| TEST-05 | 05-03, 05-07, 05-08 | Concurrent multi-tenant isolation tests with no cross-tenant leakage | SATISFIED | Query catalog, A/B/C worker tests, and two pinned live isolation/lifecycle tests passed; direct database inspection and foreign-ID checks are present. |

No Phase 5 requirement is orphaned: both roadmap-mapped IDs appear in plan frontmatter.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| Phase file scope (39 reviewed files) | - | `TBD`, `FIXME`, or `XXX` | None | No blocking debt markers found. |
| `store_core.py` / routed-store construction | 96, 468 | Missing logical tenant binding | BLOCKER | A valid mismatched identifier is accepted by a database-bound store. |
| `store_core.py` and operation mixins | 372-394 and callers | Raw tenant telemetry | BLOCKER | Shared observer/audit outputs disclose exact tenant identity. |
| `store_memory_write.py`, `store_documents.py` | first-write paths | Read-then-create under same-tenant concurrency | WARNING | A duplicate-key race can fail an otherwise idempotent concurrent first write; no Phase 5 must-have depends on same-tenant identical first-write idempotency. |
| `document_jobs.py` | claim/cancel lifecycle | Expired `cancel_requested` row is not reclaimed | DEFERRED | Phase 8 explicitly owns cancellation/crash recovery and durable ingestion reliability. |
| `file_upload.py` | session mutation | Upload append/complete/discard state lacks synchronization | DEFERRED | Phase 8 explicitly owns thread-safe upload sessions. |

### Code Review Reconciliation

The independent review's two critical findings are confirmed and both break Phase 5 must-haves.
Its three warnings do not change this phase verdict: the cancel-recovery and upload-lock concerns
map explicitly to Phase 8; the same-tenant read-then-create race remains a real non-blocking
follow-up because no later roadmap criterion explicitly owns it.

### Human Verification Required

None. The two gaps are programmatically observable failures, not uncertain or visual behavior.

### Gaps Summary

Phase 5 delivers the physical databases, ready-last lifecycle, explicit SQL predicates, bounded
routing, foreground/background integration, and live concurrent isolation gate. It does not yet
close the most important defense-in-depth seam: a routed store cannot prove that a later valid
`user_identifier` belongs to its bound database. It also violates its pseudonymous diagnostics
contract by emitting raw identities to shared spans and audits. Both issues require source and
regression-test changes before ARC-07 and the phase goal can be marked complete.

---

_Verified: 2026-07-15T14:12:00Z_
_Verifier: the agent (gsd-verifier)_
