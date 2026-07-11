# Turing AgentMemory MCP — Stabilization Milestone

## What This Is

An Agent Memory MCP server (`turing_agentmemory_mcp`) that exposes memory-lifecycle
and document tools over FastMCP, stores canonical graph + vector records in a graph+vector
database, and serves tenant-scoped, cited retrieval. It is currently TuringDB-backed and
**migrates to ArcadeDB as its sole backend this milestone** (chosen on licensing —
Apache-2.0). Provider integrations
(embedding, rerank, GLiNER2 entity extraction) are OpenAI-compatible HTTP endpoints.
This milestone hardens an already-built system: it stands the **entire infrastructure
up on Docker as a reliable one-command stack**, works through **every concern** in the
codebase audit, and installs **CI plus pre-commit / pre-push hooks** modeled on the
Aura project's engineering discipline.

## Core Value

The system must remain correct and tenant-isolated under stabilization: after every
change, a real document flows end-to-end through the dockerized MCP (async job →
truthful terminal state → canonical chunks → scoped cited search → staged bytes removed)
and the deterministic E2E score gate stays green. Stabilization that breaks retrieval
correctness or tenant isolation is a failure, not progress.

## Requirements

### Validated

<!-- Inferred from the existing codebase map (.planning/codebase/). Shipped and relied upon. -->

- ✓ FastMCP server exposing 25+ memory/document/entity/fact/community tools over stdio/HTTP/SSE — existing
- ✓ TuringDB-canonical store with graph writes + multi-index vector ops (`store.py`) — existing
- ✓ Multi-signal fused retrieval (dense, BM25, entity, graph, community) with weighted RRF + guarded rerank — existing
- ✓ SQLite FTS5 sparse index as a rebuildable projection — existing
- ✓ Async, durable, resumable document ingestion (SQLite job queue, lease/heartbeat worker, PDFium + MarkItDown) — existing
- ✓ Derived projections: entity/memory extraction, temporal graph, native Leiden community detection — existing
- ✓ Governance: pattern redaction, content-free audit JSONL, `expires_at` retention filtering — existing
- ✓ Per-operation `user_identifier` tenant scoping enforced at the store layer — existing
- ✓ Docker Compose reference stack (TuringDB, embed, rerank, GLiNER, MCP, lab) with healthchecks — existing
- ✓ Deterministic E2E score gate + real-document benchmark harness (`scripts/`) — existing

### Active

<!-- The stabilization milestone. Hypotheses until shipped and validated. -->

**Thrust 1 — Infrastructure on Docker (one-command stack)**

- [ ] `docker compose up` brings the whole stack up healthy and reproducibly from a clean checkout
- [ ] The E2E score gate runs green against the dockerized stack (not just in-process stubs)
- [ ] A real document verifies end-to-end through the dockerized MCP
- [ ] Compose config validates (`docker compose config --quiet`) and healthchecks gate readiness

**Thrust 2 — Clean every concern in CONCERNS.md (full scope, heavyweight swaps)**

