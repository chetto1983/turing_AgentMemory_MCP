# Phase 4: ArcadeDB Direct Port - Research

**Researched:** 2026-07-13
**Domain:** Graph+vector+full-text database backend port (TuringDB → ArcadeDB 26.7.1), Python HTTP/JSON client, retrieval-parity engineering
**Confidence:** MEDIUM — codebase-grounded findings (store_*.py, ids.py, compose.yaml) are HIGH confidence; ArcadeDB 26.7.1-specific syntax (function naming, exact DDL, transaction/commit-retry semantics) is genuinely unresolved even after consulting the project's `arcadedb` skill and Context7-derived capabilities doc — this is *why* D-02 makes the spike a hard gate, not a research gap this document can close.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Locked from prior milestone/roadmap (carried in, NOT re-litigated)**
- **Direct port, no driver/abstraction layer** — ArcadeDB is the sole backend. The
  "driver interface run against both backends" framing in PITFALLS.md (Pitfalls
  4/5/6/9) and STACK.md is **superseded**: there is no live dual-backend. The
  parity check is Phase 6 diffing the ported stack against the *committed* Phase-3
  baseline artifact (`baseline/03-turingdb/`), not a runtime both-drivers test.
- **Thin stdlib-`urllib` `arcadedb_client.py`** — no new HTTP dependency
  (`httpx`/`requests` forbidden); matches `embeddings.py`/`rerank.py`. Targets the
  ArcadeDB HTTP/JSON API (`/api/v1/command|query|begin|commit|rollback`,
  `sqlscript` for multi-statement). Params bound `?`/`:named`; **vector literals
  are inlined, not bindable** (capabilities §1 [S5]).
- **`stable_id()` stays canonical** — stored as an indexed/UNIQUE ArcadeDB property;
  ArcadeDB's native RID (`#12:34`) never leaks into ID or vector-ID logic (Pitfall 6).
