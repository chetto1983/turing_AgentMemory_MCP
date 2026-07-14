---
phase: 04-arcadedb-direct-port
plan: 09
subsystem: database
tags: [arcadedb, dead-code-removal, tenant-isolation, chaos-restart, e2e, docker, arc-05, arc-08, d-10]

# Dependency graph
requires:
  - phase: 04-arcadedb-direct-port (04-04)
    provides: "store_core.py's ArcadeDB seam (reconnect()/_refresh_graph_readiness, probe-driven /health)"
  - phase: 04-arcadedb-direct-port (04-05..08)
    provides: "every store_<concern>.py mixin ported to bound-param ArcadeDB SQL; sparse_encoder.py; the *_queries.py Statement-builder convention"
provides:
  - "ids.py/store_utils.py with the vector_id int-join machinery, ids.quote(), and the dead _projection_edge_literals/_cypher_value Cypher-literal builders fully deleted (ARC-05)"
  - "tests/test_vector_id_absent.py -- repo-scoped guard: no vector_id token/helper symbol and no ArcadeDB RID form in any store*.py/ids.py module"
  - "tests/test_stable_id_survives_rebuild.py -- ARC-08: stable_id() for a fixed input is byte-identical before/after rebuild_vector_projection()"
  - "tests/test_arcadedb_tenant_isolation.py -- concurrent multi-tenant write/read isolation + fail-closed-on-empty-identifier, exercised through the real bound-param query forms under thread concurrency"
  - "tests/test_arcadedb_chaos_restart.py -- D-10: a live arcadedb container is force-restarted mid-test; store degrades visibly, reconnects with no manual step, search returns correct results after recovery"
  - "the full non-integration suite returned to green (449 passed/7 failed -> 501 passed/0 failed): test_runtime_pipeline.py's ArcadeDBClient-patch migration, test_store_entity_processing.py's retired _ensure_graph_loaded test superseded"
  - "benchmark_stages.py + scripts/e2e_score.py's seam-rename orphan (load_graph_after_restart -> reconnect()) fixed; zero remaining callers repo-wide"
  - "e2e_score.py rewired off the retired local turingdb daemon onto ArcadeE2EBackend (connects to the already-running arcadedb compose service); a REAL, live VALIDATED_10_10/19-check capture at baseline/04-arcadedb/e2e-results.json"
  - "two real production bugs found and fixed live, not by inspection: non-fused search_memory dropped content/kind on every dense-channel hit (the default, non-fusion production path); reindex_document_text collided with its own Document[id]/Chunk[id] UNIQUE index"
affects: [06-phase-6-parity-gate, 07-turingdb-removal]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ArcadeE2EBackend (e2e_score_stubs.py): connects an E2E harness to an ALREADY-RUNNING compose service (drop-and-recreate a dedicated database for a clean slate) instead of spawning its own container -- avoids Docker-outside-of-Docker plumbing for a throwaway container; the restart leg shells out to `docker compose stop/start <service>` from the host, matching tests/test_arcadedb_chaos_restart.py's own pattern."
    - "Hard DELETE FROM <VertexType> WHERE ... (confirmed live: cascades incident-edge removal) as the correct pre-recreate step whenever a UNIQUE-id'd vertex must be replaced with the SAME id -- the soft status='deleted' UPDATE pattern used everywhere else in this port is NOT safe to reuse before a same-id CREATE."
    - "dense_search_statement(..., extra_fields=<all fields the row-consumer reads>) -- any dense-channel query whose result row is consumed directly (not re-fetched by id afterward) MUST request every field the consumer reads, not just id/distance."