- [ ] Tech debt: upload-session TTL/persistence + thread safety, multi-worker document ingestion, stale-vector cleanup, cooperative-cancellation timeouts
- [ ] Known bugs: vector-rebuild stale index, upload state lost on restart, session-expiry enforcement
- [ ] Security: hard-delete + audit, redaction pattern coverage, audit-sink durable flush, bearer-token log redaction
- [ ] Performance: batch embedding API, batched memory extraction, vector-search fetch tuning
- [ ] Fragile areas hardened with crash-recovery tests: document job state machine, sparse-index outbox replay, temporal-graph projection, query-graph evidence
- [ ] **Backend replacement (heavyweight):** cut TuringDB entirely and **direct-port `store.py` to ArcadeDB** (Apache-2.0; chosen on licensing) — no driver-abstraction layer, ArcadeDB is the sole backend. Fresh start: no data migration (no production data to preserve).
- [ ] **Vector + full-text on ArcadeDB (research-resolved):** use ArcadeDB native HNSW (`LSM_VECTOR`) vector search + native Lucene full-text — no separate external search engine or vector DB. Research confirmed production-adequate below ~1–5M vectors/tenant.
- [ ] **Migration-correctness gate:** snapshot the current TuringDB retrieval baseline (`e2e_score.py` + `real_document_benchmark.py`) BEFORE removal; the ArcadeDB port must meet-or-exceed it as a hard exit criterion.
- [ ] **Remaining heavyweight items:** Garage (S3-compatible) object storage for staged files (MinIO CE is dead/archived), tenant isolation via one ArcadeDB database per tenant, OAuth/OIDC via FastMCP's built-in `OAuthProxy`/`OIDCProxy` (no new dep) with `user_identifier` derived from verified token claims, vector-index versioning, `expires_at` purge enforcement, extensible observability/metrics hooks
- [ ] At-risk dependencies: version-gate graspologic-native / fastmcp with tests (the TuringDB coupling risk is eliminated by removing TuringDB)
- [ ] Test-coverage gaps closed: concurrent multi-tenant isolation, large-document ingestion, rebuild-under-query, sparse crash recovery, lease/timeout, extraction failure modes

**Thrust 3 — CI + git hooks (modeled on Aura)** — ✓ Validated in Phase 1 (CI + Git-Hook Discipline)

- [x] `lefthook.yml` with fast `pre-commit` (ruff format/check, file-size cap) and `pre-push` (import/compile check, fast pytest subset, `docker compose config`)
- [x] `.github/workflows/ci.yml` job matrix: lint (ruff), unit tests (pytest), dockerized integration + E2E score gate, compose validation, supply-chain scan (pip-audit)
- [x] No-skip-as-green discipline: a skipped test tier fails the gate rather than passing it green
- [x] Heavy gates (full E2E, real-doc E2E, coverage) live in CI; hooks stay fast enough not to be habitually bypassed
- Note: the headline enabler — decomposing `store.py` (3891 LOC) into a 34-LOC facade + 9 ≤600-LOC mixins so the no-allowlist 600-LOC cap applies with zero exemptions — was completed and is behavior-preserving (362→364 tests green; Docker E2E byte-identical to the pre-phase baseline). The local/CI *stub* E2E is 18/19 (score 9.474) — a pre-existing `HashingEmbedder`-stub limitation on one semantic document-search check; full VALIDATED_10_10 requires the real-embed GPU CI tier.

**Thrust 4 — UTCP spike (early de-risk)**

