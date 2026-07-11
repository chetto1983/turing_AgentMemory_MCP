# Architecture Research: Repository/Driver Seam for TuringDB ↔ ArcadeDB Coexistence

**Domain:** Backend abstraction for a tenant-scoped graph+vector+BM25 memory store (existing Python MCP server)
**Researched:** 2026-07-11
**Confidence:** MEDIUM-HIGH (codebase claims HIGH — read directly from `store.py`/`ids.py`/`sparse_index.py`; ArcadeDB capability claims MEDIUM — public docs, not yet verified against a running instance in this repo)

## Scoping Assumption (confirm before roadmap locks in)

PROJECT.md says TuringDB and ArcadeDB "coexist" and "deployments select one." I am treating this as: **a given deployment picks ONE backend at creation time; there is no live cutover/migration of an existing TuringDB deployment's data to ArcadeDB in this milestone.** That reading is what makes dual-run "parity validation" (compare two fresh backends against the same seed data) sufficient, instead of needing zero-downtime live migration tooling (dual-write, backfill, cutover, rollback-with-data-loss-window). If the real intent is "migrate an existing production TuringDB deployment onto ArcadeDB without data loss," that is materially more work (data export/import, drift detection, cutover runbook) and should be called out explicitly as a separate, later capability — not bundled into "coexist via driver abstraction." Flag this for the roadmapper to confirm with the user.

## Current State (read directly from the codebase)

`store.py`'s `TuringAgentMemory` is simultaneously the **domain/business-logic layer** (fusion weights, redaction, chunking, temporal projection, retry/idempotency) and the **backend-access layer** (raw TuringDB query strings). Concretely, out of ~140 methods, roughly 40 build TuringDB query strings inline using its Cypher-like dialect plus two proprietary extensions:

- **Composed vector+graph query:** `VECTOR SEARCH IN {index} FOR {limit} {vector_literal} YIELD ids, score MATCH (m:Memory) WHERE m.vector_id = ids AND m.user_identifier = "..." RETURN m.id, score` (`_episode_dense_evidence`, `_fact_dense_evidence`, `_entity_dense_evidence`, `_community_dense_evidence`). This is TuringDB's own extension — no other graph DB speaks this exact syntax.
- **Non-transactional write batching:** `_write()` opens `new_change()`, runs one statement, `CHANGE SUBMIT`s, then `checkout()` — i.e. **every `_write()` call is already its own auto-committed unit**; `_write_many()` just loops `_write()` per statement because TuringDB won't let a later `MATCH` see nodes from an *unsubmitted* earlier `CREATE` in the same change. This is **not** a transaction spanning multiple statements — TuringDB, as currently used here, gives **no cross-statement atomicity or rollback** (confirmed by `.planning/codebase/ARCHITECTURE.md`: "No rollback on mid-batch failure; job retry re-applies entire batch"). This matters a lot for the interface contract below.
- **Manual vector-index lifecycle:** `CREATE VECTOR INDEX {name} WITH DIMENSION {n} METRIC COSINE`, `SHOW VECTOR INDEXES`, bulk `LOAD VECTOR FROM "{csv}" IN {index}` (writes a CSV to the shared `/turing` volume, then tells TuringDB to ingest it — this is why the MCP and TuringDB containers must share a filesystem).
- **Per-tenant physical vector index:** `_tenant_vector_index()` hashes `user_identifier` into the index name (`{base}_tenant_{blake2b8}`) and `_ensure_tenant_vector_index()` creates a **separate vector index per tenant per signal** (memory_index, fact_index, entity_index, community_index, document_index × N tenants). This is TuringDB's actual tenant-isolation mechanism for vectors — not a `WHERE user_identifier = ...` post-filter. It's the strongest isolation primitive currently in the codebase and the one to preserve, not weaken, when porting to ArcadeDB.
- **Two ID schemes with different portability**, both in `ids.py`:
  - `stable_id(prefix, *parts) -> str` (blake2b hex digest string) — used everywhere as the canonical, human-inspectable, backend-agnostic entity/memory/fact/chunk/community ID. **Fully portable.**
  - `vector_id(namespace, identifier) -> int` (blake2b digest folded into `[1, 2_000_000_000]`) — exists **only** because TuringDB's vector index stores a bare integer and the store has to `MATCH ... WHERE m.vector_id = ids` to join it back to the graph node. **This is a TuringDB-specific workaround, not a portable concept** (see Interface Design below).