- **Delete the `vector_id` int-join** (SC#3) — native HNSW returns record + score
  together; TuringDB invariant #5 (app-layer re-sort of composed `VECTOR SEARCH …
  MATCH …`) retires.
- **Retire the SQLite-FTS5 outbox** for this backend — ArcadeDB's full-text index is
  ACID-consistent with graph writes.
- **Single DB this phase** — per-tenant-DB physical isolation is Phase 5;
  `user_identifier` scoping stays mandatory on every query regardless (invariant #1).

**Vector index**
- **D-01 (Quantization — LOCKED):** **None / full-precision, COSINE metric.** No
  INT8/BINARY. Corpus is well under the ~1–5M vectors/tenant scale where
  memory/build cost bites, and Phase 3 showed recall is fragile; do not introduce
  lossy compression during a port whose Phase-6 exit criterion is meet-or-exceed the
  baseline. Quantization stays a *future* lever if scale ever demands. Chosen
  explicitly, not defaulted (Pitfall 7).

**Spike (SC#1) — carries two deferred decisions + is a HARD gate**
- **D-02 (Hard gate — LOCKED):** The spike is a **committed smoke test in
  `arcadedb_client.py`** that MUST pass before any store query builder is written.
  It validates the capabilities §3 unknowns: filtered-ANN predicate pushdown,
  function naming (`vectorNeighbors` vs `` `vector.neighbors` ``) on 26.7.1,
  full-text analyzer + score exposure, vector DDL dimensions/metric, and
  intra-transaction read-your-writes.
- **D-03 (Filtered-ANN fallback — LOCKED):** **Keep the current
  over-fetch-then-filter (made adaptive)** as the safe default; adopt native
  predicate pushdown into the HNSW query ONLY if the spike proves it does not
  under-fill `k` when combined with `status='active' AND expires_at…`. (Peers
  diverge: neo4j-agent-memory uses naive `$limit*2` with k-underfill *unsolved*;
  mem0's Qdrant/Azure adapters pre-filter natively — ArcadeDB's behavior is the
  §3 flagged unknown, so bet nothing until measured.)
- **D-04 (Lexical channel — SPIKE-DECIDED):** The spike **builds both** candidate
  channels — native **Lucene full-text** (`CONTAINSTEXT`/`SEARCH`, per-field
  analyzer) and native **`LSM_SPARSE_VECTOR` BM25** (`vector.sparseNeighbors`,
  IDF/`minScore`) — and picks whichever better matches the FTS5 baseline ranking on
  the yardstick (D-06). Both feed the **existing Python RRF** unchanged (mem0's
  magnitude-additive fusion is a *future-milestone* idea, not adopted here). Analyzer
  is chosen to match FTS5's `unicode61` tokenization to avoid ranking drift vs the
  Phase-6 baseline (Pitfall 8), not an aggressive language-specific stemmer.
- **D-05 (Graph query surface — SPIKE-DECIDED):** The spike prototypes the 2-hop
  `entity→fact→memory` traversal (and `NEXT_CHUNK`, community reads) in **both
  ArcadeDB SQL MATCH/TRAVERSE and Cypher** on 26.7.1, and picks by which binds params
  cleanly and composes with the vector/full-text functions. Default lean: SQL, for a
  uniform surface spanning traversal + `vectorNeighbors` + `CONTAINSTEXT` + DDL
  (neo4j-agent-memory's Cypher value was in Neo4j-only procedures we replace anyway).

**Measurement yardstick**
- **D-06 (LOCKED):** The spike's "pick by recall" (D-04/D-05) is measured against
  **Phase-3's committed frozen questions + `baseline/03-turingdb/` artifact
  (D-08/D-11)** as the primary yardstick (parity-aligned with the Phase-6 gate),
  **plus a handful of hand-authored pure-lexical stress queries**
  (keyword/error-code/exact-phrase). Rationale: the grounded-passage baseline
  under-probes lexical ranking, and analyzer regressions (Pitfall 8) surface
  precisely on keyword queries — the stress queries sharpen the D-04 analyzer/channel
  call without breaking parity comparability.

**Pull-forward hardening (deliberate scope expansion — see Cross-Phase note)**
- **D-07 (Index versioning — LOCKED, from Phase 9/INFRA-03):** **Full** vector-index
  versioning in Phase 4 — versioned/namespaced index names **plus** atomic swap on
  rebuild and rebuild-without-stale-vectors (fixes the known
  `memory_rebuild_vector_projection` stale-accumulation bug on the new backend).
  Backed by Pitfall 7 ("ship versioned from day one").
- **D-08 (Write path — LOCKED, from Phase 9/PERF-01/02):** Collapse
  `_write_many`'s per-batch submit-before-match (TuringDB invariant #4) into **one
  managed `begin/commit` transaction with read-your-writes**, wrapped in
  **`commit retry N`** for MVCC optimistic-concurrency conflicts. **AND pull batched
  embedding/extraction in** (single round-trip per batch for memories and document
  chunks) — the full Pitfall-7 "day one" bundle.
- **D-09 (Index bootstrap — LOCKED):** An **idempotent startup schema-init** routine
  on store init: CREATE vertex/edge types + `LSM_VECTOR` index (dims from
  `EMBED_DIMENSIONS`, COSINE) + full-text index + UNIQUE `stable_id` index, all with
  versioned/namespaced names (supports D-07). Idempotent; raises the existing
  `ValueError` on dimension mismatch vs an existing index (mirrors `store_core.py`'s
  current dimension validation).
- **D-10 (Readiness — LOCKED, from Phase 12):** **Full readiness + reconnect now** —
  the store detects ArcadeDB unavailability and reconnects, `/health` gates on a real
  probe query (replacing the TuringDB `graph.ready` stage; invariant #6 `load_graph`
  retires), and a chaos-restart test is included in Phase 4 (Pitfall 1's ArcadeDB
  analog).

### Claude's Discretion
- Exact `arcadedb_client.py` method surface (command/query/begin/commit/rollback,
  `sqlscript` shaping, retry-N wrapper location) — planner/executor's call within the
  thin-stdlib-`urllib` constraint.
- How the entity/fact/community/temporal projections are re-expressed in the chosen
  query language (the projection *logic* is unchanged; only the query dialect ports).
- Number of lexical-stress queries added to the yardstick (D-06) — a small handful is
  the intent, exact count is open.
- Wave/plan decomposition — but note the phase is large (port + 4 pull-forward
  hardening streams + a hard-gating spike); expect multiple waves with the spike as
  Wave 1 blocking everything else.

### Deferred Ideas (OUT OF SCOPE)

**Cross-Phase Reconciliation (ACTION for `/gsd-plan-phase 4` and `/gsd-phase`):**
Phase 4 now absorbs scope from later phases by explicit user decision. At planning
and at phase transition, trim the corresponding downstream scope lines so the roadmap
stays truthful:
- **Phase 9** loses full vector-index versioning (D-07, INFRA-03) and batched
  embedding/extraction (D-08, PERF-01/02). Its remainder: adaptive-fetch tuning
  (PERF-03), A/B embedding-model swap/canary/rollback *using* the D-07 foundation,
  extraction failure-mode tests (TEST-07/08).
- **Phase 12** loses the ArcadeDB reconnect/readiness/chaos-restart work (D-10). Its
  remainder: the full one-command stack, real-doc E2E, GPU-visibility, Garage/Keycloak.
- The ROADMAP Phase-4 requirement mapping (currently ARC-02…06, 08) should gain
  PERF-01/02, INFRA-03 references (or a note) to reflect the pull-forward.

**Genuinely future (not this milestone):**
- All `FUTURE-MILESTONE-retrieval-memory-quality.md` themes T1–T5 (memory
  consolidation/ADD-UPDATE-DELETE, GraphRAG-over-documents, mem0 magnitude fusion,
  reasoning/procedural memory, POLE+O entity typology). Studied from mem0 +
  neo4j-agent-memory but explicitly out of scope; ArcadeDB is the intended substrate
  for them *after* the port lands.
- Native `vector.fuse` RRF/rerank/boost — keep the Python RRF for now.
- Per-tenant ArcadeDB database isolation — Phase 5.
- The meet-or-exceed parity *gate* itself — Phase 6.
- Removing TuringDB + rewriting CLAUDE.md invariants — Phase 7.
- OIDC-derived `user_identifier`, Garage S3 staging — Phases 10/8.
- **Live TuringDB→ArcadeDB data migration** — fresh start chosen (REQUIREMENTS.md
  Out of Scope table); no production data to preserve, so there is no rename-style
  runtime-state migration to perform for existing records (see Runtime State
  Inventory below).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ARC-02 | ArcadeDB stood up as a Compose service (`arcadedata/arcadedb:26.7.1`) with its own persistent data volume | Standard Stack (image pin, volume, healthcheck pattern); Environment Availability; Runtime State Inventory (compose coexistence with `turingdb` service) |
| ARC-03 | Thin `arcadedb_client.py` over ArcadeDB's HTTP/JSON API using stdlib `urllib` | Standard Stack; Architecture Patterns (client method surface, begin/commit/rollback, sqlscript); Common Pitfalls (endpoint-path inconsistency, param binding vs inlined vectors) |
| ARC-04 | `store.py` graph CRUD ported to ArcadeDB SQL — direct port, no abstraction layer | Architecture Patterns (multi-node CREATE → sqlscript+LET translation); Don't Hand-Roll (bound `IN` params vs string-built OR-lists); Code Examples; the full op→ArcadeDB mapping in `.planning/research/ARCADEDB-capabilities-for-port.md` §1 |
| ARC-05 | Vector search ported to ArcadeDB native `LSM_VECTOR` (HNSW); `vector_id` int-join deleted | Architecture Patterns (filtered-ANN fallback, versioned index naming); Common Pitfalls (k-underfill, quantization); Code Examples; identifies exact dead code (`ids.vector_id()`, `store_utils.py`'s five `_*_vector_id` helpers, `vector_id` property writes) |
| ARC-06 | Full-text ported to ArcadeDB native Lucene; analyzer validated against golden queries; SQLite-FTS5 outbox retired | Architecture Patterns (Lucene vs sparse-vector-BM25 channel choice); Common Pitfalls (analyzer/ranking drift); Validation Architecture (D-06 yardstick + lexical stress queries) |
| ARC-08 | Stable/deterministic IDs preserved across the port; no vector-ID drift | Architecture Patterns (ID/RID separation); Common Pitfalls (Pitfall 6); Security Domain (ID-based tenant scoping, never RID) |

Pull-forward requirements absorbed into this phase (PERF-01, PERF-02, INFRA-03) are
covered under D-07/D-08/D-09 throughout this document; see the Cross-Phase
Reconciliation note above for the ROADMAP bookkeeping action.
</phase_requirements>

<project_constraints>
## Project Constraints (from CLAUDE.md / .claude/CLAUDE.md)

- **Invariant #1 (tenant scope) is non-negotiable through the port**: every read/write
  explicitly scoped by `user_identifier`, fail-closed on empty. This phase keeps a
  single shared ArcadeDB database (Phase 5 does per-tenant DBs), so `user_identifier`
  filtering is the *only* isolation mechanism this phase — there is no DB-boundary
  defense-in-depth yet (Pitfall 5's warning applies with extra force here).
- **Invariant #2 (TuringDB canonical) is explicitly superseded** this milestone —
  ArcadeDB becomes canonical. Do not preserve any TuringDB-shaped abstraction.
- **Invariant #3 (stable/deterministic IDs)** must be preserved — `ids.py`'s
  `stable_id()` remains canonical; never substitute ArcadeDB's RID.
- **Invariants #4 (submit-before-match) / #5 (app-layer vector sort) / #6
  (`load_graph` after restart) are TuringDB-specific and retire in this port** —
  replaced by D-08 (single tx + read-your-writes) / native HNSW-with-score / D-10
  (readiness+reconnect) respectively. CLAUDE.md text itself is only rewritten in
  Phase 7 (ARC-10) — don't edit CLAUDE.md invariants in this phase, but don't design
  around the old ones either.
- **600-LOC cap, no allowlist, enforced by `scripts/check-file-size.sh` on every
  commit.** `store_documents.py` (597 LOC) and `store_memory_write.py` (599 LOC) are
  already within 1–3 lines of the cap *before* any ArcadeDB-specific query-building
  code is added — the planner must budget new sibling modules (e.g.
  `store_documents_arcadedb.py` or query-builder helpers in a new
  `arcadedb_queries.py`) rather than growing these two files in place.
  `store_core.py` is at 423 LOC with headroom, but the `_query`/`_write`/`_write_many`
  choke point is exactly where the new transactional model (D-08) adds the most code
  (begin/commit/retry wrapper) — watch this file too.
- **Stdlib `urllib` only** — `httpx`/`requests`/`arcadedb-python` are explicitly
  forbidden per the locked decisions; a new HTTP client library would itself become
  a new at-risk dependency (the exact pattern CONCERNS.md is retiring).
- **GSD workflow enforcement**: file-changing work happens through `/gsd-execute-phase`,
  not ad hoc edits — the planner should structure waves so the hard-gating spike
  (Wave 1) blocks all query-builder waves, per Claude's Discretion note above.
- **Test discipline**: `python -m pytest`, `python -m ruff check src tests scripts`
  before/after every edit; `docker compose config --quiet` as part of the full gate;
  never modify tests to force green, never skip GPU/integration tiers silently.
- **Definition of Done for document/retrieval changes**: validated end-to-end on a
  real scenario — for this phase that means the D-02 spike passing *and* the store
  operations exercised against a real (dockerized) ArcadeDB instance, not just
  mocked unit tests, before the query builders are considered done.
</project_constraints>

## Summary

Phase 4 replaces every TuringDB query in the nine `store_*.py` mixins with ArcadeDB
SQL, native `LSM_VECTOR` (JVector HNSW) dense search, and native Lucene full-text —
keeping `stable_id()` as the sole cross-record identifier and deleting the
`vector_id` int-join entirely. This is a large, hard-gated phase: the CONTEXT.md
D-02 decision requires a committed smoke test in `arcadedb_client.py` to resolve five
concrete unknowns (vector function naming, filtered-ANN behavior, full-text DDL/score
exposure, vector DDL, and intra-transaction read-your-writes) *before* any store
query builder is written. This research could not resolve those unknowns further —
even the project's own `arcadedb` skill reference (generic, not 26.7.1-pinned)
disagrees with the Context7-derived capabilities doc on HTTP endpoint paths
(`/query/graph/<db>` + `/command/<db>` vs `/api/v1/query|command|begin|commit`) and on
vector-index-type naming (`HNSW`/`LSM_VECTOR_INDEX` vs `LSM_VECTOR`) — which is itself
independent evidence that the spike, not more desk research, is the only way to close
these gaps. Treat every ArcadeDB syntax claim in this document as `[ASSUMED]` unless
explicitly marked otherwise, and treat the Assumptions Log below as the literal test
plan for the spike.

Beyond the spike, the structural work is a genuine rewrite, not a search-and-replace:
today's Cypher-flavored multi-node `CREATE (a:T1{...}), (b:T2{...}), (a)-[:R]->(b)`
literals (used throughout `store_documents.py`'s `_create_document` and
`store_rebuild.py`'s `_replace_community_graph`) have no direct single-statement
ArcadeDB SQL equivalent; they become `sqlscript` batches of `LET $x = CREATE VERTEX …
CONTENT {...}; CREATE EDGE … FROM $x TO $y; …` inside one transaction. The existing
manual string-quoting (`ids.quote()`, built for TuringDB's double-quoted Cypher
strings) should be retired in favor of bound `?`/`:named` parameters everywhere except
vector literals (which ArcadeDB requires inlined) — this both follows ArcadeDB's own
convention and closes an injection-surface risk the current hand-rolled escaping
carries into a differently-quoted SQL dialect (ArcadeDB SQL string literals are
single-quoted per its own reference docs, not double-quoted like the current code
assumes). Four pull-forward hardening streams (D-07 vector-index versioning, D-08
single-transaction batched writes, D-09 idempotent schema bootstrap, D-10
readiness/reconnect) are deliberately bundled into this phase rather than deferred —
plan for genuinely more work than "swap the query strings."

**Primary recommendation:** Sequence Wave 1 as the D-02 spike alone (a standalone,
committed `arcadedb_client.py` smoke test against a real dockerized ArcadeDB
26.7.1 instance) and treat its five resolved unknowns as a gate — no query-builder
wave starts until the spike's findings are written down and the D-03/D-04/D-05
decisions it resolves are recorded as follow-up context, not left implicit.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Graph CRUD (memories, documents, chunks, entities, facts, communities, edges) | API/Backend (`store_*.py` query construction) | Database/Storage (ArcadeDB executes) | Query-building logic (batching, dedup, validation) lives in Python; ArcadeDB is the execution/storage engine only |
| Dense vector search (`LSM_VECTOR`/HNSW) | Database/Storage (native ANN index) | API/Backend (query construction, over-fetch/filter logic) | The ANN algorithm and index structure are entirely inside ArcadeDB; Python only builds the query and (until D-03 resolves) may still post-filter |
| Full-text/lexical search (Lucene) | Database/Storage (native analyzer + index) | API/Backend (channel selection, blending with dense) | Tokenization/BM25 scoring happens inside ArcadeDB's embedded Lucene; Python decides which channel(s) to query and how to blend |
| Weighted RRF fusion (`retrieval_fusion.py`) | API/Backend | — | Explicitly kept as Python logic this phase (native `vector.fuse` is future-only); no DB-side responsibility |
| Rerank (`rerank.py`) | API/Backend | External provider (HTTP) | Cross-encoder call to an OpenAI-compatible endpoint; unaffected by the backend port |
| Stable ID generation (`ids.py`) | API/Backend | — | Must never depend on ArcadeDB internals (RID); purely a Python hash function stored as an indexed DB property |
| Transaction/write-batching (D-08) | API/Backend (client wrapper, retry policy) | Database/Storage (MVCC enforcement) | ArcadeDB enforces optimistic-concurrency conflicts; the retry/backoff policy and batch shaping are Python-side responsibilities |
| Vector-index lifecycle (D-07/D-09) | API/Backend (bootstrap routine, versioning scheme) | Database/Storage (index storage) | Naming/versioning/atomic-swap logic is application-owned; ArcadeDB just stores whichever index is currently referenced |
| Readiness/reconnect (D-10) | API/Backend (`/health`, store reconnect logic) | Database/Storage (server process state) | Detecting and recovering from ArcadeDB unavailability is store/server responsibility, not something ArcadeDB does for the caller |
| Tenant isolation | API/Backend (`user_identifier` scoping, mandatory) | Database/Storage (single shared DB this phase — no isolation boundary yet) | Per CLAUDE.md invariant #1 and Pitfall 5: app-layer scoping is the *only* isolation this phase; DB-per-tenant is Phase 5 additive defense-in-depth |

This phase has no Browser/Client, Frontend-SSR, or CDN/Static tier — it is a pure
backend/database port behind the existing FastMCP tool boundary (`server.py`
untouched apart from env wiring and `/health`).

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ArcadeDB | `arcadedata/arcadedb:26.7.1` (Docker image) | Sole canonical backend — graph + native vector + native full-text in one ACID store | Locked decision (CONTEXT.md, not re-litigated); Apache-2.0 licensing was the milestone driver; multi-model avoids running 2–3 separate stateful services (STACK.md verdict) [CITED: `.planning/research/STACK.md`, MEDIUM confidence per that document's own rating] |
| Python stdlib `urllib.request` | stdlib (3.11–3.14, already required) | HTTP/JSON transport for `arcadedb_client.py` | Matches the existing `embeddings.py`/`rerank.py` convention exactly; zero new dependency surface; explicitly locked, not a free choice [VERIFIED: codebase grep — `embeddings.py`/`rerank.py` both use `urllib.request`] |

**No new pip package is added for the ArcadeDB client this phase.** The
third-party `arcadedb-python` (Beta) driver and the Postgres-wire (`psycopg`) path
are both explicitly rejected in the locked decisions and in STACK.md's "What NOT to
Use" table — do not re-open this question.

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| (none new) | — | — | This phase adds zero new pip dependencies. `graspologic-native`, `markitdown`, `pypdfium2`, `fastmcp` are untouched; `turingdb==1.35` **stays in `pyproject.toml`** this phase (removed only in Phase 7/ARC-10) since the compose stack likely runs both services side-by-side during Phases 4–6 (see Runtime State Inventory) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Native `LSM_VECTOR` HNSW + native Lucene | Qdrant + OpenSearch as separate services | Rejected per STACK.md verdict: adds 2 more stateful services, contradicts the one-command-Docker-stack goal, not warranted below ~1–5M vectors/tenant |
| Stdlib `urllib` client | `arcadedb-python` (Beta, third-party) | Rejected: repeats the "single unofficial client library" risk CONCERNS.md is retiring for `turingdb==1.35` |
| SQL MATCH/TRAVERSE for graph traversal | openCypher (`language: "openCypher"`, not `"cypher"`) | D-05 spike-decided; default lean is SQL for a uniform surface with vector/full-text functions, but Cypher may bind params more cleanly for the 2-hop entity pattern — spike must compare both |

**Installation:**
```bash
# No pip install needed for the ArcadeDB client (stdlib urllib).
# Pull/pin the image in compose.yaml:
docker pull arcadedata/arcadedb:26.7.1
```

**Version verification:** `arcadedata/arcadedb:26.7.1` was researched and pinned in
`.planning/research/STACK.md` (2026-07-11) at MEDIUM confidence — that document's own
verdict, not re-verified in this session. Before Wave 1 (the spike), pull the image
and record the actual resolved digest/build date as part of the spike's committed
artifact, since ArcadeDB's function-naming and DDL surface has visibly moved between
its own doc pages (see Common Pitfalls) and could differ again by the time this phase
executes. `[ASSUMED: image tag exists and matches STACK.md's description — verify by
`docker pull` as the spike's first action]`.

## Package Legitimacy Audit

**No external packages are installed in this phase.** `arcadedb_client.py` is built
entirely on Python's `urllib` standard-library module (already present in every
supported Python 3.11–3.14 runtime); the ArcadeDB server itself ships as a pinned
Docker image, not a pip/PyPI artifact, so the npm/PyPI/crates legitimacy-check
protocol does not apply. `pyproject.toml`'s `dependencies` list is unchanged by this
phase (see Standard Stack — Supporting).

If a future phase reconsiders `arcadedb-python` (rejected here), it must re-run the
Package Legitimacy Gate at that time — it is currently Beta status, single
third-party maintainer, per STACK.md.

## Architecture Patterns

### System Architecture Diagram

```
MCP tool call (server.py, e.g. memory_search / document_ingest_file)
        │  passes user_identifier (mandatory, fail-closed on empty)
        ▼
TuringAgentMemory facade (store.py, mixin-composed)
        │
        ├─ store_documents.py / store_memory_write.py ── ingest path
        │     1. validate + chunk text (store_chunking.py)
        │     2. _embed_many() → embedder HTTP call (unchanged)
        │     3. build ONE sqlscript batch:
        │          LET $doc = CREATE VERTEX Document CONTENT {...};
        │          LET $c1  = CREATE VERTEX Chunk CONTENT {...};
        │          CREATE EDGE HasChunk FROM $doc TO $c1;
        │          LET $c2  = CREATE VERTEX Chunk CONTENT {...};
        │          CREATE EDGE NextChunk FROM $c1 TO $c2; ...
        │     4. arcadedb_client.begin() → command(sqlscript) → commit(retry N)
        │             (single managed transaction, D-08; no submit-before-match)
        ▼
arcadedb_client.py (stdlib urllib, thin HTTP/JSON wrapper)
        │  POST .../begin  → session/tx id
        │  POST .../command (sqlscript, params bound ?/:named; vectors inlined)
        │  POST .../commit  (retry N on MVCC conflict)
        ▼
ArcadeDB 26.7.1 engine (single shared DB this phase)
        ├─ Graph storage (vertex/edge types: User, Memory, Document, Chunk,
        │    Entity, Fact, Community + HAS_MEMORY/HAS_DOCUMENT/HAS_CHUNK/
        │    NEXT_CHUNK/SUBJECT_OF/OBJECT_OF/SUPPORTED_BY/MENTIONS/IN_COMMUNITY)
        ├─ LSM_VECTOR index per record type/property (versioned/namespaced, D-07)
        └─ Full-text (Lucene) index per record type/property (D-04 channel choice)

Search path (memory_search / search_documents):
        1. embed query text → query vector
        2. arcadedb_client query: vector search (HNSW) → candidate set
           + (parallel) full-text/BM25 query → candidate set
        3. Python: over-fetch-then-filter status/expires_at (D-03 default;
           adopt pushdown only if spike proves no k-underfill)
        4. Python weighted RRF fusion (retrieval_fusion.py, unchanged)
        5. rerank.py cross-encoder call (unchanged, external HTTP)
        6. return MemoryItem/DocumentHit list to MCP tool caller

Readiness (D-10):
   store init → schema-bootstrap (D-09, idempotent) → /health probe query
   on every request cycle; ArcadeDB unavailable → store reconnects,
   /health goes unhealthy until a real probe query succeeds (no manual
   load_graph-style runbook step)
```

### Recommended Project Structure

```
src/turing_agentmemory_mcp/
├── arcadedb_client.py         # NEW — thin urllib HTTP/JSON client: query/command/
│                               #   begin/commit/rollback/sqlscript, commit-retry
│                               #   wrapper, connection/readiness probe (D-10)
├── arcadedb_schema.py         # NEW (or folded into arcadedb_client.py if small) —
│                               #   idempotent bootstrap: vertex/edge types, LSM_VECTOR
│                               #   + full-text + UNIQUE stable_id indexes, versioned
│                               #   naming (D-07/D-09), dimension-mismatch ValueError
├── store_core.py              # PORTED — _query/_write/_write_many become thin
│                               #   wrappers over arcadedb_client's tx model;
│                               #   _ensure_vector_index/_ensure_graph_loaded rewritten
├── store_documents.py         # PORTED — _create_document/_document_graph_queries
│                               #   rewritten as sqlscript+LET batches (watch 600-LOC
│                               #   cap — already at 597 LOC pre-port)
├── store_memory_write.py      # PORTED — same sqlscript+LET pattern (599 LOC pre-port)
├── store_search.py            # PORTED — VECTOR SEARCH syntax → vectorNeighbors/
│                               #   vector.neighbors (spike-resolved); rerank/fusion
│                               #   glue unchanged
├── store_evidence.py          # PORTED — MATCH multi-hop entity→fact→memory traversal;
│                               #   OR-string-built conditions → bound IN array params
├── store_chunking.py          # PORTED — NEXT_CHUNK MATCH; chunk-batch query builder
├── store_rebuild.py           # PORTED — _replace_community_graph's multi-node CREATE
│                               #   → sqlscript+LET; vector rebuild uses D-07 versioned
│                               #   index swap instead of in-place LOAD VECTOR
├── store_utils.py             # PORTED — delete _memory_vector_id/_entity_vector_id/
│                               #   _fact_vector_id/_community_vector_id/
│                               #   _document_vector_id (dead code post-port, see
│                               #   Don't Hand-Roll)
└── ids.py                     # PORTED — delete vector_id(); stable_id()/cypher_var()
                                #   stay; quote() likely deleted in favor of bound
                                #   params (see Common Pitfalls — quoting mismatch)
```

### Pattern 1: Multi-node graph writes become `sqlscript` + `LET` batches, not a single CREATE literal

**What:** TuringDB's Cypher-flavored `CREATE (a:T1{...}), (b:T2{...}), (a)-[:R]->(b)`
single-statement literal (used in `_create_document`, `_replace_community_graph`) has
no direct ArcadeDB SQL equivalent. ArcadeDB's idiomatic multi-record-in-one-transaction
pattern is an `sqlscript` body with `LET $var = CREATE VERTEX Type CONTENT {...};` per
node, then `CREATE EDGE Type FROM $x TO $y;` per edge, submitted as one POST to
`/command` (or `/sqlscript`) inside one `begin`/`commit`.

**When to use:** Every place today's code builds a `CREATE (...), (...), (...)-[...]->(...)`
literal string: `_create_document`'s per-chunk node+edge batch, `_replace_community_graph`'s
community-node + `IN_COMMUNITY` edges, `_ensure_user`'s single-node create (simplest
case — trivially becomes `CREATE VERTEX User CONTENT {...}` if not already present).

