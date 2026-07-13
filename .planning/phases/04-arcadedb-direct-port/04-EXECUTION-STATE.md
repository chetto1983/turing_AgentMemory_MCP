# Phase 4 (ArcadeDB Direct Port) — Execution State & Forward Plan

**Updated:** 2026-07-13 (mid-execution snapshot, after Wave 3 + the 04-03 both-channels amendment)
**Status:** EXECUTING — Waves 1–3 complete, Wave 4 next.
**Read this first** if you are resuming this phase or executing any remaining plan. It records what the pre-spike plans (04-05…04-09) do NOT yet reflect: the spike outcomes, the user's both-channels lexical decision, and the test-migration debt.

---

## Where we are

| Wave | Plan | Status | Result |
|------|------|--------|--------|
| 1 | 04-01 Spike (D-02 hard gate) | ✅ complete + verified | 5 unknowns resolved live; D-03/04/05 decided; `arcadedb` service up |
| 2 | 04-02 Full client | ✅ complete + verified | `ArcadeDBClient` full surface; found+fixed a real MVCC-retry bug |
| 2 | 04-03 Schema bootstrap | ✅ complete + **amended** | idempotent schema; **both-channels amendment landed** (see below) |
| 3 | 04-04 store_core seam | ✅ complete + verified | seam speaks ArcadeDB; single managed tx; probe-gated `/health`; `store_from_env`→ArcadeDB |
| 4 | 04-05 memory write/read | ⏳ next | |
| 4 | 04-06 documents | ⏳ | |
| 4 | 04-07 fused search + evidence | ⏳ | |
| 4 | 04-08 rebuild + community | ⏳ | |
| 5 | 04-09 close the port | ⏳ | + full-suite-green consolidation (expanded, see below) |

`use_worktrees=false` → plans run **sequentially on `master`**; executors update STATE/ROADMAP themselves. Nothing pushed yet (push at phase end; pre-push runs `fast-tests`).

---

## Settled facts the remaining plans MUST use (authoritative over pre-spike plan wording)

Full detail in `04-SPIKE-FINDINGS.md`. Highlights:

- **HTTP:** `/api/v1/{query,command,begin,commit,rollback}/<db>` (+ `/api/v1/server`, `/api/v1/ready`); HTTP Basic auth; **session-header** transaction model (`arcadedb-session-id`).
- **Params:** ALL values (incl. vectors) are bound as `?`/`:named` params — `ids.quote()` interpolation is retired in ported paths.
- **Dense vector:** `vectorNeighbors("Type[embedding]", :vec, k)` returns record + `distance`; **no `vector_id` int-join** (delete it — ARC-05). Over-fetch-then-filter is the locked default (**D-03**, k-underfill is real).
- **Graph surface:** SQL `MATCH`/`TRAVERSE` (**D-05**) — composes with vector/full-text in one statement; not openCypher.
- **Client surface (04-02):** `query/command/sqlscript/begin/commit/rollback/run_in_transaction(body, commit_retries=)/is_ready()(=probe)/ensure_database/from_env`. MVCC conflict = HTTP 503 `ConcurrentModificationException`; `run_in_transaction` owns retry by redoing begin→body→commit from a **fresh** session (don't double-wrap).
- **Schema (04-03 + amendment):** `bootstrap(client, *, dimensions, version)` idempotently creates, per record type, **three channels**:

  | Type | Dense `LSM_VECTOR` | Sparse lexical `LSM_SPARSE_VECTOR` | Lucene `FULL_TEXT` |
  |------|--------------------|-----------------------------------|--------------------|
  | Memory / Entity / Fact / Community | `embedding` | `lexical_tokens, lexical_weights` | `content` |
  | Chunk | `embedding` | `lexical_tokens, lexical_weights` | **`text`** (not `content`) |

  Identity: UNIQUE `id` = `stable_id()` (User uses UNIQUE `identifier`). `versioned_vector_index(base, user, version)` = blake2b tenant digest + `_v{version}` suffix (the per-tenant/D-07 atomic-swap seam). `introspect_vector_dimension` samples a record (introspection does not expose vector dims). CREATE INDEX has **no `IF NOT EXISTS`** → idempotency via catch-"already exists".
- **Seam (04-04):** `store_core.py` (386 LOC). `_write_many` → one `run_in_transaction` (read-your-writes, D-08). `_load_vectors`/CSV deleted. Readiness = live `is_ready()` probe wired to the `RuntimeSignals "graph"` stage; `load_graph_after_restart` **renamed → `reconnect()`**; `/health` returns 503 when not ready. `store_from_env` builds `ArcadeDBClient.from_env()`.

---

## KEY DECISION — Lexical channel = BOTH (user, this session)

The spike's **D-04 chose `LSM_SPARSE_VECTOR`**; the pre-spike Wave-4 plans assumed **Lucene full-text on `content`**. The user resolved the conflict: **provision BOTH channels, both feeding the existing Python RRF** (max lexical signal + Phase-6 comparability). Consequences for the remaining plans (override their pre-spike "native Lucene" / lexical-silent wording):

1. **Shared sparse encoder** — promote the spike's validated `_sparse_vector` (blake2b hash-bucketed TF-IDF, `scripts/arcadedb_spike.py`) into a proper `src/` module. **Establish it in 04-05; reuse it verbatim in 04-06/07/08.** Write-side and query-side tokenization MUST be identical or sparse retrieval silently degrades.
2. **Writes (04-05 memory, 04-06 documents)** populate `lexical_tokens`/`lexical_weights` (sparse) on each searchable vertex; the raw text (`content`, or `text` for Chunk) is already written and Lucene auto-indexes it.
3. **Search (04-07)** queries BOTH lexical channels — `vector.sparseNeighbors` AND `SEARCH_INDEX(...) ORDER BY $score` — and feeds both into RRF. **`SEARCH_INDEX` fragility is now load-bearing:** unescaped Lucene special chars (`?`, `*`, `(`, `)`, …) can raise `IndexException`; escape the query string first.
4. **Rebuild (04-08)** re-populates BOTH lexical channels.

---

## What to do (remaining work, in order)

### Wave 4 — mixin ports (sequential: 04-05 → 06 → 07 → 08)
Each: port its mixins to route through the 04-04 seam using the settled facts above; extract verbose query builders into the planned `store_*_queries.py` sibling to stay < 600 LOC; keep every path `user_identifier`-scoped + fail-closed (invariant #1); bound params only; `stable_id` canonical, **no `vector_id`**; verify against its OWN new `test_store_arcadedb_*.py` (NOT the full suite — transiently red by design). Apply the both-channels deltas above.

### Wave 5 — 04-09 close the port (EXPANDED SCOPE)
Beyond its literal plan (delete `vector_id` machinery, tenant-isolation + chaos-restart guards, ArcadeDB e2e in the Phase-3 baseline shape):
- **Full non-integration suite must return to green** — migrate/supersede all remaining transiently-red tests once the whole store is ArcadeDB.
- **Fix source orphans of the seam rename:** `e2e_score.py` (in-scope) and **`benchmark_stages.py` (NOT in any plan's `files_modified` — must be added)** still call the renamed `store.load_graph_after_restart()` → `reconnect()`.
- Then the phase Definition of Done: `pytest` green + `ruff` + `docker compose config --quiet` + ArcadeDB-backed e2e + real-document E2E, then push.

---

## Test-migration debt (transiently-red by design)

04-04's seam change broke **23 pre-existing unit tests** (all fake-`TuringDB` contract-breaks — **zero regressions**; full list in `04-04-SUMMARY.md` "Migration Debt"). A mixin's tests can only be migrated when its mixin ports (they assert the query dialect), so the suite stays partially red until Wave 5. Routing:

- **Foundational (04-05):** add `is_ready()` to the shared store test-double / fixtures — clears the widest cohort (fakes lacking `is_ready()` AttributeError across governance/observability/retrieval/community).
- **04-05:** `test_batch_memory_write` (retired per-batch-submit), memory parts of `test_batch_memory`.
- **04-06:** document-search + ingest-span + document-expiry parts (`test_retrieval_filters`, `test_observability`, `test_governance`).
- **04-07:** `test_fused_memory_search` (3), memory-search/context filters, search spans.
- **04-08:** `test_batch_memory` rebuild-projection, `test_community_detection`.
- **04-09 consolidation:** `test_runtime_pipeline` (6 — `store_from_env` now builds `ArcadeDBClient`, patch that not `TuringDB`), `test_store_entity_processing` (deleted `_ensure_graph_loaded`), and any residual cross-cutting expiry/span tests.

Rules: NO skip-as-green (conftest guard is active); delete a test only if genuinely superseded by a new `test_store_arcadedb_*.py`, with justification in the SUMMARY.

---

## Standing prohibitions / invariants (unchanged through the port)
- TuringDB compose service + `turingdb==1.35` dependency are **RETAINED** (removal is Phase 7 / ARC-10). Add-only.
- `stable_id()` canonical; ArcadeDB RID (`#12:34`) never an identifier. No `vector_id`. Full-precision COSINE only (D-01, no quantization).
- Invariant #1: every read/write `user_identifier`-scoped, fail-closed on empty. 600-LOC cap per file (pre-commit `check-file-size.sh`, all tracked `*.py`). stdlib `urllib` only (no httpx/requests).
