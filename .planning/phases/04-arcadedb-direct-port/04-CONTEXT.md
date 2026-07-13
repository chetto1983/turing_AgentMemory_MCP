# Phase 4: ArcadeDB Direct Port - Context

**Gathered:** 2026-07-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace every TuringDB query in `store.py`'s read/write paths with ArcadeDB —
graph CRUD via ArcadeDB query language, dense vector via native `LSM_VECTOR`
(JVector HNSW), lexical/BM25 via native ArcadeDB indexing — with `stable_id()`
preserved as the sole cross-record identifier. **Direct port, no abstraction
layer; ArcadeDB is the sole backend.** Gated by an empirical spike (SC#1) that
validates ArcadeDB's real behavior *before* the query builders are committed.

**In scope:** an `arcadedb` Compose service (`arcadedata/arcadedb:26.7.1`) with a
persistent volume; a thin stdlib-`urllib` `arcadedb_client.py`; porting all graph
CRUD (memories, documents, chunks, entities, facts, communities, all edges) to
ArcadeDB; native HNSW vector search (deleting the `vector_id` int-join); native
full-text lexical channel (retiring the SQLite-FTS5 outbox); `stable_id()` stored
as an indexed property. Plus the pull-forward hardening the user locked (see
Decisions D-09…D-12 and the Cross-Phase Reconciliation note).

**Out of scope / preserved:** the Python weighted-RRF fusion is kept as-is (native
`vector.fuse` is a future opportunity, not this port); per-tenant DB isolation is
Phase 5; the meet-or-exceed parity *gate* is Phase 6 (this phase produces the
ported stack the gate measures); ranking-weight/fusion-algorithm redesign is
milestone-out-of-scope (PROJECT.md).

</domain>

<decisions>
## Implementation Decisions

### Locked from prior milestone/roadmap (carried in, NOT re-litigated)
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

### Vector index
- **D-01 (Quantization — LOCKED):** **None / full-precision, COSINE metric.** No
  INT8/BINARY. Corpus is well under the ~1–5M vectors/tenant scale where
  memory/build cost bites, and Phase 3 showed recall is fragile; do not introduce
  lossy compression during a port whose Phase-6 exit criterion is meet-or-exceed the
  baseline. Quantization stays a *future* lever if scale ever demands. Chosen
  explicitly, not defaulted (Pitfall 7).

### Spike (SC#1) — carries two deferred decisions + is a HARD gate
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

### Measurement yardstick
- **D-06 (LOCKED):** The spike's "pick by recall" (D-04/D-05) is measured against
  **Phase-3's committed frozen questions + `baseline/03-turingdb/` artifact
  (D-08/D-11)** as the primary yardstick (parity-aligned with the Phase-6 gate),
  **plus a handful of hand-authored pure-lexical stress queries**
  (keyword/error-code/exact-phrase). Rationale: the grounded-passage baseline
  under-probes lexical ranking, and analyzer regressions (Pitfall 8) surface
  precisely on keyword queries — the stress queries sharpen the D-04 analyzer/channel
  call without breaking parity comparability.

### Pull-forward hardening (deliberate scope expansion — see Cross-Phase note)
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### ArcadeDB port — feature map & settled decisions (READ FIRST)
- `.planning/research/ARCADEDB-capabilities-for-port.md` — op→ArcadeDB mapping table
  (real syntax sketches per store op), the §1.3 full-scan elimination, and the §3
  spike unknowns (filtered-ANN pushdown, function naming, full-text DDL/score, vector
  DDL dims, tx visibility). The primary implementation reference for this phase.
- `.planning/research/STACK.md` — the ArcadeDB adequacy verdict, `urllib`-client
  convention, native-HNSW+Lucene "subsumes external systems" decision, image pins.
- `.planning/research/PITFALLS.md` — Pitfalls 6 (RID/stable-id drift), 7 (MVCC +
  HNSW rebuild cost → versioning + batched + retry from day one), 8 (Lucene analyzer
  vs FTS5 ranking drift), 9 (parity gate). **Note:** Pitfalls 4/5/9's "driver
  interface / dual-backend" framing is superseded by the direct-port decision.

### Requirements & roadmap
- `.planning/ROADMAP.md` §"Phase 4" — Goal + SC#1–4; §"Phase 5/6/9/12" (the phases
  whose scope this phase touches or pulls forward).
- `.planning/REQUIREMENTS.md` — ARC-02, ARC-03, ARC-04, ARC-05, ARC-06, ARC-08
  (this phase's mapped requirements); PERF-01, PERF-02, INFRA-03 (pulled forward via
  D-07/D-08 — reconcile at transition).
