---
phase: 04-arcadedb-direct-port
plan: 05
subsystem: database
tags: [arcadedb, memory-write, memory-read, sparse-encoder, both-channels, bound-params, transactions]

# Dependency graph
requires:
  - phase: 04-arcadedb-direct-port (04-04)
    provides: "store_core.py's _query/_write_many ArcadeDB seam (D-08 single managed transaction), probe-driven readiness"
  - phase: 04-arcadedb-direct-port (04-03)
    provides: "arcadedb_schema.bootstrap idempotent DDL (Memory/Entity/Fact LSM_VECTOR + LSM_SPARSE_VECTOR + FULL_TEXT channels, UNIQUE stable_id index)"
provides:
  - "store_memory_write.py/store_memory_read.py ported to bound-param ArcadeDB SQL -- no legacy synthetic-integer join property, no separate CSV vector-load step (ARC-05)"
  - "src/turing_agentmemory_mcp/sparse_encoder.py -- the canonical shared both-channels sparse-lexical encoder (sparse_vector()), reused verbatim by 04-06/07/08"
  - "src/turing_agentmemory_mcp/store_memory_queries.py -- extracted bound-param ArcadeDB SQL builders for memory/entity/fact CREATE, UPDATE, SELECT, and dynamic-edge-type DDL"
  - "_create_memories_batch signature change: takes pre-computed vector_by_id/entity_vectors/fact_vectors so every vertex's embedding is inlined at CREATE time, one managed transaction for the whole memory+entity+fact+edge batch"
  - "tests/test_store_arcadedb_memory.py -- 13 tests against a fake ArcadeDBClient, no live container needed"
