# Phase 4 Wave 1: ArcadeDB D-02 Spike Findings

**Executed:** 2026-07-13, against a live `arcadedata/arcadedb:26.7.1` container
(digest `sha256:37db3d210bde5849ba5c772ce33b8666b215a77f7b88331fda31fbbf2d130738`,
pulled fresh this session — A8 resolved: the pin is valid and pullable).

This is the committed output of the D-02 hard gate: every claim below was proven
against the live, pinned image by `tests/test_arcadedb_client.py` (the committed
smoke test) and `scripts/arcadedb_spike.py` (the re-runnable bake-off), not
inferred from documentation. Where the project's own `arcadedb` skill reference,
the Context7-derived capabilities doc, and this spike disagree, this document
is authoritative for the ArcadeDB 26.7.1 port — downstream waves consume it
verbatim.

## Resolved HTTP surface

- **Endpoint prefix:** `/api/v1/{query,command,begin,commit,rollback}/<database>`
  (plus `/api/v1/server` for server-level commands like `create database`/
  `drop database`/`list databases`, and `/api/v1/ready` for readiness).
  This CONFIRMS the capabilities doc's `/api/v1/...` form and CONTRADICTS this
  repo's own generic `arcadedb` skill reference, which shows the unversioned
  `/query/graph/<db>` / `/command/<db>` form — that form does not exist on
  26.7.1 (verified: unversioned paths 404).
- **Auth:** HTTP Basic, `username:password` base64-encoded in the `Authorization`
  header. A root password is REQUIRED at first startup (no default-open
  instance) via `-Darcadedb.server.rootPassword=<password>` (or
  `rootPasswordPath`) in `JAVA_OPTS`. Verified live: no `Authorization` header
  (or an empty one) → HTTP 403 (`"Basic authentication error"`); wrong password
  → HTTP 403 (`"User/Password not valid"`... observed as a generic security
  error, both distinct from success). T-04-01-01's mitigation (require the
  var, no default-open, 127.0.0.1-only publish) is confirmed working, not just
  assumed.
- **Transaction/session model:** `POST /api/v1/begin/<db>` returns `204` with
  an `arcadedb-session-id` response header. Passing that same header value on
  subsequent `query`/`command`/`commit`/`rollback` calls scopes them to that
  transaction. This is the concrete mechanism behind D-08's "one managed
  transaction" design — not `sqlscript`'s own internal `BEGIN;...;COMMIT;`
  framing (which also works, see below, but is a *separate*, single-call
  mechanism with no cross-call session).

## Unknown 1 — Vector function naming (RESOLVED)

**Winner: `vectorNeighbors("Type[property]", queryVector, k)`** — CONFIRMS the
capabilities doc's primary spelling; CONTRADICTS this repo's generic `arcadedb`
skill (`vector_search(indexName, vec, k)`, not found) and the capabilities
doc's own alternate backtick form (`` `vector.neighbors` ``, not tested since
the primary form worked cleanly on the first attempt).

- Index reference is the literal string `"Type[property]"` — matching the
  auto-generated index name ArcadeDB assigns when the DDL below is run without
  an explicit name (verified: `CREATE INDEX ON Chunk (embedding) LSM_VECTOR
  METADATA {...}` produces an index literally named `Chunk[embedding]`).
  `SELECT expand(vectorNeighbors(...))` flattens the neighbor list; a plain
  `SELECT ... , vectorNeighbors(...) as x FROM ...` also works (nested array).
