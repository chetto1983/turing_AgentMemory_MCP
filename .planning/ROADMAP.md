# Roadmap: Turing AgentMemory MCP — Stabilization Milestone

## Overview

This milestone hardens an already-built TuringDB-backed Agent Memory MCP server and cuts it over to ArcadeDB as its sole backend. The journey starts by installing CI + git-hook discipline (protecting every later change), then de-risks UTCP with an early findings-only spike. It snapshots the current TuringDB retrieval baseline as the yardstick, direct-ports `store.py` to ArcadeDB (graph + native vector + native full-text), isolates tenants at the database level, and only removes TuringDB once a hard migration-correctness gate proves the port meets-or-exceeds the baseline. With ArcadeDB as the sole backend, the remaining CONCERNS.md work (ingestion/storage reliability, retrieval performance and vector lifecycle, security/governance, graph-projection robustness) proceeds in parallel off the port — none of it depends on any interface-extraction step, because there is none. The final phase stands the whole stack up as a reliable one-command `docker compose up` and verifies a real document end-to-end.

**Parallelism:** Phases 8–11 each depend only on Phase 7 (ArcadeDB is the sole backend); they parallelize off the port and may run in any order. Phase 12 is the closing integration pass and depends on all of them landing.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: CI + Git-Hook Discipline** - lefthook hooks + GitHub Actions with no-skip-as-green, guarding every downstream change (completed 2026-07-11)
- [x] **Phase 2: UTCP Spike** - Early findings-gated verdict on deeper UTCP support; no build commitment (completed 2026-07-12)
- [x] **Phase 3: TuringDB Retrieval Baseline** - Recorded, versioned baseline snapshot before any ArcadeDB work (completed 2026-07-13)
- [x] **Phase 4: ArcadeDB Direct Port** - `store.py` on ArcadeDB graph + native vector + native full-text, stable IDs preserved (completed 2026-07-14)
- [ ] **Phase 5: Per-Tenant ArcadeDB Isolation** - One database per tenant with mandatory `user_identifier` scoping still enforced
- [ ] **Phase 6: Migration-Correctness Gate** - Ported stack provably meets-or-exceeds the baseline (hard exit criterion)
- [ ] **Phase 7: Remove TuringDB + Dependency Hardening** - TuringDB cut, invariants rewritten, at-risk deps version-gated
- [ ] **Phase 8: Document Ingestion & Storage Reliability** - Durable upload sessions, Garage S3 staging, multi-worker + cancellation
- [ ] **Phase 9: Retrieval Performance & Vector Lifecycle** - Batched embedding/extraction, fetch tuning, versioned vector indexes
- [ ] **Phase 10: Security & Governance Hardening** - OIDC identity, hard-delete + purge, redaction/audit durability, metrics hooks
- [ ] **Phase 11: Graph Projection Robustness** - Crash-recovery + adversarial tests for full-text, temporal, and query-graph projections
- [ ] **Phase 12: Docker One-Command Stack + Real-Doc E2E** - Healthy `docker compose up` from clean checkout, real document verified end-to-end

## Phase Details

### Phase 1: CI + Git-Hook Discipline

**Goal**: Every commit and push is guarded by fast local hooks, and CI enforces the full gate without ever passing a skipped tier green.
**Depends on**: Nothing (first phase; independent of the Docker and backend work — sequenced first so it protects everything downstream)
**Requirements**: CI-01, CI-02, CI-03, CI-04, CI-05, CI-06, CI-07, CI-08, CI-09
**Success Criteria** (what must be TRUE):

  1. `lefthook` wires a pre-commit (ruff format --check, ruff check, and a file-size cap enforcing ≤600 LOC across all tracked `*.py` files with NO allowlist — no file is exempt) and a pre-push (import/compile smoke, fast pytest subset, `docker compose config --quiet`) that run on real commits/pushes.
  2. GitHub Actions runs lint (ruff pinned `0.15.x`), unit tests (pytest, `pythonpath=src`), compose-validation, and pip-audit (`2.10.1`) jobs on every push/PR, plus a dockerized-integration job that runs the E2E score gate + real-document E2E.
  3. A skipped GPU/integration tier fails the CI gate (no-skip-as-green); GPU-less runners degrade GPU tiers to a visible compile/stub floor, never silent green.
  4. A coverage gate enforces a floor measured against the actual current suite (not guessed).
  5. `store.py` (~3900 LOC) is decomposed into cohesive ≤600-LOC modules so the file-size cap passes with no allowlist, with behavior preserved (the E2E score gate and full pytest suite stay green across the split).

