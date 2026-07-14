# Phase 5: Per-Tenant ArcadeDB Isolation - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Give every exact, validated `user_identifier` its own physically separate ArcadeDB
database, provisioned on first use, while preserving explicit `user_identifier`
predicates and fail-closed validation inside every tenant database as defense in
depth. The phase includes deterministic tenant routing, resumable provisioning,
bounded tenant-client lifecycle management, and concurrent isolation proof against
the real pinned ArcadeDB service.

This phase does **not** add OIDC identity derivation (Phase 10), tenant offboarding or
database deletion, cross-tenant reporting, tenant migration between servers, or
naming-key rotation tooling. It does not weaken the invariant that every query must
remain explicitly tenant-scoped merely because the database is physically isolated.

</domain>

<decisions>
## Implementation Decisions

### Tenant database identity and naming

- **D-01 — Opaque deterministic identity:** Map each validated `user_identifier` to
  one deterministic opaque database name. Do not use readable/sluggified tenant
  names and do not require a reversible tenant-to-database mapping catalog.
- **D-02 — Exact identifier semantics:** Treat `user_identifier` as an opaque,
  case-sensitive Unicode string and compare/hash it code-point-for-code-point. Do
  not trim, case-fold, or Unicode-normalize. Reject an identifier containing control
  characters or leading/trailing whitespace instead of silently transforming it.
- **D-03 — Keyed derivation:** Derive the database digest with HMAC-SHA-256 using a
  dedicated tenant-naming key. The key makes likely emails/usernames unguessable
  from observed database names.
- **D-04 — Immutable key lifecycle:** Production startup fails if the dedicated
  naming key is absent. Tests and development use explicitly injected test keys,
  never an implicit fallback. The deployment key is non-rotating for this milestone;
  changing it is an explicit future migration.
- **D-05 — Locked name format:** Database names are
  `agentmem_t_v1_<full lowercase HMAC-SHA-256 hex>`. Use the complete 256-bit digest;
  the `v1` prefix makes any future naming migration explicit.
- **D-06 — Ready manifest:** Every tenant database contains one immutable manifest,
  verified when its tenant-bound client is first opened. A mismatch fails closed.
  The manifest contains only pseudonymous operational metadata: database
  name/digest, naming version, naming-key fingerprint, schema version, and creation
  timestamp. It never stores the raw `user_identifier`.
- **D-07 — Safe operator correlation:** New routing/provisioning logs and diagnostics
  expose only the opaque database name/fingerprint. Given an exact identifier, an
  operator can compute the expected database name locally; there is no raw tenant
  identifier or reversible mapping in these logs.

### First-use provisioning and failure behavior

- **D-08 — Synchronous first use:** The first valid operation for a new tenant calls
  one internal privileged provisioner and waits for database creation, schema/index
  bootstrap, and manifest readiness. The requested data operation runs only after
  the database is fully ready; public MCP tool contracts do not gain a pending state.
- **D-09 — Race-safe single flight:** Within one MCP process, allow only one active
  provision attempt per tenant. Across processes, contenders may race at the ArcadeDB
  server; an already-created database is treated as a possible race winner and must
  pass manifest and schema reconciliation before use. Do not introduce one global
  lock that serializes unrelated tenants.
- **D-10 — Ready-last recovery:** Database creation and schema bootstrap are
  idempotent. Write the immutable ready manifest only after every required schema and
  index step succeeds. An incomplete database remains unavailable and is resumed by
  a later request; never auto-drop it and never serve it early.
- **D-11 — Bounded transient retries:** Retry only transient network failures,
  server conflicts, and retryable 5xx responses using bounded exponential backoff
  with jitter. After exhaustion, fail the current MCP operation clearly. A later
  request may resume provisioning. Validation, manifest, and naming-key failures are
  deterministic and are not retried.

### Tenant routing and client lifecycle

- **D-12 — Immutable tenant-bound views:** A router validates the identifier and
  returns an immutable tenant-bound store/client view for the operation. The view
  owns its database client, bootstrap latch, manifest state, and tenant readiness.
  Heavyweight embedders, rerankers, extraction providers, community detector,
  observability recorder, redactor, and audit sink are shared. Never mutate the
  global store's `client`, and do not rely on an implicit context-local database.
- **D-13 — Bounded cache:** Reuse tenant-bound views through a configurable,
  thread-safe bounded LRU with an idle TTL. Cache eviction removes only the local
  view; it never closes/drops the ArcadeDB database. An active operation keeps its
  immutable reference even if the cache entry is concurrently evicted.
- **D-14 — Layered health:** Global `/health` reports the shared ArcadeDB server and
  router configuration/key readiness. Tenant database/manifest health is checked on
  tenant operations and exposed through tenant-specific diagnostics. One damaged
  tenant must not mark the entire service unhealthy.
- **D-15 — Minimal pseudonymous registry:** Persist a small local registry containing
  only opaque database identity, lifecycle state, and timestamps—never raw
  `user_identifier`. Routing remains HMAC-deterministic; the registry is not a
  reversible mapping. It exists so a previously-ready database that disappears
  after process restart fails closed instead of being silently reprovisioned empty.

