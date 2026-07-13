# Phase 4: ArcadeDB Direct Port - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-13
**Phase:** 4-ArcadeDB Direct Port
**Areas discussed:** Lexical/full-text channel, Vector quantization, Graph query surface, Spike gate + ANN fallback, Index-versioning foundation scope, Write transaction & MVCC-retry model, Spike measurement yardstick, Index bootstrap & dimension provisioning, Connection lifecycle & readiness

**Preparatory action (user request):** cloned `mem0ai/mem0` and `neo4j-labs/agent-memory` to `d:/tmp/` and ran two focused study agents to extract patterns relevant to the four query/index decisions. Findings woven into the options below; broader consolidation/GraphRAG patterns confirmed as future-milestone (deferred).

---

## Lexical / full-text channel

| Option | Description | Selected |
|--------|-------------|----------|
| Lucene full-text (primary) + sparse-BM25 fallback | Native Lucene `CONTAINSTEXT` as primary indexed channel; analyzer matched to FTS5; fall to `LSM_SPARSE_VECTOR` if score not orderable | |
| Native `LSM_SPARSE_VECTOR` BM25 (primary) | Sparse-vector BM25 index with explicit IDF/minScore | |
| Spike both, pick by recall | Build both in the SC#1 spike, pick by golden-query recall vs FTS5 baseline | ✓ |

**User's choice:** Spike both, pick by recall
**Notes:** Elevates the lexical-channel choice into the hard-gated SC#1 spike; both feed the existing Python RRF unchanged (mem0 magnitude fusion not adopted). Peer context: neo4j-agent-memory has no lexical channel; mem0 gets it from each store's native lexical.

## Vector quantization

| Option | Description | Selected |
|--------|-------------|----------|
| None / full-precision cosine | float32, COSINE, max recall | ✓ |
| INT8 scalar + rescore/oversample | smaller/faster, small recall hit (mem0 Azure pattern) | |
| BINARY | smallest/fastest, largest recall hit | |

**User's choice:** None / full-precision cosine
**Notes:** Corpus well under the ~1–5M/tenant scale; Phase-3 recall fragility argues against lossy compression during a meet-or-exceed port. Quantization stays a future lever (Pitfall 7 — chosen explicitly).

## Graph query surface

| Option | Description | Selected |
|--------|-------------|----------|
| ArcadeDB SQL (MATCH/TRAVERSE + INSERT/CREATE) | one language spanning traversal + vector + full-text + DDL | |
| Cypher traversals + SQL for vector/DDL | closest to neo4j-agent-memory idioms; splits surface | |
| Decide in the spike | prototype both, pick by binding + composition | ✓ |

**User's choice:** Decide in the spike
**Notes:** Second decision pushed into the spike. Default lean documented as SQL (uniform surface); neo4j-agent-memory's Cypher value was in Neo4j-only procedures we replace anyway.

## Spike gate + ANN fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Hard gate + keep adaptive over-fetch fallback | committed smoke test must pass first; over-fetch default, pushdown only if proven | ✓ |
| Hard gate + commit to native pushdown | delete 4× over-fetch if spike shows pushdown works | |
| Lightweight informational spike | run for info, proceed in parallel | |

**User's choice:** Hard gate + keep adaptive over-fetch fallback
**Notes:** Conservative, parity-protecting. Peer divergence: neo4j naive `$limit*2` (k-underfill unsolved) vs mem0 native pre-filter — ArcadeDB pushdown is the §3 unknown, so bet nothing until measured.

## Index-versioning foundation scope

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal namespacing hook only | version token + single creation helper; no swap logic | |
| Full versioning now | atomic swap + rebuild-without-stale in Phase 4 | ✓ |
| Plain names, retrofit in Phase 9 | plain index names now | |

**User's choice:** Full versioning now
**Notes:** Pull-forward from Phase 9 (INFRA-03). Backed by Pitfall 7 ("versioned from day one"); also fixes the stale-vector rebuild bug on the new backend. Flagged for cross-phase reconciliation.

## Write transaction & MVCC-retry model

| Option | Description | Selected |
|--------|-------------|----------|
| Single-tx + commit-retry now; defer batched embedding | collapse per-batch submits + retry-N; keep batched embedding in Phase 9 | |
| Single-tx + retry AND pull batched embedding in | full Pitfall-7 day-one bundle incl. PERF-01/02 | ✓ |
| Port per-item pattern as-is | harden in Phase 8/9 | |

**User's choice:** Single-tx + retry AND pull batched embedding in
**Notes:** Pull-forward from Phase 9 (PERF-01/02). Read-your-writes collapses invariant #4; `commit retry N` guards MVCC under Phase-8 multi-worker.

## Spike measurement yardstick

| Option | Description | Selected |
|--------|-------------|----------|
| Phase-3 frozen questions + a few lexical-stress queries | parity-aligned + keyword-stress to sharpen analyzer call | ✓ |
| Phase-3 frozen questions only | reproducible, zero authoring; may under-measure lexical | |
| Fresh spike-specific query set | most targeted; not comparable to Phase-6 baseline | |

**User's choice:** Phase-3 frozen questions + a few lexical-stress queries
**Notes:** Ties the spike's "pick by recall" (D-04/D-05) to the committed baseline yardstick while adding keyword/error-code/exact-phrase queries where analyzer regressions (Pitfall 8) surface.

## Index bootstrap & dimension provisioning

| Option | Description | Selected |
|--------|-------------|----------|
| Idempotent startup schema-init, fail-fast on dim mismatch | one routine on store init; ValueError on mismatch | ✓ |
| Explicit provisioning command (migration-style) | separate one-time CLI step | |
| Lazy per-type creation on first write | create on first use | |

**User's choice:** Idempotent startup schema-init, fail-fast on dim mismatch
**Notes:** Mirrors `store_core.py`'s current dimension validation; versioned/namespaced names support the full-versioning decision (D-07).

## Connection lifecycle & readiness

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal now; full resilience in Phase 12 | connect + fail-fast + /health reachability | |
| Full readiness + reconnect now | reconnect + real probe + chaos-restart in Phase 4 | ✓ |
| Match today's TuringDB health behavior 1:1 | replicate stage flags minus load_graph | |

**User's choice:** Full readiness + reconnect now
**Notes:** Pull-forward from Phase 12. Invariant #6 (`load_graph`) retires; `/health` gates on a real probe; chaos-restart test included (Pitfall 1 analog).

## Claude's Discretion

- Exact `arcadedb_client.py` method surface and retry-wrapper location.
- Query-dialect re-expression of entity/fact/community/temporal projections (logic unchanged).
- Number of lexical-stress queries added to the yardstick.
- Wave/plan decomposition (spike as Wave 1, blocking).

## Deferred Ideas

- **Cross-phase reconciliation:** Phase 4 pulls forward Phase 9 (versioning, batched embedding) and Phase 12 (readiness) scope — trim those phases' scope lines at planning/transition; add PERF-01/02, INFRA-03 to the Phase-4 requirement mapping.
- **Future milestone (T1–T5):** memory consolidation, GraphRAG-over-documents, mem0 magnitude fusion, reasoning/procedural memory, POLE+O typology — studied but out of scope; ArcadeDB is the intended substrate after the port.
- Native `vector.fuse`; per-tenant DB (Phase 5); parity gate (Phase 6); TuringDB removal (Phase 7); OIDC + Garage (Phases 10/8).