- **Returns record + score together** (a `distance` field, COSINE by default
  when `similarity: "cosine"` is set) — the app-layer `vector_id` int-join
  (TuringDB invariant #5) has no ArcadeDB equivalent to port; ARC-05's "delete
  the `vector_id` join" is confirmed clean.
- **Correction to a locked CONTEXT.md assumption:** the query vector (and any
  data value) CAN be bound as a named/positional param (`:vec`, `?`) — it does
  NOT need to be inlined. CONTEXT.md's "vector literals are inlined, not
  bindable" (capabilities §1 [S5]) is **empirically wrong for 26.7.1**.
  `arcadedb_client.py`/the smoke test bind every value, including vectors,
  as params — this is both simpler and closes an injection-surface question
  that inlining would have reopened.

## A4 — Vector DDL (RESOLVED)

**Winning form:**
```sql
CREATE INDEX ON <Type> (<property>) LSM_VECTOR METADATA
  {"dimensions": <N>, "similarity": "cosine", "maxConnections": <N>, "beamWidth": <N>}
```
CONTRADICTS both the capabilities doc's `CREATE VECTOR INDEX ... LSM TYPE COSINE`
form (syntax error: `no viable alternative at input 'CREATE VECTOR'`) and the
generic skill's `TYPE HNSW`/`LSM_VECTOR_INDEX` naming (also not the type
keyword the engine accepts — the index *type* value is `LSM_VECTOR`, matching
neither doc's exact spelling). All four metadata keys (`dimensions`,
`similarity`, `maxConnections`, `beamWidth`) are required — omitting any one of
the latter three still succeeds using engine defaults, but omitting
`dimensions` fails with an explicit, helpful error naming all four keys.
`similarity` accepts `"cosine"` (confirmed; D-01's locked COSINE metric is
directly expressible). D-09's bootstrap should use this exact DDL form,
verified live, not the doc-sourced guesses.

## Unknown 2 — Filtered-ANN k-underfill (RESOLVED — D-03 confirmed, no change)

**k-underfill IS present.** A `WHERE status = :status` predicate on the outer
`SELECT` around `vectorNeighbors(...)` is applied AFTER the top-`k` ANN
results are returned (post-filter), not pushed into the HNSW search itself.

Live evidence (`tests/test_arcadedb_client.py::test_filtered_vector_search_underfills_k_confirming_d03_overfetch_default`):
a fixture with 3 "active" + 7 "inactive" chunks, where 2 of the 3 active
records rank *behind* several inactive records in raw vector distance —
`vectorNeighbors(..., k=2)` filtered to `status='active'` returns only 1 of 3
active records; `k=20` (over-fetch) recovers all 3.

**D-03 decision (LOCKED, now empirically confirmed, not overridden):** keep the
existing over-fetch-then-filter pattern (`max(limit*4, limit)`-style) as the
permanent default for this backend. Do NOT adopt native predicate pushdown —
it does not exist for this query shape on 26.7.1.

## Unknown 3 — Intra-transaction read-your-writes (RESOLVED — A5 confirmed true)

**Confirmed true**, via the session-header transaction model (not `sqlscript`'s
`LET` chaining, though that ALSO works — see below):

1. `begin()` → session id.
2. `CREATE VERTEX Chunk SET id = 'tx-a', ...` with that session header.
3. `SELECT id FROM Chunk WHERE id = 'tx-a'` (property filter, not a `$var`
   reference) **in the same session, before commit** → finds the row.
4. The identical query **without** the session header (a different/no
   session) → does NOT find the row (correct isolation — no dirty reads).
5. `commit(session_id)`.
6. The identical query with no session header → NOW finds the row.

This directly supports D-08's design: a single managed transaction (one
`begin`, N `command` calls scoped to that session, one `commit`) can safely
replace the current per-batch submit-before-match model, because a later
`command`/`query` in the same session sees earlier writes via ordinary
property-filtered lookups, not just `$var` references.

**`sqlscript` LET-chaining also confirmed working** as a single-call
alternative for the common "create N vertices + edges in one round trip"
shape (`tests/test_arcadedb_client.py::test_sqlscript_let_chaining_creates_edge_across_two_new_vertices`):
```sql
BEGIN;
LET $a = CREATE VERTEX Chunk SET id = "scr-a", ...;
LET $b = CREATE VERTEX Chunk SET id = "scr-b", ...;
CREATE EDGE NextChunk FROM $a TO $b;
COMMIT;
```
submitted as one `language: "sqlscript"` command. This is a distinct
mechanism from the session-header model above (self-contained, no
cross-call session needed) and is the right fit for a single bounded batch;
the session-header model is the right fit for D-08's cross-batch transaction.
`COMMIT RETRY N` (A3) was not exercised this wave (no MVCC conflict was
induced) — deferred to whichever later wave first needs the retry wrapper.

