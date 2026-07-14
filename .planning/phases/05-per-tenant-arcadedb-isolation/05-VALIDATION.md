---
phase: 05
slug: per-tenant-arcadedb-isolation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-14
---

# Phase 05 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` and `tests/conftest.py` |
| **Quick run command** | `python -m pytest -q tests/test_tenant_identity.py tests/test_tenant_registry.py tests/test_tenant_router.py tests/test_tenant_query_scope.py` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | Quick gate <30 seconds; full suite runtime measured during execution |

---

## Sampling Rate

- **After every task commit:** Run the smallest focused test file named by the task's `<automated>` verification.
- **After every plan wave:** Run `python -m pytest -q tests/test_tenant_identity.py tests/test_tenant_registry.py tests/test_tenant_router.py tests/test_tenant_query_scope.py` plus any live test introduced in that wave.
- **Before `$gsd-verify-work`:** `python -m pytest -q` and `python -m pytest -q tests/test_arcadedb_physical_tenant_isolation.py` must be green.
- **Max feedback latency:** 30 seconds for the per-task focused gate; live service tests are phase/wave gates.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | ARC-07 | T-05-01 | Exact identifiers derive opaque, keyed, versioned database names without raw-identity leakage | unit | `python -m pytest -q tests/test_tenant_identity.py` | ❌ W0 | ⬜ pending |
| 05-01-02 | 01 | 1 | ARC-07 | T-05-02 | Durable pseudonymous registry fails closed on corruption, mismatch, or missing previously-ready databases | unit | `python -m pytest -q tests/test_tenant_registry.py` | ❌ W0 | ⬜ pending |
| 05-02-01 | 02 | 2 | ARC-07 | T-05-03 | Ready-last provisioning is idempotent, resumable, race-safe, and never serves an incomplete database | unit/integration | `python -m pytest -q tests/test_tenant_provisioning.py` | ❌ W0 | ⬜ pending |
| 05-03-01 | 03 | 3 | ARC-07 | T-05-04 | Immutable tenant-bound views use per-tenant clients with bounded, concurrency-safe lifecycle management | unit | `python -m pytest -q tests/test_tenant_router.py` | ❌ W0 | ⬜ pending |
| 05-03-02 | 03 | 3 | ARC-07 | T-05-05 | MCP tools and document workers route through the same exact tenant boundary | integration | `python -m pytest -q tests/test_tenant_router.py tests/test_server.py` | partial / ❌ W0 | ⬜ pending |
| 05-04-01 | 04 | 4 | ARC-07, TEST-05 | T-05-06 | Every applicable query and mutation retains an explicit `user_identifier` predicate and rejects invalid identity | static/unit | `python -m pytest -q tests/test_tenant_query_scope.py tests/test_arcadedb_tenant_isolation.py` | partial / ❌ W0 | ⬜ pending |
| 05-04-02 | 04 | 4 | TEST-05 | T-05-07 | Concurrent A/B/C workloads remain physically separated with no result, mutation, log, error, or diagnostic leakage | live integration | `python -m pytest -q tests/test_arcadedb_physical_tenant_isolation.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_tenant_identity.py` — HMAC vectors, exact Unicode semantics, invalid identifiers, and leakage checks for ARC-07.
- [ ] `tests/test_tenant_registry.py` — persistence, concurrency, corruption, key/version mismatch, and restart behavior for ARC-07.
- [ ] `tests/test_tenant_provisioning.py` — fault-injected ready-last state transitions, retry classification, and race recovery for ARC-07.
- [ ] `tests/test_tenant_router.py` — single flight, different-tenant overlap, eviction/TTL, and active-reference survival for ARC-07.
- [ ] `tests/test_tenant_query_scope.py` — query-builder catalog and bound-parameter audit for ARC-07 and TEST-05.
- [ ] `tests/test_arcadedb_physical_tenant_isolation.py` — pinned ArcadeDB 26.7.1 three-tenant live proof and chaos gate for TEST-05.
- [ ] Shared fixtures — explicit test naming key, temporary registry, fake provisioning fault script, live database cleanup, and captured-log raw-identity rejection.

---

## Manual-Only Verifications

All phase behaviors have automated verification. Local live tests may emit an explicit skip only when Docker is unavailable; under `CI=true`, the existing `tests/conftest.py` policy must convert that skip into a hard failure.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [ ] Feedback latency < 30s for focused per-task checks
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
