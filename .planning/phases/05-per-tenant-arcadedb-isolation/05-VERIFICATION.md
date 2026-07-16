---
phase: 05-per-tenant-arcadedb-isolation
verified: 2026-07-16T07:36:00Z
status: passed
score: 10/10 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 8/10
  gaps_closed:
    - "A resolved tenant store enforces agreement between its physical database binding and every explicit user_identifier before any database or telemetry activity."
    - "Logs, spans, audits, status, registry, manifests, errors, and diagnostics expose opaque tenant correlation only, never raw user_identifier values."
  gaps_remaining: []
  regressions: []
---

# Phase 5: Per-Tenant ArcadeDB Isolation Verification Report

**Phase Goal:** Each tenant gets a physically isolated ArcadeDB database while app-layer
`user_identifier` scoping remains mandatory on every query as defense in depth.

**Verified:** 2026-07-16T07:36:00Z
**Status:** passed
**Re-verification:** Yes — after gap closure (plans 05-09 through 05-12)

## Goal Achievement

### Observable Truths

The ten rows below carry forward the prior verification's merged roadmap/plan truths. Rows 5 and
9 (both prior FAILED gaps) were re-verified against the current codebase, not against SUMMARY.md
claims. Rows 1–4, 6–8, 10 received a quick regression check (targeted test re-runs) rather than a
full re-derivation, since nothing in plans 05-09 through 05-12 touched their supporting code.

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Exact identifiers are preserved, invalid identities fail before mutation, and deterministic opaque database names use the full keyed HMAC-SHA-256 contract with no fallback key. | VERIFIED | `tenant_identity.py` unchanged by 05-09..05-12; `tests/test_tenant_identity.py` regression-clean (part of the 152-test spot-check run below). |
| 2 | The durable registry is pseudonymous, metadata-bound, concurrent, reopen-safe, and distinguishes resumable provisioning from ready data-loss evidence. | VERIFIED | `tenant_registry.py` unchanged; `tests/test_tenant_registry.py` passed in the regression spot-check (152 passed, 0 failed). |
| 3 | Every applicable query builder explicitly binds `user_identifier`, scopes both tenant-owned edge endpoints, pairs stable IDs with tenant scope, and fails catalog classification for future bypasses. | VERIFIED | `tests/test_tenant_query_scope.py` — the 44-builder catalog plus the NEW `test_every_public_store_method_requires_user` static guard-coverage catalog (05-10) — both pass; independently re-run. |
| 4 | First use creates/reconciles an opaque database, bootstraps schema, writes and rereads the manifest ready-last, bounds transient retries, resumes interruptions, and fails closed for ready/missing or mismatched state. | VERIFIED | `tenant_provisioning.py` unchanged; `tests/test_tenant_provisioning.py` passed in the regression spot-check. |
| 5 | A routed store enforces agreement among the exact tenant identifier, manifest, and permanently bound physical database before all operations. | **VERIFIED (was FAILED)** | `tenant_binding.py`'s `TenantBinding.verify()` recomputes the digest via the single `derive_tenant_database_identity` path and constant-time-compares it; `TenantRouter.resolve` (tenant_router.py:123-134) constructs the binding and asserts it survived construction. `_StoreCore._require_user` (store_core.py:496-503) is now an instance method that delegates to `self.tenant_binding.verify()` when bound. Guard coverage is 18/18 public store methods (`store_memory_write.py`, `store_memory_read.py`, `store_documents.py`, `store_search.py`, `store_rebuild.py` — grep-verified, matches the static catalog test), and on every span-wrapped method the guard runs as the literal first statement, strictly before `with self._span(...)`. Adversarial proof: `tests/test_tenant_binding_enforcement.py` (18 parametrized foreign-identifier cases, all reject with zero client `query`/`command` activity; 18 bound-identifier cases succeed; a dedicated span/audit-zero-events case; a background-job-view case) — re-run independently, 144/144 passed with `test_tenant_query_scope.py`/`test_tenant_binding.py`/`test_tenant_router.py`. |
| 6 | Router single-flight/cache behavior is concurrent, tenant-local, bounded by LRU/TTL, eviction-safe, and shares heavyweight dependencies without sharing client/runtime/bootstrap state. | VERIFIED | `tenant_router.py`'s cache/inflight logic unchanged by this gap closure (only `resolve()`'s binding construction/assertion was added); `tests/test_tenant_router.py` passed in the direct re-run above. |
| 7 | Foreground tools, uploads, durable jobs, and background workers preserve exact identity, resolve once through the same resolver, and do not cache a tenant store across jobs. | VERIFIED | `document_job_manager.py:187` still calls `self.resolver.resolve(job.user_identifier).memory` per claimed job (grep-confirmed unchanged); the new `test_background_job_identifier_rejected_by_foreign_view` adds an adversarial proof at the store-binding boundary underneath this resolver call. |
| 8 | Live concurrent A/B/C operations, foreign stable-ID attempts, first-use races, cache reuse, missing-ready failure, restart recovery, and a real asynchronous file remain physically and logically isolated. | VERIFIED | `tests/test_arcadedb_physical_tenant_isolation.py` — 2 tests re-run independently against the live pinned `arcadedata/arcadedb:26.7.1` service, both passed (26.70s), including the telemetry-aware assertions added in 05-12. |
| 9 | Tenant observability and operational diagnostics are pseudonymous and never retain raw identifiers. | **VERIFIED (was FAILED)** | `tenant_binding.sanitize_tenant_attributes()` strips `user_identifier`/`identifier` keys (top-level and nested) and merges in opaque `tenant_database` correlation. `_StoreCore._span` (store_core.py:377-394) and `_StoreCore._audit` (store_core.py:396-425) are the sole choke points every span/audit event passes through; both call the sanitizer, and `_audit` never forwards its `user_identifier` parameter (`del user_identifier` at line 415). `store_rebuild.py`'s `rebuild_vector_projection` — the one real leak found live via the 05-11 full-surface test (`resource_id=user_identifier`) — is fixed to `resource_id=""` (store_rebuild.py:96, grep-confirmed no remaining `resource_id=user_identifier` occurrences anywhere in `src/`). The **live** leakage harness (`tests/_arcadedb_physical_isolation_support.py`) now wires a real `_RecordingAuditSink` and a shared `InMemorySpanRecorder` into the assembly store's `observer=`/`audit_sink=` (replacing `NoopAuditSink()`, grep-confirmed zero remaining references), captures `span_event_count`/`audit_event_count`/`telemetry_text`, and `tests/test_arcadedb_physical_tenant_isolation.py` asserts both counts are non-zero (anti-vacuity) and that no `_IDENTITY_VARIANTS` entry (including the case-variant and Cyrillic lookalike) appears in `telemetry_text` — closing the exact assertion-surface blind spot ("the live leakage test does not inspect recorder events and configures a no-op audit sink") the prior verification identified. Re-run live: 2/2 passed. |
| 10 | Production assembly, Compose policy, layered health, documentation, and CI skip policy enforce required naming/registry/cache/retry configuration without a shared tenant-data fallback. | VERIFIED | `server.py`/`compose.yaml`/`.env.example` untouched by 05-09..05-12; `docker compose config --quiet` exits 0 (orchestrator-verified, not re-run here as it is unaffected by this gap closure's file set). `docs/architecture.md` and `CHANGELOG.md` now also document the `TenantBinding` contract and the pseudonymous span/audit contract (grep-confirmed: `TenantBinding` and `tenant_database` both present in both files). |

**Score:** 10/10 must-haves verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact group | Expected | Status | Details |
|---|---|---|---|
| Identity and registry | Exact keyed identity plus durable pseudonymous lifecycle control | VERIFIED | Unchanged; 4/4 artifacts still substantive. |
| Query defense | Catalog plus memory/document/rebuild scoped builders | VERIFIED | Unchanged; catalog tests re-run and pass. |
| Provisioning | Lifecycle transport, idempotent schema, manifest, and provisioner | VERIFIED | Unchanged; provisioning tests re-run and pass. |
| Routing and store construction | Immutable views, bounded router, and tenant-local store state | **VERIFIED (was PARTIAL)** | `tenant_binding.py` (new, 87 lines) exists and is substantive: `TenantBinding`, `TenantBindingError`, `sanitize_tenant_attributes`, `TENANT_CORRELATION_KEY`, `TENANT_IDENTITY_KEYS` all present and used. `TenantRouter.resolve` constructs and asserts the binding (tenant_router.py:123-134). `store_core.py`'s `_StoreCore.__init__` carries `tenant_binding` as tenant-local state, explicitly excluded from `StoreSharedDependencies` (grep-verified: `tenant_binding` not in that dataclass's fields). |
| Foreground/background integration | Server resolvers, document ownership, and per-job routing | VERIFIED | Unchanged; `document_job_manager.py`'s per-job `resolver.resolve(job.user_identifier)` call confirmed intact. |
| Live/operations | Live isolation gate and public operator contracts | **VERIFIED (was PARTIAL)** | `tests/_arcadedb_physical_isolation_support.py` (543/600 lines) now wires real telemetry recorders; `tests/test_arcadedb_physical_tenant_isolation.py` asserts on them. Both live tests re-run and pass (2/2, 26.70s) against the pinned service. |