**Example (illustrative — exact keyword casing/`sqlscript` framing to be confirmed by spike):**
```sql
-- Source: ARCADEDB-capabilities-for-port.md §1 [S1][S3], cross-referenced against
-- this project's arcadedb skill sql-reference.md "Transaction Control" section.
-- [ASSUMED — spike must confirm sqlscript LET-chaining across CREATE VERTEX/EDGE]
BEGIN;
LET $doc = CREATE VERTEX Document CONTENT {"id": "doc_abc", "user_identifier": "u1", ...};
LET $c1  = CREATE VERTEX Chunk CONTENT {"id": "doc_abc#1", "document_id": "doc_abc", ...};
CREATE EDGE HasChunk FROM $doc TO $c1;
LET $c2  = CREATE VERTEX Chunk CONTENT {"id": "doc_abc#2", "document_id": "doc_abc", ...};
CREATE EDGE HasChunk FROM $doc TO $c2;
CREATE EDGE NextChunk FROM $c1 TO $c2;
COMMIT RETRY 100;
```

### Pattern 2: Vector DDL + versioned/namespaced index naming (D-07/D-09)

**What:** Each of today's 5 TuringDB vector indexes (memory/document/entity/fact/
community, each additionally tenant-namespaced via `_tenant_vector_index`'s
blake2b-digest suffix) becomes an ArcadeDB `LSM_VECTOR` index created at store
bootstrap, named with an explicit version suffix so a rebuild can atomically swap to
a new index name rather than mutating the live one in place.