The BM25 full-text layer (`sparse_index.py`, `SqliteFtsSparseIndex`) is **already fully backend-agnostic** — pure `sqlite3`, zero import of `turingdb`, zero coupling to the graph driver. This is important: **the driver seam does not need to touch full-text search at all.**

## Recommended Architecture: Repository/Ports Boundary, Not a Generic Query Language

### Why not a shared query-string abstraction

TuringDB's dialect (`VECTOR SEARCH ... YIELD ids, score MATCH ...`, `CHANGE SUBMIT`, `LOAD VECTOR FROM csv`) and ArcadeDB's dialect (SQL with `LSM_VECTOR` index type + `SEARCH_INDEX()`/`SEARCH_FIELDS()` for Lucene, or its Cypher/Gremlin engines) are different enough that a shared "generic Cypher builder" would either (a) become a third leaky abstraction neither backend fits cleanly, or (b) regress to lowest-common-denominator SQL that throws away TuringDB's per-tenant-index trick and ArcadeDB's native ACID multi-model transaction. The safer, more idiomatic seam — and the one CONCERNS.md itself already recommends ("Abstract TuringDB client behind a repository interface... Build adapter layer... Add integration tests with multiple backends") — is **domain-shaped repository methods**, one per call site currently embedded in `store.py`, each backend implementing it with its own native query language internally. `store.py` keeps 100% of its business logic (fusion, redaction, chunking, retry) and stops importing `turingdb` directly.

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  TuringAgentMemory (store.py) — business logic ONLY, backend-agnostic         │
│  fusion weights · redaction · chunking · temporal projection · retry/idempotency│
└───────────────────────────────┬───────────────────────────────────────────────┘
                                 │  calls narrow, typed repository methods
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    MemoryBackend (Protocol, new module: backend.py)           │
│  ┌────────────────┐ ┌──────────────────┐ ┌───────────────┐ ┌───────────────┐ │
│  │ GraphRepository │ │ VectorRepository │ │ AdminLifecycle│ │ (unchanged)   │ │
│  │ node/edge CRUD, │ │ ensure_index,    │ │ ensure_ready, │ │ SparseIndex   │ │
│  │ traversal,      │ │ upsert, search   │ │ runtime_status│ │ (SQLite FTS5,│ │
│  │ ordered_batch   │ │ (returns domain  │ │               │ │ already      │ │
│  │                 │ │  ids, not ints)  │ │               │ │  backend-    │ │
│  │                 │ │                  │ │               │ │  agnostic)   │ │
│  └────────┬────────┘ └────────┬─────────┘ └───────┬───────┘ └───────────────┘ │
└───────────┼───────────────────┼──────────────────┼─────────────────────────────┘
            │                   │                  │
   ┌────────┴───────────────────┴──────────────────┴─────────┐
   │                                                          │
   ▼                                                          ▼