key-files:
  created:
    - tests/test_vector_id_absent.py
    - tests/test_stable_id_survives_rebuild.py
    - tests/test_arcadedb_tenant_isolation.py
    - tests/test_arcadedb_chaos_restart.py
    - src/turing_agentmemory_mcp/e2e_score_check.py
    - baseline/04-arcadedb/e2e-results.json
    - baseline/04-arcadedb/NOTES.md
  modified:
    - src/turing_agentmemory_mcp/ids.py
    - src/turing_agentmemory_mcp/store_utils.py
    - src/turing_agentmemory_mcp/store_search.py
    - src/turing_agentmemory_mcp/store_documents.py
    - src/turing_agentmemory_mcp/store_documents_queries.py
    - src/turing_agentmemory_mcp/benchmark_stages.py
    - src/turing_agentmemory_mcp/e2e_score.py
    - src/turing_agentmemory_mcp/e2e_score_scenarios.py
    - src/turing_agentmemory_mcp/e2e_score_stubs.py
    - compose.yaml
    - tests/test_runtime_pipeline.py
    - tests/test_store_entity_processing.py
    - tests/test_store_arcadedb_retrieval.py
    - tests/test_store_arcadedb_documents.py
    - tests/test_ids.py

key-decisions:
  - "ArcadeDaemon's initial container-lifecycle design (spawn a throwaway docker run per e2e run) was abandoned mid-plan in favor of ArcadeE2EBackend connecting to the EXISTING arcadedb compose service -- the former needs Docker-outside-of-Docker (a docker socket + docker CLI baked into the mcp image) purely for a throwaway container, which is out of this plan's scope to add; the latter reuses the one already-running dependency every other part of the stack shares, with a dedicated drop-and-recreate database for the clean-slate guarantee."
  - "The GPU-backed, quality-comparable e2e capture (matching baseline/03-turingdb's real granite-embedding/bge-reranker sidecars) was NOT attempted this session -- downloading the pinned GGUF model weights is a multi-GB, open-ended-time operation; the committed capture is the CORRECTNESS-parity result (in-process deterministic stub embed/rerank), documented explicitly as such in baseline/04-arcadedb/NOTES.md with the exact reproduction command for the GPU-backed run, per CLAUDE.md's 'don't claim a benchmark win from mismatched configs' rule."
  - "real-document-benchmark.json was NOT captured -- its external, uncommitted corpus (D:/tmp/baseline-corpus) does not exist on this host/session; NOTES.md documents the exact reproduction command rather than fabricating a result."
  - "_ids.quote()_ and the dead _projection_edge_literals/_cypher_value Cypher-literal builders in store_utils.py were deleted alongside vector_id (not just the five _*_vector_id staticmethods the plan named) -- confirmed via repo-wide grep that quote() had zero remaining callers once its only user (_cypher_value, itself only called by _projection_edge_literals, itself never called anywhere) was traced to dead code."
  - "test_ids.py (previously ONLY testing the retired quote()) was rewritten rather than deleted -- it now covers stable_id()/cypher_var(), the two ids.py functions that survive the port, since deleting it outright would have left ids.py's two remaining functions with zero dedicated unit coverage."
  - "test_vector_bootstrap_rejects_an_existing_dimension_mismatch and test_ensure_graph_loaded_reuses_existing_graph_without_create_attempt were deleted (not migrated) -- both asserted behavior on TuringDB primitives store_core.py no longer has (_ensure_vector_index's per-name SHOW VECTOR INDEXES check; _ensure_graph_loaded itself), and both are genuinely superseded by existing 04-03/04-04 coverage (test_arcadedb_schema.py's own dimension-mismatch test; test_store_arcadedb_core.py's D5 readiness/reconnect suite) -- justified per-test in tests/test_runtime_pipeline.py/tests/test_store_entity_processing.py inline comments, not silently dropped."

patterns-established:
  - "E2E harness connects to an already-running shared service rather than owning a throwaway container's lifecycle, when the alternative would require adding container-orchestration capability (docker socket + CLI) to an application image purely for test convenience."

requirements-completed: [ARC-05, ARC-08]