**When to use:** Store init (`_StoreCore.bootstrap`/`_ensure_vector_index` today);
this becomes `arcadedb_schema.py`'s idempotent bootstrap routine (D-09).

**Example:**
```sql
-- Source: capabilities doc §1 [S2][S4]; exact SQL DDL form is a spike unknown
-- [ASSUMED — confirm CREATE VECTOR INDEX takes/infers dimensions + COSINE on 26.7.1]
CREATE VECTOR INDEX ON Chunk(embedding) LSM TYPE COSINE
-- Java-API form (confirms the options the SQL DDL should wrap):
-- buildTypeIndex('Chunk',{'embedding'}).withLSMVectorType().withDimensions(768).create()
```
Version/namespace scheme (Python-side, not ArcadeDB syntax): keep today's
`_tenant_vector_index(base_name, user_identifier)` blake2b-digest naming, and add a
version suffix (e.g. `..._v2`) bumped on each `rebuild_vector_projection` call; the
"currently active" version is tracked as a small piece of store state (a Config-type
vertex or a well-known property) so search queries always resolve to the current
version and a rebuild-in-progress never serves partially-rebuilt results.

### Pattern 3: Filtered-ANN fallback — keep over-fetch-then-filter until proven safe (D-03)

**What:** Continue the existing `max(limit * 4, limit)` over-fetch + Python-side
`status='active'`/`expires_at` filter pattern (already present in
`store_search.py`/`store_documents.py`) rather than assuming a `WHERE` clause on the
outer `SELECT` pushes down into the HNSW search. Only switch to native predicate
pushdown if the spike's smoke test proves it does not under-fill `k`.

**When to use:** Every vector search call site (`search_memory`, `search_documents`,
`_episode_dense_evidence`, `_fact_dense_evidence`, `_entity_dense_evidence`,
`_community_dense_evidence`).

### Pattern 4: Bound array parameters replace hand-built OR-condition strings

**What:** Several evidence-collection helpers build a `WHERE (a.id = "x" OR a.id =
"y" OR ...)` condition by string-joining `quote()`-escaped values
(`_expand_entity_evidence`, `_fact_sources_by_ids`, `_community_sources_by_ids`,
`_memory_rows_for_ids`, `_existing_entity_ids`). ArcadeDB's HTTP API accepts JSON
array values for named parameters; prefer `WHERE id IN :ids` bound to a JSON array
over string-built OR-lists — this removes an entire class of quoting/escaping code
and the injection-surface risk of manual string escaping in a differently-quoted SQL
dialect (see Common Pitfalls).

**When to use:** Any of the five call sites above; also the `_row_is_expired`/status
filters that currently interpolate `quote(document_id)`/`quote(user_identifier)`
directly into f-strings.

**Example:**
```sql
-- [ASSUMED — confirm ArcadeDB accepts a JSON array bound to a named param for IN;
-- capabilities doc confirms ? and :named binding generally [S5] but not array-typed
-- params specifically]
SELECT id, source_memory_id, confidence FROM Fact
WHERE user_identifier = :user_identifier AND id IN :fact_ids AND status = 'active'
```

### Anti-Patterns to Avoid

- **Using ArcadeDB's native RID as a stored/derived identifier.** Never call
  `record.getIdentity()`/reference `#12:34` in ID-generation or vector-correlation
  logic — RIDs are not stable across compaction (Pitfall 6). `stable_id()` stays the
  only identifier that crosses a rebuild.
- **Assuming `vectorNeighbors`/`` `vector.neighbors` `` resolves without testing.**
  Both spellings appear in different official ArcadeDB doc pages for what is
  apparently the same feature; this project's own generic `arcadedb` skill reference
  doesn't even show either name (it shows a third form, `vector_search()`) — pick
  one only after the spike confirms it against the pinned 26.7.1 image.
  `[ASSUMED]`
- **Assuming the HTTP endpoint paths are `/api/v1/...`.** The capabilities doc (via
  Context7) cites `/api/v1/command|query|begin|commit|rollback`; this project's own
  `arcadedb` skill reference shows unversioned `/query/graph/<db>` and
  `/command/<db>`. Confirm the actual path prefix against the pinned image before
  writing `arcadedb_client.py` — don't guess from either source alone. `[ASSUMED]`
- **Assuming `COMMIT RETRY N` is valid ArcadeDB SQL syntax.** Cited only via the
  capabilities doc's [S5] (python bindings/ha-raft test docs via Context7); not
  confirmed in this project's generic skill reference. If unsupported, D-08's retry
  policy must instead be a Python-side retry loop around `begin`/`command`/`commit`
  catching the MVCC conflict error — budget for both outcomes in the plan.
  `[ASSUMED]`
- **Reusing `ids.quote()` unchanged for ArcadeDB string literals.** It escapes for
  double-quoted Cypher-style literals (TuringDB); ArcadeDB SQL's own reference
  examples use single-quoted string literals throughout (`WHERE name = 'Alice'`).
  Retire `quote()` in favor of bound parameters wherever the value is data, not a
  pattern-variable name (see Security Domain).
- **Porting `_write_many`'s per-batch chunking-by-byte-size unchanged, believing it
  still exists "because TuringDB required it."** The *reason* for
  `document_graph_batch_chunks`/`document_graph_batch_bytes` changes under D-08 (one
  managed transaction, read-your-writes) — TuringDB's submit-before-match constraint
  goes away, but ArcadeDB's own transaction-size caveat ("the whole transaction is
  kept in host RAM... consider splitting very large transactions" — this project's
  `arcadedb` skill, core-concepts.md) means *some* size-based splitting is still
  warranted, just for a different reason. Don't delete the batching logic outright;
  re-derive its purpose.
- **Letting the ArcadeDB port grow `store_documents.py` or `store_memory_write.py`
  past 600 LOC.** Both are already at 597/599 LOC on the TuringDB code; the
  `sqlscript`+`LET` rewrite is *more* code per operation, not less. Extract
  query-building helpers into new sibling modules before this happens, not after
  `check-file-size.sh` fails a commit.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Approximate nearest-neighbor vector search | A custom cosine-similarity brute-force scan or a hand-rolled HNSW | Native `LSM_VECTOR` (JVector HNSW) index | This is the entire reason ArcadeDB was chosen for this backend (STACK.md verdict); reinventing ANN indexing is exactly the "young-but-native vs. hand-rolled" tradeoff the verdict already accepted |
