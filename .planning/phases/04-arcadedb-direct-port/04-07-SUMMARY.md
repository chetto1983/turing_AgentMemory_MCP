---
phase: 04-arcadedb-direct-port
plan: 07
subsystem: database
tags: [arcadedb, fused-search, rrf, evidence-traversal, both-channels, match, bound-params]

# Dependency graph
requires:
  - phase: 04-arcadedb-direct-port (04-04)
    provides: "store_core.py's _query/_write_many ArcadeDB seam (D-08 single managed transaction), probe-driven readiness"
  - phase: 04-arcadedb-direct-port (04-05)
    provides: "sparse_encoder.sparse_vector() shared both-channels lexical encoder; store_memory_queries.py Statement builder convention; bare-key row convention"
  - phase: 04-arcadedb-direct-port (04-06)
    provides: "store_documents_queries.py's escape_lucene_query; native-HNSW-plus-native-lexical-channel merge pattern template"
provides:
  - "store_search.py/store_evidence.py ported to bound-param ArcadeDB SQL -- no legacy synthetic-integer join property, no SQLite FTS5 outbox read (ARC-06 retired)"
  - "src/turing_agentmemory_mcp/store_retrieval_queries.py -- generic dense/sparse/lucene seed-channel builders (reused across Memory/Fact/Entity/Community) and the D-05 SQL MATCH entity-traversal + bound IN :ids array-lookup builders"
  - "fused memory search's bm25 RRF channel now merges BOTH native ArcadeDB lexical channels (vector.sparseNeighbors + SEARCH_INDEX) per record kind into one weighted-RRF input, keeping retrieval_fusion.py/rerank.py completely unchanged"
  - "tests/test_store_arcadedb_retrieval.py (13 tests) + tests/_retrieval_arcadedb_shared.py -- fake ArcadeDBClient extended for vectorNeighbors/vector.sparseNeighbors/SEARCH_INDEX/MATCH object-notation traversal, no live container needed"
  - "migrated the 04-07-routed test debt: test_fused_memory_search.py (9), plus memory-search/context-filter/search-span parts of test_governance.py/test_observability.py/test_retrieval_filters.py"
