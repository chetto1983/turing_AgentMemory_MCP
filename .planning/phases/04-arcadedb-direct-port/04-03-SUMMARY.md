---
phase: 04-arcadedb-direct-port
plan: 03
subsystem: database
tags: [arcadedb, schema, ddl, vector-index, lexical-index, bootstrap, idempotency]

# Dependency graph
requires:
  - phase: 04-01
    provides: spike-minimal ArcadeDBClient (query/command/begin/commit/rollback) empirically validated against a live arcadedata/arcadedb:26.7.1 container
  - phase: 04-02
    provides: full ArcadeDBClient transaction surface (query/command/sqlscript) this module's DDL is issued through
provides:
  - "arcadedb_schema.bootstrap(client, *, dimensions, version) -- idempotent D-09 schema-init: 7 vertex + 9 edge types, per-content-type LSM_VECTOR (dense) + LSM_SPARSE_VECTOR (D-04 lexical) channels, UNIQUE id index per stable_id()-identified type"
  - "SchemaBootstrapConfig -- validated dimensions/version/maxConnections/beamWidth"
  - "versioned_vector_index(base_name, user_identifier, version) -- D-07 foundation: extends store_core.py's _tenant_vector_index blake2b tenant-digest naming with a _v{version} suffix"
  - "introspect_vector_dimension(client, name) -- samples an existing record's vector length (ArcadeDB exposes no LSM_VECTOR dimensions metadata via SQL, confirmed live)"
affects: [04-04-store-core-seam, 04-05-store-mixins, 04-06-store-mixins, 04-07-store-mixins, 04-08-store-rebuild-atomic-swap]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Idempotency split by construct: CREATE VERTEX/EDGE TYPE and CREATE PROPERTY use their confirmed-working `IF NOT EXISTS` clause; CREATE INDEX has no such clause (confirmed live: syntax error) so its idempotency is a catch-\"already exists\"-and-continue wrapper, re-raising anything else"
    - "Dimension-mismatch detection by data sampling, not index metadata: `SELECT <property> FROM <Type> WHERE <property> IS NOT NULL LIMIT 1`, compare `len(vector)` to config.dimensions -- because ArcadeDB's schema:indexes/schema:types introspection does not return the LSM_VECTOR METADATA dimensions value (confirmed live against 26.7.1)"
    - "Per-content-type dual channel: every vector-bearing vertex type (Memory/Chunk/Entity/Fact/Community) gets both an LSM_VECTOR dense index and an LSM_SPARSE_VECTOR lexical index, mirroring store_core.py's 5 existing vector indexes and sparse_index.py's unified kind coverage (episode/entity/fact/community/document)"

key-files:
  created:
    - src/turing_agentmemory_mcp/arcadedb_schema.py
    - tests/test_arcadedb_schema.py
  modified: []