### Concurrent isolation proof

- **D-16 — Fast plus live layers:** Keep deterministic fake-client unit tests for
  race/error branches and add mandatory live integration tests against the pinned
  `arcadedata/arcadedb:26.7.1` image. Fake tests alone do not prove physical
  separation; live tests alone are too weak for deterministic fault coverage.
- **D-17 — Three-tenant workload:** Exercise tenants A/B/C concurrently using both
  identical collision-prone inputs and tenant-unique canaries. Cover representative
  memory and document write/search/list/get/update/delete paths, then directly query
  each physical database to prove it contains only its tenant's records.
- **D-18 — Query-scope audit:** Unit/static assertions must cover the store query
  surface and prove that `user_identifier` remains explicitly bound on every
  applicable read and mutation. Physical database isolation is additive, never a
  reason to remove application-layer predicates or `_require_user` checks.
- **D-19 — Adversarial boundary suite:** Tenant A must be unable to use tenant B's
  resource IDs through get/update/delete/filter paths. Tests also cover cache
  eviction/reuse, wrong-client or manifest mismatch, empty/whitespace/control
  identifiers, case variants, Unicode lookalikes, and absence of result, mutation,
  error, or diagnostic leakage.
- **D-20 — Lifecycle-chaos CI gate:** Fault-inject every provisioning boundary;
  race first use for the same and different tenants; exercise cache eviction, a
  missing previously-ready database, and ArcadeDB restart. Live tests may emit an
  explicit local skip when Docker is unavailable, but under `CI=true` an unavailable
  dependency or skip is a hard failure, preserving no-skip-as-green discipline.

### Codex's Discretion

- Exact module decomposition and public/internal class names for the router,
  tenant-bound view, provisioner, registry, and naming helpers.
- Exact LRU capacity, idle TTL, retry count/backoff ceiling, and lock implementation,
  provided they are bounded, configurable, thread-safe, and tested.
- The pseudonymous registry's concrete durable format and atomic-write mechanism,
  provided it survives MCP restarts, never contains raw identifiers, and fails closed
  on corruption or a missing previously-ready database.
- Domain-separation bytes used as HMAC input and the non-secret key-fingerprint
  encoding, provided the locked `v1` output format and exact identifier semantics hold.
- Exact test canary strings, thread counts, and representative memory/document calls,
  within the D-16 through D-20 coverage contract.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project requirements and prior decisions

- `.planning/ROADMAP.md` §“Phase 5: Per-Tenant ArcadeDB Isolation” — fixed goal,
  dependencies, and three success criteria.
- `.planning/REQUIREMENTS.md` — `ARC-07` and `TEST-05`, the requirements owned by
  this phase.
- `.planning/PROJECT.md` — database-per-tenant decision, direct-port constraint,
  invariant #1, Docker deployment target, and no-skip-as-green posture.
- `.planning/phases/04-arcadedb-direct-port/04-CONTEXT.md` — Phase 4 decisions this
  phase must preserve: thin `urllib` client, idempotent schema bootstrap, readiness,
  stable IDs, native indexes, and mandatory app-layer scoping.
- `.planning/phases/04-arcadedb-direct-port/04-SPIKE-FINDINGS.md` — empirically
  verified ArcadeDB 26.7.1 HTTP, transaction, vector, and schema behaviors.

### Existing implementation surface

- `src/turing_agentmemory_mcp/arcadedb_client.py` — frozen stateless HTTP client,
  server command, `ensure_database`, transaction sessions, and retry behavior to
  extend without changing the spike-confirmed protocol.
- `src/turing_agentmemory_mcp/arcadedb_schema.py` — idempotent type/index bootstrap
  reused independently in every tenant database.
- `src/turing_agentmemory_mcp/store_core.py` — current single-client ownership,
  bootstrap latch, shared provider state, `_query`/`_write` choke points, and
  `_require_user` invariant.
- `src/turing_agentmemory_mcp/server.py` — `store_from_env`, singleton MCP store,
  document-worker store factory, environment configuration, and app assembly where
  routing must integrate.
- `tests/test_arcadedb_tenant_isolation.py` — existing fast concurrent app-layer
  isolation guards in one fake shared database; retain and extend rather than treat
  as physical-isolation proof.
- `tests/test_arcadedb_client.py` and `tests/test_arcadedb_client_transport.py` — live
  and mocked client behavior, retry, auth, and transaction test conventions.
- `tests/test_arcadedb_chaos_restart.py` — pinned-container restart pattern and
  local-skip/CI-hard-fail convention to reuse.
- `tests/conftest.py` — existing no-skip-as-green enforcement under `CI=true`.

### 2026 industrial and security guidance