All artifacts across all six groups exist, are substantive, and are wired. No stub patterns
(`TBD`/`FIXME`/`XXX`, empty returns, hardcoded-empty span attributes) found in any of the 13
gap-closure files inspected (`tenant_binding.py`, `store_core.py`, `store_memory_write.py`,
`store_memory_read.py`, `store_documents.py`, `store_search.py`, `store_rebuild.py`,
`tenant_router.py`, `tests/test_tenant_binding.py`, `tests/test_tenant_binding_enforcement.py`,
`tests/test_tenant_telemetry_pseudonymity.py`, `tests/_arcadedb_physical_isolation_support.py`,
`tests/test_arcadedb_physical_tenant_isolation.py`).

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| Exact identifier | Opaque database identity | Central validation plus unchanged UTF-8 HMAC input | WIRED | Unchanged. |
| Registry lifecycle | Durable ready evidence | Transactional provisioning insert and CAS ready promotion | WIRED | Unchanged. |
| Store call sites | Scoped query builders | Exact method argument passed into memory/document/rebuild builders | WIRED | Unchanged. |
| Provisioner | Registry, schema, and manifest | Ready-last reconciliation | WIRED | Unchanged. |
| **Router → store factory** | `TenantBinding` | `provisioned.identity` + `provisioner.naming_key` passed into the store factory as `tenant_binding=` | **WIRED (was PARTIAL)** | `tenant_router.py:123-129`; a dropped binding fails closed with `RuntimeError` naming only the database (line 134), grep-confirmed and covered by `test_unbound_store_factory_fails_closed`. |
| Server tools | Tenant view | One `resolver.resolve(user_identifier)` per operation | WIRED | Unchanged. |
| Claimed job | Tenant view | `resolver.resolve(job.user_identifier)` | WIRED | Unchanged. |
| **Store telemetry → Pseudonymous diagnostics** | `_span`/`_audit` | `sanitize_tenant_attributes` central choke point | **WIRED (was NOT_WIRED)** | `store_core.py:391` (`_span`) and `store_core.py:421` (`_audit`) both call `sanitize_tenant_attributes`; grep count is 4 occurrences in `store_core.py` (import + 2 call sites + doc reference), exceeding the plan's `>= 3` acceptance bar. |
| **Live gate → Router and physical databases** | Telemetry-aware diagnostic scan | Real `InMemorySpanRecorder` + `_RecordingAuditSink` folded into `diagnostic_text`/`telemetry_text` | **WIRED (was blind to this channel)** | `tests/_arcadedb_physical_isolation_support.py:213-225` (observer/audit_sink construction and assembly-store wiring), `:506-524` (telemetry capture and fold into `diagnostic_text`). `NoopAuditSink` no longer imported/used (grep count 0). |
| Compose contract | Production router configuration | Required key, registry path, finite cache/retries, no shared fallback | WIRED | Unchanged. |

