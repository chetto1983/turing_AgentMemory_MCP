---
phase: 04-arcadedb-direct-port
plan: 04
subsystem: database
tags: [arcadedb, turingdb-migration, mvcc, transactions, readiness-probe, health, docker-compose]

# Dependency graph
requires:
  - phase: 04-arcadedb-direct-port (04-02)
    provides: ArcadeDBClient (query/command/sqlscript/begin/commit/rollback/run_in_transaction/is_ready/ensure_database)
  - phase: 04-arcadedb-direct-port (04-03)
    provides: arcadedb_schema.bootstrap + versioned_vector_index idempotent DDL
provides:
  - "store_core.py's _query/_write/_write_many seam ported from TuringDB to ArcadeDB"
  - "_write_many as one managed begin/command/commit-retry-N transaction (D-08) with read-your-writes"
  - "_ensure_user binding user_identifier as a bound param (injection surface closed, T-04-04-01/02)"
  - "probe-driven readiness (D-10): bootstrap()/reconnect()/runtime_status() wired to arcadedb_client.is_ready()"
  - "/health gating on a live probe instead of a boot-time latch"
  - "FTS5 outbox initialize()/replay() retired from bootstrap() (ARC-06)"
  - "store_from_env() building ArcadeDBClient.from_env() (ARC-02); compose.yaml/.env.example carry ARCADEDB_* additively"