| Full-text tokenization + BM25 scoring | A custom tokenizer/stemmer/ranking formula | Native Lucene full-text index (`CONTAINSTEXT`/`SEARCH`) with an explicitly chosen analyzer | Lucene is the same library Elasticsearch/OpenSearch/Solr wrap; a hand-rolled tokenizer would both be worse and reintroduce the exact FTS5-outbox-crash-consistency bug this port retires |
| MVCC optimistic-concurrency retry | A bespoke exponential-backoff loop with ad hoc conflict detection | ArcadeDB's own `commit retry N` (if the spike confirms it exists) or, failing that, a single small retry wrapper around `begin`/`command`/`commit` catching the documented `ConcurrentModificationException`-equivalent HTTP error | Don't build a generic retry framework; ArcadeDB's transaction model already defines what "conflict" means — wrap its own signal, don't guess at one |
| Dynamic multi-value `WHERE id = x OR id = y OR ...` conditions | Hand-built string-joined OR clauses with custom escaping (today's `_expand_entity_evidence` et al. pattern) | Bound `IN :param_array` with a JSON array value | Removes an entire escaping/injection surface and is idiomatic parameterized SQL; see Architecture Pattern 4 |
| Vector-index rebuild-in-place | Overwriting the live `LSM_VECTOR` index during `rebuild_vector_projection`/`rebuild_communities` | Versioned/namespaced index name + atomic pointer swap (D-07) | In-place rebuild is exactly the known `memory_rebuild_vector_projection` stale-vector-accumulation bug (FIX-06/D-07) this phase is pulling forward to fix, not to re-port |
| Manual "is ArcadeDB up" polling/backoff logic from scratch | A bespoke reconnect loop with sleep/retry parameters invented ad hoc | A small `arcadedb_client.probe()`/`is_ready()` method wired into `/health` (D-10), following the same shape as the existing `runtime_signals.configure_stage("graph", ...)` pattern already in `store_core.py` | The store already has a "stage readiness" abstraction (`RuntimeSignals`); extend it, don't invent a parallel health-check mechanism |

**Key insight:** ArcadeDB was selected specifically because it subsumes the need for
separate vector/search infrastructure (STACK.md verdict). Every "don't hand-roll" item
above is a case where hand-rolling would either duplicate what ArcadeDB already does
natively (ANN, full-text, MVCC) or re-introduce a bug this phase exists to fix
(stale-vector accumulation, string-escaping injection risk, silent-restart blindness).

## Runtime State Inventory

> This phase is a **backend swap**, not a rename, and REQUIREMENTS.md explicitly
> puts "live TuringDB→ArcadeDB data migration" out of scope (fresh start — no
> production data to preserve). The five categories below are answered explicitly
> per the required protocol; most are "not applicable" precisely *because* of the
> fresh-start decision, but two categories carry real action items for the planner.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None** — no existing TuringDB records need migrating; fresh ArcadeDB database starts empty (REQUIREMENTS.md Out of Scope: "Live TuringDB→ArcadeDB data migration"). Verified: no production deployment exists yet (Alpha status, `pyproject.toml` classifiers) | None |
| Live service config | **`compose.yaml` currently defines only a `turingdb`/`turingdb-volume-init` service pair** (lines 4–66) with env wiring (`TURINGDB_URL`, `TURINGDB_HOME`, `TURINGDB_GRAPH`, 5×`TURINGDB_*_INDEX`) threaded into the `turing-agentmemory-mcp` service (lines 131–150) [VERIFIED: grep of `compose.yaml`]. This phase must **add** an `arcadedb` service (new healthcheck, new persistent volume) **without removing** the `turingdb` service/env vars — ARC-10 (Phase 7) is the removal step, not this phase. Coexistence in `compose.yaml` for Phases 4–6 is expected, not a mistake to "clean up" early. | Add `arcadedb` service + volume to `compose.yaml`; add analogous `ARCADEDB_*` env vars alongside (not replacing) `TURINGDB_*`; wire `store_from_env()` to read the new vars when constructing `arcadedb_client.py` (leave `TuringDB(...)` construction and `TURINGDB_*` reads in place for now) |
| OS-registered state | **None** — no Windows Task Scheduler entries, pm2/launchd/systemd units, or other OS-level registrations reference `turingdb` by name; this is a containerized service, not a host-registered process | None |
| Secrets/env vars | `TURINGDB_AUTH_TOKEN` exists as an optional env var (`server.py:118`) but is not observed set in `.env.example`; no SOPS-managed secret keys reference `turingdb` by name in this repo (only `AGENTMEMORY_AUTH_TOKEN(S)` for MCP-level bearer auth, unrelated to the backend). New `ARCADEDB_*` env vars (URL, auth if ArcadeDB security is enabled) are net-new, not renames — verify with the spike whether the arcadedb Docker image requires a default root/admin credential (its admin-reference docs cover this) and whether that credential needs its own env var / no-default-in-code handling | Add `ARCADEDB_URL`/credential env var(s) as new entries in `.env.example`; do not reuse `TURINGDB_*` names |
| Build artifacts | `turingdb==1.35` remains a listed dependency in `pyproject.toml` (`dependencies` array) and is **not removed this phase** — removing it is explicitly Phase 7/ARC-10 scope. No stale egg-info/compiled-binary concerns since this is a pure Python dependency addition (none) rather than a build-tool rename | None this phase; note for Phase 7 planning that removing `turingdb==1.35` requires re-running `pip install -e .` to actually drop the installed package, not just editing `pyproject.toml` |

**Canonical-question answer:** After this phase's code changes land, the `turingdb`
Python package and its Docker service both still exist in the tree, running
side-by-side with the new `arcadedb` service, purely because Phase 6's gate needs a
comparison point and Phase 7 is the explicit, gated removal step. This is intentional
scope discipline, not an oversight — the planner should not "clean up" TuringDB
remnants in this phase.

## Common Pitfalls

### Pitfall 1: Treating the capabilities doc's syntax sketches as verified rather than hypotheses

**What goes wrong:** `.planning/research/ARCADEDB-capabilities-for-port.md` is a
carefully-built op→ArcadeDB mapping table, but its own confidence rating is MEDIUM
and it explicitly flags five unknowns in its §3. This research session independently
consulted the project's `arcadedb` skill (a broader, non-version-pinned reference)
and found it does **not** corroborate several specifics: it shows a third vector
function name (`vector_search(indexName, queryVector, limit)`) that matches neither
`vectorNeighbors` nor `` `vector.neighbors` ``; it shows unversioned HTTP paths
(`/query/graph/<db>`, `/command/<db>`) rather than `/api/v1/...`; and it lists the
vector index type as `HNSW` or `LSM_VECTOR_INDEX` in `CREATE INDEX ... TYPE HNSW`
form, not `LSM_VECTOR`. None of these are necessarily wrong — ArcadeDB's own docs
appear inconsistent across pages/versions — but a query builder written against any
one source without the spike could simply fail against the pinned 26.7.1 image.

**Why it happens:** ArcadeDB is a fast-moving, community-documented project where
vector/full-text features were added across multiple 2025–2026 releases (per
STACK.md's own release-note citations); doc pages get updated at different times and
scraped snapshots (Context7, static skill references) can capture different moments.

**How to avoid:** Do not write a single query builder against any cited syntax until
the D-02 spike's smoke test has executed that exact statement against the pinned
`arcadedb_client.py`/`arcadedata/arcadedb:26.7.1` container and recorded the actual
resolved function/DDL/path names as the spike's committed output.

**Warning signs:** A "port complete" claim citing only the capabilities doc or only
the generic skill reference, without a green smoke-test run against a live container.

### Pitfall 2: ArcadeDB SQL string-literal quoting differs from the current `ids.quote()` escaper

**What goes wrong:** `ids.quote()` escapes backslash/double-quote/CR/LF/tab for
embedding a value inside a **double-quoted** literal (`"{quote(value)}"`), which is
how the current TuringDB/Cypher-flavored queries build every `WHERE x = "..."` and
node-literal property. ArcadeDB SQL's own reference documentation (this project's
`arcadedb` skill, sql-reference.md) uses **single-quoted** string literals throughout
every example (`WHERE name = 'Alice'`, `SET name = 'Bob'`). If the port keeps
`quote()`'s double-quote-escaping logic unchanged but the underlying dialect expects
single-quote delimiters (or vice versa), values containing an unescaped quote
character of the *other* kind become a live SQL-injection / malformed-query surface
in the new dialect — a bug class the current TuringDB-shaped escaper was never
designed to close.

**Why it happens:** It is easy to port `quote()` as "the existing sanitizer, keep it,"
without re-deriving which delimiter character the new dialect actually uses.

**How to avoid:** Prefer bound `?`/`:named` parameters everywhere a *value* (not a
pattern-variable name) is interpolated — this sidesteps the delimiter question
entirely and is ArcadeDB's own recommended practice ("Always use parameterized
queries in application code to prevent injection attacks" — this project's `arcadedb`
skill, sql-reference.md Best Practices). Reserve `cypher_var()`-style sanitization
only for constructing pattern-variable names (which are identifiers, not data) if the
chosen graph-query surface still needs them.

**Warning signs:** Any new ArcadeDB query-building code that string-interpolates a
value inside a hand-written quote character rather than binding a parameter.

### Pitfall 3: Filtered-ANN k-underfill (the capabilities doc's own flagged unknown)

**What goes wrong:** Combining `vectorNeighbors(...)`/`vector.neighbors(...)` with an
outer `WHERE status='active' AND expires_at > ...` may filter *after* the top-k ANN
results are returned, not push the predicate into the HNSW search itself — meaning a
query can silently return fewer than `k` usable results even when more exist in the
index. TuringDB has this exact problem today (that's why `max(limit*4, limit)`
over-fetch exists); nothing confirms ArcadeDB is better or worse.

**How to avoid:** D-03's locked default — keep over-fetch-then-filter, made adaptive
— stands until the spike proves otherwise. Do not delete the over-fetch logic
speculatively.

**Warning signs:** Search results measurably fewer than `limit` for tenants known to
have adequate active records; recall regressions on the D-06 yardstick specifically
correlated with filter predicates (status/expiry), not with the vector query itself.

### Pitfall 4: Lucene analyzer mismatch silently changes lexical ranking (carried from PITFALLS.md Pitfall 8)