### Data-Flow Trace (Level 4)

Traced again from MCP/job identity → resolver → `TenantBinding` verification → provisioner/manifest
→ tenant client → scoped SQL, and separately from store operation → `_span`/`_audit` →
`sanitize_tenant_attributes` → shared observer/audit sink. Both traces are now complete: the
adversarial logical-to-physical binding edge (previously failing) rejects before any client call,
and the telemetry edge (previously leaking) sanitizes before reaching the shared, process-wide
recorder/sink.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Gap-closure test suite (144 tests: binding, binding-enforcement, telemetry-pseudonymity, query-scope, router) | `.venv/Scripts/python -m pytest tests/test_tenant_binding_enforcement.py tests/test_tenant_query_scope.py tests/test_tenant_telemetry_pseudonymity.py tests/test_tenant_binding.py tests/test_tenant_router.py -q` | 144 passed in 0.80s | PASS |
| Regression spot-check on previously-VERIFIED truths' supporting tests | `.venv/Scripts/python -m pytest tests/test_tenant_identity.py tests/test_tenant_registry.py tests/test_tenant_query_scope.py tests/test_tenant_provisioning.py tests/test_arcadedb_tenant_isolation.py -q` | 152 passed in 2.48s | PASS |
| Live physical isolation + telemetry-leakage gate (pinned `arcadedata/arcadedb:26.7.1`) | `.venv/Scripts/python -m pytest tests/test_arcadedb_physical_tenant_isolation.py -q` | 2 passed in 26.70s | PASS |
| `ruff` on the gap-closure source files | `.venv/Scripts/python -m ruff check src/turing_agentmemory_mcp/tenant_binding.py src/turing_agentmemory_mcp/store_core.py src/turing_agentmemory_mcp/store_rebuild.py src/turing_agentmemory_mcp/tenant_router.py` | All checks passed! | PASS |
| Search for any remaining `resource_id=user_identifier` leak pattern | `grep -rn "resource_id=user_identifier" src/turing_agentmemory_mcp/` | no matches | PASS |