**Plans:** 9/9 plans complete
Plans:
**Wave 1**

- [x] 01-01-PLAN.md — Decompose store.py (3891 LOC) into 9 ≤600-LOC mixin modules behind a facade
- [x] 01-02-PLAN.md — Decompose server.py, document_jobs.py, gliner_provider.py
- [x] 01-03-PLAN.md — Decompose benchmark.py + e2e_score.py (preserve the E2E gate's `main` export)
- [x] 01-04-PLAN.md — Decompose the two over-cap operator scripts (real_document_benchmark, eval_backboard_locomo)
- [x] 01-05-PLAN.md — Decompose the two over-cap test files (test_gliner_provider, test_batch_memory)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-06-PLAN.md — Repo-wide ruff format bootstrap + behavior-preservation verification gate

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-07-PLAN.md — check-file-size.sh + lefthook.yml + pyproject/Makefile wiring + CLAUDE.md exception removal

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 01-08-PLAN.md — No-skip-as-green conftest guard + negative self-test (TDD)
- [x] 01-09-PLAN.md — GitHub Actions CI matrix + measured coverage floor + pip-audit + stub E2E floor

**Cross-cutting constraints:**

- scripts/e2e_score.py still prints VALIDATED_10_10 (score >= 9.8) after the split
- The full pytest suite stays at its green baseline (362) after the splits

### Phase 2: UTCP Spike

**Goal**: A findings verdict on whether to natively serve tools over UTCP (vs. the current manual export) exists and gates any future UTCP build work.
**Depends on**: Nothing (independent early spike; no dependency on the backend port — runs early to de-risk)
**Requirements**: UTCP-01
**Success Criteria** (what must be TRUE):

  1. The current `utcp.py` / `utcp-manual` export is exercised against a real UTCP client/spec (https://github.com/universal-tool-calling-protocol) and its gaps are documented.
  2. A written verdict recommends native UTCP serving, staying on manual export, or deferring — with rationale.
  3. No UTCP build work is committed by this phase; any follow-on work is explicitly gated on the verdict.

**Plans:** 3/3 plans complete
Plans:

**Wave 1**

- [x] 02-01-PLAN.md — Static SC#1 conformance evidence: pinned spike-only deps + committed pytest reproducing the auth-type + README `file_path` gaps

**Wave 2** *(blocked on Wave 1 — needs spike deps installed)*

- [x] 02-02-PLAN.md — Live evidence harnesses: mcp round-trip (D-01/02/07/08), throwaway native-http prototype (D-06), optional utcp-agent + llama.cpp chat (D-08a)

**Wave 3** *(blocked on Wave 2 — needs captured evidence)*

- [x] 02-03-PLAN.md — Verdict deliverable: `02-FINDINGS.md` (SC#1 gaps + SC#2 verdict), SC#3 no-build-work guard, and D-10 gating (PROJECT.md decision + conditional gated ROADMAP entry)

### Phase 3: TuringDB Retrieval Baseline

**Goal**: A recorded, versioned retrieval-quality baseline of the current TuringDB stack exists as the yardstick for the migration-correctness gate.
**Depends on**: Nothing (captures the current TuringDB stack before any ArcadeDB code touches it — worthless if captured after the port drifts behavior)
**Requirements**: ARC-01
**Success Criteria** (what must be TRUE):

  1. `scripts/e2e_score.py` and `scripts/real_document_benchmark.py` run against the current TuringDB-backed stack and their numeric results are captured to a versioned artifact.
  2. The baseline artifact records provider config, corpus, and run parameters so it is reproducible and directly comparable later.
  3. The baseline is committed before any ArcadeDB code touches the stack.

**Plans:** 4/4 plans complete

Plans:

**Wave 1**

- [x] 03-01-PLAN.md — Additive D-08 frozen-questions loader (`load_frozen_questions` + `--frozen-questions`) with TDD tests, under the 600-LOC cap

**Wave 2** *(blocked on Wave 1 — runs at a tree that includes the additive loader)*

- [x] 03-02-PLAN.md — Capture both raw baseline JSONs (real-doc benchmark + real-provider e2e) against the live TuringDB stack; obtain corpus `--root` + confirm GPU providers

**Wave 3** *(blocked on Wave 2 — needs the captured raw JSONs)*

- [x] 03-03-PLAN.md — Assemble `baseline/03-turingdb/` (corpus-manifest, frozen-questions, BASELINE.md with D-11 metadata + as-observed D-07 caveats); force-add + commit
- [x] 03-04-PLAN.md — D-12 supplemental hands-on validation (install MCP in Claude Code, verify ingest + cited tenant-scoped retrieval on the Italian corpus)

### Phase 4: ArcadeDB Direct Port

**Goal**: `store.py` runs entirely on ArcadeDB — graph, vector, and full-text — with stable IDs preserved, replacing every TuringDB query in place with no abstraction layer.
**Depends on**: Phase 3 (baseline must be captured before ArcadeDB code touches the stack)
**Requirements**: ARC-02, ARC-03, ARC-04, ARC-05, ARC-06, ARC-08 — plus **pulled forward by user decision (CONTEXT.md D-07/D-08): PERF-01, PERF-02, INFRA-03** (batched embedding/extraction + single-transaction write path; versioned vector index + atomic swap). These are officially mapped to Phase 9; Phase 4 delivers them.
**Success Criteria** (what must be TRUE):

  1. An `arcadedb` Compose service (`arcadedata/arcadedb:26.7.1`) with a persistent data volume starts healthy, and a thin `arcadedb_client.py` (stdlib `urllib` over the HTTP/JSON API) performs graph, vector, and full-text ops in a smoke test — with filtered-ANN and Lucene-analyzer behavior validated empirically first.
  2. All graph CRUD (memories, documents, chunks, entities, facts, communities, and all edges) is served by ArcadeDB SQL — no `turingdb` calls remain in `store.py` read/write paths.
  3. Vector search runs on ArcadeDB native `LSM_VECTOR` (HNSW) with the TuringDB `vector_id` int-join deleted (not ported), built on a versioned/namespaced index foundation; full-text runs on native Lucene with the analyzer validated against golden queries and the SQLite-FTS5 outbox retired.
  4. `stable_id()` remains the sole cross-record identifier, stored as an indexed ArcadeDB property (never ArcadeDB's native RID); no vector-ID drift across the port.

**Plans:** 10/10 plans complete

Plans:

- [x] 04-10-PLAN.md

**Wave 1** *(hard gate — D-02 spike alone; blocks every other plan)*

- [x] 04-01-PLAN.md — D-02 spike: stand up arcadedb 26.7.1 service + minimal urllib client + committed smoke test resolving the 5 §3 unknowns + D-04/D-05 bake-off vs the Phase-3 yardstick (ARC-02, ARC-03)

**Wave 2** *(blocked on Wave 1 — consumes the spike's resolved syntax)*

- [x] 04-02-PLAN.md — Full ArcadeDBClient surface: transaction + commit-retry-N (D-08) + readiness probe (D-10) (ARC-03)
- [x] 04-03-PLAN.md — Idempotent schema bootstrap: versioned LSM_VECTOR + Lucene + UNIQUE stable_id, dimension-mismatch ValueError (D-09/D-07) (ARC-08, ARC-05, ARC-06, INFRA-03)

**Wave 3** *(blocked on Wave 2)*

- [x] 04-04-PLAN.md — store_core seam port: single-transaction writes (D-08) + probe-driven readiness (D-10) + store_from_env/compose env wiring; FTS5-outbox bootstrap retired (ARC-04, ARC-02, ARC-06)

**Wave 4** *(blocked on Wave 3 — parallel mixin ports, distinct files)*

- [x] 04-05-PLAN.md — Memory write/read port: inline vectors on stable_id, batched embed/extract (PERF-01/02), no vector_id (ARC-04, ARC-05, ARC-08, PERF-01, PERF-02)
- [x] 04-06-PLAN.md — Document ingest/chunking/search port: sqlscript+LET, native HNSW + Lucene, adaptive over-fetch (ARC-04, ARC-05, ARC-06, PERF-01)
- [x] 04-07-PLAN.md — Fused memory search + evidence traversal: HNSW dense + Lucene lexical + D-05 graph surface, RRF unchanged (ARC-04, ARC-05, ARC-06)
- [x] 04-08-PLAN.md — Rebuild + D-07 versioned-index atomic swap (no stale) + community-graph sqlscript (ARC-04, ARC-05, INFRA-03)

**Wave 5** *(blocked on Wave 4)*

- [x] 04-09-PLAN.md — Delete vector_id dead code + ID-drift/tenant-isolation/chaos-restart guards (D-10) + parity-comparable ArcadeDB capture (ARC-05, ARC-08)

### Phase 5: Per-Tenant ArcadeDB Isolation

**Goal**: Each tenant gets a physically isolated ArcadeDB database while app-layer `user_identifier` scoping remains mandatory on every query as defense-in-depth.
**Depends on**: Phase 4 (sequenced after the core port so isolation-topology bugs aren't tangled with query-porting bugs)
**Requirements**: ARC-07, TEST-05
**Success Criteria** (what must be TRUE):

  1. Each tenant is provisioned its own ArcadeDB database (physical isolation), created/opened via the client on first use.
  2. Every query still carries explicit `user_identifier` scoping and fails closed on an empty identifier — DB-level isolation never replaces the invariant-#1 contract.
  3. Concurrent multi-tenant isolation tests pass with no cross-tenant leakage under concurrency.

**Plans**: 3/8 plans executed

Plans:

**Wave 1 — Contracts and defense-in-depth**

- [x] 05-01-PLAN.md — Define exact opaque tenant identity and keyed physical database naming (ARC-07)
- [x] 05-02-PLAN.md — Persist a pseudonymous, fail-closed tenant registry and lifecycle state (ARC-07)
- [x] 05-03-PLAN.md — Audit and enforce explicit `user_identifier` predicates across every query surface (ARC-07, TEST-05)

**Wave 2 — Provisioning**

- [ ] 05-04-PLAN.md — Provision and reconcile tenant databases with ready-last lifecycle semantics (ARC-07)

**Wave 3 — Runtime routing**

- [ ] 05-05-PLAN.md — Build immutable tenant store views with single-flight provisioning and bounded caching (ARC-07)

**Wave 4 — Foreground integration**

- [ ] 05-06-PLAN.md — Route foreground server tools through exact tenant-bound stores and layered health checks (ARC-07)

**Wave 5 — Background integration** *(blocked on Wave 4's document-manager resolver contract)*

- [ ] 05-07-PLAN.md — Route uploads and document workers without identity transformation or cross-tenant reuse (ARC-07, TEST-05)

**Wave 6 — Live isolation gate**

- [ ] 05-08-PLAN.md — Prove live A/B/C physical isolation, lifecycle chaos resilience, and operational contracts (ARC-07, TEST-05)

### Phase 6: Migration-Correctness Gate

**Goal**: The ported ArcadeDB stack provably meets-or-exceeds the TuringDB baseline — the hard exit criterion that authorizes cutover.
**Depends on**: Phases 4, 5 (measures the fully-ported, tenant-isolated system against the Phase 3 baseline)
**Requirements**: ARC-09
**Success Criteria** (what must be TRUE):

  1. `scripts/e2e_score.py` and `scripts/real_document_benchmark.py` run against the ArcadeDB-backed stack and are compared against the Phase 3 baseline within a documented tolerance.
  2. Retrieval quality meets or exceeds the baseline (not merely "runs without crashing"); a shortfall blocks removal of TuringDB and everything downstream.
  3. The comparison result is recorded as the gate artifact that authorizes (or blocks) cutover.

**Plans**: TBD

### Phase 7: Remove TuringDB + Dependency Hardening

**Goal**: TuringDB is gone from the codebase and stack, CLAUDE.md invariants are rewritten for ArcadeDB, and remaining at-risk dependencies are version-gated.
**Depends on**: Phase 6 (removal is irreversible — gated strictly after the meet-or-exceed check passes)
**Requirements**: ARC-10, DEP-01, DEP-02
**Success Criteria** (what must be TRUE):

  1. TuringDB is removed from `compose.yaml`, `pyproject.toml`, and docs; the stack runs on ArcadeDB alone.
  2. CLAUDE.md invariants are updated — #2 (TuringDB canonical) superseded, #4/#6 (submit-before-match, `load_graph`) retired or replaced with the ArcadeDB equivalent — while #1 (tenant scope) and #3 (stable IDs) are reconfirmed as still enforced.
  3. `graspologic-native` and `fastmcp` have automated compatibility/version-gate checks so upgrades are tested before adoption.

**Plans**: TBD

### Phase 8: Document Ingestion & Storage Reliability

**Goal**: Document upload and ingestion survive restarts, concurrency, and cancellation, with staged bytes on durable S3-compatible storage.
**Depends on**: Phase 7 (parallelizable off the port; operates on the ArcadeDB-only stack — may run alongside Phases 9–11)
**Requirements**: FIX-01, FIX-02, FIX-03, FIX-04, FIX-05, INFRA-01, TEST-01, TEST-06
**Success Criteria** (what must be TRUE):

  1. Upload sessions persist durably with TTL expiry and thread-safe access; an interrupted upload is recoverable across restart and abandoned sessions are reclaimed (closing the memory leak, the lost-on-restart bug, and the expiry gap).
  2. Staged files live in Garage (`dxflrs/garage:v2.2.0`, S3-compatible) via boto3 with an `AbortIncompleteMultipartUpload` bucket lifecycle rule + checksum verification, shipped together with the TTL'd session persistence (not one half without the other).
  3. Document ingestion runs multiple concurrent workers with per-worker leasing, and canceled jobs actually stop via cooperative-cancellation timeouts wrapping provider/DB calls.
  4. Job state-machine crash-recovery tests (lease timeout mid-op, cancellation during indexing, orphan detection on startup) and large-document ingestion tests (>1GB / thousands of docs) pass.

**Plans**: TBD

### Phase 9: Retrieval Performance & Vector Lifecycle

**Goal**: Embedding, extraction, and vector retrieval are batched and tuned, and vector indexes are versioned with stale entries cleaned up.
**Depends on**: Phase 7 (parallelizable off the port; touches the ArcadeDB vector index — may run alongside Phases 8, 10, 11)
**Requirements**: PERF-01, PERF-02, PERF-03, FIX-06, INFRA-03, TEST-07, TEST-08
> **Pulled forward into Phase 4 (CONTEXT.md D-07/D-08):** PERF-01, PERF-02 (batched embedding/extraction), and INFRA-03 (versioned vector index + atomic swap, which also subsumes the FIX-06 stale-vector fix on the new backend) are DELIVERED in Phase 4. Phase 9's remainder: PERF-03 adaptive-fetch tuning, A/B embedding-model swap/canary/rollback *using* the D-07 foundation, and TEST-07/TEST-08 (rebuild-under-active-queries + extraction failure-mode tests).
**Success Criteria** (what must be TRUE):

  1. Embedding and memory-extraction calls are batched (single round-trip per batch), eliminating per-item HTTP calls for memories and document chunks.
  2. Vector search fetches adaptively (predicate pushdown / adaptive fetch) instead of a fixed 4× over-fetch.
  3. Vector indexes are versioned/namespaced with atomic swap on rebuild, and rebuilds remove stale vectors (no unbounded accumulation or duplicates), enabling A/B embedding-model swap, canary, and rollback.
  4. Vector-rebuild-under-active-queries tests and extraction failure-mode tests (timeouts, malformed responses, rate limiting) pass.

**Plans**: TBD

### Phase 10: Security & Governance Hardening

**Goal**: Identity is verified via OIDC, deletions and redaction are auditable and durable, expired data is actively purged, and custom KPIs are observable.
**Depends on**: Phase 7 (parallelizable off the port; SEC-04 OIDC is backend-independent — may run alongside Phases 8, 9, 11)
**Requirements**: SEC-01, SEC-02, SEC-03, SEC-04, FIX-07, INFRA-02, INFRA-04
**Success Criteria** (what must be TRUE):

  1. OAuth/OIDC via FastMCP `OIDCProxy`/`OAuthProxy` against Keycloak (26.7.0) derives `user_identifier` from verified token claims only; a valid token for tenant A with a client-supplied `user_identifier="tenant-b"` is rejected/overridden.
  2. Hard-delete with audit logging exists alongside soft delete, backup/retention purge is documented, and a background purge enforces `expires_at` (not just read-time filtering).
  3. Redaction pattern coverage is audited, custom patterns are configurable, redaction events are logged, and `Authorization`/bearer tokens are masked in logs.
  4. The audit sink flushes durably (no lost events on crash), and extensible observability/metrics hooks expose custom KPIs (ingestion latency, recall, cost).

**Plans**: TBD

### Phase 11: Graph Projection Robustness

**Goal**: Derived graph projections (full-text/outbox, temporal graph, query-graph evidence) are covered by crash-recovery and adversarial tests.
**Depends on**: Phase 7 (parallelizable off the port; tests ArcadeDB-backed projections — may run alongside Phases 8, 9, 10)
**Requirements**: TEST-02, TEST-03, TEST-04
**Success Criteria** (what must be TRUE):

  1. Full-text/outbox crash-recovery + idempotency is tested — or demonstrably retired by ArcadeDB ACID (via the Phase 4 Lucene port), with a test asserting the retirement.
  2. Temporal-graph projection tests plus entity-canonicalization schema versioning/migration pass, verifying entity-link continuity across canonicalization-rule changes.
  3. Query-graph evidence tests with adversarial entity names (special characters, long names, duplicates) and empty-result fallback pass.

**Plans**: TBD

### Phase 12: Docker One-Command Stack + Real-Doc E2E

**Goal**: `docker compose up` brings the whole ArcadeDB + Garage + Keycloak stack up healthy from a clean checkout, and a real document verifies end-to-end through the dockerized MCP.
**Depends on**: Phases 8, 9, 10, 11 (final integration/verification pass — needs the ArcadeDB, Garage, and Keycloak compose services and all concern work landed)
> **Pulled forward into Phase 4 (CONTEXT.md D-10):** the ArcadeDB reconnect/readiness/chaos-restart work is DELIVERED in Phase 4. Phase 12's remainder: the full one-command stack, real-doc E2E, GPU-visibility, and the Garage/Keycloak services.
**Requirements**: DOCK-01, DOCK-02, DOCK-03, DOCK-04, DOCK-05, DOCK-06, DOCK-07
**Success Criteria** (what must be TRUE):

  1. `docker compose up` brings the whole stack (ArcadeDB, embed, rerank, GLiNER, MCP, lab, Garage, Keycloak) up healthy from a clean checkout, with healthchecks + `depends_on: condition: service_healthy` gating startup order and readiness.
  2. `docker compose config --quiet` validates, and the deterministic E2E score gate runs green against the dockerized stack (not just in-process stubs).
  3. A real document verifies end-to-end through the dockerized MCP (async job → truthful terminal state → canonical chunks → scoped cited search → staged bytes removed on success).
  4. GPU embed/rerank/GLiNER sidecars are reproducibly buildable with GPU visibility verified from inside a compose-started container; CI degrades these tiers to a compile/stub floor on GPU-less runners.
  5. Non-root / read-only container hardening is preserved across all services, including the new ArcadeDB and Garage.

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12.
Phases 8–11 depend only on Phase 7 and may be executed in parallel or reordered among themselves.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. CI + Git-Hook Discipline | 9/9 | Complete    | 2026-07-11 |
| 2. UTCP Spike | 3/3 | Complete    | 2026-07-12 |
| 3. TuringDB Retrieval Baseline | 4/4 | Complete    | 2026-07-13 |
| 4. ArcadeDB Direct Port | 10/10 | Complete    | 2026-07-14 |
| 5. Per-Tenant ArcadeDB Isolation | 3/8 | In Progress|  |
| 6. Migration-Correctness Gate | 0/TBD | Not started | - |
| 7. Remove TuringDB + Dependency Hardening | 0/TBD | Not started | - |
| 8. Document Ingestion & Storage Reliability | 0/TBD | Not started | - |
| 9. Retrieval Performance & Vector Lifecycle | 0/TBD | Not started | - |
| 10. Security & Governance Hardening | 0/TBD | Not started | - |
| 11. Graph Projection Robustness | 0/TBD | Not started | - |
| 12. Docker One-Command Stack + Real-Doc E2E | 0/TBD | Not started | - |

### Phase 13: Harden UTCP support

**Goal:** [To be planned]
**Requirements**: TBD
**Depends on:** Phase 12
**Plans:** 0 plans

Plans:

- [ ] TBD (run /gsd-plan-phase 13 to break down)

---
*Roadmap created: 2026-07-11*
*Coverage: 55/55 v1 requirements mapped to phases (no orphans, no duplicates)*
