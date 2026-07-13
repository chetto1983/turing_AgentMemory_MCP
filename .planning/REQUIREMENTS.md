# Requirements: Turing AgentMemory MCP — Stabilization Milestone

**Defined:** 2026-07-11
**Core Value:** The system stays correct and tenant-isolated under stabilization — after every change a real document flows end-to-end through the dockerized MCP and the deterministic E2E score gate stays green.

## v1 Requirements

Requirements for this stabilization milestone. Each maps to roadmap phases. Scope = every item in `.planning/codebase/CONCERNS.md` plus the four thrusts (Docker, ArcadeDB backend replacement, CI/hooks, UTCP spike), grounded in `.planning/research/SUMMARY.md`.

### Docker (DOCK) — Thrust 1

- [ ] **DOCK-01**: `docker compose up` brings the whole stack (ArcadeDB, embed, rerank, GLiNER, MCP, lab) up healthy from a clean checkout
- [ ] **DOCK-02**: Healthchecks + `depends_on: condition: service_healthy` gate startup order and readiness
- [ ] **DOCK-03**: `docker compose config --quiet` validates as part of the gate
- [ ] **DOCK-04**: The deterministic E2E score gate runs green against the dockerized stack (not just in-process stubs)
- [ ] **DOCK-05**: A real document verifies end-to-end through the dockerized MCP (async job → truthful terminal state → canonical chunks → scoped cited search → staged bytes removed on success)
- [ ] **DOCK-06**: GPU embed/rerank/GLiNER sidecars are reproducibly buildable; CI degrades these tiers to a compile/stub floor on GPU-less runners
- [ ] **DOCK-07**: Non-root / read-only container hardening preserved across all services (incl. new ArcadeDB + Garage)

### ArcadeDB Backend Replacement (ARC) — Thrust 2 core