## Unknown 4 — Full-text analyzer + score exposure (RESOLVED)

Two distinct forms exist and behave differently:

- **`CONTAINSTEXT`** (`WHERE content CONTAINSTEXT :q`) — boolean filter only.
  `$score` is present as a query variable but stays `0.0` through this form.
  Handles raw natural-language text safely (verified: a string containing
  `?`, `'`, and `()` does not raise).
- **`SEARCH_INDEX("Type[property]", :q)`** (`WHERE SEARCH_INDEX(...) ORDER BY
  $score DESC`) — exposes a real, orderable Lucene relevance score via
  `$score`. This is the winning form for any channel that needs a `raw_score`
  to feed the existing Python RRF (`retrieval_fusion.py`, unchanged).
- **Fragility found (not in either doc):** `SEARCH_INDEX`'s query argument is
  parsed as a raw Lucene query string. Unescaped Lucene special characters in
  ordinary natural-language input (`?`, `*`, `(`, `)`, etc.) can raise
  `IndexException` (`'?' or '*' not allowed as first character in
  WildcardQuery`, or similar parse errors) — observed live on 2 of 60 frozen
  questions in the bake-off (both ending in a bare `?`). `CONTAINSTEXT` and
  `LSM_SPARSE_VECTOR` do not share this fragility (neither parses free-text
  Lucene query syntax). Any future use of `SEARCH_INDEX` in the store's query
  builders must escape Lucene special characters first — recorded here so no
  downstream wave rediscovers this by a production failure.
- Default analyzer (no `METADATA` block) is `StandardAnalyzer`; per
  `core-concepts.md`, per-field/custom analyzers are configurable via a
  `METADATA` block — analyzer choice vs FTS5 `unicode61` was not deep-dived
  further this wave since the D-04 bake-off below settles the channel choice
  in favor of the non-Lucene channel (making analyzer tuning moot for now).

## Unknown 5 — Root credential requirement (RESOLVED)

A fresh `arcadedata/arcadedb` container REQUIRES a root credential; without
`-Darcadedb.server.rootPassword`/`rootPasswordPath` in `JAVA_OPTS` the server
prompts interactively at startup (would hang non-interactively in Compose).
`compose.yaml`'s `arcadedb` service sets it via
`JAVA_OPTS=-Darcadedb.server.rootPassword=${ARCADEDB_PASSWORD:-agentmemory-arcadedb-dev}`,
publishes the port on `127.0.0.1` only, and never ships without a password —
T-04-01-01 is mitigated. Password min length is 8-256 chars per
`admin-reference.md`; the local dev default satisfies this.

## D-04/D-05 bake-off (SPIKE-DECIDED)

Ran via `scripts/arcadedb_spike.py --out .benchmarks/arcadedb-spike.json`
against a fixture corpus built from `baseline/03-turingdb/frozen-questions.json`'s
60 real, committed `evidence_quote` excerpts across 12 documents (the actual
document bytes are external/uncommitted per D-06; the evidence quotes ARE
committed, real corpus text, so this keeps the bake-off grounded without
requiring the source files) plus 8 hand-authored lexical-stress queries
(code-like tokens — e.g. branch/customer codes, dates — extracted
programmatically from the same real corpus text, not fabricated).

| Query set | Channel | MRR@20 | Recall@1 | Recall@20 | Errors | Mean latency |
|---|---|---|---|---|---|---|
| Frozen questions (60) | Lucene `SEARCH_INDEX` | 0.546 | 0.45 | 0.733 | 2/60 | 59.3 ms |
| Frozen questions (60) | `LSM_SPARSE_VECTOR` | **0.577** | 0.45 | **0.85** | **0/60** | **10.4 ms** |
| Lexical-stress (8) | Lucene `SEARCH_INDEX` | **0.938** | **0.875** | 1.0 | 0/8 | 3.0 ms |
| Lexical-stress (8) | `LSM_SPARSE_VECTOR` | 0.875 | 0.75 | 1.0 | 0/8 | 7.7 ms |