┌───────────────────────────┐                    ┌───────────────────────────────┐
│  TuringDBBackend           │                    │  ArcadeDBBackend               │
│  (existing behavior,        │                    │  (new; SQL + LSM_VECTOR HNSW  │
│   moved verbatim)            │                    │   index; native ACID          │
│  - Cypher-like dialect       │                    │   multi-model transaction)     │
│  - per-tenant vector index   │                    │  - per-tenant vector index    │
│  - vector_id int join         │                    │    naming, same pattern       │
│  - CSV bulk vector load       │                    │  - vector search returns      │
│                               │                    │    vertex id directly, no     │
│                               │                    │    int join needed            │
└───────────────────────────────┘                    └───────────────────────────────┘
```

### Component Responsibilities (the interface surface, concretely)

These are grouped by the actual call sites in `store.py` (line numbers from the current file, for the extraction phase to work from directly).

| Repository | Method (typed signature sketch) | Replaces / mirrors current call site |
|---|---|---|
| **GraphRepository** | `ensure_user(user_identifier) -> None` | `_ensure_user` (3223) |
| | `write_memory_node(user_identifier, memory: MemoryItem, edges: ...) -> None` | `_write_memory` (2201) |
| | `write_batch(ops: list[GraphOp]) -> BatchResult` — see semantics note below | `_write_many` (3287), `_document_graph_queries`/`_document_chunk_batch_query` (1907, 1980) |
| | `get_memory(user_identifier, memory_id) -> dict \| None` | `get_memory` (1339) |
| | `list_memories(user_identifier, filters) -> list[dict]` | `list_memories` (1364) |
| | `update_memory(user_identifier, memory_id, patch) -> dict` | `update_memory` (1417) |
| | `soft_delete_memory(user_identifier, memory_id) -> dict` | `delete_memory` (1541) |
| | `active_memory_rows(user_identifier) -> list[dict]` | `_active_memory_rows` (3430) — used by rebuild/BM25 projection |
| | `active_chunk_rows(user_identifier, document_id="") -> list[dict]` | `_active_chunk_rows` (3446) |
| | `get_document/reindex_document/delete_document` | 1706, 1732, 1783 |
| | `chunk_context(chunk_domain_id) -> list[dict]` | `_chunk_context` (3318) — citation-context lookup |
| | `expand_entity_evidence(user_identifier, seed_ids, limit) -> list[RetrievalEvidence]` | `_expand_entity_evidence` (1182) — 1-hop `MENTIONS` traversal |
| | `query_graph_evidence(...)` | `_query_graph_evidence` (1161) |
| | `fact_sources_by_ids` / `community_sources_by_ids` | 1249, 1274 |
| | `community_graph_inputs` / `replace_community_graph` / `active_community_ids` | 2710, 2810, 2794 |
| **VectorRepository** | `ensure_tenant_index(base_name, user_identifier, model_version="v1") -> str` | `_ensure_tenant_vector_index` (3214) + `_ensure_vector_index` (3176) |
| | `upsert_vectors(index_name, rows: list[tuple[domain_id: str, vector: list[float]]]) -> None` | `_load_vectors` (3300) — **signature change**: domain-id string in, not `(int, vector)` |
| | `search(index_name, user_identifier, query_vector, limit) -> list[tuple[domain_id: str, raw_score: float]]` | `_episode_dense_evidence`, `_fact_dense_evidence`, `_entity_dense_evidence`, `_community_dense_evidence` (970–1160) — **collapses the "VECTOR SEARCH ... MATCH ..." join into the driver**; caller never sees a vector_id int |
| | `list_indexes() -> list[dict]` | verification path inside `_ensure_vector_index` |
| **AdminLifecycle** | `ensure_ready() -> None` | `load_graph_after_restart` (2197) + `_ensure_graph_loaded` (3161) |
| | `runtime_status() -> dict` | `runtime_status` (2696) |
| **SparseIndex (unchanged)** | already a standalone Protocol-shaped component | `sparse_index.py` — no change needed for driver coexistence |

**`write_batch` semantics — the honest contract, not an aspirational one:**
Today's `_write_many` provides **ordering, not atomicity**: each statement is submitted and durably visible before the next runs, but a failure partway through leaves prior writes committed with no rollback (confirmed in `.planning/codebase/ARCHITECTURE.md` "Architectural Constraints"). The interface must document this as the **baseline guarantee both drivers must meet** ("ops execute in order; each op's effects are visible to the next op before it runs"), not promise atomicity, because TuringDB cannot provide it. ArcadeDB *can* wrap the whole batch in one real ACID transaction (multi-model, single WAL) — that's a strictly stronger property the ArcadeDB driver may opt into internally, but the interface and the store-layer retry logic (which already exists because of stable IDs) must not assume it. Document this explicitly so a future contributor doesn't accidentally write code that only works because "ArcadeDB happens to roll back cleanly."

### Why the vector-id redesign matters (this is the concrete answer to "how to keep IDs backend-agnostic")

Today: `vector_id()` produces a synthetic int, TuringDB stores vectors keyed by that int, and every dense-retrieval method does a **two-step dance**: `VECTOR SEARCH` → get ints → `MATCH (m:Memory) WHERE m.vector_id = ids` → get the real `stable_id()` string back. That two-step join is what invariant #5 ("sort vector results in the app layer; composed rows don't preserve order") is actually warning about — it's an artifact of this specific join pattern.

ArcadeDB stores the vector as a **property directly on the same vertex** used for graph traversal (`LSM_VECTOR` index on a vertex property) — there is no separate integer keyspace to join back through; a vector search there returns the vertex (and hence its `id` property, i.e. the `stable_id()` string) directly, atomically consistent with the graph.

So: **move `vector_id()` out of the shared, cross-driver contract.** Keep it in `ids.py` (or relocate into a TuringDB-driver-private module) as a TuringDB-implementation-only helper. The `VectorRepository.search()` interface method returns `(domain_id: str, score: float)` — always `stable_id()`-shaped strings — for both drivers. The TuringDB driver does the int-join internally and never leaks it; the ArcadeDB driver never needs the int at all. This makes `stable_id()` the **single, fully portable identity primitive** across both backends, which is exactly what invariant #3 requires ("stable/deterministic IDs... not ad hoc text rewriting") — the interface just needs to stop exposing the TuringDB-only int as if it were part of that contract.

One thing to verify empirically once ArcadeDB is stood up (flagged as a Gap, not asserted as fact): whether ArcadeDB's `LSM_VECTOR` query syntax supports combining an ANN search with a `WHERE user_identifier = ... AND status = 'active'` predicate in one pass, or whether it requires post-filtering after the ANN call (which would change the over-fetch-then-filter behavior already flagged in CONCERNS.md as a perf bottleneck, "Vector Search Fetches 4x Limit Before Filtering"). This determines whether the ArcadeDB driver keeps or drops today's per-tenant-index trick.

## CLAUDE.md Invariants: Interface Contract vs. Backend Quirk

| # | Invariant | Classification | How it's preserved across drivers |
|---|---|---|---|
| 1 | Every read/write explicitly scoped by `user_identifier`; fail closed on empty | **Interface contract (hard requirement)** | Every repository method takes `user_identifier: str` as an explicit, non-optional first parameter. `_require_user()` (currently a store-layer static, `store.py:3889`) stays the single choke point called *before* delegating to the driver, and each driver **also** validates defensively (defense in depth — a future driver author might call driver methods directly). No method may exist that operates on tenant data without this parameter. This is the least negotiable line in the whole interface; violating it in either driver is a shipping blocker, not a style note. |
| 2 | TuringDB canonical; FTS/vector indexes are rebuildable projections, not a second source of truth | **Interface contract, generalized per-driver** | Rewording for multi-backend: *"whichever backend is configured is canonical for that deployment; the SQLite FTS5 sparse index and (for the TuringDB driver) the CSV-loaded vector indexes remain rebuildable projections regardless of backend."* This still holds per-driver because ArcadeDB's own `LSM_VECTOR` index, if adopted, is itself a projection *of the vertex's own property* — trivially rebuildable by re-running the embed step, same as today. |
| 3 | Stable/deterministic IDs (`ids.py`) for idempotent retries and vector IDs | **Interface contract for `stable_id()`; `vector_id()` becomes a TuringDB-driver-private detail** | See "vector-id redesign" above. `stable_id()` stays exactly as-is and is the only ID type crossing the interface boundary. |
| 4 | Submit each dependent graph batch before the next `MATCH` | **TuringDB-specific quirk, absorbed entirely inside the TuringDB driver** | This is purely about TuringDB's node-visibility model within an unsubmitted change. The interface only promises ordered, durably-visible-before-next-op batch execution (see `write_batch` semantics above); the *reason* TuringDB needs per-statement submission is invisible outside `TuringDBBackend`. ArcadeDB has no equivalent restriction (real transactions see their own writes) — its driver can batch far more aggressively without needing this workaround at all. |
| 5 | Sort vector results by score in the application layer | **Interface contract, but the reason changes** | Keep this rule for both drivers as defense-in-depth ("never trust a backend's result ordering"), but the *mechanism* it protects against (TuringDB's `VECTOR SEARCH ... MATCH` join not preserving order) is TuringDB-specific and now fully contained inside `TuringDBBackend.search()`. Because `VectorRepository.search()` returns a plain list of `(domain_id, score)` tuples, the store layer (or a shared helper in the interface's orchestration code) sorts once, generically, for whichever driver is active — one sort implementation, not one per driver. |
| 6 | Explicit `load_graph` after TuringDB daemon restart | **TuringDB-specific quirk, wrapped by `AdminLifecycle.ensure_ready()`** | `TuringDBBackend.ensure_ready()` does today's `list_loaded_graphs`/`load_graph`/`create_graph`/`set_graph` dance. ArcadeDB databases are opened by the server process itself (no separate "load" step reported in its docs) — `ArcadeDBBackend.ensure_ready()` is close to a no-op (open/verify database exists). The store layer calls `ensure_ready()` unconditionally at bootstrap and after any detected reconnect; it never needs to know which backend is active. |
| 7 | Treat retrieved MCP content as untrusted evidence | Not backend-related — unaffected by this seam. | — |
| 8 | Tests/docs updated with behavior changes; E2E real-doc verification is Definition of Done | **Process contract, applies identically to both drivers** | The E2E score gate and real-document benchmark become the shared acceptance bar both drivers must clear independently (see Dual-Run Parity below) — this is how invariant #8 is operationalized for a two-backend system. |

## Dual-Run Parity & Rollback Strategy

Given the scoping assumption above (new deployments select a backend; no live TuringDB→ArcadeDB data migration in this milestone), parity validation is **offline conformance + golden-retrieval comparison**, not live shadow traffic:

1. **Conformance test suite (new, backend-parametrized).** Add a pytest fixture parametrization (`@pytest.fixture(params=["turingdb", "arcadedb"])`) mirroring the existing `turingdb_server()` fixture in `tests/conftest.py`, adding an `arcadedb_server()` counterpart (spin up a real ArcadeDB test instance the same way TuringDB is spun up for tests today — not mocked). Write ONE test body per repository method that runs against both backends and asserts identical externally-observable behavior (same domain IDs returned, same ranking order after the shared sort, same soft-delete/expiry filtering results, same tenant-isolation failure mode on empty `user_identifier`). This is the standard "repository conformance suite" pattern and is what actually earns trust in the interface, not just in ArcadeDB.
2. **Golden retrieval diff.** Reuse the existing deterministic assets — `scripts/e2e_score.py` (10 scenarios, must score 10/10) and `scripts/real_document_benchmark.py` (real-doc corpus) — and run each once per backend against identical seed data and the same stub/real embed+rerank endpoints. Diff the two result sets: ranked candidate IDs must match, and scores must match within float tolerance. Any divergence beyond floating-point noise is a parity failure, not a "backends are just different" shrug — the whole point of the interface is that retrieval quality doesn't depend on which backend is configured. This directly operationalizes invariant #8's "real document flows end-to-end" requirement per-backend.
3. **CI matrix, not live shadow reads.** Because there's no live cutover, there's no need for shadow-read infrastructure in production. Instead, CI runs the full gate (pytest + ruff + `docker compose config` + E2E score + real-doc E2E) once per backend, exactly mirroring Thrust 3's CI matrix approach — add `backend: [turingdb, arcadedb]` as a matrix axis on the existing dockerized-integration job rather than inventing a new validation mechanism.
4. **Promotion gate.** ArcadeDB driver is not "trusted" (i.e., not documented as production-viable, not made the compose default) until: conformance suite green on both backends, golden-diff clean, and the dockerized E2E + real-doc E2E green on the ArcadeDB backend specifically. Until then it should be clearly marked experimental in `docs/` (invariant #8's "update docs when a contract changes" applies here directly — `docs/architecture.md` needs a backend-selection section).
5. **Rollback.** Because selection is a single env var read once at `store_from_env()` time (proposed: `AGENTMEMORY_BACKEND=turingdb|arcadedb`, default `turingdb`), rollback for a broken ArcadeDB driver is "redeploy with the var unset/reverted" — no data undo needed, since (per the scoping assumption) a deployment's data was only ever written to one backend. If a later milestone adds live migration, its rollback story is a separate, harder problem (needs a point-in-time data snapshot or dual-write undo) and should not be assumed solved by this design.

## Recommended Build Order (Thrust 2 heavyweight items)

Ordering is driven by two things: (a) what genuinely blocks what, and (b) reducing the number of simultaneously-changing variables when touching the most load-bearing invariant (tenant isolation).

```
1. Repository/driver interface extraction (TuringDB-only, behavior-preserving)
   └─ Bakes in from day one: user_identifier-first signatures, domain-id-only
      vector search return type (kills vector_id leakage), a model_version
      parameter on ensure_tenant_index() (cheap now, expensive to retrofit later)
   └─ Gate: full existing pytest suite + ruff + E2E score gate + real-doc
      benchmark all green with ZERO functional change (pure refactor)
        │
        ▼