coverage:
  - id: D1
    description: "ids.vector_id() and the five store_utils.py _*_vector_id() staticmethods are deleted (plus the now-dead ids.quote()/_cypher_value/_projection_edge_literals Cypher-literal builders); a repo-scoped guard proves no vector_id token/helper symbol or ArcadeDB RID form remains in any store*.py/ids.py module"
    requirement: "ARC-05"
    verification:
      - kind: unit
        ref: "tests/test_vector_id_absent.py (35 parametrized cases across every store*.py module + ids.py)"
        status: pass
      - kind: unit
        ref: "grep -rlE \"\\bvector_id\\b|_memory_vector_id|_entity_vector_id|_fact_vector_id|_community_vector_id|_document_vector_id\" src/turing_agentmemory_mcp/*.py -- 0 matches"
        status: pass
    human_judgment: false
  - id: D2
    description: "stable_id() for a fixed input resolves to the identical ArcadeDB-stored id property both before and after rebuild_vector_projection() -- no vector-ID drift across a rebuild"
    requirement: "ARC-08"
    verification:
      - kind: unit
        ref: "tests/test_stable_id_survives_rebuild.py#test_stable_id_survives_rebuild_for_a_fixed_input"
        status: pass
      - kind: unit
        ref: "tests/test_stable_id_survives_rebuild.py#test_stable_id_survives_two_consecutive_rebuilds"
        status: pass
    human_judgment: false
  - id: D3
    description: "Concurrent multi-tenant writes/reads through the rewritten ArcadeDB query forms never leak across tenants in either direction, and an empty user_identifier fails closed on the concurrent path too"
    verification:
      - kind: unit
        ref: "tests/test_arcadedb_tenant_isolation.py#test_concurrent_multi_tenant_writes_never_leak_across_tenants"
        status: pass
      - kind: unit
        ref: "tests/test_arcadedb_tenant_isolation.py#test_concurrent_interleaved_reads_never_observe_cross_tenant_rows"
        status: pass
      - kind: unit
        ref: "tests/test_arcadedb_tenant_isolation.py#test_empty_user_identifier_fails_closed_on_the_concurrent_path"
        status: pass
    human_judgment: false
  - id: D4
    description: "A real ArcadeDB container is force-restarted mid-test: the store reports degraded while down, reconnects with no manual runbook step once it is back, and search returns correct (not empty/stale) results immediately after recovery (D-10)"
    verification:
      - kind: integration
        ref: "tests/test_arcadedb_chaos_restart.py#test_store_survives_arcadedb_restart_and_recovers_correct_search"
        status: pass
    human_judgment: false
  - id: D5
    description: "The full non-integration suite is green (0 failed) -- the 7 pre-existing routed reds are migrated/superseded, no skip-as-green"
    verification:
      - kind: unit
        ref: "python -m pytest -q -- 501 passed, 0 failed"
        status: pass
    human_judgment: false
  - id: D6
    description: "Every load_graph_after_restart caller repo-wide is fixed to reconnect() (benchmark_stages.py + e2e_score.py)"
    verification:
      - kind: unit
        ref: "grep -rn load_graph_after_restart src/ scripts/ -- 0 matches"
        status: pass
    human_judgment: false
  - id: D7
    description: "An ArcadeDB-backed e2e/benchmark result is captured in the baseline/03-turingdb field shape, from a real live run (not fabricated)"
    verification:
      - kind: e2e
        ref: "baseline/04-arcadedb/e2e-results.json (VALIDATED_10_10, 19/19 checks, captured 2026-07-14 against the live arcadedb compose service)"
        status: pass
    human_judgment: false

# Metrics
duration: 75min
completed: 2026-07-14
status: complete
---

# Phase 04 Plan 09: Close the Port (ArcadeDB Direct Port Consolidation) Summary

**Deleted the retired `vector_id` int-join machinery and `ids.quote()`, added ARC-08/tenant-isolation/D-10 chaos-restart regression guards, drove the full non-integration suite from 449/7 to 501/0, and captured a REAL, live `VALIDATED_10_10` ArcadeDB e2e run — finding and fixing two genuine production bugs (`search_memory`'s missing dense-channel fields, `reindex_document_text`'s UNIQUE-index collision) along the way that no prior wave's fake-client tests could have caught.**

## Performance