- [ArcadeDB database concepts](https://docs.arcadedb.com/arcadedb/concepts/databases)
  — one process hosts many independent databases; each database is a top-level
  on-disk container with no cross-database transactions or joins.
- [ArcadeDB HTTP/JSON API](https://docs.arcadedb.com/arcadedb/reference/http-api/http)
  — database lifecycle endpoints and database-qualified query/transaction paths.
- [Azure multitenant control-plane guidance](https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/considerations/control-planes)
  — provisioning as one privileged, repeatable workflow with explicit race and
  partial-failure handling.
- [Azure tenancy models](https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/considerations/tenancy-models)
  — tenant-to-resource routing and isolation tradeoffs.
- [AWS SaaS general design principles](https://docs.aws.amazon.com/wellarchitected/latest/saas-lens/general-design-principles.html)
  — bind tenant context at every layer, isolate all tenant resources, and automate
  repeatable onboarding.
- [AWS SaaS isolation testing](https://docs.aws.amazon.com/wellarchitected/latest/saas-lens/foundations.html)
  — continually validate isolation and cross-tenant impact under realistic load.
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
  — opaque exact-string identifier semantics and the future `iss` + `sub` identity
  source that Phase 10 will bind to `user_identifier`.
- [NIST SP 800-63C](https://pages.nist.gov/800-63-3/sp800-63c.html) — keyed,
  irreversible, unguessable derivation for pseudonymous identifiers.
- [OWASP Multi-Tenant Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html)
  — defense-in-depth scoping, tenant-safe cache keys, onboarding controls, and
  adversarial cross-tenant checks.
- [OWASP APTS-MR-021](https://owasp.org/APTS/standard/6_Manipulation_Resistance/)
  — three-tenant canary-based adversarial isolation testing across data and
  diagnostic channels.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `ArcadeDBClient` is a frozen configuration object with database-qualified HTTP
  paths, bounded retry logic, and no long-lived socket/pool to close. Tenant-specific
  instances or immutable clones are cheap and naturally safe to retain in bounded
  views.
- `arcadedb_schema.bootstrap()` already provides the idempotent schema/index creation
  required for ready-last per-tenant provisioning.
- `_StoreCore` centralizes the client reference, schema latch, shared integrations,
  readiness, and all low-level database calls, giving the planner a clear seam for a
  tenant-bound store/view factory.
- The Phase 4 fake concurrent client and live chaos-restart harness provide both
  halves of the chosen fast-plus-live test strategy.

### Established Patterns

- Every store API accepts `user_identifier`, `_require_user` rejects empty values,
  and query builders bind the identifier as an explicit parameter. Preserve and
  strengthen this pattern; never infer scope from the selected database alone.
- ArcadeDB is canonical and fail-hard. Optional ML projections may degrade, but
  routing, manifest, schema, and database failures must fail closed.
- Live integration tests may skip visibly on a developer machine without Docker,
  while `tests/conftest.py` turns the same skip into failure in CI.
- Python files are capped at 600 lines with no allowlist, favoring small concern-split
  router, naming, provisioning, and registry modules.

### Integration Points

- `server.store_from_env()` currently builds and bootstraps one database-bound store;
  it must instead assemble shared dependencies once and expose tenant-bound views.
- MCP tool closures and `DocumentIngestManager` currently retain/factory-create a
  `TuringAgentMemory`; both synchronous tools and background document jobs must route
  through the exact same tenant boundary.
- `_query`, `_write`, `_write_many`, readiness, audit, and span helpers are the choke
  points where the tenant-bound client and opaque diagnostic identity meet.
- The existing `ARCADEDB_DATABASE=agent_memory` shared database becomes legacy input,
  not a fallback for tenant data. The milestone's fresh-start decision means Phase 5
  does not migrate records out of it or silently read from it.

</code_context>

<specifics>
## Specific Ideas

- Prefer industrial 2026 database-per-tenant patterns even where they add deliberate
  lifecycle rigor: keyed opaque naming, ready-last provisioning, bounded caches,
  durable pseudonymous inventory, and adversarial live proof.
- Defense in depth is explicit: physical database separation, immutable manifest
  verification, and mandatory row-level `user_identifier` predicates must all agree.
- A previously-ready database disappearing is an incident, not a new empty tenant;
  fail closed and preserve evidence rather than hiding loss behind auto-provisioning.

</specifics>

<deferred>
## Deferred Ideas

- Naming-key rotation, historical keyrings, and tenant database rename/migration
  tooling — future operational capability requiring an explicit migration design.
- Full tenant control plane, reversible tenant catalog, placement across ArcadeDB
  servers/stamps, quotas, billing, and offboarding — future scale/lifecycle work.
- OIDC-derived tenant identity and removal of client-supplied identity trust — Phase 10
  (`SEC-04`); Phase 5 keeps a clean routing seam for it but does not implement auth.
- Fleet-wide schema rollout orchestration across all dormant tenant databases — the
  per-open manifest/schema check lays groundwork, while full fleet operations belong
  in a later operational phase.
- Existing audit-retention/redaction redesign beyond the new routing/provisioning
  diagnostics — Phase 10 security and governance scope.

</deferred>

---

*Phase: 5-Per-Tenant ArcadeDB Isolation*
*Context gathered: 2026-07-14*