2. Conformance/contract test suite written against the interface
   (runs against TuringDB driver only for now — it's the reference implementation)
        │
        ▼
3. ArcadeDB driver implementation (net-new; TuringDB driver untouched)
   + ArcadeDB service added to compose.yaml (parallels Thrust 1's stack work)
   Design decisions locked in by this research (see "Vector + Full-Text
   Strategy" below): native LSM_VECTOR for vectors, SQLite FTS5 kept as-is
   for BM25 (unchanged, both drivers use the same sparse_index.py)
        │
        ▼
4. Dual-run parity validation (conformance suite + golden-diff E2E on
   both backends; CI matrix axis added)
        │
        ▼
5. Backend selection wiring (AGENTMEMORY_BACKEND env var), docs + CHANGELOG

   ── In parallel with 3–5 (depends only on step 1, not on ArcadeDB existing) ──
6. Multi-worker document ingestion (SQLite job queue is already
   backend-agnostic; only needs step 1's stable batch-write contract to
   reason about retry idempotency cleanly). Validate against BOTH drivers
   once step 4 completes, since ArcadeDB's real transactions may behave
   differently than TuringDB's per-statement writes under concurrent workers.
7. OAuth/OIDC principal→user_identifier mapping at the MCP boundary
   (server.py/auth_from_env() only — zero storage-layer coupling).
   Sequenced after step 1 as a risk-reduction choice (don't change how
   identity arrives AND how it's enforced in the same window), not a hard
   dependency.

   ── Fully independent of the driver work; sequence by ops readiness ──
8. S3-compatible staging + upload-session persistence
   (bundle these — fixing the upload-session TTL/thread-safety/restart-loss
   tech debt properly requires the same durable-storage redesign that S3
   migration needs, so do it once). Needs Thrust 1's Docker stack settled
   first (adds a MinIO/S3 container to compose) but has no dependency on
   the graph/vector driver at all.

   ── After ArcadeDB driver exists and is trusted (step 4) ──
9. Tenant-scoped isolation hardening: evaluate ArcadeDB per-database
   isolation as an opt-in stronger mode vs. the default (per-tenant-index-
   within-shared-database, mirroring TuringDB's current pattern). Treat as
   an enhancement on top of a working driver, not bundled into step 3 —
   keeps the initial driver's surface area smaller and easier to parity-test.
10. Vector-index versioning FEATURE (A/B embedding model canary): the
    *interface shape* for this ships in step 1 (model_version parameter);
    this step is building the actual dual-version-serving/compare feature
    on top of it. Low priority relative to the rest of Thrust 2.
```

Independent of the driver seam entirely, and unaffected by any of the above: `graspologic-native` and `fastmcp` version-gating (CONCERNS.md "at-risk dependencies") — community detection and the MCP protocol layer both read/write through the repository interface (or don't touch storage at all, in fastmcp's case) regardless of backend, so pin-testing them can happen on whatever schedule Thrust 2 chooses without waiting on ArcadeDB.

## Vector + Full-Text Strategy (research-decided, per PROJECT.md Key Decisions)

**Full-text (BM25):** Keep `sparse_index.py` (SQLite FTS5) exactly as-is for **both** drivers. It already has zero coupling to TuringDB, already satisfies invariant #2 (rebuildable projection), and ArcadeDB's native Lucene-backed full-text (`SEARCH_INDEX()`/`SEARCH_FIELDS()`) — while real and reportedly capable — would be a second, backend-specific full-text implementation to maintain and parity-test for no retrieval-quality gain. There is no evidence in this codebase's scale (CONCERNS.md's SQLite ceiling is "~100GB / many tenants," not hit yet) that forces a change now. **Do not adopt ArcadeDB's native full-text in this milestone.**

**Vector:** Have the ArcadeDB driver use ArcadeDB's own **native `LSM_VECTOR` (HNSW) index** rather than introducing a third, dedicated external vector database (Qdrant/Pinecone/Weaviate class). Reasoning: (a) it mirrors the exact pattern already in use — TuringDB's vectors are native/in-graph today, so ArcadeDB-native keeps the two drivers structurally parallel and easiest to parity-test; (b) ArcadeDB's vector index lives on the *same vertex* used for graph traversal, giving atomic multi-model writes in one ACID transaction — a genuine capability upgrade over TuringDB's current non-atomic CSV-load-then-join dance; (c) CONCERNS.md's scaling limit for external vector DBs ("Consider separate vector database... for massive scale") is framed as a >10M-vectors problem this codebase has no evidence of hitting; introducing a fourth infrastructure dependency in a *stabilization* milestone contradicts Thrust 1's "one-command reproducible stack" goal. **Do not introduce a dedicated external vector database in this milestone; revisit only if a future milestone's scale data actually demands it.**

Net effect: the "vector + full-text strategy" research question resolves to **"ArcadeDB's natives subsume the need for a second dedicated vector DB, but do not replace the already-adequate, already-portable SQLite FTS5 layer."** This shapes step 3 above directly — the ArcadeDB driver's `VectorRepository` implementation targets `LSM_VECTOR`, and its full-text needs are zero (delegated entirely to the unchanged `sparse_index.py`).

## Recommended Project Structure (new/changed files)

```
src/turing_agentmemory_mcp/
├── store.py                    # UNCHANGED role: business logic only; stops
│                                #   importing `turingdb` directly; imports the
│                                #   MemoryBackend protocol instead
├── backend.py                  # NEW: MemoryBackend / GraphRepository /
│                                #   VectorRepository / AdminLifecycle Protocols
│                                #   (typed, documented contract — this file
│                                #   IS the interface deliverable of step 1)
├── backends/
│   ├── __init__.py
│   ├── turingdb_backend.py     # NEW: today's store.py query-building code,
│   │                            #   moved here verbatim behind the Protocol
│   │                            #   (includes vector_id() int-join, CSV load,
│   │                            #   per-statement CHANGE SUBMIT looping)
│   └── arcadedb_backend.py     # NEW: ArcadeDB driver (step 3)
├── ids.py                      # stable_id() unchanged/shared; vector_id()
│                                #   documented as TuringDB-backend-private
│                                #   (or moved into backends/turingdb_backend.py)
├── sparse_index.py              # UNCHANGED — already backend-agnostic
└── server.py                    # store_from_env() gains AGENTMEMORY_BACKEND
                                  #   selection, dispatching to the right
                                  #   backends.* factory
```

### Structure Rationale

- **`backend.py` as the single Protocol home**, not scattered across `store.py`: makes the contract reviewable in one file, and is what the conformance test suite (step 2) imports and type-checks against.
- **`backends/` package (one module per backend)** rather than one giant `drivers.py`: matches the existing convention of small modules split by concern (CLAUDE.md "prefer small modules split by concern (`<name>_<concern>.py`)").
- **`store.py` stays the large central exception** (per CLAUDE.md) but shrinks meaningfully — the ~40 methods that currently build raw query strings move out; what remains is fusion/redaction/chunking orchestration, which is the part that should never need to differ by backend.

## Architectural Patterns

### Pattern 1: Ports-and-Adapters (Repository) over TuringDB's native driver

**What:** `store.py` depends only on the `MemoryBackend` Protocol (the "port"); `TuringDBBackend` and `ArcadeDBBackend` are interchangeable "adapters" selected at `store_from_env()` time.
**When to use:** Exactly this situation — one canonical backend needs a second, structurally different implementation to coexist, without the orchestration layer caring which is active.
**Trade-offs:** Costs an up-front refactor (step 1) that touches ~40 methods across `store.py`; pays for itself the moment a second backend needs to exist, and again every time a conformance test catches a divergence before it ships.

### Pattern 2: Conformance (contract) test suite parametrized by backend

**What:** One shared test body, run against every backend via pytest fixture parametrization.
**When to use:** Any time an interface has more than one implementation and "they behave the same" is a claim that needs to be continuously verified, not asserted once.
**Trade-offs:** Requires a real (not mocked) test instance per backend in CI — heavier CI, but it's the only thing that actually catches "ArcadeDB's vector search doesn't support combined ANN+predicate filtering" before it becomes a production surprise.

### Pattern 3: Golden-retrieval diff for migration trust, instead of live shadow reads

**What:** Run the same deterministic scenario corpus (`e2e_score.py`, `real_document_benchmark.py`) once per backend against identical seed data; diff ranked results.
**When to use:** When there is no live cutover to shadow (per the scoping assumption above) — this is cheaper and equally rigorous for "new deployments pick a backend" rather than "migrate a live one."
**Trade-offs:** Does not validate live production traffic patterns or concurrency-under-load parity; if a later milestone needs live migration, this pattern alone is insufficient and shadow-read infrastructure would need to be added then.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Leaking `vector_id()` (the int) across the interface boundary

**What people do:** Keep today's "vector search returns ints, caller joins them back to nodes" shape as the interface contract because it's what TuringDB does today.
**Why it's wrong:** ArcadeDB has no equivalent concept — its vector search returns the vertex directly. Forcing ArcadeDB's driver to fabricate a fake int-join to satisfy a TuringDB-shaped interface reintroduces exactly the ordering/coupling problem invariant #5 exists to warn about, on a backend that never needed it.
**Do this instead:** `VectorRepository.search()` returns `(stable_id_string, score)` always; the int-join is a private implementation detail fully contained in `TuringDBBackend`.

### Anti-Pattern 2: Assuming ArcadeDB's real ACID transactions mean `write_batch` can promise atomicity

**What people do:** Since ArcadeDB *can* roll back a whole batch, write store-layer logic that relies on "if this fails, nothing was written" — which works on ArcadeDB and silently breaks retry/idempotency assumptions on TuringDB.
**Why it's wrong:** The interface must be defined by its weakest honest implementation (TuringDB: ordered, non-atomic) or the TuringDB driver becomes a second-class, harder-to-trust backend and the whole "coexist" premise weakens.
**Do this instead:** Document `write_batch` as ordered-but-non-atomic in the Protocol docstring; keep relying on `stable_id()`-based idempotent retries (already the existing pattern for job retry) rather than transactional rollback, on both backends. Let ArcadeDB's real atomicity be a bonus property, never a load-bearing one.

### Anti-Pattern 3: Bundling the ArcadeDB driver delivery with per-database tenant isolation

**What people do:** Try to ship "ArcadeDB driver" and "stronger per-tenant-database isolation" as one phase because they're both about ArcadeDB.
**Why it's wrong:** It roughly doubles the surface area under parity-test at once (a brand-new backend AND a brand-new isolation topology), making it much harder to tell which change caused a regression, and delays getting the baseline driver conformance-tested and trusted.
**Do this instead:** Ship the ArcadeDB driver first with the same isolation *pattern* TuringDB already uses (per-tenant physical vector index within one shared database), prove parity, then treat per-database isolation as a follow-on hardening phase (step 9 above).

## Integration Points

### Internal Boundaries

| Boundary | Communication | Notes |
|---|---|---|
| `store.py` ↔ `backend.py` Protocol | Direct typed Python calls (no RPC/serialization layer) | This is the seam under design; keep it synchronous like today — no need to introduce async here just because a second backend exists |
| `store.py` ↔ `sparse_index.py` | Direct calls, unchanged | Explicitly NOT part of this refactor — already portable |
| `document_job_manager.py` ↔ `store.py` | Existing calls into store's document-ingestion methods, unchanged shape | Multi-worker ingestion (build-order step 6) validates its concurrency assumptions against whichever backend is configured, but doesn't need its own backend awareness |
| `server.py:store_from_env()` ↔ `backends/*` | New: env-driven factory dispatch (`AGENTMEMORY_BACKEND`) | Same pattern already used for `embedder_from_env()`, `entity_processor_from_env()` etc. — nothing novel here, just extend the existing convention |
| MCP auth boundary (`auth_from_env`) ↔ `user_identifier` | OAuth/OIDC (build-order step 7) maps principal → `user_identifier` here only | Zero coupling to the storage backend; the mapped `user_identifier` string is all that crosses into the repository interface, same as today's bearer-token path |

## Gaps to Address (confirm/verify before locking phase plans)

- **Scoping assumption above** (new-deployment backend selection vs. live migration of existing data) needs explicit confirmation — materially changes what "coexist" requires.
- **ArcadeDB's filtered-ANN capability** (can a `WHERE user_identifier = ... AND status = 'active'` predicate combine with `LSM_VECTOR` search in one query, or does it require post-filtering?) is asserted from public docs, not verified against a running instance in this repo. Verify empirically in step 3 before finalizing whether the ArcadeDB driver keeps the per-tenant-index pattern or can safely use a single shared index with predicate filtering.
- **ArcadeDB Cypher/Gremlin/SQL dialect choice** for the driver's graph-write queries (node/edge CRUD, traversal) is not decided here — ArcadeDB supports SQL, Cypher, and Gremlin simultaneously; pick one consistently for the driver implementation (SQL is the most-documented and has first-class `LSM_VECTOR`/`SEARCH_INDEX` support, so it's the pragmatic default) rather than mixing dialects across methods.
- **Vector dimension/model-version interplay with per-tenant index naming**: confirm the naming scheme (`{base}_tenant_{hash}_v{model_version}`) doesn't collide with either backend's identifier length/charset limits before baking it into step 1's interface.

## Sources

- Direct codebase reads: `src/turing_agentmemory_mcp/store.py`, `ids.py`, `sparse_index.py` (HIGH confidence — read directly)
- `.planning/codebase/ARCHITECTURE.md`, `CONCERNS.md`, `STRUCTURE.md` (2026-07-11 audit) (HIGH confidence — prior codebase mapping)
- `CLAUDE.md` invariants #1–#8 (HIGH confidence — project-authoritative)
- ArcadeDB official docs: [Vector Embeddings](https://docs.arcadedb.com/arcadedb/how-to/data-modeling/vector-embeddings), [Full-Text Index](https://docs.arcadedb.com/arcadedb/how-to/data-modeling/full-text-index), [Multi-Model Architecture](https://docs.arcadedb.com/arcadedb/concepts/multi-model), [What is ArcadeDB?](https://docs.arcadedb.com/arcadedb/tutorials/what-is-arcadedb) (MEDIUM confidence — public web docs, not yet verified hands-on in this repo)
- ArcadeDB project pages: [arcadedb.com](https://arcadedb.com/), [GitHub ArcadeData/arcadedb](https://github.com/ArcadeData/arcadedb) (MEDIUM confidence)

---
*Architecture research for: TuringDB ↔ ArcadeDB repository/driver seam (stabilization milestone, Thrust 2)*
*Researched: 2026-07-11*