- [ ] Early roadmap phase: spike deeper UTCP (Universal Tool Calling Protocol) support — native serving over UTCP alongside MCP vs the current manual export (`utcp.py` / `utcp-manual`), validated against real UTCP clients/spec (https://github.com/universal-tool-calling-protocol)
- [ ] Spike produces a findings verdict; any resulting UTCP build work is gated on that verdict, not assumed

### Out of Scope

- New product features unrelated to the audited concerns — [this is a stabilization milestone, not a feature milestone]
- Rewriting the retrieval-fusion algorithm or ranking weights — [current fusion is Validated; stabilize, don't redesign scoring]
- Changing the embedding model — [would require rebuilding all vectors; orthogonal to stabilization, gate separately]
- Frontend/Lab redesign beyond what a concern requires — [not an audited concern this milestone]

## Context

- Existing, substantial Python 3.11+ codebase; `store.py` is the large central module. Read `.planning/codebase/` (ARCHITECTURE, STACK, INTEGRATIONS, CONCERNS, CONVENTIONS, STRUCTURE, TESTING) for the full audit.
- CONCERNS.md (2026-07-11) enumerates 6 tech-debt items, 3 known bugs, 4 security considerations, 4 perf bottlenecks, 4 fragile areas, 4 scaling limits, 3 at-risk deps, 7 missing features, and 6 test-coverage gaps — all in scope this milestone.
- CI/hook discipline is modeled on `D:\Repo\Aura` (lefthook + GitHub Actions, no-skip-as-green, fast hooks / heavy gates in CI). Aura is Go; this repo is Python, so the *discipline* is mirrored and the *tooling* adapted (ruff, pytest, the E2E score gate, `docker compose config`).
- The E2E stack's default CUDA embed/rerank sidecars require an NVIDIA GPU visible to Docker; CI on GPU-less runners must degrade those tiers to a compile/stub floor without silently skipping (Aura's pattern).
- ArcadeDB source cloned for reference at `d:/tmp/arcadedb` (shallow). Relevant modules for the port: `server/` + `network/` (HTTP/JSON API our `urllib` driver targets), `postgresw/` (Postgres-wire adapter — a `psycopg` connection option to weigh vs raw HTTP), `e2e-python/` (official Python examples), `engine/` (LSM + vector/HNSW). Target images: `arcadedata/arcadedb:26.7.1`, `dxflrs/garage:v2.2.0`, Keycloak 26.7.0.

## Constraints

- **Tech stack**: Python 3.11–3.14, FastMCP 3.4–4, TuringDB 1.35, ruff (line-length 100, E501 ignored), pytest — [established; changes are themselves audited concerns, not free choices]
- **Architecture — replaced this milestone**: CLAUDE.md invariant #2 (TuringDB canonical) is superseded — **ArcadeDB becomes the sole canonical backend**; TuringDB is removed. ArcadeDB's native vector + full-text are ACID-consistent with graph writes, retiring the SQLite-FTS5 outbox as a separate rebuildable projection. CLAUDE.md invariants must be updated as part of this milestone. The port must preserve tenant isolation (invariant #1) and stable/deterministic IDs (invariant #3).
- **Tenant isolation**: every read/write explicitly scoped by `user_identifier`, fail-closed on empty — non-negotiable through the port; reinforced by one ArcadeDB database per tenant — [CLAUDE.md invariant #1]
- **Durability**: ArcadeDB data, the SQLite job DB, staged files (moving to Garage/S3), and audit/span JSONL are the durable state; ArcadeDB persists to its own data volume — [server-side CSV vector loading was a TuringDB constraint and no longer applies]
- **GPU dependency**: embed/rerank sidecars are GPU-mandatory for the full stack — [CI must degrade gracefully on GPU-less runners]

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Full-scope stabilization: address every category in CONCERNS.md | User chose "Everything in CONCERNS.md" over stabilization-only | — Pending |
| Cut TuringDB entirely; ArcadeDB is the sole backend, **direct port** of `store.py` (no abstraction layer) | User: "cut off touringdb we decide arcadedb for license" + "direct port to ArcadeDB" — Apache-2.0 licensing | — Pending (⚠ supersedes invariant #2; snapshot baseline before removal) |
| Fresh start — no TuringDB→ArcadeDB data migration | User chose "Fresh start on ArcadeDB"; no production data to preserve | — Pending |
| ArcadeDB native HNSW vector + native Lucene full-text; no separate external search/vector DB | Research confirmed production-adequate below ~1–5M vectors/tenant | — Pending |
| Garage for S3 staging; FastMCP built-in OAuth/OIDC; one ArcadeDB DB per tenant | Research: MinIO CE archived Apr 2026; FastMCP `OAuthProxy` in pinned range; per-DB physical isolation | — Pending |
| One-command Docker stack as the deployment target, verified by the E2E gate | User chose "Reliable one-command stack" | — Pending |
| Done = green gate (pytest + ruff + E2E score) + healthy compose + real-document E2E | User chose "Above + real doc E2E" | — Pending |
| CI + pre-commit + pre-push modeled on Aura (lefthook + GitHub Actions, no-skip-as-green) | User: "install also all ci precommit and prepush look D:\Repo\Aura" | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-12 after Phase 1 (CI + Git-Hook Discipline) completion*