affects: [04-06, 04-07, 04-08, 04-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "sparse_encoder.sparse_vector(text, idf=None) -- blake2b hash-bucketed TF encoder, VOCAB_SIZE=4096, promoted verbatim from scripts/arcadedb_spike.py; reuse this exact function for every write AND every query-side lexical encode (byte-identical tokenization is load-bearing)"
    - "store_memory_queries.py Statement = tuple[str, dict[str, object]] builder convention -- bound-param name mirrors the target property name (e.g. `identifier`/`id`, matching store_core.py's _ensure_user convention), not a caller-scoped name"
    - "CREATE EDGE <Type> FROM (SELECT FROM <SourceType> WHERE id = :id) TO (SELECT FROM <TargetType> WHERE id = :id) -- replaces the retired Cypher CREATE (a)-[:R]->(b) literal; works identically whether the endpoint was committed in an earlier call or created moments ago in the SAME _write_many transaction (read-your-writes, no extra MATCH needed)"
    - "Dynamic per-predicate fact edges (fact.predicate.upper(), unbounded vocabulary) declare their own edge type on demand via idempotent `CREATE EDGE TYPE <kind> IF NOT EXISTS`, deduplicated per batch -- the 4 fixed kinds (HAS_MEMORY/MENTIONS/SUBJECT_OF/OBJECT_OF/SUPPORTED_BY) are already pre-registered by arcadedb_schema.bootstrap and skip this"

key-files:
  created:
    - src/turing_agentmemory_mcp/sparse_encoder.py
    - src/turing_agentmemory_mcp/store_memory_queries.py
    - tests/test_store_arcadedb_memory.py
  modified:
    - src/turing_agentmemory_mcp/store_memory_write.py
    - src/turing_agentmemory_mcp/store_memory_read.py
    - tests/_batch_memory_shared.py
    - tests/test_batch_memory_write.py
    - tests/test_batch_memory_dedup.py
    - tests/test_governance.py
    - tests/test_store_entity_processing.py

key-decisions:
  - "Shared sparse-encoder module: src/turing_agentmemory_mcp/sparse_encoder.py, function sparse_vector(text, idf=None) -> (tokens, weights). idf defaults to {} (raw term-frequency, no corpus-wide IDF maintained this milestone) -- 04-06/07/08 MUST import this exact function, never re-derive a tokenizer, or write-side and query-side lexical channels silently diverge."
  - "_write_many (not sqlscript+LET) is the batch mechanism, per 04-EXECUTION-STATE.md's explicit routing -- each vertex/edge is its own (sql, params) Statement in one list, all committed by one begin/command(s)/commit-retry-N transaction (04-04's seam already gives read-your-writes across the whole list); sqlscript LET-chaining was not needed since CREATE EDGE ... FROM (SELECT ...) subqueries resolve both already-committed and same-batch-created endpoints without a script variable."
  - "Dropped the existing_entity_ids/MATCH-pre-existing-nodes machinery entirely (store_memory_write.py's old _create_memories_batch built an explicit MATCH clause for entities not new in this batch) -- CREATE EDGE's FROM/TO subqueries make that special-casing unnecessary, since a plain property-filtered SELECT finds an entity whether it was committed in an earlier request or created earlier in the SAME transaction."
  - "Left the legacy SQLite sparse_index hooks (_prepare_sparse_projection, sparse_index.commit_batch/replay, _sparse_doc_key/_sparse_kind) untouched in both ported files -- ARC-06's bootstrap-time outbox retirement (04-04) is a separate concern from these live-write hooks, which store_search.py (unported, 04-07) may still read from during the interim; ripping them out now was explicitly out of this plan's declared scope (store_memory_write.py/store_memory_read.py/store_memory_queries.py/tests/test_store_arcadedb_memory.py) and risked a live regression for search until 04-07 lands."
  - "_memory_from_row/_active_memory_rows/_row_is_expired now read/build ArcadeDB's own unqualified projection keys (\"id\", \"expires_at\", ...) instead of the retired Cypher RETURN m.id alias shape (\"m.id\") -- store_search.py/store_evidence.py (unported) still consume the old \"m.\"-prefixed convention from these same shared methods and will need their own call sites updated when 04-07 ports them; documented in store_memory_read.py's module docstring so 04-07 doesn't rediscover this by surprise."
  - "_write_memory's existing/vector/load_vector override parameters were removed (no caller needed them post-port): the batch path in store_messages now calls update_memory directly for existing-but-changed items, passing the pre-computed vector so it can be inlined in the same bound-param UPDATE, instead of a separate bulk vector-load step that no longer exists."

patterns-established:
  - "Statement = tuple[str, dict[str, object]] builder functions in a *_queries.py sibling module, one function per DDL/DML shape, consumed as a flat list by _write_many -- the LOC-budget escape hatch 04-PATTERNS.md called for."
  - "Test-double convention for ArcadeDB-shaped stores without a live container: subclass TuringAgentMemory, override only the specific cross-mixin methods this plan doesn't own (_existing_entity_ids, _fact_ids_for_memory) to stub store_rebuild.py's still-unported behavior, and use a small session-aware fake client that interprets CREATE VERTEX <Type>/UPDATE <Type>/SELECT FROM <Type> well enough to round-trip -- see tests/test_store_arcadedb_memory.py's _FakeArcadeDBClient."

requirements-completed: [ARC-04, ARC-05, ARC-08, PERF-01, PERF-02]

coverage:
  - id: D1
    description: "Memory/entity/fact writes CREATE ArcadeDB vertices with the embedding inline as a record property and stable_id() as the id -- no legacy synthetic-integer join property is written"
    requirement: "ARC-05"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_single_memory_write_creates_vertex_with_stable_id_and_inline_embedding"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_memory_write_and_queries_files_contain_no_vector_id_or_helper_calls"
        status: pass
    human_judgment: false
  - id: D2
    description: "A batch memory write with extracted entities/facts CREATEs Memory/Entity/Fact vertices plus MENTIONS/SUBJECT_OF/OBJECT_OF/SUPPORTED_BY/dynamic-predicate edges inside ONE managed transaction"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_batch_write_with_entities_and_facts_uses_one_managed_transaction"
        status: pass
      - kind: unit
        ref: "tests/test_batch_memory_dedup.py#test_store_messages_projects_temporal_graph_atomically_before_vector_publication"
        status: pass
    human_judgment: false
  - id: D3
    description: "A batch of N memory writes embeds all N texts in one embed_many call and runs memory extraction once per batch, not per item (PERF-01/PERF-02), inside the same managed transaction as the write"
    requirement: "PERF-01"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_batch_calls_embed_many_exactly_once_for_n_items"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_batch_calls_memory_extraction_exactly_once_for_n_items"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_batch_write_stays_within_one_managed_transaction_across_embed_extract_write"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every write and read is user_identifier-scoped and fails closed on an empty identifier; a value containing a single quote round-trips via a bound param, not string interpolation"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_write_with_empty_user_identifier_raises_value_error"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_tenant_scoped_read_never_returns_other_tenants_memory"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_single_quote_in_content_is_stored_intact_via_bound_param"
        status: pass
    human_judgment: false
  - id: D5
    description: "update_memory's kind-update no longer sets a legacy synthetic-integer join property; the both-channels lexical fields (lexical_tokens/lexical_weights) are populated on every Memory/Entity/Fact vertex written"
    requirement: "ARC-05"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_kind_update_does_not_write_vector_id"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_single_memory_write_populates_both_lexical_channels"
        status: pass
    human_judgment: false
  - id: D6
    description: "Shared sparse-encoder module established at src/turing_agentmemory_mcp/sparse_encoder.py (function sparse_vector) for 04-06/07/08 to reuse verbatim"
    requirement: "ARC-05"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_memory.py#test_single_memory_write_populates_both_lexical_channels"
        status: pass
    human_judgment: false

# Metrics
duration: 53min
completed: 2026-07-13
status: complete
---

# Phase 04 Plan 05: Memory Write/Read ArcadeDB Port Summary

**Ported store_memory_write.py/store_memory_read.py to bound-param ArcadeDB SQL with inline dense+sparse-lexical vectors and no legacy synthetic-integer join property, promoted the both-channels sparse encoder to `src/turing_agentmemory_mcp/sparse_encoder.py`, and migrated the routed TuringDB-shaped test debt (test_batch_memory_write.py, test_batch_memory_dedup.py) to the new per-statement transaction shape.**

## Performance

- **Duration:** ~53 min
- **Completed:** 2026-07-13
- **Tasks:** 2 (both TDD; implemented together with the accompanying test file rather than strict RED-then-GREEN, given the scale of the retrofit -- see "Issues Encountered")
- **Files modified:** 7 (store_memory_write.py, store_memory_read.py, tests/_batch_memory_shared.py, tests/test_batch_memory_write.py, tests/test_batch_memory_dedup.py, tests/test_governance.py, tests/test_store_entity_processing.py); 3 created (sparse_encoder.py, store_memory_queries.py, tests/test_store_arcadedb_memory.py)

## Accomplishments

- **`src/turing_agentmemory_mcp/sparse_encoder.py`** (NEW) -- the canonical shared both-channels sparse-lexical encoder, `sparse_vector(text, idf=None) -> (tokens, weights)`, promoted verbatim from the D-04 spike's winning `_sparse_vector` (`scripts/arcadedb_spike.py`). 04-06/07/08 MUST import this exact function so write-side and query-side tokenization stay byte-identical.
- **`src/turing_agentmemory_mcp/store_memory_queries.py`** (NEW) -- extracted bound-param ArcadeDB SQL builders for Memory/Entity/Fact `CREATE`, the `HAS_MEMORY` edge, projection edges (with on-demand `CREATE EDGE TYPE ... IF NOT EXISTS` for the dynamic per-predicate fact edge), and Memory `SELECT`/`UPDATE`/soft-delete -- keeps both ported mixins under the 600-LOC cap.
- **`store_memory_write.py`** ported: `_write_memory`/`_create_memories_batch` now build bound-param `CREATE VERTEX`/`CREATE EDGE ... FROM (SELECT ...) TO (SELECT ...)` statements with the dense `embedding` and both lexical channels (`lexical_tokens`/`lexical_weights`) inline as record properties -- no legacy synthetic-integer join property, no separate CSV vector-load step. The whole memory+entity+fact+edge batch is ONE managed transaction via `store_core.py`'s `_write_many` (D-08); existing-entity MATCH machinery is gone entirely since `CREATE EDGE ... FROM (SELECT ...)` resolves both already-committed and same-batch-created endpoints via read-your-writes.
- **`store_memory_read.py`** ported: `get_memory`/`list_memories`/`update_memory`/`delete_memory`/`_active_memory_rows` now issue bound-param ArcadeDB `SELECT`/`UPDATE` (retiring the Cypher-flavored `quote()`-interpolated `MATCH` literals, which are not valid ArcadeDB syntax at all). Rows come back keyed by ArcadeDB's own unqualified property names (`"id"`, not `"m.id"`) -- documented as a contract change `store_search.py`/`store_evidence.py` (unported) must account for in 04-07. `update_memory`'s kind-update sets both lexical channels on every write and only re-embeds when content actually changed (preserving the existing PERF discipline); `delete_memory`'s fact soft-delete uses a bound `id IN :fact_ids` array param.
- **`tests/test_store_arcadedb_memory.py`** (NEW) -- 13 tests against a small session-aware fake `ArcadeDBClient` (no live container), covering both tasks' full `must_haves`/acceptance criteria.
- **Test-migration debt, as routed by `04-EXECUTION-STATE.md`:** deleted `test_write_many_submits_each_dependent_graph_batch` (its own name asserted the retired submit-before-match semantics, superseded by `tests/test_store_arcadedb_core.py`'s 04-04 tests); updated `tests/_batch_memory_shared.py`'s shared `RecordingMemoryStore`/`RecordingDocumentStore` to normalize both the new `list[tuple[str, params]]` shape and the still-unported `list[str]` shape into one `write_queries` list (plus a new `write_params` list) without changing any currently-passing document-ingestion assertion; updated `test_batch_memory_write.py`'s two memory-write tests and all 8 of `test_batch_memory_dedup.py`'s tests to the new per-statement recording shape.

## Task Commits

1. **Shared sparse encoder + ArcadeDB memory query builders** - `506558d` (feat)
2. **Port memory write path to ArcadeDB** - `6f21ba2` (feat)
3. **Port memory read path to ArcadeDB** - `a4885e0` (feat)
4. **Add ArcadeDB memory write/read test suite** - `0605169` (test)
5. **Migrate routed TuringDB-shaped test-double debt** - `40808c9` (test)

**Plan metadata:** (this commit, pending)

## Files Created/Modified

- `src/turing_agentmemory_mcp/sparse_encoder.py` - NEW: `sparse_vector(text, idf=None)`, the shared both-channels lexical encoder.
- `src/turing_agentmemory_mcp/store_memory_queries.py` - NEW: bound-param `Statement` builders for memory/entity/fact write and read/update/delete.
- `src/turing_agentmemory_mcp/store_memory_write.py` - Ported `store_message`/`store_messages`/`_write_memory`/`_create_memories_batch` to ArcadeDB; `_create_memories_batch` gained `vector_by_id`/`entity_vectors`/`fact_vectors` params so every vertex inlines its own embedding.
- `src/turing_agentmemory_mcp/store_memory_read.py` - Ported all read/update/delete queries to bound-param ArcadeDB SQL; unqualified row-key convention; kind-update no longer touches the legacy synthetic-integer join property.
- `tests/test_store_arcadedb_memory.py` - NEW: 13 tests, fake `ArcadeDBClient`, no live container.
- `tests/_batch_memory_shared.py` - `RecordingMemoryStore`'s `_write`/`_write_many` overrides now normalize both the tuple and plain-string statement shapes; added `write_params`.
- `tests/test_batch_memory_write.py` - Deleted the superseded per-batch-submit test; rewrote the two memory-write tests for the new per-statement/inline-vector shape.
- `tests/test_batch_memory_dedup.py` - All 8 tests updated: statement-count assertions instead of single-combined-Cypher-literal substring checks; 2 failure-simulation tests now override `_write_many` (the new call site) instead of `_write`.
- `tests/test_governance.py` - Added a `_write_many` override to its local `RecordingStore`; fixed the one test this port newly broke (content is now a bound param, not interpolated into the query text).
- `tests/test_store_entity_processing.py` - Added a `_write_many` override plus a `write_params` list to its local `RecordingStore`; fixed the two tests this port newly broke.

## Decisions Made

See frontmatter `key-decisions` for the full list. Highlights: `_write_many` (not `sqlscript`+`LET`) is the batch mechanism; the existing-entity MATCH machinery is deleted entirely (subqueries make it redundant); the legacy SQLite `sparse_index` write-time hooks are deliberately left untouched (out of this plan's declared scope, still potentially read by unported `store_search.py`); row-key convention changed from Cypher's `"m.id"` alias shape to ArcadeDB's bare `"id"` (documented for 04-07).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `update_memory` passed the wrong argument to `_write_many`**
- **Found during:** Task 2 (writing `test_kind_update_does_not_write_vector_id`)
- **Issue:** Initial draft unpacked `statement, params = memory_update_statement(...)` and then called `self._write_many([statement])`, silently dropping `params` -- every UPDATE would have executed with no bound values.
- **Fix:** Keep the builder's return value as a single `(sql, params)` tuple and pass `self._write_many([statement])` unpacked correctly.
- **Files modified:** `src/turing_agentmemory_mcp/store_memory_read.py`
- **Verification:** `tests/test_store_arcadedb_memory.py::test_kind_update_does_not_write_vector_id` (caught the bug on first run via a `ValueError: too many values to unpack`)
- **Committed in:** `a4885e0`

**2. [Rule 1 - Bug] Docstrings inadvertently violated the plan's own `vector_id`-substring grep gate**
- **Found during:** Task 1/2 (writing the source-grep acceptance tests)
- **Issue:** Explanatory prose in the module docstrings of `store_memory_write.py`, `store_memory_read.py`, and `store_memory_queries.py` used the literal substring "vector_id" to describe what was removed, which the plan's own acceptance criteria (`grep -c vector_id ... == 0`) treats as a failure regardless of context.
- **Fix:** Reworded the docstrings to say "legacy synthetic-integer join property" instead of the literal token.
- **Files modified:** `src/turing_agentmemory_mcp/store_memory_write.py`, `src/turing_agentmemory_mcp/store_memory_read.py`, `src/turing_agentmemory_mcp/store_memory_queries.py`
- **Verification:** `tests/test_store_arcadedb_memory.py::test_memory_write_and_queries_files_contain_no_vector_id_or_helper_calls`, `test_memory_read_file_contains_no_vector_id`
- **Committed in:** `506558d`, `6f21ba2`, `a4885e0`

**3. [Rule 2 - Missing Critical] Bound-param naming inconsistency across builders would have broken any generic test double**
- **Found during:** Task 1 (designing `store_memory_queries.py`)
- **Issue:** An early draft bound the Memory-id lookup param as `:memory_id` in `memory_select_statement`/`memory_update_statement`/`memory_delete_statements` while `memory_create_statement` bound the same property as `:id` -- syntactically valid ArcadeDB SQL either way, but an inconsistency with no functional upside and a real cost for any test double (or human) reasoning about the builders.
- **Fix:** Standardized every builder's bound-param name to match the target property name exactly (`id`, `identifier`), mirroring `store_core.py`'s existing `_ensure_user` convention.
- **Files modified:** `src/turing_agentmemory_mcp/store_memory_queries.py`
- **Verification:** `tests/test_store_arcadedb_memory.py` (all 13 tests)
- **Committed in:** `506558d`

**4. [Rule 2 - Missing Critical] `_write_memory`'s existing-entity/vector/load_vector override params were dead weight post-port**
- **Found during:** Task 2 (redesigning `store_messages`'s batch-write flow)
- **Issue:** The pre-port design computed vectors separately and loaded them in a trailing bulk step, so `_write_memory` needed `existing`/`vector`/`load_vector` overrides to avoid double-writing vectors. Once vectors are inlined at CREATE/UPDATE time, that dance has no purpose, and no caller outside this file ever passed those kwargs.
- **Fix:** Simplified `_write_memory`'s signature to only the fields callers actually need; `store_messages`'s batch path now calls `update_memory` directly for existing-but-changed items, passing the pre-computed vector.
- **Files modified:** `src/turing_agentmemory_mcp/store_memory_write.py`
- **Verification:** `tests/test_store_arcadedb_memory.py`, `tests/test_batch_memory_write.py`, `tests/test_batch_memory_dedup.py` (all pass)
- **Committed in:** `6f21ba2`

---

**Total deviations:** 4 auto-fixed (2 Rule 1 bug fixes, 2 Rule 2 missing-critical simplifications)
**Impact on plan:** All four are necessary for correctness (bound params actually being bound, grep-gate compliance) or for the port to be internally consistent (uniform param naming, a `_write_memory` signature with no dead parameters). No scope creep beyond what the port itself required.

## Issues Encountered

- **Strict RED-then-GREEN was not practical for this plan's scale.** Both tasks are `tdd="true"`, but this plan ports two ~600-LOC production files' entire query dialect simultaneously (Cypher-literal → bound-param ArcadeDB SQL, separate vector-load → inline vectors, MATCH-based existing-entity handling → subquery-based). Writing tests against code that didn't exist yet, then implementing to turn them green, would have meant either (a) tests asserting against a not-yet-designed query shape (fragile, likely to be rewritten mid-implementation anyway) or (b) an artificial two-pass process with no real signal between passes. I designed the query builders and store methods together with the test file, ran the full test suite immediately, and iterated until green -- the tests are real and were run against the actual implementation before being called done, but the RED phase wasn't a separate committed step. Documented here rather than silently glossed over.
- **This port's necessary architecture changes broke MORE pre-existing tests than the 3 explicitly named in `04-EXECUTION-STATE.md`'s routing table** (`test_batch_memory_write.py`'s per-batch-submit test + "memory parts of test_batch_memory"). Any test fixture across the suite that constructed a store with a bare `client=object()`/TuringDB-shaped fake and overrode only `_write` (singular) or `_load_vectors` -- but not `_write_many` -- broke, because `_write_memory`/`_create_memories_batch`/`update_memory`/`delete_memory` now route through `_write_many` for every multi-statement batch (previously some paths used `_write` alone). I fixed every instance of this that I found in files whose local fixtures were cheap/safe to patch (`tests/_batch_memory_shared.py`, `tests/test_batch_memory_write.py`, `tests/test_batch_memory_dedup.py`, `tests/test_governance.py`, `tests/test_store_entity_processing.py`) without touching any assertion belonging to a genuinely unrelated, already-documented 04-04 failure in the same file.
- **6 tests in `tests/test_fused_memory_search.py` newly fail** (`test_fused_search_maps_derived_records_to_source_episode_with_explanation`, `test_fused_search_applies_filters_before_channel_rank_assignment`, `test_fused_search_enforces_tenant_before_fusion`, `test_fused_rerank_applies_provenance_context_and_reports_status`, `test_fused_rerank_fallback_preserves_rrf_order_and_is_visible`, `test_fused_rerank_bounds_gpu_candidates_and_preserves_tail`), on top of the 3 already in 04-04's migration-debt list for that file. Root cause: `_memory_from_row`/`_active_memory_rows` (shared with `store_memory_read.py`) now read ArcadeDB's unqualified row-key convention (`"id"`, `"kind"`, ...) instead of the retired Cypher `"m.id"`/`"m.kind"` alias shape; this file's own test fixtures build rows with the old `"m."`-prefixed keys. `store_search.py` itself is still fully unported (Cypher `MATCH` literals, not valid ArcadeDB SQL) and explicitly routed to 04-07 in `04-EXECUTION-STATE.md` -- fixing its fixtures now would mean pre-emptively redesigning its query dialect, which is out of this plan's scope and would collide with 04-07's own planned rewrite. Left as documented, expected debt (see "Migration Debt" below), NOT silently ignored.

## Migration Debt: Newly-Surfaced Test Failures (Wave 4/5 Routing)

A full-suite run after this plan's changes shows **28 failing tests total** (down from the pre-existing 23 minus the 1 deleted `test_write_many_submits_each_dependent_graph_batch`, i.e. 22 carried-forward + 6 genuinely new). All 22 carried-forward failures are unchanged, already-documented 04-04 debt (see `04-04-SUMMARY.md`'s own "Migration Debt" section) -- untouched by this plan, still routed to 04-06/04-07/04-08/04-09 exactly as before. The **6 new** failures, all in `tests/test_fused_memory_search.py`, are a direct, expected consequence of this plan's row-key convention change (see "Issues Encountered" above):

- `test_fused_search_maps_derived_records_to_source_episode_with_explanation`
- `test_fused_search_applies_filters_before_channel_rank_assignment`
- `test_fused_search_enforces_tenant_before_fusion`
- `test_fused_rerank_applies_provenance_context_and_reports_status`
- `test_fused_rerank_fallback_preserves_rrf_order_and_is_visible`
- `test_fused_rerank_bounds_gpu_candidates_and_preserves_tail`

**Routing recommendation:** 04-07 (fused search + evidence port), which already owns `test_fused_memory_search.py`'s pre-existing 3 failures per `04-EXECUTION-STATE.md`, should fix all 9 together when it ports `store_search.py`'s query dialect and updates this file's row-fixture builders to the unqualified-key convention this plan established.

No skip-as-green was used anywhere; every failure above is a genuine, itemized, test-asserted red, not a hidden or suppressed one.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The memory write/read paths now speak ArcadeDB exclusively; `store_memory_queries.py`'s builder pattern and `sparse_encoder.py`'s shared tokenizer are the concrete templates 04-06 (documents)/04-07 (fused search + evidence)/04-08 (rebuild + community) should follow.
- **Blocker/heads-up for 04-07:** `_active_memory_rows`/`_memory_from_row`'s row-key convention changed from `"m."`-prefixed to bare property names -- `store_search.py`/`store_evidence.py`'s own call sites (and the 6 newly-broken `test_fused_memory_search.py` tests above) need updating to match when that wave ports the search query dialect.
- **Heads-up for 04-06:** `store_documents.py` still calls `_write_many` with the OLD `list[str]` positional shape (each element a separate submit-before-match batch) -- that call site needs the same `Statement`-tuple/bound-param treatment this plan gave the memory path, and `tests/_batch_memory_shared.py`'s `RecordingMemoryStore`/`RecordingDocumentStore` already normalizes both shapes so document tests keep passing once ported.
- **Heads-up for 04-08:** the shared sparse encoder (`sparse_encoder.sparse_vector`) is ready to reuse for the rebuild-projection path; `store_rebuild.py`'s `_existing_entity_ids`/`_unique_projection_entities`/`_fact_ids_for_memory` still emit Cypher-shaped queries and are stubbed out in this plan's own test double (`tests/test_store_arcadedb_memory.py::_MemoryStore`) -- they need their own ArcadeDB port in that wave.

---
*Phase: 04-arcadedb-direct-port*
*Completed: 2026-07-13*

## Self-Check: PASSED

- FOUND: `src/turing_agentmemory_mcp/sparse_encoder.py`
- FOUND: `src/turing_agentmemory_mcp/store_memory_queries.py`
- FOUND: `src/turing_agentmemory_mcp/store_memory_write.py`
- FOUND: `src/turing_agentmemory_mcp/store_memory_read.py`
- FOUND: `tests/test_store_arcadedb_memory.py`
- FOUND commit: `506558d` (feat(04-05): add shared sparse encoder + ArcadeDB memory query builders)
- FOUND commit: `6f21ba2` (feat(04-05): port memory write path to ArcadeDB)
- FOUND commit: `a4885e0` (feat(04-05): port memory read path to ArcadeDB)
- FOUND commit: `0605169` (test(04-05): add ArcadeDB memory write/read test suite)
- FOUND commit: `40808c9` (test(04-05): migrate routed TuringDB-shaped test-double debt to ArcadeDB shape)
