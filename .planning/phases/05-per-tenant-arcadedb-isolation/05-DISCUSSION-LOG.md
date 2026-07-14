# Phase 5: Per-Tenant ArcadeDB Isolation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md; this log preserves the alternatives considered.

**Date:** 2026-07-14
**Phase:** 5-Per-Tenant ArcadeDB Isolation
**Areas discussed:** Tenant database identity and naming, first-use provisioning and
failure behavior, tenant routing and client lifecycle, concurrent isolation proof
**Mode:** Interactive text fallback; user selected all areas and requested online
research into 2026 industrial patterns.

---

## Tenant Database Identity and Naming

| Question | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Identifier-to-database mapping | Deterministic opaque cryptographic name | Persistent tenant catalog; sanitized readable name; planner discretion |
| Identifier equivalence | Exact case-sensitive opaque value; reject surrounding whitespace/control characters | Trim only; normalize and case-fold; planner discretion |
| Wrong-route detection | Immutable manifest verified when a database client is first opened | Verify every operation; trust digest only; planner discretion |
| Operator correlation | Compute expected opaque name locally; no raw/reversible logging | Raw identifier logs; reverse-mapping catalog; planner discretion |
| Keyed or plain digest | HMAC-SHA-256 | Plain SHA-256; environment-dependent mode; planner discretion |
| Naming-key lifecycle | Required immutable production key; explicit test key; migration-only rotation | Auto-generate in a volume; historical keyring; planner discretion |
| Database-name encoding | `agentmem_t_v1_` plus full lowercase 256-bit hex digest | 128-bit truncated hex; Base32; planner discretion |
| Manifest contents | Pseudonymous name/digest, versions, key fingerprint, timestamp only | Raw identifier; digest only; planner discretion |

**User's choices:** The user selected the recommended option for all eight decisions.

**Notes:** Initial plain SHA-256 naming was deepened after NIST research into
HMAC-SHA-256 so likely identifiers cannot be dictionary-tested from observed names.
The user rejected raw identifiers in manifests and routing/provisioning diagnostics.

---

## First-Use Provisioning and Failure Behavior

| Question | Selected | Alternatives considered |
|----------|----------|-------------------------|
| First request | Synchronous lazy provisioning through one internal privileged provisioner | Async pending state; explicit pre-provisioning only; planner discretion |
| Concurrent first use | Per-tenant local single-flight plus server-side race reconciliation | Local lock only; global deployment lock; planner discretion |
| Mid-provision crash | Idempotent ready-last bootstrap that resumes incomplete databases | Drop/recreate; permanent manual-repair failure; planner discretion |
| Transient failure | Bounded exponential-backoff retries with jitter, then clear failure | Immediate failure; background continuation; unbounded retry; planner discretion |

**User's choices:** The user selected the recommended option for all four decisions.

**Notes:** The roadmap's first-use requirement was retained while industrial
control-plane guidance shaped a single privileged, repeatable provisioning boundary.
No operation may run against a database before its ready manifest exists.

---

## Tenant Routing and Client Lifecycle

| Question | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Routing model | Immutable tenant-bound store/client view with shared heavyweight dependencies | Context-local client proxy; mutable global client; planner discretion |
| View lifecycle | Configurable bounded LRU plus idle TTL; active references survive eviction | Unbounded cache; no cache; planner discretion |
| Health semantics | Global server/router health plus tenant-scoped database diagnostics | Probe all cached tenants; any tenant degrades global health; planner discretion |
| Missing established DB | Durable minimal pseudonymous registry; fail closed if a ready database disappears | No registry and silent empty recreation; disable lazy creation after restart; planner discretion |

**User's choices:** The user selected the recommended option for all four decisions.

**Notes:** The pseudonymous registry does not reverse-map raw tenants and is not used
for routing. It records opaque lifecycle state so deletion cannot masquerade as first
use after an MCP restart.

---

## Concurrent Isolation Proof

| Question | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Test layers | Deterministic fake-client unit tests plus mandatory live ArcadeDB 26.7.1 integration | Live only; fake only; planner discretion |
| Workload breadth | Three-tenant collision/canary matrix, memory/document lifecycle, direct DB inspection, query audit | Minimal memory CRUD; every MCP tool E2E; planner discretion |
| Negative cases | Cross-resource replay, cache/route/manifest attacks, identifier edge cases, diagnostic non-leakage | Cross-ID only; property fuzzing only; planner discretion |
| Failure/CI gate | Lifecycle-chaos tests; visible local skips and hard failure for unavailable/skipped live tier under CI | Concurrency only; best-effort integration; planner discretion |

**User's choices:** The user selected the recommended option for all four decisions.

**Notes:** Physical database creation must be proven on the real pinned container;
the existing Phase 4 fake-client tests remain valuable only as the deterministic
unit layer. Isolation is tested as both a positive routing property and an adversarial
absence-of-leakage property.

---

## Codex's Discretion

- Module/class names and concern split.
- Concrete bounded cache values, retry counts, lock mechanics, registry format, HMAC
  domain separation, key-fingerprint encoding, and exact test canaries/thread counts.
- These choices remain constrained by the explicit security, durability, concurrency,
  and CI contracts in `05-CONTEXT.md`.

## Deferred Ideas

- Naming-key rotation and tenant migration tooling.
- Reversible/global tenant catalog, placement across database servers, quotas,
  offboarding, billing, and a full control plane.
- OIDC-derived identity (Phase 10), fleet-wide schema orchestration, and broader audit
  governance redesign.