Full-suite evidence (independently reproduced by the orchestrator on a clean tree at HEAD, not
re-run here to avoid a redundant ~2-minute full pass): `python -m pytest -q` → 825 passed, 1
skipped (the one skip is `tests/test_utcp_conformance.py`, unrelated to isolation);
`ruff check src tests scripts` → clean; `docker compose config --quiet` → exit 0;
`bash scripts/check-file-size.sh` → clean; `scripts/e2e_score.py` → 19/19, score 10.0,
`VALIDATED_10_10`.

### Probe Execution

No phase PLAN/SUMMARY declares a `probe-*.sh` contract, and Phase 5 is not a migration/tooling
probe phase. The live ArcadeDB integration test and the deterministic E2E score command are the
applicable runtime gates; both were executed (live test independently re-run above; E2E score
independently reproduced by the orchestrator).

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|---|---|---|---|---|
| ARC-07 | 05-01 through 05-12 | One physical ArcadeDB database per tenant with mandatory app-layer scoping | **SATISFIED (was BLOCKED)** | Physical creation and SQL predicates (05-01..05-08) plus the logical-to-physical binding enforcement (05-09/05-10) and pseudonymous telemetry (05-11/05-12) are all present, wired, and adversarially tested — including a live leakage gate that now genuinely observes the channel it previously missed. |
| TEST-05 | 05-03, 05-07, 05-08, 05-10, 05-12 | Concurrent multi-tenant isolation tests with no cross-tenant leakage | SATISFIED | Query catalog, A/B/C worker tests, the 18-method adversarial binding matrix (05-10), and the live isolation + telemetry-leakage gate (05-12) all pass. |

