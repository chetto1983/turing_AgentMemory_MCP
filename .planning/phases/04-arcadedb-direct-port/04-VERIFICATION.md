---
phase: 04-arcadedb-direct-port
verified: 2026-07-14T06:23:21Z
status: passed
score: 4/4 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 3/4
  gaps_closed:
    - "Full-text runs on native Lucene and the SQLite-FTS5 outbox is retired (Success Criterion #3 / ARC-06) — write-side outbox (prepare/commit_batch/replay/discard_prepared) fully retired by plan 04-10"
  gaps_remaining: []
  regressions: []
human_verification: []
---

# Phase 04: ArcadeDB Direct Port Verification Report

**Phase Goal:** `store.py` runs entirely on ArcadeDB — graph, vector, and full-text — with stable IDs preserved, replacing every TuringDB query in place with no abstraction layer.
**Verified:** 2026-07-14T06:23:21Z
**Status:** passed
**Re-verification:** Yes — after gap closure (plan 04-10) + code-review fix cycle (04-REVIEW.md, 10/10 findings resolved)

## What changed since the prior verification

The prior verification (2026-07-14T01:09:12Z) returned `gaps_found` (3/4) with exactly one
gap: Success Criterion #3 / ARC-06's write-side SQLite-FTS5 outbox (`sparse_index.prepare/
commit_batch/replay/discard_prepared`) was still live in `store_memory_write.py`,
`store_memory_read.py`, `store_rebuild.py`, and `store_rebuild_sparse.py`, reachable whenever
`AGENTMEMORY_FUSION_ENABLED=true`.

Since then:

1. **Plan 04-10** removed the last four write-side outbox call sites (`store_messages`,
   `update_memory`, `delete_memory`, `rebuild_communities`), deleted the orphaned
   `store_rebuild_sparse.py` mixin, and fixed a real unhandled `SparseSchemaMismatch` crash on
   fresh deployment volumes with fusion enabled.
2. **04-REVIEW.md** (deep code review, 21 files) found 10 issues (1 critical, 3 high, 3
   medium, 3 low) — 3 of them (CR-01, HI-01, HI-02) were genuine tenant-isolation
   defense-in-depth gaps in graph traversal/soft-delete statements that only filtered the seed
   record by `user_identifier`, not every hop. All 10 were fixed and each carries a dedicated
   regression test that plants a cross-tenant record/edge directly and asserts no leak.

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | An `arcadedb` Compose service (`arcadedata/arcadedb:26.7.1`) with a persistent data volume starts healthy, and a thin `arcadedb_client.py` (stdlib `urllib`) performs graph/vector/full-text ops, with filtered-ANN + Lucene-analyzer behavior validated empirically first | ✓ VERIFIED | Unchanged since prior verification. `compose.yaml` `arcadedb` service pinned image, named volume, healthcheck; `arcadedb_client.py` stdlib-`urllib`-only imports confirmed by re-read. |
| 2 | All graph CRUD (memories, documents, chunks, entities, facts, communities, all edges) is served by ArcadeDB SQL — no `turingdb` calls remain in `store.py` read/write paths | ✓ VERIFIED | Re-ran `grep -rniE "turingdb\|TuringDB\(" store_core.py store_documents.py store_memory_read.py store_memory_write.py store_search.py store_rebuild.py store_evidence.py store_chunking.py store_utils.py store.py` — only comment-only historical references remain, zero live calls. `turingdb` service/dependency intentionally retained (Phase 7 concern per REQUIREMENTS.md ARC-10). |
| 3 | Vector search on ArcadeDB native `LSM_VECTOR` (HNSW) with `vector_id` deleted (not ported), on a versioned/namespaced index foundation; full-text on native Lucene, SQLite-FTS5 outbox retired (both-channels: BOTH `LSM_SPARSE_VECTOR` AND Lucene `FULL_TEXT` feed the unchanged RRF) | ✓ VERIFIED (gap closed) | **Vector-search half:** unchanged, still fully verified (`grep -rlE "\bvector_id\b\|_memory_vector_id\|..."` = 0 matches). **Full-text/outbox half — now closed:** `grep -rnE "sparse_index\.(prepare\|commit_batch\|replay\|discard_prepared)\("` across `store_memory_write.py`/`store_memory_read.py`/`store_rebuild.py` = 0 matches (verified independently, not just quoted from SUMMARY); repo-wide grep for the same pattern across all of `src/turing_agentmemory_mcp/*.py` = 0 matches; `store_rebuild_sparse.py` confirmed deleted (`ls` fails with "No such file or directory"). Native `sparse_vector()` → `lexical_tokens`/`lexical_weights` still written on every memory/entity/fact create (`store_memory_write.py:375,446,493`). `store_evidence.py`'s `_lexical_evidence`/`_merged_lexical_scores` still merge native `vector.sparseNeighbors` + Lucene `SEARCH_INDEX`, both feeding the unchanged RRF (unchanged from prior verification, re-confirmed by re-read). |
| 4 | `stable_id()` remains the sole cross-record identifier, stored as an indexed ArcadeDB property (never native RID); no vector-ID drift across the port | ✓ VERIFIED | Unchanged. `ids.py` re-read: only `stable_id()`/`cypher_var()` remain, no `vector_id`. `tests/test_vector_id_absent.py` + `tests/test_stable_id_survives_rebuild.py` re-run directly: pass. |

**Score:** 4/4 truths verified (0 present, behavior-unverified)

### Note on `sparse_index.py` / `SparseIndex` construction (not a gap)

`server.py` still imports `SparseIndex` and constructs it (`sparse_index=SparseIndex(sparse_path)
if fusion_enabled else None`), and `store_core.py` still holds a `self.sparse_index` reference
used only by `runtime_status()`'s diagnostic `.status()` call. This is deliberate and
explicitly scoped out of 04-10 (confirmed in 04-10-SUMMARY.md's "Decisions Made" and re-verified
here): the gap that was found and fixed was specifically the **write outbox call sites**
(`prepare/commit_batch/replay/discard_prepared`), which are now completely gone. Retaining the
class import/construction/status-diagnostic is not a violation of Success Criterion #3's
"outbox retired" — the prepare/commit/replay path (the actual "outbox" mechanism) is what was
retired, and it is. `store_core.py:149`'s `identity={"backend": "sqlite-fts5"}` label is a
stale diagnostic string (flagged Info-level, non-blocker, in the prior verification) — still
present, still cosmetic only, not part of any must-have.

`admin_repair.py`'s `repair_sparse_projection()`/`repair_community_projection()` functions
still reference `SparseIndex`/`SparseDocument`, but neither is wired to the `repair-vector-index`
CLI command (confirmed via `grep` on `cli.py` — only `repair_vector_index`, an unrelated
TuringDB-vector-quarantine tool, is dispatched). These two functions are pre-existing dead code,
outside 04-10's scope (the gap it closed was specifically the store_messages/update_memory/
delete_memory/rebuild_communities write paths) and outside any of the 9 requirement IDs mapped
to this phase. Not treated as a gap.

### Tenant-Isolation Hardening (code review, verified live in source + tests)

| Finding | File | Fix Confirmed | Regression Test Confirmed |
|---|---|---|---|
| CR-01 | `store_retrieval_queries.py::entity_traversal_statement` | Every hop (`e`, `n`, `f`, `m`) now binds `user_identifier = :user_identifier`, not just the seed — re-read directly, confirmed | `tests/test_store_arcadedb_retrieval.py::test_expand_entity_evidence_never_crosses_tenant_via_intermediate_hops` — plants a cross-tenant intermediate entity + fact + memory via direct edges at hop=1 and hop=2, asserts `_expand_entity_evidence` returns `[]` and `search_memory` never leaks. Ran directly: pass. |
| HI-01 | `store_documents_queries.py::chunk_context_statement` | Now takes `user_identifier` and binds it in both inner and outer `WHERE` — re-read, confirmed | `tests/test_store_arcadedb_documents.py::test_chunk_context_never_crosses_tenant_via_next_chunk_edge`. Ran directly (as part of the targeted 99-test run): pass. |
| HI-02 | `store_memory_queries.py::memory_delete_statements` (Fact soft-delete) | `UPDATE Fact ... AND user_identifier = :user_identifier` now matches its sibling Memory-status UPDATE — re-read, confirmed | `tests/test_store_arcadedb_memory.py::test_delete_memory_never_soft_deletes_another_tenants_fact` — plants a cross-tenant fact via a monkeypatched `_fact_ids_for_memory`, asserts the row is untouched by `delete_memory`. Ran directly: pass. |
| HI-03 | `store_documents.py::reindex_document_text` | Hard-delete + recreate folded into one managed transaction (per 04-REVIEW.md Fix Outcomes, live-verified against a real ArcadeDB container by the fixer) | Regression test asserts exactly one begin/commit cycle (part of full-suite green). |

These three (CR-01/HI-01/HI-02) directly serve CLAUDE.md invariant #1 (every read/write
explicitly scoped by `user_identifier`, fail-closed) — this milestone's core value. All three
fixes are present in source (independently re-read, not just quoted from 04-REVIEW.md) and each
has a dedicated regression test that plants the exact cross-tenant condition the finding
described and asserts no leak, not a generic smoke test.

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|---|---|---|---|---|
| ARC-02 | 04-01, 04-04 | ArcadeDB Compose service with persistent volume | ✓ SATISFIED | Unchanged; `compose.yaml` re-confirmed. |
| ARC-03 | 04-01, 04-02 | Thin stdlib-`urllib` `arcadedb_client.py` | ✓ SATISFIED | Unchanged; stdlib-only imports re-confirmed. |
| ARC-04 | 04-04, 04-05, 04-06, 04-07, 04-08 | All graph CRUD via ArcadeDB SQL, no abstraction layer | ✓ SATISFIED | Re-confirmed no turingdb calls in store read/write paths. |
| ARC-05 | 04-03, 04-05, 04-06, 04-07, 04-08, 04-09 | Native `LSM_VECTOR` (HNSW); `vector_id` deleted not ported | ✓ SATISFIED | Zero `vector_id` references repo-wide, re-confirmed. |
| ARC-06 | 04-03, 04-04, 04-06, 04-07, **04-10** | Native Lucene full-text; SQLite-FTS5 outbox retired | ✓ **SATISFIED (gap closed)** | Write-side `prepare/commit_batch/replay/discard_prepared` now 0 matches repo-wide; `store_rebuild_sparse.py` deleted; read-side (04-07) unchanged and still verified. |
| ARC-08 | 04-03, 04-05, 04-09 | Stable IDs preserved; no vector-ID drift | ✓ SATISFIED | `tests/test_stable_id_survives_rebuild.py` re-run: pass. |
| PERF-01 | 04-05, 04-06 | Batch embedding API (single round-trip) | ✓ SATISFIED | Unchanged; `_embed_many` re-confirmed. |
| PERF-02 | 04-05 | Batched memory extraction (no per-item HTTP) | ✓ SATISFIED | Unchanged; `extract_many` re-confirmed. |
| INFRA-03 | 04-03, 04-08 | Vector-index versioning (atomic swap) | ✓ SATISFIED | Unchanged; `versioned_vector_index()` + atomic swap re-confirmed. |

All 9 requirement IDs declared across the 10 plans' frontmatter (`requirements:` fields) —
ARC-02, ARC-03, ARC-04, ARC-05, ARC-06, ARC-08, PERF-01, PERF-02, INFRA-03 — match exactly the 9
IDs REQUIREMENTS.md maps to Phase 4, all marked `[x]`/`Complete`. No orphaned requirements.

### Behavioral Spot-Checks / Full-Suite Verification (independently re-run this session)

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full non-integration suite green | `.venv/Scripts/python.exe -m pytest -q` | `514 passed, 2 warnings in 45.24s` (up from 501 at prior verification; matches 04-REVIEW.md's claimed final count exactly) | ✓ PASS |
| Lint clean | `.venv/Scripts/python.exe -m ruff check src tests scripts` | `All checks passed!` | ✓ PASS |
| Compose config valid | `docker compose config --quiet` | exit 0 | ✓ PASS |
| File-size cap | `bash scripts/check-file-size.sh` | `all tracked *.py files within the 600-LOC cap` | ✓ PASS |
| Write-side outbox calls gone | `grep -rnE "sparse_index\.(prepare\|commit_batch\|replay\|discard_prepared)\(" src/turing_agentmemory_mcp/store_memory_write.py store_memory_read.py store_rebuild.py` | 0 matches | ✓ PASS |
| Write-side outbox calls gone, repo-wide | same pattern across all of `src/turing_agentmemory_mcp/*.py` | 0 matches | ✓ PASS |
| `store_rebuild_sparse.py` deleted | `ls src/turing_agentmemory_mcp/store_rebuild_sparse.py` | "No such file or directory" | ✓ PASS |
| Targeted ARC-06/tenant-isolation/rebuild/retrieval regression suite | `pytest tests/test_vector_id_absent.py tests/test_stable_id_survives_rebuild.py tests/test_arcadedb_tenant_isolation.py tests/test_arcadedb_chaos_restart.py tests/test_store_arcadedb_retrieval.py tests/test_store_arcadedb_documents.py tests/test_store_arcadedb_memory.py tests/test_store_arcadedb_rebuild.py -q` | `99 passed` | ✓ PASS |
| No debt markers in touched files | `grep -nE "TBD\|FIXME\|XXX"` across 8 store/query files touched by 04-10 + the review fixes | no matches | ✓ PASS |

### Probe Execution

Skipped — no `scripts/*/tests/probe-*.sh` convention exists in this repo and none is declared in
any 04-*-PLAN.md/SUMMARY.md (unchanged from prior verification).

### Anti-Patterns Found

None remaining that block the phase goal. The two anti-patterns flagged in the prior
verification (`store_memory_write.py`'s live write to the retired outbox, and
`store_rebuild.py`/`store_rebuild_sparse.py`'s same pattern) are both resolved — confirmed by
direct re-grep, not by trusting the SUMMARY. The `store_core.py:149` stale
`identity={"backend": "sqlite-fts5"}` label remains and is still ℹ️ Info-level only (ARC-06's
must-have is about the outbox mechanism, not this diagnostic string).

### Deferred Items

None. `ARC-07`/`TEST-05` (per-tenant database isolation, concurrent-isolation tests) remain
correctly scoped to Phase 5 per REQUIREMENTS.md/ROADMAP.md — not a Phase 4 gap.

### Human Verification Required

None. All findings were programmatically verifiable via source inspection, grep, and direct
test/lint/compose/file-size execution, run independently in this session rather than trusted
from SUMMARY/REVIEW claims.

### Gaps Summary

No gaps remain. The single gap from the prior verification (write-side SQLite-FTS5 outbox not
retired, Success Criterion #3 / ARC-06 partial) is closed: plan 04-10 removed every remaining
`sparse_index.prepare/commit_batch/replay/discard_prepared` call site and deleted the orphaned
`store_rebuild_sparse.py` mixin, independently re-verified here via direct grep (0 matches,
repo-wide) rather than by trusting the SUMMARY's own grep output. The subsequent code review
(04-REVIEW.md) found and fixed 10 additional issues, 3 of which (CR-01, HI-01, HI-02) were
genuine tenant-isolation defense-in-depth gaps directly relevant to this milestone's core value
(CLAUDE.md invariant #1) — all three fixes are confirmed live in source and each carries a
targeted regression test that plants the exact cross-tenant condition and asserts no leak,
independently re-run in this session (all pass). The full suite (514 passed, 0 failed), ruff,
`docker compose config --quiet`, and the file-size cap are all independently confirmed green.
All 9 requirement IDs mapped to Phase 4 are satisfied with no orphans. Phase 4's goal —
`store.py` runs entirely on ArcadeDB (graph, vector, full-text) with stable IDs preserved and no
abstraction layer — is fully achieved.

---

*Verified: 2026-07-14T06:23:21Z*
*Verifier: Claude (gsd-verifier)*
*Re-verification of: .planning/phases/04-arcadedb-direct-port/04-VERIFICATION.md (2026-07-14T01:09:12Z, gaps_found, 3/4)*
