# Phase 5: Per-Tenant ArcadeDB Isolation - Research

**Researched:** 2026-07-14
**Domain:** Multi-tenant database routing, lifecycle provisioning, and isolation verification
**Overall confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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

### Deferred Ideas

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
</user_constraints>

## Research Summary

Phase 5 should be planned as a control-plane seam around the existing store, not as a
rewrite of its data model. `ArcadeDBClient` is already a frozen, stateless
configuration object, and `arcadedb_schema.bootstrap()` is already idempotent. The
smallest robust design is therefore: validate and derive an opaque database identity;
reconcile a durable pseudonymous registry; create/bootstrap/manifest the database
ready-last; then return an immutable store view whose client is permanently bound to
that database. [VERIFIED: `src/turing_agentmemory_mcp/arcadedb_client.py`,
`src/turing_agentmemory_mcp/arcadedb_schema.py`,
`src/turing_agentmemory_mcp/store_core.py`]

The most important planning risk is broader than database selection. The current MCP
assembly closes every tool over one singleton store, the document worker retains a
single store, and several document job/upload paths silently call `.strip()` on
`user_identifier`. In addition, several relationship query builders locate an edge
endpoint by stable record ID without also asserting its tenant. All of those paths
must move through one exact-identity router and the query-scope audit; otherwise the
phase could appear physically isolated while violating D-02 or D-18.
[VERIFIED: `src/turing_agentmemory_mcp/server.py`,
`src/turing_agentmemory_mcp/document_jobs.py`,
`src/turing_agentmemory_mcp/file_upload.py`,
`src/turing_agentmemory_mcp/store_memory_queries.py`,
`src/turing_agentmemory_mcp/store_documents_queries.py`,
`src/turing_agentmemory_mcp/store_rebuild_queries.py`]

