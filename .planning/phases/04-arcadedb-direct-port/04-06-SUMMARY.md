---
phase: 04-arcadedb-direct-port
plan: 06
subsystem: database
tags: [arcadedb, documents, chunking, hnsw, lucene, both-channels, bound-params, transactions]

# Dependency graph
requires:
  - phase: 04-arcadedb-direct-port (04-04)
    provides: "store_core.py's _query/_write_many ArcadeDB seam (D-08 single managed transaction), probe-driven readiness"
  - phase: 04-arcadedb-direct-port (04-03)
    provides: "arcadedb_schema.bootstrap idempotent DDL (Chunk LSM_VECTOR + LSM_SPARSE_VECTOR + FULL_TEXT(text) channels, UNIQUE stable_id index)"
  - phase: 04-arcadedb-direct-port (04-05)
    provides: "sparse_encoder.sparse_vector() shared both-channels lexical encoder; store_memory_queries.py Statement builder convention; bare-key row convention"
provides:
  - "store_documents.py/store_chunking.py ported to bound-param ArcadeDB SQL -- no vector_id, no separate CSV vector-load step, no byte-budget batch splitter (ARC-05)"
  - "src/turing_agentmemory_mcp/store_documents_queries.py -- extracted Statement builders for Document/Chunk CREATE, HAS_DOCUMENT/HAS_CHUNK/NEXT_CHUNK edges, NEXT_CHUNK context traversal, and the two document-search channels (vectorNeighbors + SEARCH_INDEX)"
  - "document search runs native HNSW + native Lucene full-text as two bound, tenant-scoped channels with adaptive over-fetch (D-03), replacing the old full active-chunk-rows table scan"
  - "tests/test_store_arcadedb_documents.py -- 11 tests against a fake ArcadeDBClient, no live container needed"