key-decisions:
  - "Reconciled the plan's 'native Lucene full-text index' wording to the spike's D-04 decision: bootstrap() creates LSM_SPARSE_VECTOR (vector.sparseNeighbors) lexical channels, not Lucene SEARCH_INDEX -- D-04 won on every primary-yardstick metric (MRR@20 0.577 vs 0.546, recall@20 0.85 vs 0.733, 0/60 vs 2/60 errors) and the query-string fragility Lucene's SEARCH_INDEX has is a real correctness risk LSM_SPARSE_VECTOR does not carry"
  - "The lexical (sparse-vector) channel is provisioned per content-bearing type (Memory/Chunk/Entity/Fact/Community), not as one global index, mirroring the dense-vector index set 1:1 -- ArcadeDB indexes are strictly type+property scoped (confirmed live: no cross-type index), and this set matches sparse_index.py's existing SQLite-FTS5 kind coverage (episode/entity/fact/community/document) that the D-04 channel replaces"
  - "stable_id() identity: every record type produced by `ids.stable_id()` (Memory, Document, Chunk, Entity, Fact, Community) stores that value in an `id` STRING property with a UNIQUE index -- matching the existing codebase convention (`id=stable_id(...)` in temporal_graph.py/community_detection.py, `MemoryItem.id` in models.py), not a literal property named `stable_id`. User is excluded: its identity is the caller-supplied `identifier` (raw user_identifier), never a stable_id() digest; it gets its own UNIQUE index on `identifier` (Rule 2 -- `_ensure_user`'s current linear MATCH scan has no supporting index today)"
  - "introspect_vector_dimension() samples data, not metadata, because ArcadeDB's schema:indexes/schema:types SQL introspection does not expose the dimensions an LSM_VECTOR index was created with -- empirically confirmed live against arcadedata/arcadedb:26.7.1 during this plan (queried both endpoints directly; neither returns a dimensions/metadata field for an LSM_VECTOR index). This means dimension drift is only caught once at least one record has been written with the new dimension count; a brand-new index with zero records cannot be verified against config before any data exists. This is a real backend constraint, not a design shortcut -- documented in the module docstring so Wave 3+ does not rediscover it."
  - "CREATE INDEX has no IF NOT EXISTS support on ArcadeDB 26.7.1 (confirmed live: 'mismatched input IF' syntax error) -- its idempotency uses a catch-'already exists'-and-continue wrapper (`_create_index_idempotent`), while CREATE VERTEX/EDGE TYPE and CREATE PROPERTY use their confirmed-working IF NOT EXISTS clause. This resolves 04-SPIKE-FINDINGS.md's open item ('CREATE INDEX ... IF NOT EXISTS was not tested this wave')."
  - "versioned_vector_index() is a pure naming helper (base_name + blake2b tenant digest + _v{version} suffix, cypher_var-sanitized) -- it is NOT invoked by bootstrap() itself. bootstrap() provisions the global/canonical schema (7 vertex + 9 edge types + one base dense+lexical channel per content type); versioned_vector_index() is the seam later waves (04-04 store_core port, 04-08 store_rebuild atomic swap) use to compute per-tenant, per-version property/index names for the actual per-tenant vector indexes the store creates lazily on first write (mirroring store_core.py's current `_ensure_tenant_vector_index`, called from store_documents.py/store_evidence.py/store_memory_write.py/store_search.py/store_rebuild.py, none of which are touched by this plan)"

metrics:
  duration_minutes: 70
  tasks_completed: 1
  files_changed: 2
  completed: 2026-07-13
status: complete
---

# Phase 4 Plan 03: ArcadeDB Schema Bootstrap (D-09) Summary

Idempotent ArcadeDB schema bootstrap creating 7 vertex + 9 edge types, a
full-precision COSINE `LSM_VECTOR` dense index plus a D-04-chosen native
`LSM_SPARSE_VECTOR` lexical index per content-bearing record type, and a
UNIQUE `id` index anchoring `ids.stable_id()` as the sole cross-record
identity — the schema contract every later-wave store query builder writes
into and the versioned-naming foundation the Wave 5 atomic-swap rebuild
depends on.

## What Was Built

`src/turing_agentmemory_mcp/arcadedb_schema.py` (254 LOC):