ArcadeDB's database boundary matches the intended physical isolation: one server can
host multiple independent top-level databases, and database-qualified query,
transaction, and command endpoints operate on exactly one database. Creation is a
server command and a duplicate create fails, so cross-process first-use races must
treat an already-existing database as an invitation to reconcile, never as proof of
readiness. [CITED: https://docs.arcadedb.com/arcadedb/concepts/databases]
[CITED: https://docs.arcadedb.com/arcadedb/reference/http-api/http]
[VERIFIED: `.planning/phases/04-arcadedb-direct-port/04-SPIKE-FINDINGS.md`]

## Phase Requirements

<phase_requirements>

| ID | Requirement | Planning consequence |
|---|---|---|
| ARC-07 | One ArcadeDB database per tenant for physical isolation, with app-layer `user_identifier` scoping still mandatory on every query (invariant #1) | Plan the router/provisioner and the query-scope audit as co-equal deliverables; neither may be deferred behind the other. |
| TEST-05 | Concurrent multi-tenant isolation tests (High priority — no cross-tenant leakage under concurrency) | Require deterministic fake race/fault tests and a live A/B/C proof against `arcadedata/arcadedb:26.7.1`, including direct inspection of each physical database. |

</phase_requirements>

[VERIFIED: `.planning/REQUIREMENTS.md`]

## Project Constraints and Existing Seams

- Every read and write must fail closed on missing tenant scope; stable IDs do not
  replace tenant predicates. [VERIFIED: `CLAUDE.md`, `.claude/CLAUDE.md`]
- The project is a fresh start. The legacy shared `agent_memory` database is not a
  migration source, compatibility fallback, or tenant-data target for this phase.
  [VERIFIED: `.planning/PROJECT.md`, `.planning/ROADMAP.md`]
- Python files are capped at 600 lines with no allowlist, so routing, identity,
  registry, and provisioning should remain separate concerns. [VERIFIED: `CLAUDE.md`]
- There is no repository `AGENTS.md` and no project-local researcher skill overlay;
  the governing repository instructions are `CLAUDE.md` and
  `.claude/CLAUDE.md`. [VERIFIED: repository instruction discovery, 2026-07-14]
- Phase 4 locked a thin standard-library `urllib` client and validated the exact
  ArcadeDB 26.7.1 transport behavior. Phase 5 should derive tenant clients from that
  client rather than introduce an SDK. [VERIFIED:
  `.planning/phases/04-arcadedb-direct-port/04-CONTEXT.md`,
  `.planning/phases/04-arcadedb-direct-port/04-SPIKE-FINDINGS.md`]

## Recommended Architecture

### Responsibility map

```text
MCP/API operation(user_identifier)
              |
              v
 exact validator + HMAC identity
              |
              v
 TenantRouter --- bounded LRU/idle TTL --- per-database single flight
              |                                  |
              |                                  v
              |                         TenantProvisioner
              |                         /       |       \
              |                  SQLite registry |   ready manifest
              |                                  |
              v                                  v
 immutable TenantStoreView --------------> tenant ArcadeDB database
       |                                            |
       +-- shared provider dependencies             +-- explicit user predicates
```

The database name, not the raw identifier, should be the cache and in-flight key
after validation. The view may retain the exact identifier for calling the existing
store API, but diagnostics, registry rows, and new lifecycle logs should receive only
the opaque database identity. This confines raw identity handling to the request and
data-predicate boundary. [CITED:
https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html]

### Component responsibilities

| Component | Owns | Must not own |
|---|---|---|
| `tenant_identity.py` | Exact validation, domain-separated HMAC-SHA-256 database derivation, key parsing, non-secret fingerprint | Registry I/O, database creation, logging raw IDs |
| `tenant_registry.py` | Durable opaque lifecycle state, naming-version/key-fingerprint binding, timestamps, short atomic transactions | Raw IDs, routing decisions, ArcadeDB schema |
| `tenant_provisioning.py` | Database existence/create reconciliation, idempotent schema bootstrap, immutable ready manifest, transient retry classification | Global tenant serialization, database dropping |
| `tenant_router.py` | Per-key single flight, bounded LRU/idle TTL, immutable view creation, tenant diagnostics | Mutable global client selection, schema details |
| tenant-bound store/view factory | One client/database, one schema/readiness latch, tenant-local runtime state; references to shared providers | Cross-tenant cache state, global mutable client |
| server/tool integration | Resolve on every operation and background job; global versus tenant health separation | Singleton data store closed over by every tool |

Recommendation: use the module names above unless an existing concern split makes a
different name clearer. They map directly to the failure boundaries and keep files
inside the project limit.

### Standard stack

No new runtime package is needed:

- `hmac` and `hashlib` for HMAC-SHA-256 and constant-time manifest comparisons.
  Python's `hmac` accepts byte keys/messages, supports SHA-256, emits lowercase hex,
  and supplies `compare_digest`. [CITED: https://docs.python.org/3/library/hmac.html]
- `sqlite3` for the local durable registry. It is disk-backed, transactional, and
  provides an explicit lock timeout; use one connection per short operation rather
  than sharing connections across worker threads. [CITED:
  https://docs.python.org/3.13/library/sqlite3.html]
- `threading.RLock`, `concurrent.futures.Future`, `collections.OrderedDict`, and
  `dataclasses.replace` for in-process coordination and cheap immutable client
  derivation. [VERIFIED: Python 3.11+ project runtime and existing frozen
  `ArcadeDBClient`]

Package legitimacy audit: not applicable. The recommendation adds no third-party
package and keeps the locked thin-client architecture.

## Detailed Design Patterns

### 1. Exact identity and keyed naming

Recommendation: implement one validator and require every public tenant-bearing
entry point—including upload/job persistence—to call it. It should:

1. Require a `str` with at least one code point.
2. Reject, rather than replace, when `value != value.strip()`.
3. Reject Unicode control-category code points. Also reject lone surrogate code
   points because they cannot be encoded safely as normal UTF-8.
4. Perform no normalization, case folding, trimming, or slugging.
5. Encode the unchanged string as UTF-8 for HMAC input.

The current `_require_user` only checks `if not user_identifier.strip()`. It rejects
empty/whitespace-only values but still accepts and then preserves surrounding
whitespace; document job/upload code additionally stores a stripped value. A central
validator must replace this fragmented behavior. [VERIFIED:
`src/turing_agentmemory_mcp/store_core.py`,
`src/turing_agentmemory_mcp/document_jobs.py`,
`src/turing_agentmemory_mcp/file_upload.py`]

Recommended derivation:

```python
message = b'turing-agentmemory/tenant-db/v1\x00' + exact_id.encode('utf-8')
digest = hmac.new(naming_key, message, hashlib.sha256).hexdigest()
database_name = f'agentmem_t_v1_{digest}'
```

Use an explicitly supplied base64-encoded environment key of at least 32 random
bytes; `AGENTMEMORY_TENANT_NAMING_KEY` is a clear name. Parse and validate it during
router assembly so production startup fails before health reports ready. Tests must
inject a fixed key explicitly. The exact environment name and encoding are planner
discretion, while the output format and absence of fallback are locked.

Recommendation: bind the registry's global metadata to both naming version and a
non-secret key fingerprint (for example, a domain-separated SHA-256 digest of the
key). This is essential: changing the key changes the derived database name, so a
manifest in the old database cannot detect the wrong key before a new empty name is
chosen. A registry-level mismatch must fail startup before any tenant database can
be created.

### 2. Durable registry and ready-last state machine

SQLite is the best fit for the discretion allowed by D-15: it is standard-library,
durable, atomic, and handles cross-process writers more safely than rewriting a JSON
file. Recommended minimum schema:

```text
registry_meta(singleton, naming_version, key_fingerprint, created_at)
tenant_database(database_name PRIMARY KEY, digest, state, created_at, updated_at)
state in {provisioning, ready}
```

Recommendation: enable a finite busy timeout, use explicit short transactions and
one connection per operation, validate schema/meta on open, and fail closed on
corruption or fingerprint/version mismatch. The registry is inventory, not routing:
the HMAC always derives the name, and no raw identifier is ever persisted.

Provisioning should be an idempotent reconciliation:

```text
1. Validate exact identifier and derive opaque identity.
2. Read/insert registry row as provisioning.
3. List/check the physical database.
4. If registry says ready but the database is absent: fail closed; never recreate.
5. If new/provisioning and absent: create. Treat already-exists as a race candidate.
6. Derive immutable tenant client; run idempotent schema/index bootstrap.
7. Read manifest:
   - absent while not ready: insert it only after all bootstrap steps succeeded;
   - present: constant-time compare all identity fields and verify schema version;
   - mismatch: deterministic fail-closed error, no retry.
8. Mark registry ready only after the matching manifest is durable and re-readable.
9. Return the tenant-bound view.
```

A `provisioning` registry row plus matching manifest is a recoverable interrupted
finalization: verify and promote it to `ready`. A `ready` row plus absent/mismatched
manifest is an incident and must fail. No branch drops a database. This explicitly
distinguishes incomplete creation from loss of previously-ready data.

The ready manifest should be a singleton ArcadeDB record with a unique singleton key
and exactly the pseudonymous fields locked by D-06. Its application-level
immutability must be enforced by never exposing a general update path and by treating
duplicate insert as a race that requires exact re-read verification.

### 3. Per-tenant single flight and bounded cache

Recommendation: an `RLock` should protect only the cache metadata and in-flight map.
Provisioning must occur after releasing that lock. Keep one `Future` per opaque
database name:

```python
with lock:
    if cached_and_fresh(name):
        return cache[name].view
    future = inflight.get(name)
    if future is None:
        future = inflight[name] = Future()
        leader = True

if not leader:
    return future.result()  # wait outside the router lock

try:
    view = provision_and_build(name)
    publish_cache(view)
    future.set_result(view)
    return view
except BaseException as exc:
    future.set_exception(exc)
    raise
finally:
    remove_inflight_if_same(name, future)
```

Use an `OrderedDict` entry containing the immutable view and monotonic last-access
time. Enforce both capacity and idle TTL during access/insert. Eviction only deletes
the router's reference; an active call remains safe because it already holds its own
reference. Do not call database close/drop or mutate a view on eviction.

Test the exception path carefully: all same-tenant waiters should observe the same
attempt outcome, the in-flight entry must clear, and a later request must be able to
resume. Different-tenant leaders must demonstrably overlap rather than serialize on
one global lock.

### 4. Immutable store assembly and request routing

`ArcadeDBClient` is frozen and contains only connection configuration plus a
`database` field; its operations build request-scoped HTTP calls. A tenant client can
therefore be derived cheaply with `dataclasses.replace(base_client,
database=database_name)` or an equivalent explicit constructor. [VERIFIED:
`src/turing_agentmemory_mcp/arcadedb_client.py`]

`_StoreCore` currently co-locates `self.client`, one schema latch, provider
dependencies, and runtime signals. The plan should introduce a shared immutable
dependency bundle, then construct a separate `TuringAgentMemory` (or thin tenant
view around it) per database. Provider objects, community detector, observer,
redactor, and audit sink can be shared; client, bootstrap/readiness, manifest state,
and tenant-local runtime signal state cannot. [VERIFIED:
`src/turing_agentmemory_mcp/store_core.py`]

The server seam must change from singleton-store closure to tenant resolution:

- Each MCP tool validates/resolves `user_identifier` at the operation boundary, then
  calls the existing store method with that exact unchanged identifier.
- Direct injected fake stores used by unit tests can be adapted through a static
  resolver implementing the same protocol.
- `DocumentIngestManager` must accept a tenant-aware resolver/factory. Its worker may
  not cache one store globally in `_run`; it must resolve from the exact identifier
  carried by each job.
- Upload session, job row, idempotency key, and tenant comparison paths must use the
  central validator and unchanged identity, never `.strip()`.

[VERIFIED: `src/turing_agentmemory_mcp/server.py`,
`src/turing_agentmemory_mcp/document_job_manager.py`,
`src/turing_agentmemory_mcp/document_jobs.py`,
`src/turing_agentmemory_mcp/file_upload.py`]

Global health should check base ArcadeDB reachability, naming-key parse/fingerprint
binding, registry readability, and router configuration. Tenant diagnostics should
inspect an already-known opaque database/manifest state and must not accidentally
provision a database merely because health was requested. One tenant failure stays
tenant-scoped.

## Query-Scope Audit Findings

The existing query layer is split across `store_memory_queries.py`,
`store_documents_queries.py`, `store_retrieval_queries.py`, and
`store_rebuild_queries.py`. Most top-level data reads and mutations bind
`user_identifier`, but the audit must inspect nested edge endpoints and staging
updates, not just the outer statement. [VERIFIED: those four query-builder modules]

Specific high-risk builders observed during research:

- `memory_edge_statement` selects the `User` endpoint by identifier but selects the
  `Memory` endpoint by record ID without an explicit tenant predicate.
- `document_edge_statement`, `has_chunk_edge_statement`, and
  `next_chunk_edge_statement` locate document/chunk endpoints by stable ID without
  consistently asserting the same tenant.
- Projection edge builders select source/target records by ID alone.
- Community replacement selects `Entity` endpoints by ID alone.
- Some vector staging mutations update a record by ID alone.

[VERIFIED: `src/turing_agentmemory_mcp/store_memory_queries.py`,
`src/turing_agentmemory_mcp/store_documents_queries.py`,
`src/turing_agentmemory_mcp/store_rebuild_queries.py`]

Recommendation: make D-18 a builder-catalog test with an explicit exemption list only
for schema, manifest, and server-level provisioning statements. Required assertions:

- create paths bind and persist `user_identifier`;
- every tenant data read/update/delete binds the exact user parameter;
- every edge `FROM`/`TO` subquery constrains the endpoint to the same tenant;
- the `User` vertex uses exact identifier equality;
- a new unclassified query builder fails the audit instead of silently bypassing it.

Pair static/catalog assertions with a spy transport test that inspects bound
parameters, plus adversarial execution using another tenant's stable IDs. This
prevents string-presence checks from becoming the only defense.

## Runtime State Inventory

| State | Current location | Required Phase 5 ownership | Persistence/lifetime |
|---|---|---|---|
| Base server URL/auth/retry config | `ArcadeDBClient` | Shared base client config | Process/config |
| Selected database | One global client/store | Immutable tenant client/view | Cache entry and active-operation reference |
| Schema bootstrap latch | One `_StoreCore` boolean/lock | Per tenant view | Process cache; reconciled from DB on reopen |
| Ready manifest | Absent | Per tenant database | Durable in ArcadeDB |
| Tenant lifecycle | Absent | Pseudonymous registry | Durable local SQLite |
| Naming version/key fingerprint | Absent | Registry singleton metadata/router startup | Durable plus process |
| In-flight provisioning | Absent | Router map keyed by opaque database name | Process only |
| LRU/idle TTL | Absent | Router | Process only, bounded |
| Provider/model dependencies | Store instance | Shared dependency bundle | Process |
| Document worker store | One cached factory result | Resolve per job identifier | Job operation |
| Global health | One store/bootstrap result | Base server + router/key/registry | Request |
| Tenant health | Absent | Registry/database/manifest diagnostic | Request; no implicit provisioning |

[VERIFIED: `src/turing_agentmemory_mcp/arcadedb_client.py`,
`src/turing_agentmemory_mcp/store_core.py`,
`src/turing_agentmemory_mcp/server.py`,
`src/turing_agentmemory_mcp/document_job_manager.py`]

## Security Domain

### Applicable ASVS 5.0 areas

OWASP ASVS 5.0.0 is the current stable ASVS release. The most relevant verification
areas are input validation/business logic, authorization, cryptography, secure
configuration, data protection, architecture, and security logging. [CITED:
https://owasp.org/www-project-application-security-verification-standard/]
[CITED: https://github.com/OWASP/ASVS]

- V2: validate untrusted tenant input at a trusted service layer; exact rejection
  rules must be centralized. ASVS 5.0 `2.2.1` and `2.2.2` are Level 1 controls.
  [CITED:
  https://github.com/OWASP/ASVS/blob/master/5.0/en/0x11-V2-Validation-and-Business-Logic.md]
- V8: prevent IDOR/BOLA and enforce authorization at a trusted service layer.
  `8.2.2` and `8.3.1` are Level 1; explicit cross-tenant control `8.4.1` is Level 2
  but is directly relevant to this phase's goal. [CITED:
  https://github.com/OWASP/ASVS/blob/master/5.0/en/0x17-V8-Authorization.md]
- V11/V13/V14/V15/V16: protect the naming secret, fail on insecure configuration,
  avoid tenant identity disclosure, preserve architectural isolation, and emit safe
  lifecycle diagnostics. [CITED:
  https://github.com/OWASP/ASVS/tree/master/5.0/en]

### Threat model and mandatory mitigations

| Threat | Concrete failure mode | Required mitigation/proof |
|---|---|---|
| Spoofing / tenant confusion | Case-fold, trim, or normalization maps two supplied IDs unexpectedly | One exact validator; distinct case/Unicode lookalike tests; rejected whitespace/control tests before DB creation |
| Tampering | Wrong client or manifest points an operation at another database | Immutable binding; manifest exact comparison; wrong-client/mismatch tests |
| Repudiation / unsafe telemetry | Raw tenant IDs appear in provisioning logs or registry | Opaque DB/fingerprint only; captured-log and registry-content assertions |
| Information disclosure | Results, errors, health, cache keys, or diagnostics reveal another tenant | Explicit query predicates; IDOR suite; tenant-specific opaque diagnostics; error-content assertions |
| Denial of service | Global lock, unbounded clients, retry storms, or stuck single flight | Per-key coordination; bounded LRU/TTL; bounded retry/jitter; failure-clears-inflight tests |
| Elevation / authorization bypass | Stable foreign resource ID succeeds within a physically isolated or misbound client | Tenant predicate on every data/edge endpoint plus adversarial A-uses-B-ID execution |
| Data loss camouflage | Missing previously-ready DB is silently recreated empty | Durable ready registry; missing-ready fail-closed restart test |
| Secret/config drift | Naming key changes and routes tenants to new empty names | Registry-level fingerprint/version binding checked at startup |

OWASP's multi-tenant guidance explicitly recommends tenant validation at the data
access layer, tenant-aware cache keys, database isolation as defense in depth,
prevention of cross-tenant IDOR, safe logs, and dedicated isolation tests. [CITED:
https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html]

## Validation Architecture

### Test layers

1. **Pure identity tests:** exact code-point behavior, HMAC known vectors, locked
   format, key absence/invalid length, fingerprint stability, and no raw input in
   derived metadata.
2. **Registry tests:** create/open/restart, short concurrent writers, state
   transitions, corruption, wrong key/version, and no raw identity on disk.
3. **Provisioner fake tests:** inject a fault after every boundary—registry insert,
   create request, create-race response, each bootstrap class/index step, manifest
   write/read, registry-ready promotion—and prove a later attempt resumes safely.
4. **Router tests:** same-tenant single flight, different-tenant overlap,
   exception fan-out and cleanup, capacity/TTL eviction, active reference survival,
   and immutable client selection.
5. **Query-scope tests:** catalog/static builder audit, spy-bound-parameter audit,
   and foreign stable-ID adversarial operations.
6. **Live pinned-service tests:** concurrent A/B/C workload, direct physical DB
   inspection, cache/restart/missing-ready chaos, and CI hard-fail dependency policy.

Recommendation: create Wave 0 test helpers before production wiring:

- fixed explicit test naming key fixture;
- fake server/provisioning fault script;
- registry temp-path fixture and raw-byte leakage assertion;
- query-builder catalog/exemption helper;
- live helper that derives expected DB names and cleans up only databases created by
  the test fixture;
- captured-log assertion rejecting all exact A/B/C identifiers.

### Live proof contract

The live test must use `arcadedata/arcadedb:26.7.1` and three concurrent tenants.
Give all three collision-prone identical content plus unique canaries; exercise
representative memory and document write, search, list, get, update, and delete
paths. Attempt tenant B's IDs through tenant A. Derive the three expected database
names from the explicit test key, assert they are distinct, and directly query each
database to prove all persisted tenant-bearing records have only its exact
`user_identifier` and no foreign canary. Then verify manifests, registry bytes,
captured errors, logs, and diagnostics contain no raw tenant identity.

ArcadeDB exposes database listing/existence and database-qualified query/command and
transaction routes, so the test can prove physical separation without inspecting
container filesystem internals. [CITED:
https://docs.arcadedb.com/arcadedb/reference/http-api/http]

Case variants and Unicode lookalikes must produce distinct databases. Empty,
whitespace-only, leading/trailing-whitespace, control-character, and lone-surrogate
inputs must fail before registry or server mutation. A wrong manifest/client,
missing previously-ready database, process/router restart, and ArcadeDB container
restart must all fail or recover according to the ready-last state table.

### Verification commands

Fast focused gate, expected under 30 seconds once implemented:

```powershell
python -m pytest -q tests/test_tenant_identity.py tests/test_tenant_registry.py tests/test_tenant_router.py tests/test_tenant_query_scope.py
```

Live isolation/chaos gate:

```powershell
python -m pytest -q tests/test_arcadedb_physical_tenant_isolation.py
```

Full repository gate:

```powershell
python -m pytest -q
```

The current relevant pre-change baseline passed:
`python -m pytest -q tests/test_arcadedb_tenant_isolation.py
tests/test_arcadedb_client_transport.py tests/test_arcadedb_schema.py` → 22 passed in
0.96 seconds. [VERIFIED: local execution, 2026-07-14]

`tests/conftest.py` already converts integration skips to failures under `CI=true`.
Reuse that convention; do not add a second weaker skip policy. [VERIFIED:
`tests/conftest.py`]

## Environment Availability

| Capability | Research-time state | Planning consequence |
|---|---|---|
| Python | 3.13.3 | Compatible with project requirement Python 3.11+ |
| pytest | 8.3.5 | Focused baseline runs locally |
| Git | 2.51.0 | Documentation commit available |
| Docker | 29.6.1; daemon reachable | Live service can be started locally |
| Docker Compose | v5.3.0 | Existing compose harness can be reused |
| `arcadedata/arcadedb:26.7.1` image | Not present locally | First live run must pull the pinned image |
| Running ArcadeDB service | Not running; client readiness false at `127.0.0.1:2480` | Start the pinned compose service before live verification |

[VERIFIED: local tool and daemon checks, 2026-07-14]

The unavailable image/service is not a design blocker because Docker and Compose are
working and the exact pinned dependency is known. It is a setup prerequisite for the
live gate; in CI, inability to obtain/start it must fail rather than skip.

## Suggested Plan Decomposition

### Plan 05-01 — Exact identity and durable opaque registry

- Add the central exact validator, explicit key loading, HMAC naming, and
  fingerprint/version binding.
- Add the SQLite registry with lifecycle/meta validation and restart/corruption
  tests.
- Update environment examples/config parsing so production has no implicit naming
  key and development/CI inject explicit values.

Deliverable gate: pure identity and registry tests, including raw-byte leakage
inspection and wrong-key startup failure.

### Plan 05-02 — Ready-last provisioner and immutable manifest

- Derive tenant clients from the frozen base client.
- Add existence/create-race reconciliation, idempotent schema bootstrap, manifest
  creation/verification, registry transition, and retry classification.
- Add deterministic fault injection at every provisioning boundary and missing-ready
  fail-closed restart coverage.

Dependency: 05-01. Deliverable gate: every interrupted state either resumes safely
or fails closed; no code path drops or prematurely serves a database.

### Plan 05-03 — Tenant router, bounded lifecycle, and all request seams

- Add immutable tenant views, per-key single flight, bounded LRU/idle TTL, and
  layered health/diagnostics.
- Split shared provider dependencies from tenant-local store state.
- Route every MCP tool and every document upload/job/worker operation; remove silent
  identifier transformations.
- Preserve test injection with a resolver protocol/static adapter.

Dependency: 05-02. Deliverable gate: same-tenant coalescing, different-tenant
parallelism, eviction/reuse, active-reference safety, and exact-ID job routing.

### Plan 05-04 — Defense-in-depth audit and live isolation gate

- Repair every query/edge/staging path found by the query-scope audit and add a
  future-proof builder catalog.
- Add live concurrent A/B/C physical proof, foreign-ID attempts, direct per-database
  canary inspection, manifest/registry/log leakage checks, and restart/cache chaos.
- Update deployment documentation and changelog; keep the legacy shared database
  out of tenant routing.

Dependency: 05-03. Deliverable gate: ARC-07 and TEST-05 are both proven by static,
fake, and live layers.

This sequence is intentionally dependency-driven: identity/registry define the
irreversible routing contract; provisioning establishes readiness; routing then
integrates all call paths; the final plan repairs/audits the complete query surface
and proves the assembled system live.

## Common Pitfalls

- **Treating duplicate create as success.** It proves only that a database name
  exists; schema and manifest reconciliation are still mandatory. [CITED:
  https://docs.arcadedb.com/arcadedb/concepts/databases]
- **Detecting key drift only inside the tenant database.** A changed key chooses a
  different name before that manifest can be read. Bind the key fingerprint in
  registry metadata and fail at startup.
- **Reusing `strip()` as validation.** A predicate check may reject empty input while
  another layer stores a transformed tenant. Validate once and pass the unchanged
  string.
- **Holding the router lock during provisioning.** That serializes unrelated tenants
  and converts one slow database into service-wide head-of-line blocking.
- **Closing or mutating on LRU eviction.** Active operations must retain a valid
  immutable reference; eviction is only cache dereferencing.
- **Writing ready before the final schema/index step.** Any ready marker must be the
  last durable tenant-database step and re-verified before registry promotion.
- **Letting tenant failure poison global health.** Base server/router readiness and
  tenant manifest health are different layers.
- **Auditing only outer query text.** Edge endpoint subqueries and record-ID staging
  updates can bypass scope even when the outer operation has a user parameter.
- **Allowing a local integration skip to look green in CI.** Reuse the existing
  `CI=true` skip-to-failure enforcement.
- **Falling back to `ARCADEDB_DATABASE=agent_memory`.** Fresh-start scope means the
  shared database is neither migration nor compatibility behavior.

## Assumptions Log

No implementation-critical assumptions remain. Recommendations above select among
the explicit discretion in `05-CONTEXT.md`; all current-code and external-platform
claims are tied to repository evidence, the Phase 4 live spike, or primary
documentation.

## Open Questions for Planning

No user decision is required before planning. The planner may choose concrete bounded
defaults for LRU capacity, idle TTL, retry ceiling, SQLite busy timeout, and
fingerprint display length under the existing discretion. Those values should be
centralized in environment/config parsing and covered by boundary tests.

The only environment action before live verification is to pull/start
`arcadedata/arcadedb:26.7.1`. Do not weaken the live gate if that setup fails.

## Sources

### Primary project evidence

- `.planning/phases/05-per-tenant-arcadedb-isolation/05-CONTEXT.md`
- `.planning/REQUIREMENTS.md`
- `.planning/PROJECT.md` and `.planning/ROADMAP.md`
- `.planning/phases/04-arcadedb-direct-port/04-CONTEXT.md`
- `.planning/phases/04-arcadedb-direct-port/04-SPIKE-FINDINGS.md`
- `src/turing_agentmemory_mcp/arcadedb_client.py`
- `src/turing_agentmemory_mcp/arcadedb_schema.py`
- `src/turing_agentmemory_mcp/store_core.py`
- `src/turing_agentmemory_mcp/server.py`
- Tenant query, document job/upload/ingest, and existing isolation/transport/chaos
  tests cited inline above

### External primary/authoritative sources

- ArcadeDB database concepts:
  https://docs.arcadedb.com/arcadedb/concepts/databases
- ArcadeDB HTTP/JSON API:
  https://docs.arcadedb.com/arcadedb/reference/http-api/http
- Python `hmac`:
  https://docs.python.org/3/library/hmac.html
- Python `sqlite3`:
  https://docs.python.org/3.13/library/sqlite3.html
- OWASP Multi-Tenant Security Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html
- OWASP ASVS project and 5.0 sources:
  https://owasp.org/www-project-application-security-verification-standard/
  https://github.com/OWASP/ASVS

## Research Metadata

- **Research mode:** generic-agent workaround using the GSD research-plan seam
- **Internal evidence confidence:** HIGH
- **ArcadeDB protocol confidence:** HIGH due to repository live spike against the
  exact pinned 26.7.1 image, corroborated by official docs
- **Standard-library API confidence:** MEDIUM from Context7/official Python docs
- **Security guidance confidence:** MEDIUM from official OWASP sources
- **Validity window:** Reconfirm external documentation after 2026-08-13 or if the
  pinned ArcadeDB/Python versions change
- **Last verified:** 2026-07-14