- `.planning/PROJECT.md` — Key Decisions (direct port, fresh start, native
  vector+FTS), Constraints (invariants #1/#3 preserved, #2 superseded).

### Parity yardstick (Phase-3 output consumed by the spike)
- `baseline/03-turingdb/` — committed baseline: `BASELINE.md`, frozen questions,
  corpus manifest, per-check e2e results with inflation caveats (D-06 yardstick).
- `.planning/phases/03-turingdb-retrieval-baseline/03-CONTEXT.md` — D-07 (inflated
  e2e score, per-check diffing) and D-08 (`--frozen-questions` contract) that Phase 4
  and Phase 6 both depend on.
- `.planning/research/FUTURE-MILESTONE-retrieval-memory-quality.md` — §1.3 (the
  O(all-chunks) scan the port fixes for free), §1.2 (reranker leverage). Its
  consolidation/GraphRAG themes (T1–T5) are **future-milestone, deferred** — not this
  port.

### Code to port (the TuringDB-touching surface)
- `src/turing_agentmemory_mcp/store_core.py` — the hub: `_query`/`_write`/
  `_write_many`/`load_graph_after_restart`, vector-index verify/create, dimension
  validation. `from turingdb import TuringDB` at :17. Ground zero for the port.
- `src/turing_agentmemory_mcp/store_documents.py` — `search_documents` (the §1.3
  full-scan), `ingest_document_text` (doc-level dedup, `stable_id`).
- `src/turing_agentmemory_mcp/store_search.py` — `_search_memory_fused` → RRF; rerank
  guard. `store_chunking.py` — `_chunk_context` (`NEXT_CHUNK`). `store_evidence.py` —
  `_expand_entity_evidence` (entity→fact→memory hops). `store_rebuild.py` — vector
  projection rebuild (the stale-vector bug D-07 fixes). `ids.py` — `stable_id()`,
  `_document_vector_id`.
- Other `turingdb` importers to sweep in Phase 7 (out of this phase's read/write
  scope but noted): `server.py`, `e2e_score.py`, `e2e_score_stubs.py`,
  `agent_quality_eval.py`, `benchmark_schema.py`.

### Invariants & discipline
- `CLAUDE.md` — invariants #1 (tenant scope, preserved), #3 (stable IDs, preserved),
  #4/#5/#6 (TuringDB-specific, retire in this port), Definition of Done for
  document/retrieval changes; the `.claude/CLAUDE.md` milestone constraints.

### Peer references (studied for this phase; clones at `d:/tmp/`)
- `d:/tmp/agent-memory` (neo4j-labs) — graph-native peer: `$param`-bound Cypher
  traversals port to SQL MATCH; filtered-ANN is naive `$limit*2` over-fetch
  (k-underfill unsolved); **no lexical channel/fusion**; IDs are app-level UUIDs.
- `d:/tmp/mem0` (mem0ai) — `utils/scoring.py` sigmoid-BM25 + magnitude fusion
  (*future-milestone T3*, not adopted); Qdrant/Azure adapters do **native
  pre-filter pushdown** and cosine-default; Azure exposes scalar/binary quantization
  + oversample/rescore (informs the deferred quantization lever, not D-01).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`store_core.py`'s `_query`/`_write`/`_write_many`/`_span` seam** is the single
  choke point — porting concentrates here; the concern-split `store_*.py` mixins
  build query strings that route through it.
- **Dimension-validation pattern** (`store_core.py` `SHOW VECTOR INDEXES` + `ValueError`
  on mismatch) is the model for D-09's fail-fast bootstrap.
- **`embeddings.py`/`rerank.py` `urllib.request` clients** are the exact convention
  `arcadedb_client.py` copies (no new HTTP dep).
- **Phase-3 `--frozen-questions` loader + `baseline/03-turingdb/`** are the ready
  yardstick for the spike (D-06); `real_document_benchmark_scoring.py` does the
  deterministic scoring.

### Established Patterns
- Every store op is `user_identifier`-scoped and fails closed on empty — MUST hold
  through the port (invariant #1); DB-per-tenant (Phase 5) is additive, never a
  replacement.
- Benchmark/e2e scripts emit machine-readable JSON — the spike's bake-off results
  should follow suit for reproducibility.
- 600-LOC cap, no allowlist (`scripts/check-file-size.sh`): `arcadedb_client.py` and
  any new modules must land as small concern-split files; `store_core.py` is already
  at 423 LOC — the port must not push it over 600.

### Integration Points
- The ported stack is the exact input Phase 6 (`ARC-09`) measures against
  `baseline/03-turingdb/` — keep e2e/benchmark outputs comparable (D-06).
- New `arcadedb` Compose service must inherit the existing non-root/read-only
  hardening + `/tmp`-pinned cache env pattern (Pitfall 3) — any client temp/cache
  dir pinned to `/tmp` or the data volume.
- `EMBED_DIMENSIONS` couples the embedder to the vector index (D-09 bootstrap);
  changing the embedding model still requires a vector rebuild (now versioned via D-07).

</code_context>

<specifics>
## Specific Ideas

- The user drove the strategy toward **de-risk-by-spike**: two decisions (lexical
  channel, graph query surface) are deliberately resolved *empirically in the spike*
  rather than pre-locked, and the spike is a **hard gate** before query builders.
- The user consistently chose to **harden in-phase / pull forward** rather than defer:
  full index versioning (Phase 9), batched+retry write path (Phase 9), and full
  connection readiness (Phase 12) all land in Phase 4. Read this as: prefer a heavier,
  correct-from-day-one port over a thin port that re-opens known bugs on the new
  backend.
- Retrieval quality is treated as fragile and load-bearing (Phase-3 reranker finding):
  hence full-precision vectors (D-01), FTS5-matching analyzer (D-04), and a
  parity-aligned yardstick with lexical-stress augmentation (D-06).

</specifics>

<deferred>
## Deferred Ideas

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

</deferred>

---

*Phase: 4-ArcadeDB Direct Port*
*Context gathered: 2026-07-13*