- **`bootstrap(client, *, dimensions, version=1) -> SchemaBootstrapConfig`** —
  idempotently creates `VERTEX_TYPES` (User, Memory, Document, Chunk, Entity,
  Fact, Community) and `EDGE_TYPES` (HAS_MEMORY, HAS_DOCUMENT, HAS_CHUNK,
  NEXT_CHUNK, SUBJECT_OF, OBJECT_OF, SUPPORTED_BY, MENTIONS, IN_COMMUNITY),
  then for each of `VECTOR_TYPES` (Memory, Chunk, Entity, Fact, Community)
  creates an `embedding` property + full-precision COSINE `LSM_VECTOR` index
  (dims from config, checked against any existing sampled vector) and a
  `lexical_tokens`/`lexical_weights` property pair + `LSM_SPARSE_VECTOR`
  index (D-04's winning lexical channel), and for each of `STABLE_ID_TYPES`
  (Memory, Document, Chunk, Entity, Fact, Community) creates an `id` STRING
  property with a UNIQUE index. `User` separately gets a UNIQUE index on its
  existing `identifier` property.
- **`SchemaBootstrapConfig`** — frozen dataclass (`dimensions`, `version`,
  `max_connections`, `beam_width`), validates all four are positive
  (non-bool) ints in `__post_init__`, matching `embeddings.py`'s convention.
- **`versioned_vector_index(base_name, user_identifier, version)`** —
  `cypher_var(f"{base_name}_tenant_{digest}_v{version}")` where `digest` is
  the same blake2b(user_identifier, digest_size=8) hex digest
  `store_core.py`'s `_tenant_vector_index` already uses; validates `version`
  is a positive int.
- **`introspect_vector_dimension(client, name)`** — parses the
  `"Type[property]"` literal (the same form `vectorNeighbors`/
  `vector.sparseNeighbors` consume per 04-SPIKE-FINDINGS.md), samples one
  existing record's vector length via `SELECT <property> FROM <Type> WHERE
  <property> IS NOT NULL LIMIT 1`, returns `None` if no record exists yet.

`tests/test_arcadedb_schema.py` (168 LOC, 7 tests, all against a fake
`_FakeArcadeDBClient` — no live container required): idempotent full-schema
bootstrap + re-run no-op, LSM_VECTOR DDL carries `dimensions`/`cosine` and no
quantization keyword, dimension-mismatch `ValueError`, `versioned_vector_index`
determinism/uniqueness/validation, UNIQUE `id` index presence with no RID
reference, and `introspect_vector_dimension`'s no-sample/malformed-reference
paths.

## Live-Container Verification (D-02-style empirical grounding)

Before writing any DDL string, I ran ad hoc scripts against the running
`arcadedb` container (`arcadedata/arcadedb:26.7.1`, healthy) to resolve three
things 04-SPIKE-FINDINGS.md left open or didn't cover, per this plan's
prohibition on guessing DDL/schema syntax:

1. **`LSM_SPARSE_VECTOR` DDL form** — `CREATE INDEX ON <Type> (tokens,
   weights) LSM_SPARSE_VECTOR` (no METADATA block) succeeds; a second
   identical attempt raises `CommandExecutionException: Index '...' already
   exists` — same idempotency shape as `LSM_VECTOR`.
2. **Dimension introspection** — `SELECT FROM schema:indexes` and `SELECT
   FROM schema:types` both return index name/type/properties but never a
   `dimensions` field for an `LSM_VECTOR` index; confirmed by creating an
   index with `dimensions: 4`, then querying both endpoints and finding no
   trace of the value. Introspecting a sample record's stored vector length
   is the only observable signal.
3. **`CREATE INDEX ... IF NOT EXISTS`** — raises a SQL syntax error
   (`mismatched input 'IF'`) on 26.7.1; `CREATE VERTEX/EDGE TYPE ... IF NOT
   EXISTS` and `CREATE PROPERTY ... IF NOT EXISTS <type>` both work natively.
   This resolves the exact open item 04-SPIKE-FINDINGS.md flagged
   ("`CREATE INDEX ... IF NOT EXISTS` was not tested this wave").

All scratch types created during this verification (`ScratchDenseProbe*`,
`ScratchSparseProbe`, `ScratchIdem`, `ScratchEdgeIdem`, `ScratchNoProp`) were
dropped afterward; confirmed via `SELECT FROM schema:types` that the
`agent_memory` database has zero types remaining from this session.

## Deviations from Plan

### Auto-fixed / Reconciled

**1. [Rule 1/2 — reconciliation, directed by prompt] Lexical index is D-04's `LSM_SPARSE_VECTOR`, not Lucene**

- **Found during:** Task 1, before writing any DDL.
- **Issue:** The plan's `<action>`/must_haves text says "a native Lucene
  full-text index." That wording predates 04-SPIKE-FINDINGS.md's D-04
  bake-off, which chose native `LSM_SPARSE_VECTOR` over Lucene
  `SEARCH_INDEX` (higher MRR@20/recall@20, zero errors vs 2/60 Lucene
  query-parse failures on unescaped punctuation, ~6x lower latency).
  Building the Lucene index the ported search (Wave 4+) would never query
  would be wasted, misleading schema.
- **Fix:** `bootstrap()` creates `LSM_SPARSE_VECTOR` indexes (via
  `lexical_tokens`/`lexical_weights` array properties) on the same 5
  content-bearing types that get dense vector indexes, not a Lucene
  `FULL_TEXT` index.
- **Files modified:** `src/turing_agentmemory_mcp/arcadedb_schema.py`
- **Commit:** `f15fe49`

**2. [Rule 2 — missing critical functionality] UNIQUE index on `User.identifier`**

- **Found during:** Task 1, while deciding User's identity property.
- **Issue:** `store_core.py`'s current `_ensure_user` does a linear `MATCH`
  scan with no supporting index (`WHERE u.identifier = "..."`). User isn't
  produced by `ids.stable_id()` so it's outside the "stable_id UNIQUE index"
  set the plan calls for, but leaving it entirely unindexed would carry the
  same missing-index gap forward into the new backend.
- **Fix:** Added `CREATE PROPERTY User.identifier IF NOT EXISTS STRING` +
  `CREATE INDEX ON User (identifier) UNIQUE` to `bootstrap()`.
- **Files modified:** `src/turing_agentmemory_mcp/arcadedb_schema.py`
- **Commit:** `f15fe49`

No other deviations. Plan's task list, threat model mitigations (T-04-03-01
UNIQUE stable_id + no-RID grep gate; T-04-03-02 introspect-and-raise
ValueError), and prohibitions (no quantization keyword, no RID/native
identity reference, ValueError not RuntimeError) were all honored as
written.

## Issues Encountered

None blocking. The three live-container checks above were exploratory
verification runs (ad hoc Python snippets against the running container, not
committed test code) required by this plan's prohibition on guessing DDL —
all scratch state was cleaned up afterward and none of it is part of the
committed diff.

## Next Phase Readiness

`arcadedb_schema.bootstrap()`, `SchemaBootstrapConfig`,
`versioned_vector_index()`, and `introspect_vector_dimension()` are ready
for Wave 3 (`store_core.py` port, 04-04) to call at store init and for Wave 5
(`store_rebuild.py` atomic swap, 04-08) to use for per-tenant versioned
index naming. No `store_*.py` mixin was touched (prohibited this plan,
honored).

**For Wave 3/4 briefing — the final index set this schema creates:**

- **Dense vector (per Memory/Chunk/Entity/Fact/Community):** `LSM_VECTOR`
  on `embedding`, full-precision COSINE, dims from `EMBED_DIMENSIONS`
  (`Memory[embedding]`, `Chunk[embedding]`, etc. — the literal
  `"Type[property]"` form `vectorNeighbors` consumes).
- **Lexical (per Memory/Chunk/Entity/Fact/Community):** `LSM_SPARSE_VECTOR`
  on `(lexical_tokens, lexical_weights)` — D-04's winning channel, queried
  via `vector.sparseNeighbors("Type[lexical_tokens,lexical_weights]", ...)`.
  **Not Lucene** — do not add a `SEARCH_INDEX`/`FULL_TEXT` call site against
  this schema; the query-string escaping fragility 04-SPIKE-FINDINGS.md
  documents for `SEARCH_INDEX` is exactly why.
- **Identity:** `id` STRING UNIQUE per Memory/Document/Chunk/Entity/Fact/
  Community (stores `ids.stable_id()` output); `identifier` STRING UNIQUE
  on User (raw `user_identifier`, unaffected by stable_id()).
- **Per-tenant/versioned indexes** (04-08's atomic-swap target) are NOT
  created by `bootstrap()` — they're computed on demand via
  `versioned_vector_index(base_name, user_identifier, version)` and created
  the same way `bootstrap()`'s helpers do (idempotent-create-then-verify),
  which Wave 3+ should reuse rather than re-deriving.

## Self-Check: PASSED

- `src/turing_agentmemory_mcp/arcadedb_schema.py` — FOUND
- `tests/test_arcadedb_schema.py` — FOUND
- commit `24b00ce` (RED: failing test) — FOUND in `git log --oneline --all`
- commit `f15fe49` (GREEN: implementation) — FOUND in `git log --oneline --all`
- `python -m pytest tests/test_arcadedb_schema.py -q` — 7 passed
- `python -m pytest -q` (full suite) — 400 passed
- `python -m ruff check src tests scripts` — all checks passed
- `bash scripts/check-file-size.sh` — all tracked `*.py` files within the
  600-LOC cap (`arcadedb_schema.py` is 254 LOC)
- `grep -c "raise ValueError" src/turing_agentmemory_mcp/arcadedb_schema.py`
  → 7 (≥ 1 required)
- `grep -ciE "int8|binary_quant|quantiz" src/turing_agentmemory_mcp/arcadedb_schema.py`
  → 0
- `grep -c "getIdentity\|@rid" src/turing_agentmemory_mcp/arcadedb_schema.py`
  → 0

## TDD Gate Compliance

- RED gate: `test(04-03): add failing test for arcadedb schema bootstrap`
  (`24b00ce`) — confirmed failing (`ModuleNotFoundError`) before commit by
  temporarily removing the not-yet-restored implementation file.
- GREEN gate: `feat(04-03): implement idempotent ArcadeDB schema bootstrap (D-09)`
  (`f15fe49`) — confirmed passing (7/7 tests) after commit.
- No REFACTOR commit was needed — the implementation was written directly
  against the test spec with no post-GREEN cleanup required.

## Amendment (post-completion)

A user decision this session reconciled the D-04 spike finding above with
pre-spike plans that already assumed a Lucene channel: the lexical
retrieval channel is now **BOTH** native `LSM_SPARSE_VECTOR` (this plan's
original choice) **AND** a native Lucene `FULL_TEXT` index on the record's
raw text property — both feed the existing Python RRF
(`retrieval_fusion.py`, unchanged). This directly reverses the "Not
Lucene — do not add a `SEARCH_INDEX`/`FULL_TEXT` call site" guidance
recorded earlier in this summary; that guidance is superseded.

`bootstrap()` now also creates, per `VECTOR_TYPES` (Memory, Chunk, Entity,
Fact, Community):

- `CREATE PROPERTY <Type>.<text_property> IF NOT EXISTS STRING`
- `CREATE INDEX ON <Type> (<text_property>) FULL_TEXT`

where `<text_property>` is `content` for every type except `Chunk`, which
uses `text` (matching `store_rebuild.py`'s `_canonical_vector_records`
text_property mapping — Chunk's raw text field is not named `content`).
No `METADATA` analyzer block — default `StandardAnalyzer`, matching
`scripts/arcadedb_spike.py`'s already-proven `SEARCH_INDEX` bake-off form.
DDL verified live against the running `arcadedb` container (26.7.1) before
landing, including idempotent re-create ("already exists" absorbed) and a
`SEARCH_INDEX(...) ORDER BY $score` query against inserted data.

The Lucene `SEARCH_INDEX`/`?`/`*` query-string escaping fragility
documented above under `04-SPIKE-FINDINGS.md` Unknown 4 still applies and
is now load-bearing (not moot): any future query builder that calls
`SEARCH_INDEX` against this new index must escape Lucene special
characters first.

Landed as `feat(04-03): add Lucene full-text index to schema bootstrap
(both-channels decision)` (commit `357fd6a`), extending
`src/turing_agentmemory_mcp/arcadedb_schema.py` and
`tests/test_arcadedb_schema.py` only. All 8 schema tests green (7 prior +
1 new), ruff clean, file 293 LOC (< 600-LOC cap). This must land before
Wave 4's write plans so Lucene indexes content as it is written.