- **Duration:** ~75 min
- **Completed:** 2026-07-14
- **Tasks:** 3 (per plan) + the EXECUTION-STATE-mandated expanded scope (full-suite-green migration, e2e wiring, two live bug fixes)
- **Files modified:** 15; created 7 (4 new test files, `e2e_score_check.py`, `baseline/04-arcadedb/e2e-results.json` + `NOTES.md`)
- **Commits:** 7 (`945649d` through `a206a9b`)

## Accomplishments

- **Task 1 (vector_id deletion):** `ids.vector_id()`, the five `store_utils.py` `_*_vector_id()` staticmethods, `ids.quote()`, and the dead `_projection_edge_literals`/`_cypher_value` Cypher-literal builders (which only `quote()` fed, and which nothing called anymore post-04-05..08) are all deleted. `tests/test_vector_id_absent.py` is a repo-scoped, parametrized guard over every `store*.py` module + `ids.py` proving zero `vector_id` tokens/helper symbols and zero ArcadeDB RID (`#12:34`/`@rid`) literals used as identifiers, ever, going forward.
- **Task 2 (regression guards):** `tests/test_stable_id_survives_rebuild.py` proves `stable_id()` for a fixed input is byte-identical before/after `rebuild_vector_projection()` (ARC-08). `tests/test_arcadedb_tenant_isolation.py` is a real multithreaded test — a lock-guarded fake `ArcadeDBClient` interpreting the ACTUAL bound-param `CREATE VERTEX`/`SELECT`/`UPDATE` statements `store_memory_queries.py` builds — proving zero cross-tenant leakage under genuine concurrent writer/reader interleaving in both directions, plus fail-closed behavior on an empty `user_identifier` under that same concurrency (T-04-09-01).
- **Task 3 (D-10 chaos-restart + e2e capture), executed against a REAL live ArcadeDB container throughout:**
  - `tests/test_arcadedb_chaos_restart.py` force-restarts the actual `arcadedb` compose container (`docker compose stop`/`start`) mid-test and asserts all four required transitions: degraded-while-down, reconnect with no manual step, healthy again, and correct (not stale/empty) search results immediately after recovery. This test is what caught Bug 1 below.
  - `e2e_score.py` (the deterministic 19-check score gate) is rewired off the retired local `turingdb` CLI daemon onto `ArcadeE2EBackend` — connects to the already-running `arcadedb` compose service with a dedicated drop-and-recreate database for a clean slate, instead of spawning its own throwaway container (which would have required Docker-outside-of-Docker plumbing this plan's scope doesn't cover). The restart leg now genuinely restarts the `arcadedb` service and calls `store.reconnect()` (fixing the `load_graph_after_restart` seam-rename orphan this file itself carried).
  - **Real capture, not fabricated:** `baseline/04-arcadedb/e2e-results.json` is the actual output of running this gate against the live `arcadedb` compose service on 2026-07-14 — **`VALIDATED_10_10`, 19/19 checks passing.** `baseline/04-arcadedb/NOTES.md` documents exactly what this capture does and does NOT prove: it validates deterministic tool-surface/tenant-scoping/hybrid-explain/idempotency/restart-durability correctness (in-process stub embed/rerank), NOT retrieval-quality parity with the GPU-backed baseline (that capture, and the `real-document-benchmark.json` capture requiring an external corpus not present on this host, are both documented with exact reproduction commands, not fabricated).