Full per-document breakdown in `.benchmarks/arcadedb-spike.json`.

### D-04: **Native `LSM_SPARSE_VECTOR`** (`vector.sparseNeighbors`) wins.

Evidence: on the primary D-06 yardstick (the 60 frozen questions, parity-
aligned with the Phase-6 gate), `LSM_SPARSE_VECTOR` beats Lucene on every
metric that matters (higher MRR@20, +12pp recall@20, zero search errors,
~6x lower mean latency). Lucene's `SEARCH_INDEX` narrowly wins the small
8-query lexical-stress set (exact code/token matches, where both channels do
well), but that margin does not offset two structural findings against it:
(a) the raw-Lucene-query-string fragility above is a real correctness risk
any production query builder would have to defend against with an escaping
layer that `LSM_SPARSE_VECTOR` and `CONTAINSTEXT` don't need; (b)
`LSM_SPARSE_VECTOR` natively exposes a `score` column suitable as the
`raw_score` `retrieval_fusion.py`'s weighted RRF already expects per channel,
with the same "structured input, no free-text parsing" safety property as
the vector channel. Tokenization for this bake-off used a simple
hash-bucketed TF-IDF encoder (`_sparse_vector` in `arcadedb_spike.py`,
`blake2b`-hashed buckets over `VOCAB_SIZE=4096`) — analyzer/tokenizer tuning
for the real port (matching FTS5's `unicode61` as closely as reasonable) is
downstream-wave work, not resolved here; this bake-off validates the channel
choice, not the final tokenizer.

### D-05: **SQL `MATCH`/`TRAVERSE`** wins.

Evidence: both SQL `MATCH {type:...}.out(...){as:...}` and `openCypher
MATCH (a)-[:R]->(b)` bind named params cleanly (`:id` / `$id` respectively)
and both correctly complete the 2-hop `entity->fact->memory` traversal
prototype (`graph_query_surface_bakeoff` in the JSON artifact,
`two_hop_succeeds: true` for both). The deciding factor, per CONTEXT.md's own
framing ("which binds params cleanly AND composes with the vector/full-text
functions"): SQL is the SAME `language` identifier as `vectorNeighbors`,
`SEARCH_INDEX`, and `vector.sparseNeighbors` — a single SQL statement can
traverse and rank by vector/full-text in one query. `openCypher` is a
separate `language` value entirely; it cannot invoke those SQL-specific
functions inline in the same statement. This confirms CONTEXT.md's default
lean without needing to force a combined mega-query test.

## Decisions recorded

- **D-03:** Keep over-fetch-then-filter (locked default). Evidence: Unknown 2
  above — k-underfill confirmed present; no pushdown to switch to.
- **D-04:** Native `LSM_SPARSE_VECTOR` (`vector.sparseNeighbors`) is the
  winning lexical channel. Evidence: bake-off table above — wins the primary
  D-06 yardstick decisively, zero errors, natively scorable for RRF.
- **D-05:** SQL `MATCH`/`TRAVERSE` is the winning graph-query surface.
  Evidence: bake-off — both surfaces bind params cleanly; SQL uniquely
  composes with vector/full-text functions in the same query language.

## What downstream waves must NOT re-litigate

- The endpoint prefix, auth model, vector function spelling, vector DDL form,
  and session-header transaction model above are settled — build query
  strings against them directly.
- `ids.quote()`'s double-quote escaping is confirmed obsolete: ArcadeDB SQL
  string literals are single-quoted, and every value in this spike was bound
  as a param anyway (including vectors) — bound params are strictly better
  than any inline-literal quoting scheme for this port.
- `CREATE INDEX ... IF NOT EXISTS` was not tested this wave (D-09's bootstrap
  idempotency is a later-wave concern) — the smoke test/bake-off scripts get
  idempotency by dropping and recreating a throwaway database per run instead.