affects: [04-05, 04-06, 04-07, 04-08, 04-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_write_many(statements: list[tuple[str, params]]) single managed transaction via ArcadeDBClient.run_in_transaction, replacing per-batch submit-before-match"
    - "bound-param queries (params=dict) replacing quote()-interpolated string literals in the seam"
    - "_ensure_schema() memoized delegate to arcadedb_schema.bootstrap() replacing per-name CREATE VECTOR INDEX DDL"
    - "_refresh_graph_readiness() re-probe on every runtime_status()/bootstrap()/reconnect() call, no boot-time latch"

key-files:
  created:
    - tests/test_store_arcadedb_core.py
  modified:
    - src/turing_agentmemory_mcp/store_core.py
    - src/turing_agentmemory_mcp/server.py
    - compose.yaml

key-decisions:
  - "_write_many's signature changed from list[str] to list[tuple[str, dict|None]] so every statement can bind its own params -- a deliberate forward-contract break for Wave 4 mixins, not a compat shim, since D-08 requires bound params end-to-end"
  - "_ensure_vector_index/_ensure_tenant_vector_index kept as back-compat shims delegating to _ensure_schema()/versioned_vector_index rather than deleted outright, so unported Wave-4 mixin call sites don't AttributeError immediately (though their query dialect still needs porting)"
  - "load_graph_after_restart renamed to reconnect() (grep-gate requires zero 'load_graph' substring matches in the readiness path per the plan's own acceptance criteria)"
  - "_records rewritten to accept ArcadeDBClient's plain list[dict] instead of assuming a pandas DataFrame (.to_dict('records')) -- a Rule 1 bug fix surfaced by the port, not a new design"

patterns-established:
  - "Session-header single-transaction write batches: begin() once, N command() calls sharing one session_id, commit() once -- read-your-writes confirmed by the 04-02 spike, not sqlscript LET-chaining"
  - "Readiness re-probes on every runtime_status() call rather than latching a boot-time flag, per D-10"

requirements-completed: [ARC-04, ARC-02, ARC-06]

coverage:
  - id: D1
    description: "store_core's _query/_write/_write_many route through arcadedb_client with bound params; no TuringDB primitives (new_change/CHANGE SUBMIT/checkout/LOAD VECTOR/turingdb import) remain in the seam"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_query_delegates_to_client_inside_arcadedb_query_span"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_seam_contains_no_turingdb_write_primitives_or_csv_vector_load"
        status: pass
    human_judgment: false
  - id: D2
    description: "_write_many opens one managed begin/command/commit-retry-N transaction (D-08) with read-your-writes across statements in the same batch, not per-batch submit-before-match"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_write_many_opens_one_managed_transaction_and_commits_once"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_write_many_read_your_writes_within_same_transaction"
        status: pass
    human_judgment: false
  - id: D3
    description: "_ensure_user binds user_identifier as a bound param; a value containing a single quote does not corrupt the query text (T-04-04-01/02 tenant-isolation mitigation)"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_ensure_user_binds_identifier_as_param_not_a_string_literal"
        status: pass
    human_judgment: false
  - id: D4
    description: "No CSV vector-load mechanism remains (_load_vectors deleted; vectors are written inline as record properties)"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_no_csv_vector_load_mechanism_remains"
        status: pass
    human_judgment: false
  - id: D5
    description: "Readiness is a real arcadedb_client.is_ready() probe wired into RuntimeSignals' graph stage; reconnect() re-probes without a load_graph call; a transient failure then recovery flips the stage back to ready"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_bootstrap_sets_graph_ready_when_probe_succeeds"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_bootstrap_leaves_graph_not_ready_when_probe_fails"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_reconnect_reprobe_recovers_readiness_after_transient_failure"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_readiness_path_has_no_load_graph_or_bare_exception_swallow"
        status: pass
    human_judgment: false
  - id: D6
    description: "/health returns 503/degraded when the graph stage is not ready and 200/ok once the probe recovers -- a live gate, not a boot-time latch"
    requirement: "ARC-04"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_health_returns_503_when_not_ready_and_200_once_probe_recovers"
        status: pass
    human_judgment: false
  - id: D7
    description: "bootstrap() no longer replays the FTS5 outbox (sparse_index.initialize()/replay() calls retired, ARC-06)"
    requirement: "ARC-06"
    verification:
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_bootstrap_does_not_replay_fts5_outbox"
        status: pass
      - kind: unit
        ref: "tests/test_store_arcadedb_core.py#test_sparse_outbox_replay_calls_absent_from_source"
        status: pass
    human_judgment: false
  - id: D8
    description: "store_from_env() constructs ArcadeDBClient.from_env(); compose.yaml/.env.example carry ARCADEDB_* env additively alongside retained TURINGDB_* vars; turingdb service and turingdb==1.35 dependency untouched"
    requirement: "ARC-02"
    verification:
      - kind: automated_ui
        ref: "docker compose config --quiet"
        status: pass
      - kind: unit
        ref: "tests/test_compose_config.py (19 tests, unchanged)"
        status: pass
      - kind: unit
        ref: "tests/test_docker_hardening.py (unchanged)"
        status: pass
    human_judgment: false

# Metrics
duration: 35min
completed: 2026-07-13
status: complete
---

# Phase 04 Plan 04: ArcadeDB store_core Seam Port Summary

**Ported the store_core choke point (`_query`/`_write`/`_write_many`/bootstrap/readiness) from TuringDB to ArcadeDB: single managed begin/command/commit-retry-N transactions with read-your-writes (D-08), bound-param tenant scoping, probe-driven `/health` (D-10), and an ArcadeDB-backed `store_from_env()` (ARC-02).**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-07-13
- **Tasks:** 3 (Tasks 1-2 TDD: RED→GREEN each; Task 3 non-TDD)
- **Files modified:** 3 (store_core.py, server.py, compose.yaml); 1 created (tests/test_store_arcadedb_core.py)

## Accomplishments

- `_query`/`_write`/`_write_many` route through `ArcadeDBClient` instead of TuringDB; `_write_many` collapses to ONE managed `begin`/`command`(s)/`commit-retry-N` transaction via `run_in_transaction`, replacing the per-batch submit-before-match loop (invariant #4, retired) — read-your-writes is confirmed across every statement in the same batch via the spike-confirmed session-header model.
- `_ensure_user` binds `user_identifier` as a bound param instead of `quote()`-interpolating it into the query text — closes the T-04-04-01/02 injection surface; a value containing a single quote cannot corrupt or escape the query.
- `_ensure_vector_index`/`_ensure_tenant_vector_index` now delegate to `arcadedb_schema.bootstrap`/`versioned_vector_index` (04-03) instead of an inline `CREATE VECTOR INDEX ... METRIC COSINE` DDL string that was TuringDB syntax.
- The CSV-file vector-load mechanism (`_load_vectors`) is deleted entirely — ArcadeDB stores vectors inline as record properties, no separate load step.
- Readiness is a real `arcadedb_client.is_ready()` probe wired into `RuntimeSignals`' `"graph"` stage (`_refresh_graph_readiness`), re-evaluated on every `bootstrap()`/`reconnect()`/`runtime_status()` call — `/health` reflects live reachability instead of a boot-time latch, returning 503 when down and 200 once the probe recovers, with no manual reconnect step.
- `bootstrap()` no longer replays the FTS5 outbox (`sparse_index.initialize()`/`replay()` deleted) — ArcadeDB's native `LSM_SPARSE_VECTOR`/Lucene channels are ACID-consistent with graph writes (ARC-06).
- `store_from_env()` builds `ArcadeDBClient.from_env()`; `compose.yaml` gains `ARCADEDB_URL`/`DATABASE`/`USER`/`PASSWORD`/`*_INDEX` env vars on the mcp service (additive, `${VAR:-default}` templated) plus an `arcadedb: condition: service_healthy` `depends_on` entry; `.env.example` already carried the `ARCADEDB_*` vars from Wave 1. The `turingdb` service and `turingdb==1.35` pyproject dependency are untouched.

## Task Commits

Each task was committed atomically (Tasks 1-2 as RED then GREEN per TDD):

1. **Task 1 RED: add failing seam tests** - `cc29867` (test)
2. **Task 1 GREEN: port `_query`/`_write_many` seam** - `c362af7` (feat)
3. **Task 2 RED: add failing readiness/health tests** - `bce5685` (test)
4. **Task 2 GREEN: wire probe-driven readiness** - `cfced36` (feat)
5. **Task 3: rewire `store_from_env` + compose wiring** - `3fb6333` (feat)

**Plan metadata:** (this commit, pending)

## Files Created/Modified

- `src/turing_agentmemory_mcp/store_core.py` - Ported seam: `_query`/`_write`/`_write_many`/`_run_write_batch` route through `ArcadeDBClient`; `_ensure_user` binds params; `_ensure_schema`/`_ensure_vector_index`/`_tenant_vector_index` delegate to `arcadedb_schema`; `bootstrap`/`reconnect`/`runtime_status`/`_refresh_graph_readiness` implement D-10 probe-driven readiness; `_load_vectors` deleted; `_records` accepts plain `list[dict]`.
- `src/turing_agentmemory_mcp/server.py` - `store_from_env()` builds `ArcadeDBClient.from_env()` and reads `ARCADEDB_*_INDEX` vars; fixed the FastMCP instructions string ("backed by TuringDB" → "backed by ArcadeDB").
- `compose.yaml` - Added `ARCADEDB_URL`/`DATABASE`/`USER`/`PASSWORD`/`*_INDEX` env vars to the `turing-agentmemory-mcp` service (additive) and an `arcadedb: condition: service_healthy` `depends_on` entry.
- `tests/test_store_arcadedb_core.py` - New: 14 tests against a session-aware fake `ArcadeDBClient`, covering the seam's transaction plumbing, bound-param tenant scoping, CSV-load absence, probe-driven readiness, and `/health` gating.

## Decisions Made

- **`_write_many`'s signature changed** from `list[str]` to `list[tuple[str, dict[str, object] | None]]` so every statement in a batch can bind its own params. This is a deliberate forward-contract break, not a compat shim — D-08's security requirement (bound params, not string interpolation) demands per-statement params, and Wave 4 mixins will redesign their call sites around ArcadeDB SQL anyway.
- **`_ensure_vector_index`/`_ensure_tenant_vector_index` kept as back-compat shims** delegating to `_ensure_schema()`/`versioned_vector_index` rather than deleted outright, so the nine still-unported mixins' call sites don't `AttributeError` immediately — though their query *dialect* (Cypher-shaped literals) still needs Wave 4 porting regardless.
- **`load_graph_after_restart` renamed to `reconnect()`.** The plan's own acceptance criteria grep-gates for zero `"load_graph"` substring matches in the readiness path; keeping the old name (even re-implemented as a re-probe) would fail that literal gate. External callers (`benchmark_stages.py`, `e2e_score.py`) that invoke the old name are out of this plan's `files_modified` scope — flagged below as follow-up debt, not silently ignored.
- **`_records` rewritten to accept ArcadeDBClient's plain `list[dict]`** instead of assuming a pandas DataFrame (`.to_dict("records")`). This is a Rule 1 bug fix the port surfaces, not a new design choice — the old code was already dead-wrong for any non-TuringDB-DataFrame return shape.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_records` assumed a pandas DataFrame API that no longer applies**
- **Found during:** Task 1
- **Issue:** `_records(df)` called `df.to_dict("records")`, assuming TuringDB's pandas-DataFrame query return shape. `ArcadeDBClient.query()` returns a plain `list[dict[str, Any]]` (JSON-decoded), so the old code would `AttributeError` on every call.
- **Fix:** Rewrote `_records` to accept `Any`, defensively check `isinstance(rows, list)`, and clean each dict entry (NaN guard retained for safety, `.item()`/numpy handling dropped since ArcadeDB responses are plain JSON).
- **Files modified:** `src/turing_agentmemory_mcp/store_core.py`
- **Verification:** `tests/test_store_arcadedb_core.py::test_records_accepts_plain_list_of_dicts_not_a_dataframe`
- **Committed in:** `c362af7` (Task 1 GREEN commit)

**2. [Rule 1 - Bug] FastMCP server instructions string claimed the wrong backend**
- **Found during:** Task 3
- **Issue:** `create_mcp_app`'s FastMCP `instructions=` string read "Scoped memory and document retrieval backed by TuringDB" — factually wrong once `store_from_env` builds an ArcadeDB-backed store.
- **Fix:** Updated the string to "backed by ArcadeDB".
- **Files modified:** `src/turing_agentmemory_mcp/server.py`
- **Verification:** Visual diff review; no test asserts this exact string's backend name.
- **Committed in:** `3fb6333` (Task 3 commit)

**3. [Rule 2 - Missing Critical] Added `arcadedb` to the mcp service's compose `depends_on`**
- **Found during:** Task 3
- **Issue:** The plan's compose env-wiring instructions didn't mention `depends_on`, but `store_from_env()` now calls `store.bootstrap()` against ArcadeDB immediately at container start. Without a `service_healthy` dependency on `arcadedb`, the mcp container could start before ArcadeDB accepts connections, making every deployment racy.
- **Fix:** Added `arcadedb: condition: service_healthy` to `turing-agentmemory-mcp`'s `depends_on` block, alongside the existing `turingdb`/`agentmemory-embed`/`agentmemory-rerank`/`agentmemory-gliner` entries.
- **Files modified:** `compose.yaml`
- **Verification:** `docker compose config --quiet` passes; `tests/test_docker_hardening.py` (asserts on other `depends_on` entries) still passes unchanged.
- **Committed in:** `3fb6333` (Task 3 commit)

---

**Total deviations:** 3 auto-fixed (2 Rule 1 bug fixes, 1 Rule 2 missing-critical addition)
**Impact on plan:** All three are necessary for correctness (records shape, doc accuracy) or reliable deployment (health-gated startup ordering). No scope creep beyond the plan's own artifact list.

## Issues Encountered

None beyond the deviations above.

## User Setup Required

None - no external service configuration required. `.env.example` already carried the `ARCADEDB_*` vars from Wave 1 (04-01); this plan only added the corresponding compose env-wiring for the mcp service.

## Migration Debt: Pre-existing Tests Now Failing (Wave 4/5 Routing)

Per this plan's own instructions, the full suite was run once after all three tasks to enumerate tests that now fail as a direct, expected consequence of the seam contract change (the nine `store_<concern>.py` mixins still emit TuringDB-shaped Cypher query strings and construct TuringDB-shaped fake clients until Wave 4 ports them). **23 tests fail; all 23 are category (a) — seam/fake-client contract change, Wave 4/5 migration debt. None are genuine regressions.**

Breakdown by root cause (all traced, none require a fix in this plan):

**(a1) `runtime_status()` now calls `client.is_ready()` (D-10) — fake/stub clients lacking `is_ready()` AttributeError (13 tests):**
- `tests/test_fused_memory_search.py::test_default_fusion_weights_prioritize_direct_evidence`
- `tests/test_fused_memory_search.py::test_collectors_build_independent_dense_sparse_and_graph_channels`
- `tests/test_fused_memory_search.py::test_collector_failure_is_reported_without_losing_other_channels`
- `tests/test_governance.py::test_expired_memory_is_hidden_from_get_list_and_search`
- `tests/test_governance.py::test_document_ingest_applies_redaction_expiry_and_audit`
- `tests/test_governance.py::test_expired_document_chunks_are_hidden_from_search`
- `tests/test_observability.py::test_store_message_records_embed_query_and_vector_load_spans`
- `tests/test_observability.py::test_search_memory_records_embed_query_and_rerank_spans`
- `tests/test_observability.py::test_ingest_document_text_records_chunk_and_vector_load_spans`
- `tests/test_retrieval_filters.py::test_memory_search_filters_by_session_source_tags_and_created_range`
- `tests/test_retrieval_filters.py::test_memory_get_context_applies_same_filters_as_memory_search`
- `tests/test_retrieval_filters.py::test_document_search_filters_by_source_tags_and_updated_range`
- `tests/test_community_detection.py::test_batch_community_refresh_records_degradation_without_failing_ingest`

**(a2) `_write_many`/`_write` signature and transaction model changed (D-08) — TuringDB-shaped fakes/assertions on the old `list[str]`/submit-before-match dialect (3 tests):**
- `tests/test_batch_memory.py::test_rebuild_vector_projection_reembeds_each_active_canonical_kind`
- `tests/test_batch_memory.py::test_canonical_vector_records_use_active_document_chunk_text`
- `tests/test_batch_memory_write.py::test_write_many_submits_each_dependent_graph_batch` (name itself asserts the retired per-batch-submit semantics)

**(a3) `_ensure_vector_index`/`_ensure_schema` now delegate to `arcadedb_schema` and require `self._schema_bootstrapped` — a `TuringAgentMemory` subclass that skips `_StoreCore.__init__` (and a `_query` stub returning a pandas-DataFrame-shaped `Rows` object) breaks (1 test):**
- `tests/test_runtime_pipeline.py::test_vector_bootstrap_rejects_an_existing_dimension_mismatch`

**(a4) `_ensure_graph_loaded` deleted (replaced by `_refresh_graph_readiness`) — a test calling the old method directly against a TuringDB-shaped `GraphClient` fake (1 test):**
- `tests/test_store_entity_processing.py::test_ensure_graph_loaded_reuses_existing_graph_without_create_attempt`

**(a5) `store_from_env()` no longer constructs via `TuringDB(...)` — `monkeypatch.setattr(server, "TuringDB", FakeClient)` now `AttributeError`s since `server.TuringDB` no longer exists (5 tests):**
- `tests/test_runtime_pipeline.py::test_store_from_env_wires_the_fused_pipeline_once`
- `tests/test_runtime_pipeline.py::test_store_from_env_rejects_invalid_fused_configuration[AGENTMEMORY_FUSION_ENABLED-sometimes]`
- `tests/test_runtime_pipeline.py::test_store_from_env_rejects_invalid_fused_configuration[AGENTMEMORY_LEIDEN_SEED--1]`
- `tests/test_runtime_pipeline.py::test_store_from_env_rejects_invalid_fused_configuration[AGENTMEMORY_LEIDEN_RESOLUTION-nan]`
- `tests/test_runtime_pipeline.py::test_store_from_env_rejects_invalid_fused_configuration[AGENTMEMORY_FUSION_WEIGHTS-[]]`

**Routing recommendation:** (a1) is the widest-blast-radius category and should be resolved as part of whichever Wave 4 plan first touches the shared mixin test fixtures (`_batch_memory_shared.py` and the per-mixin `client=object()`/fake-store conventions) — a single shared fake `ArcadeDBClient`-shaped test double covering `is_ready()` (plus `query`/`command`) would likely fix most of (a1)/(a2)/(a3) at once. (a4) is a one-line test deletion/rewrite once `_ensure_graph_loaded` is confirmed retired for good. (a5) should be resolved in whichever Wave 4/5 plan next touches `store_from_env()`'s test coverage — the fix is `monkeypatch.setattr(server, "ArcadeDBClient", FakeClient)` instead of the old `TuringDB` patch target.

Additionally (not test-covered, flagged for awareness): `benchmark_stages.py:429` and `e2e_score.py:104` call `store.load_graph_after_restart()`, which no longer exists (renamed `reconnect()` to satisfy this plan's own `load_graph`-substring grep gate). These files are outside this plan's `files_modified` scope and are not exercised by any test in the current suite, but will `AttributeError` if invoked before their own call sites are updated — flagged as a real, if currently untested, follow-up.

## Next Phase Readiness

- The store_core seam now speaks ArcadeDB exclusively — Wave 4 (04-05 through 04-09 per current ROADMAP numbering) can port the nine `store_<concern>.py` mixins' query dialect against a stable, tested foundation (`_query`/`_write_many`/`_ensure_user`/readiness).
- **Blocker for Wave 4 planning:** every mixin's Cypher-shaped query strings and `list[str]`-based `_write_many` calls need rewriting to ArcadeDB SQL with bound params and the new `list[tuple[str, params]]` signature — this is the bulk of the remaining direct-port work.
- The 23 failing tests above are the concrete, itemized starting checklist for that migration; none block this plan's own completion.

---
*Phase: 04-arcadedb-direct-port*
*Completed: 2026-07-13*

## Self-Check: PASSED

- FOUND: `src/turing_agentmemory_mcp/store_core.py`
- FOUND: `src/turing_agentmemory_mcp/server.py`
- FOUND: `compose.yaml`
- FOUND: `tests/test_store_arcadedb_core.py`
- FOUND commit: `cc29867` (test(04-04): add failing tests for the ArcadeDB seam)
- FOUND commit: `c362af7` (feat(04-04): port _query/_write_many seam)
- FOUND commit: `bce5685` (test(04-04): add failing tests for probe-driven readiness)
- FOUND commit: `cfced36` (feat(04-04): wire probe-driven readiness)
- FOUND commit: `3fb6333` (feat(04-04): rewire store_from_env to ArcadeDBClient)