- **Full non-integration suite returned to green (449 passed/7 failed → 501 passed/0 failed):** `test_runtime_pipeline.py`'s 6 (patch `server.ArcadeDBClient`'s `from_env()`, not the retired `server.TuringDB`; the old per-name dimension-mismatch test is superseded by `test_arcadedb_schema.py`'s own coverage) and `test_store_entity_processing.py`'s 1 (`_ensure_graph_loaded` retired in 04-04, superseded by `test_store_arcadedb_core.py`'s readiness/reconnect suite) — both deletions justified inline, not silently dropped.
- **Seam-rename orphans fixed repo-wide:** `benchmark_stages.py:429` and `e2e_score.py`'s own restart leg both still called the retired `store.load_graph_after_restart()`; both now call `reconnect()`. `grep -rn load_graph_after_restart src/ scripts/` returns zero matches.
- **Two real production bugs found live (not by inspection) and fixed, each with its own regression test:**
  1. **`store_search.py`'s non-fused `search_memory`** (the actual production default — fusion is opt-in via `AGENTMEMORY_FUSION_ENABLED`, and every existing test fixture only builds `fusion_enabled=True` stores) called `dense_search_statement()` with no `extra_fields`, so every hit's `content`/`kind`/`session_id`/etc. came back empty whenever a memory was found via the dense channel — virtually always. Found via the chaos-restart test's own genuine end-to-end assertion. Fixed by passing `extra_fields=MEMORY_FIELDS` (minus `id`); added a fast unit regression (`test_non_fused_search_memory_returns_full_content_not_just_id_and_distance`).
  2. **`store_documents.py`'s `reindex_document_text`** called the soft `delete_document()` (an `UPDATE ... SET status = 'deleted'`) before recreating a Document/Chunk with the SAME `id` — but a soft-deleted row still occupies its slot in `Document[id]`/`Chunk[id]`'s UNIQUE index, so the recreate raised a live `DuplicatedKeyException` on every reindex. There was no existing test for `reindex_document_text` anywhere in the suite (why this shipped unnoticed through 04-06). Fixed with a genuine hard `DELETE FROM <VertexType> WHERE ...` (confirmed live: ArcadeDB cascades incident-edge removal) before recreating; added `test_reindex_document_text_hard_deletes_old_rows_before_recreating_same_id`.
  3. **`e2e_score_scenarios.py`'s hardcoded chunk-id literals** (`"doc-machine-safety#1"`) assumed the pre-port TuringDB `f"{document_id}#{ordinal}"` format; chunk ids have been `stable_id()`-based since 04-06 (ARC-08). Fixed via a `_chunk_id()` helper computing the same construction `store_documents.py` uses.
- **`compose.yaml`'s `e2e` profile service** now `depends_on: arcadedb` and carries `ARCADEDB_URL`/`USER`/`PASSWORD` pointed at the compose-network hostname (was previously unreachable from inside that container); the scratch-dir env var is renamed `ARCADEDB_E2E_HOME` to match the rewire.

## Task Commits

1. **Task 1: delete vector_id/quote dead code + add no-vector_id/no-RID guard** - `945649d` (feat)
2. **Full-suite-green migration + benchmark_stages.py seam-rename fix** - `0eb35c4` (test)
3. **Task 2: ARC-08 id-survives-rebuild + concurrent tenant-isolation guards** - `aa6ce66` (test)
4. **Bug 1 fix: non-fused search_memory dropped content/kind + chaos-restart test** - `f96da57` (fix)
5. **Bug 2 fix: reindex_document_text UNIQUE-index collision** - `781f155` (fix)
6. **Task 3: wire e2e_score.py to ArcadeDB, capture VALIDATED_10_10** - `8a2cccd` (feat)
7. **compose.yaml e2e service wiring fix** - `a206a9b` (fix)

**Plan metadata:** (this commit, pending)

## Files Created/Modified

- `src/turing_agentmemory_mcp/ids.py` - `vector_id()`/`quote()` deleted; `stable_id()`/`cypher_var()` unchanged.
- `src/turing_agentmemory_mcp/store_utils.py` - Five `_*_vector_id()` staticmethods + the dead `_projection_edge_literals`/`_cypher_value` Cypher-literal builders deleted; unused `cypher_var`/`EdgeProjection` imports removed.
- `src/turing_agentmemory_mcp/store_search.py` - Non-fused `search_memory`'s dense channel now requests every field `_memory_from_row` reads (Bug 1 fix).
- `src/turing_agentmemory_mcp/store_documents.py` / `store_documents_queries.py` - `reindex_document_text` hard-deletes old Document/Chunk rows before recreating the same id (Bug 2 fix); new `document_hard_delete_statement`/`chunk_hard_delete_statement` builders.
- `src/turing_agentmemory_mcp/benchmark_stages.py` - `load_graph_after_restart()` → `reconnect()`.
- `src/turing_agentmemory_mcp/e2e_score.py` / `e2e_score_stubs.py` / `e2e_score_scenarios.py` / `e2e_score_check.py` (new) - Rewired to `ArcadeE2EBackend`; retired chunk-id literal expectations fixed; `payload`/`check` extracted to a new sibling module for the 600-LOC cap.
- `compose.yaml` - `e2e` service wired to reach `arcadedb` over the compose network.
- `tests/test_vector_id_absent.py`, `tests/test_stable_id_survives_rebuild.py`, `tests/test_arcadedb_tenant_isolation.py`, `tests/test_arcadedb_chaos_restart.py` (all new) - see coverage table.
- `tests/test_runtime_pipeline.py`, `tests/test_store_entity_processing.py`, `tests/test_ids.py` - migrated/superseded per the full-suite-green routing.
- `tests/test_store_arcadedb_retrieval.py`, `tests/test_store_arcadedb_documents.py` - fast unit regressions for Bugs 1 and 2.
- `baseline/04-arcadedb/e2e-results.json`, `baseline/04-arcadedb/NOTES.md` (new) - the real capture + its documented scope/caveats.

## Decisions Made

See frontmatter `key-decisions` for the full list. Highlights: `ArcadeE2EBackend` connects to the already-running `arcadedb` compose service rather than owning a throwaway container's lifecycle (avoids Docker-outside-of-Docker scope creep); the GPU-backed quality-parity capture and `real-document-benchmark.json` were deliberately NOT attempted/fabricated this session (documented with exact reproduction commands instead); `ids.quote()` and its two dead callers were deleted alongside `vector_id` since nothing called them; `test_ids.py` was rewritten (not deleted) to cover the two surviving `ids.py` functions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Non-fused `search_memory` dropped content/kind on every dense-channel hit**
- **Found during:** Task 3 (writing `tests/test_arcadedb_chaos_restart.py`, then confirmed via the live e2e capture)
- **Issue:** `dense_search_statement()` was called with no `extra_fields`, so the SELECT only returned `id`/`distance`; `_memory_from_row` then built every `MemoryItem` from a row missing `content`/`kind`/`session_id`/etc. This is the ACTUAL production default (fusion is opt-in), and no existing test fixture built a `fusion_enabled=False` store to catch it.
- **Fix:** `extra_fields=_MEMORY_DENSE_EXTRA_FIELDS` (all of `MEMORY_FIELDS` minus `id`, already included).
- **Files modified:** `src/turing_agentmemory_mcp/store_search.py`
- **Verification:** `tests/test_store_arcadedb_retrieval.py::test_non_fused_search_memory_returns_full_content_not_just_id_and_distance`; `tests/test_arcadedb_chaos_restart.py` (live)
- **Committed in:** `f96da57`

**2. [Rule 1 - Bug] `reindex_document_text` collided with its own UNIQUE(id) index**
- **Found during:** Task 3 (the live e2e capture's `document_reindex_text` MCP-tool call raised a real `com.arcadedb.exception.DuplicatedKeyException`)
- **Issue:** Reindex called the soft `delete_document()` (an `UPDATE ... SET status = 'deleted'`) before recreating a Document/Chunk with the SAME `id` — a soft-deleted row still occupies its slot in the UNIQUE `id` index, so the recreate always failed. No test anywhere in the suite exercised `reindex_document_text`.
- **Fix:** New `document_hard_delete_statement`/`chunk_hard_delete_statement` (genuine `DELETE FROM`, confirmed live to cascade incident-edge removal) used before recreate; the user-facing `delete_document()` soft-delete path is unchanged.
- **Files modified:** `src/turing_agentmemory_mcp/store_documents.py`, `src/turing_agentmemory_mcp/store_documents_queries.py`
- **Verification:** `tests/test_store_arcadedb_documents.py::test_reindex_document_text_hard_deletes_old_rows_before_recreating_same_id`; live e2e capture
- **Committed in:** `781f155`

**3. [Rule 1 - Bug] `e2e_score_scenarios.py`'s hardcoded chunk-id literals were stale post-ARC-08**
- **Found during:** Task 3 (the live e2e capture's document-search checks failed against real chunk ids)
- **Issue:** `"doc-machine-safety#1"`-style literals assumed the pre-port `f"{document_id}#{ordinal}"` chunk-id format; 04-06 changed chunk ids to `stable_id()`-based (ARC-08).
- **Fix:** `_chunk_id()` helper computing the identical `stable_id("chunk", user_identifier, document_id, str(ordinal))` construction `store_documents.py` uses.
- **Files modified:** `src/turing_agentmemory_mcp/e2e_score_scenarios.py`, `src/turing_agentmemory_mcp/e2e_score.py`
- **Verification:** Live e2e capture (`VALIDATED_10_10`)
- **Committed in:** `8a2cccd`

**4. [Rule 3 - Blocking] `e2e_score_scenarios.py` exceeded the 600-LOC cap after the chunk-id fix**
- **Found during:** Task 3, post-fix file-size check
- **Issue:** Adding the `_chunk_id()` helper pushed the file to 609 lines.
- **Fix:** Extracted `payload()`/`check()` into a new sibling module `e2e_score_check.py`, re-exported unchanged.
- **Files modified:** `src/turing_agentmemory_mcp/e2e_score_check.py` (new), `src/turing_agentmemory_mcp/e2e_score_scenarios.py`
- **Verification:** `bash scripts/check-file-size.sh`
- **Committed in:** `8a2cccd`

**5. [Rule 3 - Blocking] `compose.yaml`'s `e2e` service couldn't reach `arcadedb`**
- **Found during:** Task 3, verifying the rewired `e2e_score.py` would also work via `docker compose run --rm e2e`
- **Issue:** The `e2e` service had no `ARCADEDB_URL`/`depends_on` — `127.0.0.1` (the default) doesn't resolve to a sibling compose service from inside a container.
- **Fix:** Added `depends_on: arcadedb: condition: service_healthy` and `ARCADEDB_URL=http://arcadedb:2480` (+ user/password); renamed the scratch-dir env var to `ARCADEDB_E2E_HOME`.
- **Files modified:** `compose.yaml`
- **Verification:** `docker compose config --quiet`; `tests/test_compose_config.py`/`tests/test_docker_hardening.py` (19 tests, unchanged)
- **Committed in:** `a206a9b`

---

**Total deviations:** 5 auto-fixed (3 Rule 1 real-bug fixes found live, 2 Rule 3 blocking fixes)
**Impact on plan:** All five were necessary for correctness (two were genuine production bugs that would have shipped broken behavior; the third was a broken test assertion) or for the plan's own Definition-of-Done gates to hold (LOC cap, compose validity). No scope creep beyond what closing the port required — and finding these bugs is precisely what the plan's "validated end-to-end on a real scenario, not just green unit tests" framing was for.

## Issues Encountered

- **Running `e2e_score.py` on this Windows host required a `sys.modules["turingdb"]` stub** for the capture session (the `turingdb` PyPI package has no Windows wheel and is genuinely not installed in this `.venv` — a pre-existing, out-of-scope condition; the same stub convention already exists throughout this repo's test suite for the same reason). Documented in `baseline/04-arcadedb/NOTES.md`; a normal Linux CI/Docker run needs no such stub.
- **The GPU-backed embed/rerank sidecars were available (NVIDIA GPU confirmed via `nvidia-smi`, Docker Desktop reachable) but were not brought up** — downloading the pinned GGUF model weights is a multi-GB, open-ended-time operation not attempted this session. Documented as a deliberate, non-fabricated gap in `baseline/04-arcadedb/NOTES.md` with the exact command to produce that capture later (Phase 6 "owns the pass/fail threshold" per this plan's own scope framing).
- **`real-document-benchmark.json` could not be captured**: its external corpus (`D:/tmp/baseline-corpus`) does not exist on this host. Documented, not fabricated.

## User Setup Required

None - no external service configuration required. The `arcadedb` compose service must be running (`docker compose up -d arcadedb`) to reproduce the e2e capture or run the chaos-restart/tenant-isolation-adjacent integration tests; this is already the case for any dev environment following this repo's own `docker-compose.yaml`.

## Next Phase Readiness

- **Phase 4 (ArcadeDB direct port) is complete.** Every store mixin speaks ArcadeDB exclusively; `vector_id` is fully deleted; `stable_id()` is proven to survive a rebuild; concurrent tenant isolation is proven under real thread concurrency; a live ArcadeDB container restart is proven to recover correctly (D-10); the full non-integration suite is green; and a real, non-fabricated e2e capture exists.
- **For Phase 6 (parity gate):** `baseline/04-arcadedb/e2e-results.json` is the correctness-parity capture (deterministic stub embed/rerank). Phase 6 should run the GPU-backed capture (exact command in `baseline/04-arcadedb/NOTES.md`) against the same real GPU sidecars `baseline/03-turingdb` used, and separately obtain/re-point at an equivalent corpus for `real_document_benchmark.json`, before drawing any quality-parity conclusion. `retrieval_fusion.py` and `baseline/03-turingdb/frozen-questions.json` are confirmed untouched throughout this phase.
- **For Phase 7 (turingdb removal, ARC-10):** `turingdb` the PyPI dependency, the `turingdb` compose service, and `TuringDaemon`/`LocalEmbedServer`-style re-exports in `e2e_score.py` are all still retained and in active use by the legacy `benchmark.py`/`agent_quality_eval.py` harnesses — those two files (and their own TuringDB-backed daemon-lifecycle code) are the concrete removal targets for that phase, not touched here.
- No blockers.

---
*Phase: 04-arcadedb-direct-port*
*Completed: 2026-07-14*

## Self-Check: PASSED

- FOUND: `src/turing_agentmemory_mcp/ids.py`
- FOUND: `src/turing_agentmemory_mcp/store_utils.py`
- FOUND: `tests/test_vector_id_absent.py`
- FOUND: `tests/test_stable_id_survives_rebuild.py`
- FOUND: `tests/test_arcadedb_tenant_isolation.py`
- FOUND: `tests/test_arcadedb_chaos_restart.py`
- FOUND: `src/turing_agentmemory_mcp/e2e_score_check.py`
- FOUND: `baseline/04-arcadedb/e2e-results.json`
- FOUND: `baseline/04-arcadedb/NOTES.md`
- FOUND commit: `945649d` (feat(04-09): delete vector_id/quote dead code + add no-vector_id/no-RID guard)
- FOUND commit: `0eb35c4` (test(04-09): migrate remaining TuringDB-shaped test debt; fix benchmark_stages.py seam orphan)
- FOUND commit: `aa6ce66` (test(04-09): add ARC-08 id-survives-rebuild + concurrent tenant-isolation guards)
- FOUND commit: `f96da57` (fix(04-09): non-fused search_memory dropped content/kind on every dense hit)
- FOUND commit: `781f155` (fix(04-09): reindex_document_text collided with its own UNIQUE(id) index)
- FOUND commit: `8a2cccd` (feat(04-09): wire e2e_score.py to ArcadeDB, capture a real VALIDATED_10_10 run)
- FOUND commit: `a206a9b` (fix(04-09): wire the e2e compose service to the arcadedb service)

## Final Verification (verbatim)

```
$ python -m pytest -q
501 passed, 2 warnings in 45.79s

$ python -m ruff check src tests scripts
All checks passed!

$ bash scripts/check-file-size.sh
check-file-size: all tracked *.py files within the 600-LOC cap.

$ docker compose config --quiet
(exit 0)

$ grep -rlE "\bvector_id\b|_memory_vector_id|_entity_vector_id|_fact_vector_id|_community_vector_id|_document_vector_id" src/turing_agentmemory_mcp/*.py
(no output, exit 1)

$ grep -rn "load_graph_after_restart" src/ scripts/
(no output, exit 1)
```