- [x] **ARC-01**: Snapshot the current TuringDB retrieval baseline (`e2e_score.py` + `real_document_benchmark.py`) before any backend change — the yardstick for the correctness gate
- [x] **ARC-02**: ArcadeDB stood up as a Compose service (`arcadedata/arcadedb:26.7.1`) with its own persistent data volume
- [x] **ARC-03**: Thin `arcadedb_client.py` over ArcadeDB's HTTP/JSON API using stdlib `urllib` (matching `embeddings.py`/`rerank.py`; evaluate the `postgresw` Postgres-wire path as an alternative)
- [x] **ARC-04**: `store.py` graph CRUD ported to ArcadeDB SQL (memories, documents, chunks, entities, facts, communities, and all edges) — direct port, no abstraction layer
- [x] **ARC-05**: Vector search ported to ArcadeDB native `LSM_VECTOR` (HNSW); the TuringDB `vector_id` int-join is deleted, not ported
- [x] **ARC-06**: Full-text ported to ArcadeDB native Lucene; analyzer/tokenizer validated against golden queries; the SQLite-FTS5 outbox prepare/commit/replay path retired
- [ ] **ARC-07**: One ArcadeDB database per tenant for physical isolation, with app-layer `user_identifier` scoping still mandatory on every query (invariant #1)
- [x] **ARC-08**: Stable/deterministic IDs preserved across the port (invariant #3); no vector-ID drift
- [ ] **ARC-09**: Migration-correctness gate — the ported ArcadeDB code meets-or-exceeds the ARC-01 baseline (HARD exit criterion; nothing downstream proceeds until it passes)
- [ ] **ARC-10**: TuringDB removed from the codebase and Compose stack; CLAUDE.md invariants updated (ArcadeDB canonical, invariant #2 superseded)

### Tech-Debt & Bug Fixes (FIX) — Thrust 2 concerns

- [ ] **FIX-01**: Upload sessions get TTL expiry + durable persistence, closing the memory leak and the lost-on-restart bug
- [ ] **FIX-02**: Upload store is thread-safe (locks around `_sessions` access)
- [ ] **FIX-03**: Upload session expiry enforced — no indefinitely-held upload IDs
- [ ] **FIX-04**: Multi-worker document ingestion (thread pool / concurrent workers with per-worker lease management)
- [ ] **FIX-05**: Cooperative-cancellation timeouts wrap provider/DB calls so canceled jobs actually stop
- [ ] **FIX-06**: Vector rebuild removes stale vectors (no unbounded accumulation / duplicates)
- [ ] **FIX-07**: Audit sink flushes durably (no lost events on crash)

### Security (SEC) — Thrust 2 concerns

- [ ] **SEC-01**: Hard-delete with audit logging beyond soft delete; backup/retention purge procedure documented
- [ ] **SEC-02**: Redaction pattern coverage audited, custom patterns configurable, redaction events logged
- [ ] **SEC-03**: `Authorization`/bearer-token redaction in logs (HTTP header masking)
- [ ] **SEC-04**: OAuth/OIDC via FastMCP `OAuthProxy`/`OIDCProxy` (no new dep) with a Keycloak IdP; `user_identifier` derived from verified token claims, never client-supplied

### Performance (PERF) — Thrust 2 concerns

- [ ] **PERF-01**: Batch embedding API for memories and document chunks (single round-trip per batch)
- [ ] **PERF-02**: Batched memory extraction (no per-item HTTP calls)
- [ ] **PERF-03**: Vector-search fetch tuning (predicate pushdown / adaptive fetch instead of fixed 4× over-fetch)

### Storage & Infra (INFRA) — Thrust 2 concerns

- [ ] **INFRA-01**: Document staging on Garage (S3-compatible, `dxflrs/garage:v2.2.0`) via boto3; bucket-side `AbortIncompleteMultipartUpload` lifecycle rule + checksum + TTL
- [ ] **INFRA-02**: `expires_at` purge enforcement (background/compliance purge, not just read-time filtering)
- [x] **INFRA-03**: Vector-index versioning (A/B embedding models, canary, rollback)
- [ ] **INFRA-04**: Extensible observability/metrics hooks for custom KPIs (ingestion latency, recall, cost)

### Fragile Areas & Test Coverage (TEST) — Thrust 2 concerns

- [ ] **TEST-01**: Document job state-machine crash-recovery tests (lease timeout mid-op, cancellation during indexing, orphan detection on startup)
- [ ] **TEST-02**: Full-text/outbox crash-recovery + idempotency tests (or demonstrably retired by ArcadeDB ACID via ARC-06)
- [ ] **TEST-03**: Temporal-graph projection tests + entity-canonicalization schema versioning/migration
- [ ] **TEST-04**: Query-graph evidence tests with adversarial entity names + empty-result fallback
- [ ] **TEST-05**: Concurrent multi-tenant isolation tests (High priority — no cross-tenant leakage under concurrency)
- [ ] **TEST-06**: Large-document ingestion tests (>1GB / thousands of docs — chunking edges, memory, timeouts)
- [ ] **TEST-07**: Vector rebuild under active queries tests
- [ ] **TEST-08**: Entity/memory extraction failure-mode tests (timeouts, malformed responses, rate limiting)

### Dependencies (DEP) — Thrust 2 concerns

- [ ] **DEP-01**: Version-gate `graspologic-native` with automated compatibility testing before upgrades
- [ ] **DEP-02**: Version-gate `fastmcp` (compatibility shim / version-gated tool features)

### CI & Git Hooks (CI) — Thrust 3

- [x] **CI-01**: lefthook `pre-commit` (ruff format --check, ruff check, file-size cap enforcing ≤600 LOC across all tracked `*.py` with NO allowlist — `store.py` is decomposed into ≤600-LOC modules to comply, not exempted; CLAUDE.md's store.py-exception language is removed)
- [x] **CI-02**: lefthook `pre-push` (import/compile smoke, fast pytest subset, `docker compose config --quiet`)
- [x] **CI-03**: GitHub Actions lint job (ruff; pin bumped from stale `>=0.9` to `0.15.x`)
- [x] **CI-04**: GitHub Actions unit-test job (pytest, `pythonpath=src`)
- [x] **CI-05**: GitHub Actions dockerized-integration job running the E2E score gate + real-document E2E
- [x] **CI-06**: GitHub Actions compose-validation + supply-chain scan (pip-audit `2.10.1`)
- [x] **CI-07**: No-skip-as-green — a skipped GPU/integration tier FAILS under CI rather than passing green
- [x] **CI-08**: GPU-less CI degrades GPU tiers to a compile/stub floor (never silent green)
- [x] **CI-09**: Coverage gate with a floor measured against the actual current suite (not guessed)

### UTCP Spike (UTCP) — Thrust 4

- [x] **UTCP-01**: Early findings-gated spike on deeper UTCP support (native serving over UTCP vs the current `utcp.py` manual export), validated against real UTCP clients/spec; produces a verdict — any build work is gated on it

## v2 Requirements

Deferred; tracked but not in this milestone's roadmap.

### Scale / Future Backend

- **SCALE-01**: Dedicated external search engine / vector DB — only if a tenant exceeds ~1–5M vectors (ArcadeDB native is adequate below that)
- **SCALE-02**: TuringDB→ArcadeDB live data-migration tooling — not needed (fresh start chosen); revisit only if a TuringDB deployment must be preserved

### CI

- **CI-10**: Windows CI lane (justified by "Windows/PowerShell is primary" but not explicitly requested — P3 decision at planning time)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Live TuringDB→ArcadeDB data migration | Fresh start chosen; no production data to preserve |
| Repository/driver abstraction, dual-backend conformance suite, `AGENTMEMORY_BACKEND` switch | Superseded by the direct-port decision |
| New product features unrelated to the audited concerns | This is a stabilization milestone |
| Retrieval-fusion algorithm redesign / ranking-weight changes | Fusion is Validated; stabilize, don't re-tune scoring |
| Changing the embedding model | Would require rebuilding all vectors; orthogonal — gate separately |

## Traceability

Each v1 requirement maps to exactly one phase (see `.planning/ROADMAP.md`).

| Requirement | Phase | Status |
|-------------|-------|--------|
| DOCK-01 | Phase 12 | Pending |
| DOCK-02 | Phase 12 | Pending |
| DOCK-03 | Phase 12 | Pending |
| DOCK-04 | Phase 12 | Pending |
| DOCK-05 | Phase 12 | Pending |
| DOCK-06 | Phase 12 | Pending |
| DOCK-07 | Phase 12 | Pending |
| ARC-01 | Phase 3 | Complete |
| ARC-02 | Phase 4 | Complete |
| ARC-03 | Phase 4 | Complete |
| ARC-04 | Phase 4 | Complete |
| ARC-05 | Phase 4 | Complete |
| ARC-06 | Phase 4 | Complete |
| ARC-07 | Phase 5 | Pending |
| ARC-08 | Phase 4 | Complete |
| ARC-09 | Phase 6 | Pending |
| ARC-10 | Phase 7 | Pending |
| FIX-01 | Phase 8 | Pending |
| FIX-02 | Phase 8 | Pending |
| FIX-03 | Phase 8 | Pending |
| FIX-04 | Phase 8 | Pending |
| FIX-05 | Phase 8 | Pending |
| FIX-06 | Phase 9 | Pending |
| FIX-07 | Phase 10 | Pending |
| SEC-01 | Phase 10 | Pending |
| SEC-02 | Phase 10 | Pending |
| SEC-03 | Phase 10 | Pending |
| SEC-04 | Phase 10 | Pending |
| PERF-01 | Phase 9 | Pending |
| PERF-02 | Phase 9 | Pending |
| PERF-03 | Phase 9 | Pending |
| INFRA-01 | Phase 8 | Pending |
| INFRA-02 | Phase 10 | Pending |
| INFRA-03 | Phase 9 | Complete |
| INFRA-04 | Phase 10 | Pending |
| TEST-01 | Phase 8 | Pending |
| TEST-02 | Phase 11 | Pending |
| TEST-03 | Phase 11 | Pending |
| TEST-04 | Phase 11 | Pending |
| TEST-05 | Phase 5 | Pending |
| TEST-06 | Phase 8 | Pending |
| TEST-07 | Phase 9 | Pending |
| TEST-08 | Phase 9 | Pending |
| DEP-01 | Phase 7 | Pending |
| DEP-02 | Phase 7 | Pending |
| CI-01 | Phase 1 | Complete |
| CI-02 | Phase 1 | Complete |
| CI-03 | Phase 1 | Complete |
| CI-04 | Phase 1 | Complete |
| CI-05 | Phase 1 | Complete |
| CI-06 | Phase 1 | Complete |
| CI-07 | Phase 1 | Complete |
| CI-08 | Phase 1 | Complete |
| CI-09 | Phase 1 | Complete |
| UTCP-01 | Phase 2 | Complete |

**Coverage:**

- v1 requirements: 55 total (DOCK 7, ARC 10, FIX 7, SEC 4, PERF 3, INFRA 4, TEST 8, DEP 2, CI 9, UTCP 1)
- Mapped to phases: 55 ✓ (all v1 requirements mapped to exactly one phase)
- Unmapped: 0 ✓ (no orphans, no duplicates)

**By phase:**

- Phase 1 (CI + Git-Hook Discipline): CI-01..09 — 9
- Phase 2 (UTCP Spike): UTCP-01 — 1
- Phase 3 (TuringDB Retrieval Baseline): ARC-01 — 1
- Phase 4 (ArcadeDB Direct Port): ARC-02, ARC-03, ARC-04, ARC-05, ARC-06, ARC-08 — 6
- Phase 5 (Per-Tenant ArcadeDB Isolation): ARC-07, TEST-05 — 2
- Phase 6 (Migration-Correctness Gate): ARC-09 — 1
- Phase 7 (Remove TuringDB + Dependency Hardening): ARC-10, DEP-01, DEP-02 — 3
- Phase 8 (Document Ingestion & Storage Reliability): FIX-01, FIX-02, FIX-03, FIX-04, FIX-05, INFRA-01, TEST-01, TEST-06 — 8
- Phase 9 (Retrieval Performance & Vector Lifecycle): PERF-01, PERF-02, PERF-03, FIX-06, INFRA-03, TEST-07, TEST-08 — 7
- Phase 10 (Security & Governance Hardening): SEC-01, SEC-02, SEC-03, SEC-04, FIX-07, INFRA-02, INFRA-04 — 7
- Phase 11 (Graph Projection Robustness): TEST-02, TEST-03, TEST-04 — 3
- Phase 12 (Docker One-Command Stack + Real-Doc E2E): DOCK-01..07 — 7

---
*Requirements defined: 2026-07-11*
*Last updated: 2026-07-11 after roadmap traceability mapping*