affects: [04-08, 04-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "store_retrieval_queries.py: ONE generic Statement builder per seed-channel shape (dense_search_statement/sparse_search_statement/lucene_search_statement), parameterized by type_name and extra_fields -- reused across Memory/Fact/Entity/Community instead of 4 near-duplicate query strings per channel"
    - "BOTH-channels lexical merge: _merged_lexical_scores(type_name, ...) runs vector.sparseNeighbors AND SEARCH_INDEX for a record kind and merges by id, keeping the higher of the two scores -- feeds ONE 'bm25' RRF channel (not two new channel keys), since extending store_core.py's fusion_weights schema was out of this plan's declared scope"
    - "D-05 SQL MATCH object-notation traversal: MATCH {type: Entity, as: e, where: (id IN :entity_ids AND user_identifier = :user_identifier AND status = 'active')}.out('SUBJECT_OF'){as: f, ...}.out('SUPPORTED_BY'){as: m, ...} RETURN m.id AS memory_id, ... -- the ONLY MATCH form 04-01's spike empirically confirmed live for 26.7.1; a hop=2 traversal inserts a `.both(){as: n, ...}` step (undirected any-edge-type hop), mirroring the retired Cypher `(e:Entity)--(n:Entity)` step"
    - "vectorNeighbors' cosine `distance` (0=identical) is converted to a higher-is-better `_similarity()` score in every dense evidence collector, since _collect_retrieval_evidence sorts every channel uniformly by -raw_score (matches store_documents.py's search_documents precedent)"

key-files:
  created:
    - src/turing_agentmemory_mcp/store_retrieval_queries.py
    - tests/test_store_arcadedb_retrieval.py
    - tests/_retrieval_arcadedb_shared.py
  modified:
    - src/turing_agentmemory_mcp/store_search.py
    - src/turing_agentmemory_mcp/store_evidence.py
    - tests/test_fused_memory_search.py
    - tests/test_governance.py
    - tests/test_observability.py
    - tests/test_retrieval_filters.py

key-decisions:
  - "BOTH-channels lexical decision resolved by MERGING, not adding new RRF channel keys: the bm25 channel's evidence list is built by running vector.sparseNeighbors AND SEARCH_INDEX per record kind (Memory/Fact/Entity/Community) and keeping the higher-scoring hit per id, then feeding the merged list into the SAME single 'bm25' fusion_weights key store_core.py already defines. Extending store_core.py's fusion_weights schema with two new channel keys was out of this plan's declared files_modified scope (store_search.py/store_evidence.py/store_retrieval_queries.py only); the merge preserves 'both channels feed RRF' while respecting that boundary. Documented here for 04-09's consolidation wave to reconsider if a future phase wants the two lexical channels weighted independently."
  - "_ensure_tenant_vector_index calls dropped entirely from store_search.py's non-fused dense channel and every store_evidence.py dense/lexical collector -- matching 04-05/04-06's established precedent that ported reads never call the schema-bootstrap shim (only bootstrap(), called once at server startup via server.py's store_from_env(), does). This ALSO fixed 5 pre-existing test failures whose fixtures used a bare client=object()/TuringDB-shaped fake lacking .command()/.query(), which crashed the moment search_memory tried to lazily bootstrap the schema through the shim."
  - "Dense evidence collectors convert vectorNeighbors' raw cosine distance to a higher-is-better similarity score (max(0.0, 1.0 - distance)) before returning RetrievalEvidence -- _collect_retrieval_evidence's final per-channel sort assumes -raw_score is 'best first' uniformly across every channel; leaving distance un-converted for dense channels while lexical channels return an already-higher-is-better score would have silently inverted dense channel ranking."
  - "D-05's graph surface uses the object-notation MATCH {type:...,as:...,where:(...)}.out('Kind'){as:...} form exclusively -- the ONLY form 04-01's spike (scripts/arcadedb_spike.py's run_graph_surface_bakeoff) empirically confirmed live for ArcadeDB 26.7.1, not the simplified Cypher-like (variable:type {property: value}) pattern some generic ArcadeDB docs/skill references show (that pattern is the RETIRED literal shape this whole phase ports away from)."

patterns-established:
  - "Generic per-seed-channel-shape Statement builder (dense_search_statement/sparse_search_statement/lucene_search_statement), parameterized by type_name + extra_fields, reused across every content-bearing record type -- the template any future new vector-bearing type should follow rather than writing a bespoke query string per type."

requirements-completed: [ARC-04, ARC-05, ARC-06]

coverage:
  - id: D1
    description: "Fused memory search builds its per-channel seed candidates (episode/fact/entity dense via native HNSW; lexical/bm25 via BOTH native ArcadeDB lexical channels merged) and feeds them to the UNCHANGED Python weighted RRF"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_fused_search_feeds_per_channel_candidates_to_unchanged_rrf"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_bm25_channel_reads_native_arcadedb_lexical_not_sqlite_sparse_index"
        status: pass
    human_judgment: false
  - id: D2
    description: "Dense seed/evidence channels order by native HNSW score with no vector_id join, and the D-03 adaptive over-fetch multiplier is applied"
    requirement: "ARC-05"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_dense_channel_orders_by_native_hnsw_score_with_no_vector_id_join"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_fused_search_applies_adaptive_overfetch_multiplier_to_dense_channel"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_dense_evidence_channels_order_by_native_score_with_no_vector_id_join"
        status: pass
    human_judgment: false
  - id: D3
    description: "The 2-hop entity-to-fact-to-memory traversal runs on the D-05 SQL MATCH surface with a bound IN :entity_ids array param, replacing the retired string-built OR-list"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_expand_entity_evidence_runs_two_hop_traversal_on_match_surface"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_fact_sources_by_ids_binds_array_param_single_quote_safe"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every seed channel, traversal, and multi-id lookup is user_identifier-scoped; a tenant-A search/traversal never returns tenant-B candidates or evidence"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_fused_search_tenant_a_never_sees_tenant_b_candidates"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_evidence_traversal_and_lookups_are_tenant_scoped"
        status: pass
    human_judgment: false
  - id: D5
    description: "The lexical channel reads native ArcadeDB full-text (both vector.sparseNeighbors and SEARCH_INDEX) -- the SQLite FTS5 outbox is never consulted for reads (ARC-06)"
    requirement: "ARC-06"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_store_search_does_not_read_sqlite_sparse_index"
        status: pass
    human_judgment: false
  - id: D6
    description: "store_search.py and store_evidence.py stay under the 600-LOC cap and contain no vector_id/VECTOR SEARCH IN/string-built OR-list references"
    requirement: "ARC-05"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_store_search_and_evidence_contain_no_vector_id_or_helper_calls"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_store_evidence_has_no_string_built_or_list"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_retrieval.py#test_store_search_and_evidence_under_loc_cap"
        status: pass
    human_judgment: false

# Metrics
duration: 95min
completed: 2026-07-14
status: complete
---

# Phase 04 Plan 07: Fused Search + Evidence Traversal ArcadeDB Port Summary

**Ported fused memory search's per-channel seed-candidate fetch and entity/fact/community evidence traversal to ArcadeDB (native HNSW dense + BOTH native lexical channels merged into one bm25 RRF input + D-05 SQL MATCH graph traversal), keeping `retrieval_fusion.py`'s weighted RRF and `rerank.py`'s guard/blend completely untouched.**

## Performance

- **Duration:** ~95 min
- **Completed:** 2026-07-14
- **Tasks:** 2 (both TDD; implemented together with the accompanying test suite rather than strict RED-then-GREEN, given the plan's scale -- same rationale 04-05/04-06 documented)
- **Files modified:** 6 (store_search.py, store_evidence.py, tests/test_fused_memory_search.py, tests/test_governance.py, tests/test_observability.py, tests/test_retrieval_filters.py); 3 created (store_retrieval_queries.py, tests/test_store_arcadedb_retrieval.py, tests/_retrieval_arcadedb_shared.py)

## Accomplishments

- **`src/turing_agentmemory_mcp/store_retrieval_queries.py`** (NEW) -- bound-param ArcadeDB `Statement` builders: `dense_search_statement`/`sparse_search_statement`/`lucene_search_statement` (one generic builder per seed-channel shape, parameterized by `type_name`/`extra_fields`, reused across Memory/Fact/Entity/Community instead of writing near-duplicate query strings per channel), `entity_traversal_statement` (the D-05 SQL `MATCH` object-notation 2-hop entity-to-fact-to-memory surface, bound `id IN :entity_ids` array param), and `fact_sources_by_ids_statement`/`community_sources_by_ids_statement`/`memory_rows_by_ids_statement` (bound `IN :xxx_ids` array multi-id lookups, replacing the retired string-built `" OR ".join(...)` condition).
- **`store_search.py`** ported: the non-fused `search_memory` dense channel now uses `dense_search_statement` (native `vectorNeighbors`, D-03 over-fetch-then-filter, no legacy synthetic-integer join property) with bare-key row reads (`"id"`/`"content"`/`"expires_at"`, not the retired `"m."`-prefixed Cypher alias shape); `_ensure_tenant_vector_index` and the TuringDB-specific "Unknown label: Memory" exception catch are both dropped (matching 04-05/04-06's precedent that ported reads never lazily bootstrap schema). `_search_memory_fused`'s row-key reference was also fixed to bare keys.
- **`store_evidence.py`** ported: `_episode_dense_evidence`/`_fact_dense_evidence`/`_entity_dense_evidence`/`_community_dense_evidence` all use `dense_search_statement`, converting `vectorNeighbors`' raw cosine distance to a higher-is-better similarity score via a shared `_similarity()` helper (matches `_collect_retrieval_evidence`'s uniform `-raw_score` sort convention). The lexical/`bm25` channel is now `_lexical_evidence`, which runs BOTH native channels (`sparse_search_statement`/`lucene_search_statement`) per record kind via `_merged_lexical_scores` and merges by id (keeping the higher score) -- retiring the SQLite FTS5 outbox read entirely (ARC-06; the `self.sparse_index is not None` gate is gone). `_expand_entity_evidence` runs the 2-hop traversal on the D-05 `MATCH` surface (4 traversal queries: direct/two-hop x SUBJECT_OF/OBJECT_OF, collapsed into one `entity_traversal_statement(edge_kind, hop, ...)` builder). `_fact_sources_by_ids`/`_community_sources_by_ids`/`_memory_rows_for_ids` all bind `IN :xxx_ids` arrays.
- **`tests/_retrieval_arcadedb_shared.py`** (NEW) -- a fake `ArcadeDBClient` extending the 04-05/04-06 session-aware convention to also interpret `vectorNeighbors`, `vector.sparseNeighbors`, `SEARCH_INDEX`, and the D-05 `MATCH {type:...,as:...,where:(...)}.out(...)` object-notation traversal, plus a `_ScriptedExtractor` that builds a real 2-hop entity graph through the actual (04-05-ported) write path. Split out of the test file to stay under the 600-LOC cap (mirrors `_batch_memory_shared.py`'s naming convention).
- **`tests/test_store_arcadedb_retrieval.py`** (NEW) -- 13 tests covering both tasks' full `must_haves`/acceptance criteria: RRF channel composition (asserts `fuse_rankings` is invoked with per-channel `RetrievalCandidate` lists), dense/lexical ordering with no `vector_id`, D-03 over-fetch multiplier, tenant isolation across seed channels and evidence traversal, 2-hop MATCH traversal, bound-array single-quote safety, and source-grep acceptance gates (no `vector_id`/`VECTOR SEARCH IN`, no `sparse_index` read in `store_search.py`, no string-built OR-list in `store_evidence.py`, both files under 600 LOC).
- **Test-migration debt, as routed by `04-EXECUTION-STATE.md`:** migrated all 9 `test_fused_memory_search.py` failures (row-key convention, `CollectorStore`'s canned per-operation rows redesigned for the BOTH-channels native shapes, `client=object()` -> a minimal `is_ready()`-only stub), plus the memory-search/context-filter/search-span parts of `test_governance.py`/`test_observability.py`/`test_retrieval_filters.py`.

## Task Commits

1. **Port fused-search dense/lexical seed channels to ArcadeDB (Task 1)** - `4a00585` (feat)
2. **Port entity/fact/community evidence traversal to ArcadeDB (Task 2)** - `4b83e00` (feat)
3. **Add ArcadeDB fused search + evidence traversal test suite** - `56afc03` (test)
4. **Migrate routed TuringDB-shaped test-double debt to ArcadeDB shape** - `d48a234` (test)

**Plan metadata:** (this commit, pending)

## Files Created/Modified

- `src/turing_agentmemory_mcp/store_retrieval_queries.py` - NEW: generic dense/sparse/lucene seed-channel `Statement` builders, D-05 MATCH entity-traversal builder, bound `IN :ids` array multi-id lookup builders.
- `src/turing_agentmemory_mcp/store_search.py` - Ported the non-fused `search_memory` dense channel to `dense_search_statement`; fixed `_search_memory_fused`'s remaining `"m."`-prefixed row-key reference; dropped `_ensure_tenant_vector_index`.
- `src/turing_agentmemory_mcp/store_evidence.py` - Ported all 4 dense evidence collectors, the both-channels lexical merge (`_lexical_evidence`/`_merged_lexical_scores`), the D-05 MATCH 2-hop traversal (`_expand_entity_evidence`), and the 3 bound-array multi-id lookups.
- `tests/test_store_arcadedb_retrieval.py` - NEW: 13 tests, fake ArcadeDBClient, no live container.
- `tests/_retrieval_arcadedb_shared.py` - NEW: shared fixtures (fake client + scripted extractor), split out for the 600-LOC cap.
- `tests/test_fused_memory_search.py` - Row-key convention fixed; `CollectorStore` redesigned for native dense/lexical canned rows; `client=object()` -> `ReadyOnlyClient`.
- `tests/test_governance.py` - `QueryClient.query()` now actually filters by bound params instead of ignoring them.
- `tests/test_observability.py` - Span assertions updated to `arcadedb.query`/`arcadedb.write_batch`; `vector.load` assertion dropped.
- `tests/test_retrieval_filters.py` - `FilterStore._query` returns a plain list (not the retired `Rows.to_dict("records")` wrapper); bare-key rows.

## Decisions Made

See frontmatter `key-decisions` for the full list. Highlights: the BOTH-channels lexical decision is resolved by MERGING both native channels into the single existing `bm25` RRF weight key (not adding two new fusion-weight keys, which would have required extending `store_core.py` outside this plan's declared scope); `_ensure_tenant_vector_index` is dropped everywhere in this plan's mixins (matching 04-05/04-06 precedent); dense evidence collectors convert `vectorNeighbors`' distance to a higher-is-better score to preserve `_collect_retrieval_evidence`'s uniform sort convention; the D-05 graph surface uses ONLY the object-notation `MATCH {type:...}.out(){as:...}` form the spike empirically confirmed, not the simplified Cypher-like literal some generic docs show.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `QueryClient.query()` (test_governance.py) ignored bound params entirely**
- **Found during:** Task 1 (fixing `test_expired_memory_is_hidden_from_get_list_and_search`)
- **Issue:** The fixture always returned every row in `self.rows` regardless of the requested `memory_id`/`user_identifier` params, silently masking a get-by-id lookup that should return exactly one row (or none). This was previously hidden behind an earlier schema-bootstrap crash (`_ensure_tenant_vector_index` calling `object().command()`); once that crash was fixed by this plan's `_ensure_tenant_vector_index` removal, the fixture's leniency surfaced as a genuine wrong-answer bug.
- **Fix:** Added a `_filtered()` helper that narrows `self.rows` by any bound param key the row actually carries, skipping vector/limit-only params.
- **Files modified:** `tests/test_governance.py`
- **Verification:** `tests/test_governance.py::test_expired_memory_is_hidden_from_get_list_and_search`
- **Committed in:** `d48a234`

**2. [Rule 3 - Blocking] `test_fused_memory_search.py`'s `CollectorStore`/`test_retrieval_filters.py`'s `FilterStore` returned a `Rows`/pandas-style wrapper `_records()` no longer unwraps**
- **Found during:** Task 1/2 (migrating the routed test debt)
- **Issue:** `store_core.py`'s ported `_records()` expects `_query()` to return a plain `list[dict]` directly; both fixtures wrapped their canned rows in a local `Rows` class with a `.to_dict("records")` method (a leftover convention from before 04-04's port), so `_records()` silently discarded every result (`isinstance(rows, list)` is `False` for a `Rows` instance), making every channel appear empty regardless of the canned data.
- **Fix:** Removed the `Rows` wrapper in both files; `_query()` now returns `list[dict[str, object]]` directly.
- **Files modified:** `tests/test_fused_memory_search.py`, `tests/test_retrieval_filters.py`
- **Verification:** All tests in both files pass with real canned-row data flowing through.
- **Committed in:** `d48a234`

---

**Total deviations:** 2 auto-fixed (1 Rule 1 bug fix, 1 Rule 3 blocking fix affecting 2 files)
**Impact on plan:** Both are necessary for the routed test-migration debt to actually exercise the ported code paths (not silently no-op). No scope creep beyond what the port itself required.

## Issues Encountered

- **Strict RED-then-GREEN was not practical for this plan's scale**, same as 04-05/04-06: both tasks port an entire query dialect (Cypher-literal + inline-vector-join reads -> bound-param ArcadeDB SQL across 3 seed-channel shapes plus a graph-traversal surface) simultaneously across `store_search.py`/`store_evidence.py`/`store_retrieval_queries.py`. I designed the query builders and store methods together with the test file, ran the suite immediately, and iterated to green -- documented here rather than silently glossed over.
- **The both-channels lexical decision required an explicit scope-respecting design choice** (see key-decisions): rather than extending `store_core.py`'s `fusion_weights` schema with two new channel keys (out of this plan's declared `files_modified`), the two native lexical channels are merged pre-RRF into the existing single `bm25` weight. This is documented as a decision open to revisiting in 04-09's consolidation wave if a later phase wants the two lexical channels weighted independently in the RRF.
- **The initial `test_store_arcadedb_retrieval.py` draft (729 lines) exceeded the 600-LOC cap** -- split the fake-client/fixture machinery into a new `tests/_retrieval_arcadedb_shared.py` sibling module (mirroring `_batch_memory_shared.py`'s established convention), bringing both files under the cap (325 and 428 lines respectively).
- **A 2-hop test scenario initially asserted a single evidence entry per memory** and failed because the test data naturally produced BOTH a hop=1 and a hop=2 path to the same memory (the shared "hiking" entity connects to both facts) -- this is correct, expected behavior (evidence is deduped later by `retrieval_fusion.py`'s RRF, not by `_expand_entity_evidence` itself), so the test assertion was corrected to check "any evidence at that hop" rather than assuming exactly one entry per memory.

## Migration Debt: Confirmed Resolved (Wave 4/5 Routing)

Before this plan, the full test suite carried 24 pre-existing failures. This plan resolves exactly its routed cohort (14 of the 24):

- `tests/test_fused_memory_search.py` (9)
- memory-search/context-filter parts of `tests/test_retrieval_filters.py` (2)
- search-span parts of `tests/test_observability.py` (2)
- the memory-search part of `tests/test_governance.py` (1)

The remaining 10 failures are untouched, still correctly routed exactly as `04-EXECUTION-STATE.md` predicted:

- **04-08 (rebuild + community):** `test_batch_memory.py`'s 2 rebuild-projection tests, `test_community_detection.py`'s 1 -- `store_rebuild.py` is still Cypher-shaped.
- **04-09 (close the port):** `test_runtime_pipeline.py`'s 6 (`store_from_env` now builds `ArcadeDBClient`), `test_store_entity_processing.py`'s `_ensure_graph_loaded` test (method retired in 04-04).

No skip-as-green was used anywhere; every failure above is a genuine, itemized, pre-existing test-asserted red, not a hidden or suppressed one. Full-suite run after this plan: 438 passed, 10 failed (exactly the 04-08/04-09 cohort), 0 new regressions.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Fused memory search and evidence traversal now speak ArcadeDB exclusively; `store_retrieval_queries.py`'s generic per-seed-channel-shape builder pattern and the both-channels lexical merge pattern established here are concrete templates 04-08 (rebuild + community) should follow when it ports `store_rebuild.py`'s canonical-vector-record rebuild path and community-refresh queries.
- **Heads-up for 04-08:** `store_rebuild.py`'s `_existing_entity_ids`/`_unique_projection_entities`/`_fact_ids_for_memory` still emit Cypher-shaped queries (stubbed out in this plan's own test fixtures, per the established 04-05/04-06 convention) -- they need their own ArcadeDB port in that wave. During this plan's own manual testing, `store_messages`'s community-refresh path (`_refresh_communities_after_batch`, unported) was observed issuing old-style `MATCH (e:Entity) WHERE ...` Cypher-literal queries against the live store during ordinary writes -- harmless against both the fake test client (silently returns no rows) and this plan's own new tests, but confirms `store_rebuild.py` is the sole remaining Cypher-shaped mixin blocking full port completion.
- **Heads-up for 04-09:** if a future phase wants the two lexical channels (`vector.sparseNeighbors`/`SEARCH_INDEX`) weighted independently in the RRF rather than pre-merged into one `bm25` channel, that requires extending `store_core.py`'s `fusion_weights` default dict with two new channel keys -- explicitly left as future work per this plan's scope boundary (see key-decisions).
- `store_search.py`/`store_evidence.py` are both comfortably under the 600-LOC cap (521/502 lines) with headroom for 04-09's final consolidation pass.

---
*Phase: 04-arcadedb-direct-port*
*Completed: 2026-07-14*

## Self-Check: PASSED

- FOUND: `src/turing_agentmemory_mcp/store_retrieval_queries.py`
- FOUND: `src/turing_agentmemory_mcp/store_search.py`
- FOUND: `src/turing_agentmemory_mcp/store_evidence.py`
- FOUND: `tests/test_store_arcadedb_retrieval.py`
- FOUND: `tests/_retrieval_arcadedb_shared.py`
- FOUND commit: `4a00585` (feat(04-07): port fused-search dense/lexical seed channels to ArcadeDB)
- FOUND commit: `4b83e00` (feat(04-07): port entity/fact/community evidence traversal to ArcadeDB)
- FOUND commit: `56afc03` (test(04-07): add ArcadeDB fused search + evidence traversal test suite)
- FOUND commit: `d48a234` (test(04-07): migrate routed TuringDB-shaped test-double debt to ArcadeDB shape)