**What goes wrong:** ArcadeDB's full-text index lets you pick (and mix per-field)
different Lucene analyzers; none is guaranteed to match SQLite FTS5's default
`unicode61` tokenization. A mismatch produces "index built, queries return results"
correctness with silently different *ranking* — invisible to unit tests, visible
only on the D-06 golden-query/lexical-stress comparison.

**How to avoid:** D-04 requires the spike to build both Lucene and
`LSM_SPARSE_VECTOR`/BM25 channels and pick empirically against the yardstick — do not
default to whatever Lucene analyzer ArcadeDB ships without comparison.

**Warning signs:** Recall/MRR drops specifically on the hand-authored
keyword/error-code/exact-phrase stress queries while semantic queries look fine — the
signature of a tokenizer mismatch, not a broader retrieval bug.

### Pitfall 5: Read-your-writes assumption inside the new single-transaction write path (D-08)

**What goes wrong:** Collapsing `_write_many`'s per-batch submit-before-match into
one managed transaction assumes a `MATCH`/`SELECT` later in the *same* transaction
can see a `CREATE VERTEX` earlier in that transaction (needed for the `LET $prev =
...; CREATE EDGE ... FROM $prev TO ...` chaining pattern). This project's `arcadedb`
skill reference states MVCC and ACID transactions generally but does not explicitly
confirm same-transaction read-your-writes for freshly created vertices referenced by
`LET`-bound RID variables versus a later independent `MATCH`. The capabilities doc
[S3] asserts intra-transaction visibility but flags it as an unknown in its own §3.

**How to avoid:** The D-02 spike must explicitly test: create vertex A, in the same
transaction run a `MATCH`/`SELECT` that finds A by a property filter (not just by the
`$var` reference used to create the edge), and confirm it succeeds before committing
to removing per-batch submission entirely.

**Warning signs:** Intermittent "chunk N+1 not found" errors during document ingest
under D-08's new single-transaction model, especially for documents large enough to
span what used to be multiple TuringDB batches.

### Pitfall 6: Compose coexistence with TuringDB is easy to "clean up" prematurely

**What goes wrong:** Since ARC-10 (removing TuringDB from `compose.yaml`/
`pyproject.toml`) is a separate, later, gated phase (Phase 7), a well-meaning
"stabilization" instinct during Phase 4 might remove the `turingdb`/
`turingdb-volume-init` compose services or the `turingdb==1.35` pyproject dependency
once the ArcadeDB path looks like it works — but Phase 6's migration-correctness gate
still needs the *option* of running both stacks side by side for manual comparison,
and the requirement traceability explicitly assigns ARC-10 to Phase 7, not Phase 4.

**How to avoid:** Add, don't replace, in `compose.yaml`/`pyproject.toml` this phase
(see Runtime State Inventory). Removal is Phase 7's explicit, gated deliverable.

**Warning signs:** A Phase 4 diff that deletes `turingdb`-related compose service
definitions, env vars, or the `turingdb` pyproject dependency.

## Code Examples

### Vector search — the two competing syntax forms this phase must resolve empirically

```sql
-- Source: ARCADEDB-capabilities-for-port.md §1 [S2][S4] (Graph-RAG page / vector-DBMS doc)
-- [ASSUMED — pick exactly one after the spike; do not implement both]
SELECT content, source FROM Chunk
ORDER BY vectorNeighbors('Chunk[embedding]', :vec, :k) DESC
LIMIT :k
```
```sql
-- Alternate function-call form cited by the same capabilities doc
-- [ASSUMED]
SELECT expand(`vector.neighbors`('Chunk[embedding]', :vec, 50))
```
```sql
-- Third form observed in this project's own arcadedb skill reference (generic,
-- non-version-pinned) — matches neither of the above
-- [ASSUMED]
SELECT name, vector_search('embedding_index', @embedding, 10) as similar FROM Documents
```

### Full-text — CONTAINSTEXT is the one form corroborated by both sources

```sql
-- Source: capabilities doc §1 [S2][S4] AND this project's arcadedb skill
-- (sql-reference.md Filtering Syntax "Full-text search" example) — the one
-- vector/full-text claim in this document with two independent corroborating
-- sources, so treat as [CITED] rather than pure [ASSUMED]
SELECT * FROM Chunk WHERE content CONTAINSTEXT 'knowledge graph'
```

### Multi-hop graph traversal — SQL MATCH form (D-05 default lean)

```sql
-- Source: capabilities doc §1 [S3]; syntax style corroborated by this project's
-- arcadedb skill (sql-reference.md Graph-Specific SQL section), though the exact
-- curly-brace {type,as,where}.out() chaining vs arrow-notation choice is itself
-- part of the D-05 spike comparison
-- [ASSUMED — confirm untyped bidirectional `--` two-hop matches today's Cypher
-- `(e:Entity)--(n:Entity)` semantics]
MATCH {type: Entity, as: e, where: (user_identifier = :user_identifier AND status = 'active')}
  .out('SUBJECT_OF'){as: f}
  .out('SUPPORTED_BY'){as: m}
RETURN m.id, f.id, f.confidence, e.id
```

### Transaction control (D-08)