affects: [04-07, 04-08, 04-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "store_documents_queries.py Statement = tuple[str, dict[str, object]] builder convention, mirroring store_memory_queries.py (04-05) -- one function per DDL/DML/search shape"
    - "escape_lucene_query(text) -- backslash-escapes Lucene reserved characters before SEARCH_INDEX, neutralizing the spike-documented IndexException risk (unescaped '?', '*', '(', ')', ...)"
    - "chunk_id = stable_id('chunk', user_identifier, document_id, str(ordinal)) -- deterministic, tenant-scoped, ARC-08 canonical identifier; Chunk's own 'id' property IS the chunk_id (no separate synthetic-integer join property)"
    - "Document search channels: chunk_vector_search_statement (vectorNeighbors over-fetch-then-filter, D-03) + chunk_lucene_search_statement (SEARCH_INDEX on Chunk[text]) merged by chunk_id into one candidate pool, scored by the existing hybrid.py blend_hybrid_score/lexical_score (unchanged Python math) -- replaces the old full active-chunk-rows table scan fallback"

key-files:
  created:
    - src/turing_agentmemory_mcp/store_documents_queries.py
    - tests/test_store_arcadedb_documents.py
  modified:
    - src/turing_agentmemory_mcp/store_documents.py
    - src/turing_agentmemory_mcp/store_chunking.py
    - src/turing_agentmemory_mcp/store_memory_read.py
    - tests/test_batch_memory_write.py
    - tests/test_governance.py
    - tests/test_observability.py
    - tests/test_retrieval_filters.py
    - tests/test_store_entity_processing.py

key-decisions:
  - "_write_many (flat Statement list), not sqlscript+LET -- the plan body's pre-spike wording said sqlscript+LET, but 04-EXECUTION-STATE.md/04-05's precedent settle on _write_many as the batch mechanism for ALL Wave-4 mixins; _create_document builds one flat list of (sql, params) Statements (document + edge + N chunks + N HAS_CHUNK + (N-1) NEXT_CHUNK) committed in ONE managed transaction, with read-your-writes across the whole batch (04-04 seam) making a script-variable mechanism unnecessary."
  - "Deleted the entire byte-budget batch splitter (_document_graph_queries/_document_chunk_batch_query/_DocumentChunkGraphUnit) rather than porting it -- it solved TuringDB's submit-before-match visibility gap (invariant #4, retired), which does not exist under D-08's single managed transaction (store_core.py's own docstring already says as much); document_graph_batch_chunks/document_graph_batch_bytes remain defined in store_core.py (unmodified, out of scope) but store_documents.py no longer consumes them."
  - "Document search drops _ensure_tenant_vector_index/_ensure_schema entirely (matching 04-05's memory-port precedent) -- ArcadeDB's Chunk[embedding]/Chunk[text] indexes are global Type-level channels filtered by user_identifier, not a per-tenant named index requiring a lazy-create call. This also incidentally fixed a pre-existing test failure (schema bootstrap called against fake test clients lacking .command())."
  - "Lexical channel for THIS plan's simpler document-search blend is native Lucene SEARCH_INDEX only (not LSM_SPARSE_VECTOR) -- the both-channels decision's SECOND lexical channel (sparseNeighbors) feeds the full weighted-RRF fusion, which is store_search.py's territory (04-07, unported). Document search keeps its existing simpler hybrid.py blend_hybrid_score/lexical_score math unchanged; only the channel INFRASTRUCTURE changed (native HNSW + native Lucene candidate-fetch replacing a Cypher VECTOR SEARCH + a full active-chunk-rows scan), not the scoring formula."
  - "_row_matches_metadata_filters (store_memory_read.py, shared mixin) gained a prefix=\"\" default -- ArcadeDB's bare unqualified row-key convention (04-05) needs no dot-prefix; a non-empty prefix is kept for backward compatibility with any still-unported \"prefix\"-style caller (there are none left after this plan; store_search.py doesn't call this helper)."

patterns-established:
  - "Statement builder functions in a *_queries.py sibling module (Statement = tuple[str, dict]) consumed as a flat list by _write_many -- the LOC-budget escape hatch, now established for BOTH store_memory_queries.py (04-05) and store_documents_queries.py (04-06)."
  - "Native-channel document/entity search shape: an over-fetch-then-filter vector query (D-03) plus a second native lexical-channel query, merged by stable identifier into one candidate pool before the existing Python blend/rerank math runs -- the template 04-07 should follow for memory search's own RRF channel-building."

requirements-completed: [ARC-04, ARC-05, ARC-06, PERF-01]

coverage:
  - id: D1
    description: "Document ingest CREATEs a Document + Chunk vertices + HAS_CHUNK/NEXT_CHUNK edges in one managed transaction via _write_many, with chunk embeddings inline and stable_id ids"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_documents.py#test_ingest_document_creates_document_and_chunks_in_one_managed_transaction"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_documents.py#test_chunk_id_is_stable_id_with_inline_embedding_and_no_vector_id"
        status: pass
    human_judgment: false
  - id: D2
    description: "Re-ingesting the same title+text is deduped by hash (existing document returned, not duplicated)"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_documents.py#test_reingesting_same_title_and_text_dedupes_by_hash"
        status: pass
    human_judgment: false
  - id: D3
    description: "_chunk_context(chunk_id) resolves NEXT_CHUNK neighbors by chunk_id graph traversal, not vector_id"
    requirement: "ARC-05"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_documents.py#test_chunk_context_resolves_next_chunk_neighbor_by_chunk_id"
        status: pass
    human_judgment: false
  - id: D4
    description: "Document ingest/search fail closed on empty user_identifier and are tenant-scoped (ingest, get_document, search_documents)"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_documents.py#test_ingest_with_empty_user_identifier_raises_value_error"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_documents.py#test_tenant_scoped_get_document_never_returns_other_tenants_document"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_documents.py#test_document_search_tenant_scoped_never_returns_other_tenants_chunks"
        status: pass
    human_judgment: false
  - id: D5
    description: "Document search runs native HNSW vector search AND native Lucene full-text, keeping the adaptive over-fetch-then-filter default (D-03), with no vector_id join"
    requirement: "ARC-06"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_documents.py#test_document_search_returns_hits_ordered_by_native_vector_score"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_documents.py#test_document_search_applies_adaptive_overfetch_multiplier"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_documents.py#test_document_search_matches_via_native_lucene_full_text"
        status: pass
    human_judgment: false
  - id: D6
    description: "Chunk embeddings are computed in one batched round-trip (PERF-01)"
    requirement: "PERF-01"
    verification:
      - kind: unit
        ref: "tests/test_batch_memory_write.py#test_ingest_document_text_batches_chunk_embeddings_and_writes_inline_vectors"
        status: pass
    human_judgment: false

# Metrics
duration: 45min
completed: 2026-07-14
status: complete
---

# Phase 04 Plan 06: Document ArcadeDB Port Summary

**Ported document ingest/chunking/search to ArcadeDB: one-managed-transaction chunk writes with inline dense+sparse-lexical vectors keyed on `stable_id`, and native HNSW + Lucene full-text search channels replacing the old Cypher `VECTOR SEARCH` join plus a full active-chunk table scan.**

## Performance

- **Duration:** ~45 min
- **Completed:** 2026-07-14
- **Tasks:** 2 (both TDD; implemented together with the accompanying test file rather than strict RED-then-GREEN, given the plan's scale -- see "Issues Encountered", same rationale 04-05 documented)
- **Files modified:** 8 (store_documents.py, store_chunking.py, store_memory_read.py, tests/test_batch_memory_write.py, tests/test_governance.py, tests/test_observability.py, tests/test_retrieval_filters.py, tests/test_store_entity_processing.py); 2 created (store_documents_queries.py, tests/test_store_arcadedb_documents.py)

## Accomplishments

- **`src/turing_agentmemory_mcp/store_documents_queries.py`** (NEW) -- bound-param ArcadeDB `Statement` builders for Document/Chunk `CREATE`, `HAS_DOCUMENT`/`HAS_CHUNK`/`NEXT_CHUNK` edges, `SELECT`/`UPDATE` (get/metadata-update/soft-delete), `NEXT_CHUNK` graph-traversal context, and the two document-search channels: `chunk_vector_search_statement` (native `vectorNeighbors` HNSW, D-03 over-fetch-then-filter) and `chunk_lucene_search_statement` (native `SEARCH_INDEX` full-text on `Chunk[text]`, with `escape_lucene_query` neutralizing the spike-documented `IndexException` risk from unescaped `?`/`*`/`(`/`)`).
- **`store_documents.py`** ported: `_create_document` builds ONE flat `Statement` list (Document + N Chunks + HAS_CHUNK + NEXT_CHUNK edges) committed via `store_core.py`'s `_write_many` (D-08 single managed transaction) -- the entire TuringDB-shaped byte-budget batch splitter (`_document_graph_queries`/`_document_chunk_batch_query`/`_DocumentChunkGraphUnit`) is deleted, since D-08's read-your-writes transaction has no submit-before-match visibility gap to work around. Every Chunk's `id` is `stable_id("chunk", user_identifier, document_id, str(ordinal))` (ARC-08); the dense `embedding` and both lexical channels (`lexical_tokens`/`lexical_weights`, reusing 04-05's `sparse_encoder.sparse_vector` verbatim) are inline record properties -- no legacy synthetic-integer join property, no separate CSV vector-load step (ARC-05). `search_documents` now queries native HNSW + native Lucene as two bound, tenant-scoped channels merged by chunk id, keeping the existing `hybrid.py` `blend_hybrid_score`/`lexical_score` Python math unchanged -- this replaces the old full active-chunk-rows table scan the module used as its lexical fallback (the Section 1.3 full-scan the port fixes for free).
- **`store_chunking.py`** ported: `_chunk_context(chunk_id)` resolves `NEXT_CHUNK` neighbors by `chunk_id` traversal (no `vector_id` int parameter); `_document_from_row` reads ArcadeDB's bare row-key convention (`"id"`, `"chunk_count"`, ...), matching 04-05's precedent; `_active_chunk_rows`/`_document_chunk_batch_query` are deleted (dead code once the byte-budget splitter and the full-scan fallback are gone).
- **`store_memory_read.py`**: `_row_matches_metadata_filters` gained a `prefix=""` bare-key default (backward compatible for any non-empty-prefix caller, of which none remain after this plan) so `store_documents.py`'s new bare-key rows can reuse this shared helper without duplicating it.
- **`tests/test_store_arcadedb_documents.py`** (NEW) -- 11 tests against a small session-aware fake `ArcadeDBClient` extended to interpret `vectorNeighbors(...)`, `SEARCH_INDEX(...)`, and `out('NEXT_CHUNK')` well enough to round-trip real statements (no live container), covering both tasks' full `must_haves`/acceptance criteria.
- **Test-migration debt, as routed by `04-EXECUTION-STATE.md` plus two tests this plan's own port newly broke:** migrated document-search parts of `test_retrieval_filters.py`, ingest-span parts of `test_observability.py`, document-expiry parts of `test_governance.py`, and the document tests in `test_batch_memory_write.py`/`test_store_entity_processing.py` that this port's inline-vector/bound-param shape broke.

## Task Commits

1. **Port document ingest/chunking/search to ArcadeDB (Tasks 1+2)** - `e6fde74` (feat)
2. **Add ArcadeDB document write/search test suite** - `c97b4f2` (test)
3. **Migrate routed TuringDB-shaped test-double debt to ArcadeDB shape** - `e5d5a85` (test)

**Plan metadata:** (this commit, pending)

## Files Created/Modified

- `src/turing_agentmemory_mcp/store_documents_queries.py` - NEW: bound-param `Statement` builders for document/chunk write, read/update/delete, and the two search channels; `escape_lucene_query`.
- `src/turing_agentmemory_mcp/store_documents.py` - Ported `ingest_document_text`/`_create_document`/`_update_document_metadata`/`delete_document`/`get_document`/`search_documents` to ArcadeDB; deleted the byte-budget batch splitter.
- `src/turing_agentmemory_mcp/store_chunking.py` - Ported `_chunk_context`/`_document_from_row` to bare-key/`chunk_id` convention; deleted `_active_chunk_rows`/`_document_chunk_batch_query`.
- `src/turing_agentmemory_mcp/store_memory_read.py` - `_row_matches_metadata_filters` gained a `prefix=""` bare-key default.
- `tests/test_store_arcadedb_documents.py` - NEW: 11 tests, fake `ArcadeDBClient`, no live container.
- `tests/test_batch_memory_write.py` - Rewrote the chunk-embedding test for inline vectors; deleted the byte-budget-splitter test (behavior retired).
- `tests/test_governance.py` - `QueryClient` gained the ArcadeDB client surface; the two document tests assert bound params / bare-key chunk rows.
- `tests/test_observability.py` - `QueryRecordingClient` gained the ArcadeDB client surface; the ingest-span test asserts `embed`/inline-embedding params instead of the retired `vector.load` span.
- `tests/test_retrieval_filters.py` - Added `DocumentFilterStore` (bare-key chunk rows); deleted the two `_chunk_context` "unknown edge type" tests (retired behavior).
- `tests/test_store_entity_processing.py` - The document-ingest test now asserts chunk text in bound params, not the query text.

## Decisions Made

See frontmatter `key-decisions` for the full list. Highlights: `_write_many` (flat `Statement` list), not `sqlscript`+`LET`, is the batch mechanism (overriding the plan body's stale pre-spike wording, per 04-EXECUTION-STATE.md/04-05's precedent); the TuringDB byte-budget batch splitter is deleted entirely, not ported; document search drops per-tenant vector-index lazy-create calls (matching 04-05); the both-channels lexical decision's second channel (`LSM_SPARSE_VECTOR`) stays reserved for 04-07's full RRF fusion -- this plan's simpler document-search blend keeps native Lucene as its one lexical channel.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Docstring inadvertently violated the plan's own `vector_id`-substring grep gate**
- **Found during:** writing the source-grep acceptance test
- **Issue:** Explanatory prose in `store_documents.py`/`store_chunking.py`'s inline comments used the literal substring "vector_id" to describe what was removed, which the plan's own acceptance criteria (`grep -cE "vector_id|..."` == 0) treats as a failure regardless of context -- the exact same pitfall 04-05 hit and documented.
- **Fix:** Reworded to "legacy synthetic-integer join property"/"parameter".
- **Files modified:** `src/turing_agentmemory_mcp/store_documents.py`, `src/turing_agentmemory_mcp/store_chunking.py`
- **Verification:** `tests/test_store_arcadedb_documents.py::test_document_files_contain_no_vector_id_or_helper_calls`
- **Committed in:** `e6fde74`

**2. [Rule 3 - Blocking] `_row_matches_metadata_filters` (shared helper) needed a bare-key mode to be reusable from the ported document search**
- **Found during:** designing `search_documents`'s metadata-filter call
- **Issue:** The pre-existing helper (in `store_memory_read.py`, out of this plan's declared `files_modified`) required a non-empty `prefix` producing `"{prefix}.{name}"`-shaped lookup keys (the retired Cypher alias convention) -- ArcadeDB's bare-key rows have no such prefix, and the only other caller of this helper (`store_documents.py`, this same plan) needed the bare form.
- **Fix:** Added a `prefix=""` default that skips the dot-prefix when empty, backward compatible for any non-empty-prefix caller (none remain after this plan; verified `store_search.py` does not call this helper).
- **Files modified:** `src/turing_agentmemory_mcp/store_memory_read.py`
- **Verification:** `tests/test_store_arcadedb_documents.py` (search-filter path exercised indirectly via `search_documents`), `tests/test_retrieval_filters.py::test_document_search_filters_by_source_tags_and_updated_range`
- **Committed in:** `e6fde74`

---

**Total deviations:** 2 auto-fixed (1 Rule 1 grep-gate wording fix, 1 Rule 3 shared-helper compatibility fix)
**Impact on plan:** Both are necessary for the port to be internally consistent and for the plan's own acceptance criteria to be met. No scope creep beyond what the port itself required.

## Issues Encountered

- **Strict RED-then-GREEN was not practical for this plan's scale**, same as 04-05: both tasks are `tdd="true"` but port an entire query dialect (Cypher-literal + byte-budget-batched multi-node CREATE + `VECTOR SEARCH ... MATCH` join → bound-param ArcadeDB SQL, single-transaction `Statement` list, native `vectorNeighbors`/`SEARCH_INDEX` channels) simultaneously across `store_documents.py`/`store_chunking.py`/`store_documents_queries.py`. I designed the query builders and store methods together with the test file, ran the suite immediately, and iterated to green -- documented here rather than silently glossed over.
- **This port's necessary architecture changes broke 5 pre-existing tests beyond the ones explicitly named in `04-EXECUTION-STATE.md`'s routing table**: two document tests in `test_batch_memory_write.py` (inline-vector shape, and the now-retired byte-budget-splitter test), two `_chunk_context` tests in `test_retrieval_filters.py` (retired "unknown edge type" exception-swallowing), and one document-ingest test in `test_store_entity_processing.py` (bound params vs. interpolated content). Fixed/migrated all 5 in the same wave as the explicitly routed debt -- see "test-migration debt" in Accomplishments and the SUMMARY's dedicated migration commit.
- **Full-suite delta verified precisely against a pre-change baseline** (via `git stash`): 28 pre-existing failures before this plan's changes → 24 after. All 24 remaining failures are exactly the already-documented 04-04 debt still routed to 04-07 (`test_fused_memory_search.py`'s 9, memory-search parts of `test_governance.py`/`test_observability.py`/`test_retrieval_filters.py`), 04-08 (`test_batch_memory.py`'s 2 rebuild tests, `test_community_detection.py`), and 04-09 (`test_runtime_pipeline.py`'s 6, `test_store_entity_processing.py`'s `_ensure_graph_loaded` test). Zero new regressions, zero skip-as-green.

## Migration Debt: Confirmed Unchanged (Wave 4/5 Routing)

The full test suite carries forward exactly the 24 failures 04-05's own migration-debt list would predict for the remaining unported mixins, all still correctly routed:

- **04-07 (fused search + evidence):** `test_fused_memory_search.py` (9), memory-search parts of `test_governance.py`/`test_observability.py`/`test_retrieval_filters.py` (5) -- `store_search.py`/`store_evidence.py` are still Cypher-shaped and out of this plan's scope.
- **04-08 (rebuild + community):** `test_batch_memory.py`'s 2 rebuild-projection tests, `test_community_detection.py`'s 1 -- `store_rebuild.py` is still Cypher-shaped.
- **04-09 (close the port):** `test_runtime_pipeline.py`'s 6 (`store_from_env` now builds `ArcadeDBClient`), `test_store_entity_processing.py`'s `_ensure_graph_loaded` test (method retired in 04-04).

No skip-as-green was used anywhere; every failure above is a genuine, itemized, pre-existing test-asserted red, not a hidden or suppressed one.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Document ingest/chunking/search now speaks ArcadeDB exclusively; `store_documents_queries.py`'s builder pattern and the native-HNSW-plus-native-lexical-channel merge pattern established here are concrete templates 04-07 (fused search + evidence) should follow when it ports `store_search.py`'s per-channel query builders (dense/BM25/graph/community) into its own RRF fusion.
- **Heads-up for 04-07:** the both-channels lexical decision's SECOND channel (`vector.sparseNeighbors` over `LSM_SPARSE_VECTOR`) is still unconsumed for documents -- this plan's `search_documents` only uses native Lucene as its one lexical channel (preserving the existing simpler `blend_hybrid_score` math). If 04-07's full weighted-RRF wants a sparse-vector channel for documents too (mirroring what it will build for memory), that channel wiring is still open work, not done here.
- **Heads-up for 04-08:** `store_rebuild.py`'s canonical-vector-record rebuild path (`_canonical_vector_records`, `test_batch_memory.py::test_canonical_vector_records_use_active_document_chunk_text`) still expects the OLD Cypher-shaped `"c."`-prefixed chunk rows and the retired `_document_vector_id`-keyed vector rebuild -- it needs its own ArcadeDB port in that wave, now that `store_documents.py`/`store_chunking.py`'s row shape has changed underneath it.
- **Heads-up for 04-09:** `store_core.py`'s `document_graph_batch_chunks`/`document_graph_batch_bytes` config knobs are no longer consumed by `store_documents.py` (the byte-budget batch splitter they served is deleted) -- consider whether to retire them from `store_core.py`/`server.py`'s env wiring or repurpose them, during the close-the-port consolidation wave.

---
*Phase: 04-arcadedb-direct-port*
*Completed: 2026-07-14*

## Self-Check: PASSED

- FOUND: `src/turing_agentmemory_mcp/store_documents_queries.py`
- FOUND: `src/turing_agentmemory_mcp/store_documents.py`
- FOUND: `src/turing_agentmemory_mcp/store_chunking.py`
- FOUND: `tests/test_store_arcadedb_documents.py`
- FOUND commit: `e6fde74` (feat(04-06): port document ingest/chunking/search to ArcadeDB)
- FOUND commit: `c97b4f2` (test(04-06): add ArcadeDB document write/search test suite)
- FOUND commit: `e5d5a85` (test(04-06): migrate routed TuringDB-shaped test-double debt to ArcadeDB shape)