No Phase 5 requirement is orphaned: both roadmap-mapped IDs appear in plan frontmatter across
05-01 through 05-12, and `.planning/REQUIREMENTS.md` marks both `[x]` Complete under Phase 5.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| 13 gap-closure files reviewed (05-09..05-12) | - | `TBD`, `FIXME`, or `XXX` | None | No blocking debt markers found. |
| `store_memory_write.py`, `store_documents.py` | first-write paths | Read-then-create under same-tenant concurrency | WARNING (carried forward) | Pre-existing, non-blocking; no Phase 5 must-have depends on same-tenant identical first-write idempotency. Not addressed by 05-09..05-12 (out of this gap-closure's stated scope). |
| `document_jobs.py` | claim/cancel lifecycle | Expired `cancel_requested` row is not reclaimed | DEFERRED | Phase 8 explicitly owns cancellation/crash recovery (confirmed still explicitly out of scope per 05-12's own objective section). |
| `file_upload.py` | session mutation | Upload append/complete/discard state lacks synchronization | DEFERRED | Phase 8 explicitly owns thread-safe upload sessions (confirmed still explicitly out of scope per 05-12's own objective section). |

Both BLOCKER anti-patterns from the prior verification (`store_core.py`'s missing logical tenant
binding, and raw tenant telemetry in `store_core.py`/mixins) are resolved and no longer present.
The three pre-existing WARNING/DEFERRED items are unchanged and remain correctly out of this
phase's scope — 05-12's own plan text explicitly names all three as out of bounds.

### Code Review Reconciliation

Not re-run as a separate step this cycle; the prior verification's two critical findings are the
gaps this re-verification exists to close, and both are confirmed closed by direct code inspection,
independent test execution, and independent live-gate execution above (not by trusting SUMMARY.md
narrative).

### Human Verification Required

None. Both re-verified truths are programmatically observable (adversarial unit tests plus an
independently re-run live integration gate), consistent with the prior verification's determination
that these are not visual/UX/uncertain items.

### Gaps Summary

Both BLOCKER gaps from the prior verification are closed:

1. **Binding enforcement (was gap 1):** `TenantBinding` is threaded through `TenantRouter.resolve`
   into every routed store; `_StoreCore._require_user` is now an instance-bound guard that verifies
   a keyed digest before any client, span, or audit activity; guard coverage spans all 18 public
   store methods (verified by both a static anti-regression catalog test and an 18-method
   adversarial matrix with zero-client-activity assertions).
2. **Pseudonymous telemetry (was gap 2):** `_StoreCore._span`/`_audit` sanitize centrally via
   `sanitize_tenant_attributes`, stripping raw identity and merging opaque `tenant_database`
   correlation; a real leak outside the original 6-site enumeration
   (`store_rebuild.py::rebuild_vector_projection`'s `resource_id=user_identifier`) was found and
   fixed to `resource_id=""`. Critically, the **live** leakage harness now actually observes this
   channel — it previously scanned `caplog`/errors/reprs/status/manifests but wired a `NoopAuditSink`
   and never read the `InMemorySpanRecorder` it constructed, which is exactly the assertion-surface
   blind spot that let the gap ship. That blind spot is closed: the harness now wires real
   recorders, folds their events into the scanned `diagnostic_text`, asserts non-zero event counts
   (anti-vacuity), and asserts zero exact-identifier leakage including case-variant and Cyrillic
   lookalike identifiers.

No regressions were found in the eight previously-VERIFIED truths on regression spot-check. Phase 5
achieves its stated goal: each tenant is physically isolated at the ArcadeDB database level, that
physical isolation now has an enforced logical counterpart (a foreign-but-valid identifier is
rejected before any activity), and the phase's own operational telemetry is pseudonymous and
provably so via a live gate that can no longer pass while the channel leaks.

---

_Verified: 2026-07-16T07:36:00Z_
_Verifier: the agent (gsd-verifier)_