```sql
-- Source: this project's arcadedb skill (sql-reference.md "Transaction Control")
-- confirms BEGIN/COMMIT/ROLLBACK exist as SQL keywords; the `RETRY N` clause and
-- exact isolation-level syntax are only cited via the capabilities doc [S5],
-- unconfirmed by this project's skill reference
-- [CITED for BEGIN/COMMIT/ROLLBACK; ASSUMED for RETRY N]
BEGIN
INSERT INTO Person CONTENT {"name": "John"}
UPDATE Person SET status = 'active'
COMMIT
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| TuringDB `VECTOR SEARCH IN {idx} FOR {k} {literal} YIELD ids, score MATCH ... WHERE vector_id = ids` (int-join, app-layer re-sort per invariant #5) | Native `LSM_VECTOR`/HNSW returns record + score directly, no join | This phase (ARC-05) | `ids.vector_id()` and all five `_*_vector_id()` staticmethods become dead code; every `vector_id: {vid}` property write is deleted from node-creation literals |
| TuringDB per-batch `new_change()`/`CHANGE SUBMIT`/`checkout()` (invariant #4, submit-before-match) | One managed `begin`/`command(sqlscript)`/`commit retry N` transaction with read-your-writes | This phase (D-08) | `_write_many`'s per-batch chunking logic is repurposed (transaction-size hygiene, not correctness) rather than deleted outright |
| SQLite FTS5 outbox (`sparse_index.py`, prepare/commit/replay crash-consistency pattern) | Native ArcadeDB Lucene full-text, ACID-consistent with graph writes | This phase (ARC-06) | `sparse_index.py`'s outbox mechanism is retired for this backend; `fusion_enabled`'s `sparse_index is not None` gate and the "bm25" channel's data source both change, RRF weighting logic (`retrieval_fusion.py`) stays |
| `load_graph` manual/undocumented reconnect step after a daemon restart (invariant #6, Pitfall 1) | Store-level readiness probe + reconnect wired into `/health` (D-10) | This phase | `load_graph_after_restart()` (currently only called from `e2e_score.py`/`benchmark_stages.py` test harnesses, never from a reconnect path) becomes the model for a *real* reconnect handler, not test-only plumbing |
| In-place vector index rebuild (known stale-vector-accumulation bug, FIX-06) | Versioned/namespaced index name + atomic swap on rebuild completion | This phase (D-07) | `rebuild_vector_projection`/`rebuild_communities` must track "current version" state and swap it only after the new index is fully populated |

**Deprecated/outdated:**
- `ids.vector_id()` — the synthetic int-hash vector ID scheme is deleted, not ported;
  native vector search correlates directly to the record carrying `stable_id()`.
- `sparse_index.py`'s outbox `prepare`/`commit_batch`/`discard_prepared`/`replay`
  cycle — retired for the ArcadeDB backend (native Lucene is already ACID).
- CLAUDE.md invariants #4/#5/#6 — superseded by this phase's design, though the
  CLAUDE.md text itself is only rewritten in Phase 7.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `vectorNeighbors(...)` or `` `vector.neighbors`(...) `` (not `vector_search(...)`) is the correct 26.7.1 function name for HNSW search | Architecture Patterns, Code Examples | Every vector-search query builder fails at runtime; blocks ARC-05 entirely — this is why D-02 gates the whole phase |
| A2 | HTTP API paths are `/api/v1/command|query|begin|commit|rollback` (capabilities doc) rather than unversioned `/query/graph/<db>`/`/command/<db>` (this project's `arcadedb` skill) | Standard Stack, Architecture Patterns | `arcadedb_client.py`'s base URL construction is wrong; every request 404s until corrected — cheap to fix once discovered, but must be discovered by the spike, not assumed |
| A3 | `COMMIT RETRY N` is valid ArcadeDB SQL/sqlscript syntax for MVCC-conflict auto-retry | Architecture Patterns, Code Examples, D-08 | If unsupported, the write path needs a Python-side retry wrapper instead — different code shape, different LOC budget, different place in `arcadedb_client.py`'s method surface |
| A4 | `CREATE VECTOR INDEX ... LSM TYPE COSINE` (SQL DDL) both takes/infers the correct dimensionality from `EMBED_DIMENSIONS` and matches the Java-API `withDimensions(N)` form | Architecture Patterns, D-09 | Dimension mismatch either silently truncates/pads vectors or raises at a different point than today's fail-fast `ValueError`; D-09's bootstrap validation logic depends on knowing exactly how ArcadeDB reports a mismatch |
| A5 | A `MATCH`/`SELECT` later in the same transaction can find (by property filter, not just `$var` reference) a vertex `CREATE`d earlier in that same transaction (read-your-writes) | Architecture Patterns, Common Pitfalls (Pitfall 5), D-08 | If false, the entire "collapse into one managed transaction" design (D-08) doesn't work as sketched and needs a different chunking strategy — much larger replanning impact than the other assumptions |
| A6 | ArcadeDB SQL string literals are single-quoted (not double-quoted like `ids.quote()` currently assumes) | Common Pitfalls (Pitfall 2), Security Domain | If the port keeps `quote()`'s escaping unchanged assuming double-quote delimiters, malformed queries or an injection surface can appear in code paths not fully converted to bound params |
| A7 | ArcadeDB accepts a JSON array bound to a single named parameter for use with `IN :param` | Architecture Patterns (Pattern 4), Don't Hand-Roll | If unsupported, the OR-string-list-building pattern in `_expand_entity_evidence` et al. must stay (with bound scalar params per value instead, e.g. dynamically generated `id = ?` OR-chain with positional params) rather than being replaced by a single bound array |
| A8 | `arcadedata/arcadedb:26.7.1` is a valid, pullable Docker Hub tag matching the described feature set (native `LSM_VECTOR`, Lucene, HTTP/JSON API as described) | Standard Stack | If the tag has moved or been superseded, the whole phase's version pin needs updating before Wave 1 can even start pulling the image |
| A9 | ArcadeDB's admin default credentials / auth requirements for a fresh container (whether a root password is required at startup) | Runtime State Inventory (Secrets/env vars) | Missing auth wiring could mean either an insecure default-credential deployment or a startup failure the spike needs to surface early |

**All nine assumptions above are exactly the surface the D-02 spike must resolve.**
None of them should be treated as authoritative until the spike's committed smoke
test passes against the pinned image — this is the literal meaning of "hard gate."

## Open Questions

1. **Which of `vectorNeighbors`/`` `vector.neighbors` ``/`vector_search` actually
   resolves on `arcadedb:26.7.1`, and does it accept the property-qualified
   `'Type[property]'` index-reference form the capabilities doc shows, or a
   separate named-index argument?**
   - What we know: three different spellings appear across three consulted sources.
   - What's unclear: which (if any) is current for 26.7.1 specifically.
   - Recommendation: spike test 1 (of the D-02 smoke test) — create a small
     `LSM_VECTOR` index, insert a handful of known vectors, and try each spelling
     until one succeeds; record the winner as spike output, not a research finding.

2. **Does a `WHERE` predicate on the outer `SELECT`/`MATCH` around a vector-search
   function push into the ANN search (partition pruning) or only post-filter the
   top-k?**
   - What we know: TuringDB has this exact problem today (hence 4× over-fetch);
     nothing in any consulted source confirms ArcadeDB's behavior either way.
   - What's unclear: whether combining `status='active' AND expires_at > NOW()`
     with the vector function under-fills `k`.
   - Recommendation: spike test 2 — populate an index with a known mix of
     active/inactive/expired records, run a filtered top-k query, and count
     returned vs. expected results at several `k` values.

3. **Does `sqlscript`'s `LET $x = CREATE VERTEX ...` binding make `$x` (and records
   reachable by property lookup, not just the `$var`) visible to a later `MATCH`
   inside the same transaction?**
   - What we know: MVCC/ACID transactions are confirmed generally; same-transaction
     read-your-writes for freshly created vertices is asserted by the capabilities
     doc but flagged there as unconfirmed.
   - What's unclear: whether this holds for property-filtered lookups specifically
     (not just `$var`-to-`$var` edge creation), which is what the chunk-batching
     rewrite needs.
   - Recommendation: spike test 3 — in one transaction, `CREATE VERTEX` A, then
     `SELECT FROM Type WHERE someProperty = 'A-value'` and confirm A is found before
     `COMMIT`.

4. **Which Lucene analyzer (if any) approximates SQLite FTS5's `unicode61`
   tokenization closely enough to avoid ranking drift on the D-06 yardstick, and how
   is the matched document's relevance score exposed as an orderable SQL column?**
   - What we know: `CONTAINSTEXT` is corroborated by two sources as a filter
     predicate; score *exposure* (as opposed to just filtering) is not confirmed by
     either source read in this session.
   - What's unclear: whether `CONTAINSTEXT` alone is boolean-only (candidate-set
     filtering, score comes from elsewhere) or exposes a scorable value directly.
   - Recommendation: spike test 4, feeding directly into D-04/D-06.

5. **Is there a default/required root credential for a fresh `arcadedata/arcadedb`
   container, and does the compose healthcheck pattern need an auth-aware probe?**
   - What we know: none of the sources consulted in this session covered ArcadeDB
     security/auth defaults in depth (out of scope for the capabilities doc; the
     `arcadedb` skill's admin-reference.md was not read this session).
   - What's unclear: whether `arcadedb_client.py`'s `begin`/`command`/`commit` calls
     need to carry Basic Auth credentials by default.
   - Recommendation: read `.claude/skills/arcadedb/references/admin-reference.md`
     (Security section) as part of Wave 1 spike prep, before writing the compose
     service definition.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Engine | ArcadeDB compose service, the D-02 spike's smoke test | Yes (verified this session) | 29.6.1 | — |
| Python | `arcadedb_client.py` (stdlib `urllib`) | Yes | 3.12.10 (dev venv); repo targets 3.11–3.14 | — |
| ArcadeDB Docker image (`arcadedata/arcadedb:26.7.1`) | ARC-02, the whole port | Not yet pulled/verified this session | — (pin per STACK.md, `[ASSUMED]` — verify by `docker pull` as Wave 1's first step) | None — this is the hard dependency the whole phase exists to stand up |
| `turingdb` PyPI package (`turingdb==1.35`) | Coexistence during Phases 4–6 (Runtime State Inventory) | Already an installed dependency (existing venv) | 1.35 | — |

**Missing dependencies with no fallback:**
- The pinned ArcadeDB image itself has not been pulled/verified in this research
  session — do this as the literal first action of Wave 1, before writing any client
  code, since A8 (image tag validity) is otherwise an unverified assumption blocking
  everything downstream.

**Missing dependencies with fallback:**
- None identified — Docker and Python are both present and adequate.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.2+ (already pinned, `pyproject.toml` `[project.optional-dependencies].dev`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths=tests`, `pythonpath=src` |
| Quick run command | `python -m pytest tests/test_<affected>.py -q` |
| Full suite command | `python -m pytest -q` |
| Deterministic correctness gate | `python scripts/e2e_score.py --out e2e-results.json` (or `make e2e`) — spins up a temporary local backend + stub embed/rerank endpoints; this is the harness that must be pointed at ArcadeDB for the parity comparison this phase feeds into Phase 6 |
| Dockerized variant | `docker compose run --rm e2e` (or `make docker-e2e`) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ARC-02 | `arcadedb` compose service starts healthy with a persistent volume | integration (compose) | `docker compose up -d arcadedb && docker compose ps arcadedb` (assert `healthy`) | ❌ Wave 0 — no existing compose-health test for a new service; follow the existing `test_docker_hardening.py`-style structural-test pattern |
| ARC-03 | `arcadedb_client.py` performs graph + vector + full-text ops via stdlib `urllib` | unit + smoke (this IS the D-02 hard gate) | `python -m pytest tests/test_arcadedb_client.py -q` (committed spike smoke test) | ❌ Wave 0 — net-new file, this is the phase's Wave 1 deliverable itself |
| ARC-04 | All graph CRUD served by ArcadeDB SQL; no `turingdb` calls remain in `store.py` read/write paths | unit (per store_*.py mixin) + static check | `python -m pytest tests/test_store_*.py -q`; `grep -rn "from turingdb import\|self.client\." src/turing_agentmemory_mcp/store_*.py` (should show `arcadedb_client`, not `turingdb`, in read/write paths) | Partial — most `store_*.py` behavior is exercised via feature-level tests (`test_fused_memory_search.py`, `test_hybrid_search.py`, `test_document_*.py`) rather than a dedicated `test_store_core.py`; no test currently asserts "which backend module is imported" |
| ARC-05 | Vector search on native `LSM_VECTOR`; `vector_id` int-join deleted | unit + static check | `python -m pytest tests/test_hybrid_search.py tests/test_fused_memory_search.py -q`; `grep -rn "vector_id\b" src/turing_agentmemory_mcp/` (should show zero hits outside historical/deleted code after the port) | ❌ Wave 0 — no existing test asserts `vector_id` is *absent*; add one as a regression guard |
| ARC-06 | Full-text on native Lucene; analyzer validated against golden queries; FTS5 outbox retired | integration (yardstick comparison, D-06) | The spike's bake-off script (new, Wave 1/2 deliverable) comparing Lucene vs `LSM_SPARSE_VECTOR` against `baseline/03-turingdb/frozen-questions.json` + hand-authored lexical-stress queries | ❌ Wave 0 — this bake-off script does not exist yet; it is this phase's own deliverable, not pre-existing test debt |
| ARC-08 | `stable_id()` remains sole cross-record identifier; no vector-ID drift | unit (regression) | A new test computing `stable_id()` for a fixed input and asserting the same value is used as the ArcadeDB-stored/queryable `id` property before and after a `rebuild_vector_projection` call | ❌ Wave 0 — no existing "ID survives rebuild" test; add one per Pitfall 6's own recommended verification |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_<narrowest affected>.py -q` +
  `python -m ruff check src tests scripts`
- **Per wave merge:** `python -m pytest -q` (full suite) + `docker compose config
  --quiet`
- **Phase gate:** Full suite green, `docker compose up -d arcadedb` healthy, the D-02
  spike's committed smoke test green, AND the D-06 yardstick comparison recorded
  (even though the *pass/fail threshold* for meet-or-exceed is Phase 6's job — Phase
  4 must produce the comparable numbers, not just "it runs")

