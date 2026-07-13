# ArcadeDB Capabilities for the TuringDB→ArcadeDB Port

**Purpose:** code-grounded feature map for Phase 4 (ArcadeDB Direct Port). Builds on
settled decisions in `STACK.md`/`PITFALLS.md`/`ROADMAP.md` (native LSM_VECTOR HNSW +
Lucene full-text, ACID, one DB per tenant, SQLite-FTS5 retired, stdlib-`urllib`
client, `stable_id()` never the RID). Every ArcadeDB feature below is backed by a doc
actually read (URL in Sources). Do NOT re-litigate those decisions.

**Confidence:** MEDIUM. Function-name/DDL variants differ between the official
Graph-RAG page and the vector-DBMS doc (see Unknowns) — validate empirically in the
Phase 4 spike (SC#1) before committing query builders.

## 1. Operation → ArcadeDB mapping

Ops extracted from `store_documents.py`, `store_search.py`, `store_evidence.py`,
`store_chunking.py`, `retrieval_fusion.py`, `store_core.py`.

| Our op (TuringDB today) | ArcadeDB feature | Real syntax sketch | Source |
|---|---|---|---|
| Graph node/edge create — `MATCH (u:User)…CREATE (d:Document…), (c:Chunk…), (u)-[:HAS_DOCUMENT]->(d), (d)-[:HAS_CHUNK]->(c), (prev)-[:NEXT_CHUNK]->(c)` via `_write`/`_write_many` (one tx per batch, invariant #4) | Vertex/edge types + SQL `INSERT`/`CREATE VERTEX`/`CREATE EDGE`, run inside one managed transaction. Intra-tx read-your-writes removes the submit-before-match dance | `POST /api/v1/begin/{db}` → `arcadedb-session-id` header on each `POST /api/v1/command/{db}` → `POST /api/v1/commit/{db}`; multi-stmt via `sqlscript` with `LET x = CREATE VERTEX…; CREATE EDGE Rel FROM $x TO $y` | [S1][S3] |
| Point read by property — `get_document`: `MATCH (d:Document) WHERE d.id=… AND d.user_identifier=… AND d.status="searchable"` | Composite secondary index (`LSM_TREE`, UNIQUE on `id`) + SQL filter | `SELECT FROM Document WHERE id = ? AND user_identifier = ? AND status = 'searchable'` | [S3][S6] |
| Dense vector k-NN — `VECTOR SEARCH IN {idx} FOR k {vec} YIELD ids, score MATCH (m:Memory) WHERE m.vector_id=ids…` (episode/fact/entity/community + document channels) | Native `LSM_VECTOR` (JVector HNSW), COSINE. **Delete the `vector_id` int-join** (SC#3): score+record come back together | `SELECT content, source FROM Chunk ORDER BY vectorNeighbors('Chunk[embedding]', :vec, :k) DESC LIMIT :k`  •  fn form: `SELECT expand(` `` `vector.neighbors` `` `('Chunk[embedding]', :vec, 50))`  •  radius: `{ maxDistance: 0.05 }` | [S2][S4] |
| Lexical/BM25 channel — `sparse_index.py` (SQLite-FTS5) **and** the `search_documents` Python full-scan (`_active_chunk_rows` → `lexical_score` on every chunk, §1.3) | Lucene full-text index (ACID, per-field analyzer) via `CONTAINSTEXT`; **or** native `LSM_SPARSE_VECTOR` BM25 (`minScore`, IDF) | `SELECT content, source FROM Chunk WHERE content CONTAINSTEXT 'knowledge graph' LIMIT :k`  •  BM25: `SELECT expand(` `` `vector.sparseNeighbors` `` `('Doc[tokens,weights]', :qIdx, :qVal, 100, { minScore: 0.5 }))` | [S2][S4] |
| Next-chunk context — `_chunk_context`: `MATCH (c:Chunk)-[:NEXT_CHUNK]->(n:Chunk) WHERE c.vector_id=… AND …status="active"` | SQL `MATCH`/projection or Cypher | SQL: `MATCH {type:Chunk, as:c, where:(chunk_id=?)}.out('NEXT_CHUNK'){as:n, where:(status='active')} RETURN n.chunk_id, n.locator, n.text`  •  Cypher: `MATCH (c:Chunk)-[:NEXT_CHUNK]->(n:Chunk) …` | [S3][S4] |
| Entity/fact/community graph channels — `_expand_entity_evidence` 1–2 hop `(e:Entity)-[:SUBJECT_OF\|OBJECT_OF]->(f:Fact)-[:SUPPORTED_BY]->(m:Memory)` | SQL `MATCH` multi-hop with inline `where`, or `TRAVERSE … WHILE $depth<=2` | `MATCH {type:Entity, as:e, where:(user_identifier=? AND status='active')}.out('SUBJECT_OF'){as:f}.out('SUPPORTED_BY'){as:m} RETURN m.id, f.id, f.confidence, e.id` | [S3] |
| Weighted RRF fusion — `retrieval_fusion.py` | **Keep the Python fusion** (rewriting it is out of scope). Each channel above returns `(source_id, score)`; Python RRF unchanged. Native `vector.fuse(dense, sparse, {fusion:'RRF', groupBy, groupSize})` exists but is a *future* opportunity, not this port | `SELECT expand(` `` `vector.fuse` `` `(neighbors…, sparseNeighbors…, { fusion:'RRF' }))` | [S4] |
| Stable/vector IDs — `ids.py` `stable_id()`, `_document_vector_id` | Store `id` as an **indexed property** (UNIQUE `LSM_TREE`); never persist/derive from ArcadeDB RID (`#12:34` is not stable across compaction) — Pitfall 6 | `CREATE INDEX ON Chunk (id) UNIQUE` | [S6][PIT] |
| Per-tenant isolation — app-layer `user_identifier` only today | One ArcadeDB **database per tenant** (physical isolation) **plus** mandatory `user_identifier` scoping as defense-in-depth (Phase 5, Pitfall 5) | server cmd `create database <tenant_db>` via `POST /api/v1/server`; partition-prune within DB: `… FROM Doc WHERE tenant_id = ?` | [S3][S4] |
| Client/transport — `turingdb` client `new_change`/`CHANGE SUBMIT`/`checkout` | Thin stdlib-`urllib` HTTP/JSON client. Params bound `?` (positional) / `:named` — **except vector literals**, which must be inlined (not bindable) | `command`/`query`/`begin`/`commit`/`rollback` under `/api/v1/…`; `sqlscript` supports `BEGIN ISOLATION REPEATABLE_READ; …; commit retry 100` | [S1][S3][S5] |

Index build (Java-API form, confirms options the SQL DDL wraps):
`buildTypeIndex('Chunk',{'embedding'}).withLSMVectorType().withDimensions(N).create()`;
SQL form on the Graph-RAG page: `CREATE VECTOR INDEX ON Chunk(embedding) LSM TYPE COSINE`. [S2][S4]

## 2. Eliminating the §1.3 full-scan

`search_documents` currently over-fetches vector hits **then** iterates
`_active_chunk_rows` — every active chunk for the tenant — recomputing `lexical_score`
in Python (`blend_hybrid_score`). That O(all-chunks) scan is the bottleneck. On ArcadeDB
both signals become **indexed** queries:

1. **Dense:** `vectorNeighbors('Chunk[embedding]', :vec, k)` (HNSW) returns the top-k
   with scores — no `vector_id` join, no re-sort workaround (TuringDB invariant #5 retires).
2. **Lexical:** replace the Python scan with either an indexed Lucene `CONTAINSTEXT`
   query (candidate set only) **or** the `LSM_SPARSE_VECTOR` BM25 index
   (`vector.sparseNeighbors`, exposes a real BM25/IDF score). Both return only matching
   chunks; neither scans the full type.
3. Both are ACID-consistent with graph writes, so `sparse_index.py`'s FTS5 outbox
   (prepare/commit/replay) is retired for this backend (SC#3). The Python hybrid blend
   still runs, but only over the union of two bounded, indexed candidate lists.

Per-tenant DBs (Phase 5) further shrink the filter problem: the vector index holds one
tenant's vectors, so the only in-DB predicates left are `status='active'`, `document_id`,
and expiry — low-cardinality, not `user_identifier` across all tenants.

## 3. Gotchas / unknowns to validate in the Phase-4 spike

- **Filtered ANN (the flagged caveat).** `vectorNeighbors`/`vector.neighbors` return
  top-k from the index; `{maxDistance}`/`{minScore}` are post-filters, not property
  pre-filters. Combining k-NN with `WHERE status='active' AND expires_at…` can under-fill
  results (fetch k, filter, get <k). Validate: does a `WHERE` on the outer `SELECT`
  push down (partition pruning), or must we over-fetch k? Confirm before deleting the
  4× over-fetch logic. [S4]
- **Function naming.** Graph-RAG page: `vectorNeighbors(...)`; vector-DBMS doc:
  `` `vector.neighbors`(...) ``. Likely alias/version. Confirm which resolves on
  `arcadedata/arcadedb:26.7.1` and settle on one. [S2][S4]
- **Full-text DDL + score exposure.** `CONTAINSTEXT` is confirmed official, but the
  exact `CREATE … FULL_TEXT` DDL, analyzer selection (Pitfall 8 — match FTS5
  tokenization), and whether Lucene relevance is exposed as an orderable SQL score
  (vs. only the sparse-vector BM25 path) are unverified. Validate against golden queries. [S2]
- **Vector DDL dimensions.** `CREATE VECTOR INDEX … LSM TYPE COSINE` (SQL) vs
  `withDimensions(N)` (Java) — confirm the SQL DDL takes/infers dimensions and the
  COSINE metric matches our embeddings; pick quantization explicitly (Pitfall 7). [S2][S4]
- **Transaction/visibility + write batching.** Confirm intra-transaction read-your-writes
  (so `_write_many`'s per-batch submit collapses into one tx) and use `commit retry N`
  for MVCC conflicts under the multi-worker ingest (Pitfall 7). [S3][S5]
- **Read-only container caches.** Pin any client temp/cache dirs to `/tmp` (Pitfall 3).

## Sources

- [S1] HTTP API — begin/commit/rollback, command vs query, `create database`:
  https://github.com/arcadedata/arcadedb (studio `api.html`, via Context7 `/arcadedata/arcadedb`)
- [S2] Official Graph-RAG page (`CREATE VECTOR INDEX … LSM TYPE COSINE`, `vectorNeighbors`,
  `CONTAINSTEXT`, hybrid, Cypher MENTIONS traversal): https://arcadedb.com/graph-rag.html
- [S3] SQL MATCH / TRAVERSE / out()/in(), Cypher, `create database` HTTP:
  https://github.com/arcadedata/arcadedb (via Context7)
- [S4] `arcadedb-vs-leading-vector-dbms.md` — `vector.neighbors`/`sparseNeighbors`/`fuse`/
  `rerank`/`boost`, `maxDistance`/`minScore`, RRF, partition-prune multitenancy:
  https://github.com/arcadedata/arcadedb/blob/main/docs/arcadedb-vs-leading-vector-dbms.md
- [S5] Params `?`/`:named`, vector literals not bindable, `sqlscript`/`commit retry`:
  https://github.com/arcadedata/arcadedb (python bindings + ha-raft test docs, via Context7)
- [S6] LSM_TREE secondary/unique index (`createTypeIndex`, `CREATE INDEX … UNIQUE`):
  https://github.com/arcadedata/arcadedb (via Context7)
- [PIT] `.planning/research/PITFALLS.md`, `STACK.md` — settled decisions, analyzer/quant/RID caveats