### Additional Validation Surfaces This Phase Must Design (beyond the generic map above)

1. **Spike bake-off (D-02/D-04/D-05).** A committed, re-runnable script (not just
   ad hoc exploration) that: (a) stands up ArcadeDB via compose, (b) runs the five
   smoke tests in the Open Questions section above, (c) for D-04, indexes a small
   fixture corpus with both Lucene and `LSM_SPARSE_VECTOR`, runs
   `baseline/03-turingdb/frozen-questions.json` plus the hand-authored lexical-stress
   queries against both, and diffs against `baseline/03-turingdb/`'s recorded
   per-check results, (d) for D-05, runs the same 2-hop entity→fact→memory traversal
   in both SQL MATCH and Cypher and records which one composes cleanly with the
   chosen vector/full-text functions from (a). Output: a machine-readable JSON
   artifact (matching the existing benchmark-script convention) plus a short written
   decision record for D-03/D-04/D-05, since these are spike-decided, not
   pre-locked.
2. **Chaos-restart test (D-10, Pitfall 1's ArcadeDB analog).** Start the full
   compose stack, confirm `/health` reports the ArcadeDB stage ready, force-restart
   the `arcadedb` container (`docker compose restart arcadedb` or a `docker kill`),
   and assert: (a) `/health` transitions to unhealthy while ArcadeDB is down, (b) the
   store reconnects without a manual runbook step once ArcadeDB is back, (c)
   `/health` returns to healthy, (d) a `search_memory`/`search_documents` call
   immediately after recovery returns correct (not empty/stale) results — this is
   the direct ArcadeDB-backend equivalent of Pitfall 1's TuringDB `load_graph` gap,
   and D-10 explicitly requires it in this phase, not deferred to Phase 12.
3. **Tenant-isolation-through-the-port check.** Because this phase keeps a single
   shared ArcadeDB database (Phase 5 does per-tenant DBs) and every TuringDB
   `user_identifier`-scoping query is being rewritten, re-run (or newly write, if it
   doesn't already exist against TuringDB) a test asserting that a query for tenant A
   never returns tenant B's records, specifically exercising the *new* ArcadeDB query
   forms (bound params, `sqlscript` batches) — a copy-paste error introducing an
   unscoped `MATCH`/`SELECT` during the rewrite is exactly the failure mode Pitfall 5
   warns about, and it has zero defense-in-depth this phase (no DB-per-tenant yet).
4. **Parity-comparability, not parity-pass/fail, is this phase's job.** Phase 6 owns
   the meet-or-exceed *gate*; Phase 4 must ensure its own output (the ArcadeDB-backed
   `e2e_score.py`/`real_document_benchmark.py` runs) is captured in a format directly
   diffable against `baseline/03-turingdb/`'s artifact structure
   (`BASELINE.md`/`corpus-manifest.json`/`frozen-questions.json`/
   `e2e-results.json`/`real-document-benchmark.json`) — don't invent a different
   output shape that Phase 6 then has to reconcile.

### Wave 0 Gaps

- [ ] `tests/test_arcadedb_client.py` — the D-02 spike's own committed smoke test
      (net-new; this is Wave 1's primary deliverable, not pre-existing debt)
- [ ] A compose-health structural test for the new `arcadedb` service, following the
      existing `test_docker_hardening.py` pattern
- [ ] A regression test asserting `vector_id` no longer appears in any node-creation
      literal or vector-search query (guards ARC-05's "delete, don't port" contract)
- [ ] A regression test asserting `stable_id()` survives `rebuild_vector_projection`/
      `rebuild_communities` unchanged (guards ARC-08/Pitfall 6)
- [ ] A chaos-restart test for the `arcadedb` compose service (D-10)
- [ ] The D-04/D-05 bake-off script + its committed decision-record output (new;
      no analog exists today since TuringDB never offered a lexical-channel or
      graph-query-surface choice)
- [ ] Framework install: none — pytest/ruff/docker-compose are already wired; no new
      test framework needed

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No (this phase) | ArcadeDB-level auth (if any, per Open Question 5) is service-to-service credential handling, not end-user authentication; OIDC/end-user auth is Phase 10 (SEC-04), out of scope here |
| V3 Session Management | No | No session concept changes in this phase |
| V4 Access Control | **Yes — the phase's central security property** | `user_identifier` scoping on every query, fail-closed on empty (CLAUDE.md invariant #1); this phase has *no* DB-level isolation boundary yet (single shared database), so V4 correctness rests entirely on the rewritten query strings carrying the same scoping the TuringDB versions did — verify this explicitly per rewritten query, not just "it compiles" |
| V5 Input Validation | **Yes** | Bound `?`/`:named` parameters for all data values (Architecture Pattern 4, Don't Hand-Roll); retire `ids.quote()`'s double-quote escaping in favor of parameterization rather than porting it unchanged into a single-quoted SQL dialect (Pitfall 2) |
| V6 Cryptography | No | Not touched this phase; ArcadeDB's own at-rest/in-transit security (if configured) is an admin/deployment concern (Open Question 5), not an application-cryptography one |

### Known Threat Patterns for This Phase's Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via hand-built string interpolation surviving the dialect change (double-quote escaper reused against a single-quote dialect, or vice versa) | Tampering | Bound parameters (`?`/`:named`) for every data value; reserve any custom sanitizer strictly for pattern-variable *names* (identifiers), never data (Pitfall 2, Architecture Pattern 4) |
| Cross-tenant data leakage via a copy-paste-missed `user_identifier` filter during the query rewrite | Information Disclosure / Elevation of Privilege | Re-run (or write, if absent) a concurrent multi-tenant isolation test against the *rewritten* ArcadeDB queries specifically (Validation Architecture item 3); treat every rewritten query as a new risk surface, not a mechanical translation |
| Vector-ID / stable-ID drift enabling stale or cross-record vector correlation after a rebuild | Tampering (data integrity) | `stable_id()` stays canonical, stored as an indexed property, never ArcadeDB's RID (Pitfall 6, ARC-08); regression test in Wave 0 gaps |
| Unauthenticated or default-credential ArcadeDB access from within the compose network | Spoofing / Elevation of Privilege | Resolve Open Question 5 (admin/auth defaults) before wiring the compose service; do not ship a default-open ArcadeDB instance even inside the private compose network, matching the existing hardening posture (`read_only: true`, non-root) applied to every other service |
| Oversized/unbounded `sqlscript` transaction payloads (D-08) exhausting host RAM (per this project's own `arcadedb` skill: "the whole transaction is kept in host's RAM") | Denial of Service | Preserve size-based batching for very large documents (Anti-Patterns note under Architecture Patterns), re-derived for the new reason rather than deleted |

## Sources

### Primary (HIGH confidence)
- `.planning/phases/04-arcadedb-direct-port/04-CONTEXT.md` — locked decisions D-01–D-10, phase boundary, deferred scope
- `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` §Phase 4/5/6/9/12, `.planning/STATE.md` — requirement IDs, phase sequencing, project history
- Direct reads of `src/turing_agentmemory_mcp/store_core.py`, `store_documents.py`, `store_search.py`, `store_chunking.py`, `store_evidence.py`, `store_rebuild.py`, `store_utils.py`, `store.py`, `ids.py` — the exact TuringDB call sites this phase ports
- Direct reads of `compose.yaml`, `.env.example`, `pyproject.toml`, `server.py` — env var wiring, current dependency list, `/health` endpoint shape
- `docker --version`/`docker info` executed this session — confirmed Docker 29.6.1 available and running

### Secondary (MEDIUM confidence)
- `.planning/research/ARCADEDB-capabilities-for-port.md` — op→ArcadeDB mapping, §3 spike unknowns (this document's own stated confidence: MEDIUM)
- `.planning/research/STACK.md`, `.planning/research/PITFALLS.md` — ArcadeDB adequacy verdict, urllib-client convention, Pitfalls 1/5/6/7/8/9 (both documents' own stated confidence: MEDIUM)
- `.claude/skills/arcadedb/references/sql-reference.md`, `references/api-reference.md`, `references/core-concepts.md` (consulted via the project's `arcadedb` skill this session) — corroborates `CONTAINSTEXT`, `BEGIN`/`COMMIT`/`ROLLBACK`, MVCC/optimistic-concurrency description; **diverges** from the capabilities doc on vector function naming, HTTP endpoint paths, and vector-index-type DDL naming — this divergence is itself load-bearing evidence for the D-02 spike, documented throughout Common Pitfalls/Assumptions Log

### Tertiary (LOW confidence)
- None separately tracked — every claim not corroborated by a primary/secondary source above is explicitly tagged `[ASSUMED]` inline and listed in the Assumptions Log rather than presented as fact.

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM — image pin and urllib-client convention are locked/settled decisions from prior research, not re-litigated; not independently re-verified in this session (image not yet pulled)
- Architecture: LOW-MEDIUM — the structural patterns (sqlscript+LET, versioned index naming, bound params) are sound engineering derivations from confirmed ArcadeDB primitives, but the exact syntax is unresolved pending the spike; treat every code example as illustrative, not copy-paste-ready
- Pitfalls: HIGH for codebase-grounded pitfalls (quoting mismatch, 600-LOC budget, compose coexistence — all directly verified by reading this repo's files); MEDIUM for ArcadeDB-specific pitfalls (k-underfill, analyzer drift — inherited from prior PITFALLS.md research at that document's own MEDIUM rating)

**Research date:** 2026-07-13
**Valid until:** Effectively until the D-02 spike executes — this is a hard-gated
phase where "valid until" is a gate event, not a calendar date. If the spike has not
run within ~14 days of this research (fast-moving ArcadeDB doc surface), re-check the
Assumptions Log claims against current ArcadeDB docs before trusting them as spike
inputs.
