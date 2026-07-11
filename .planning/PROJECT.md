# Turing AgentMemory MCP — Stabilization Milestone

## What This Is

A TuringDB-backed Agent Memory MCP server (`turing_agentmemory_mcp`) that exposes
memory-lifecycle and document tools over FastMCP, stores canonical graph + vector
records in TuringDB, and serves tenant-scoped, cited retrieval. Provider integrations
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
- [ ] **Scaling swaps (heavyweight):** migrate sparse index to an external search engine, adopt an external vector DB, move staged files to S3-compatible object storage, add tenant-scoped graph isolation
- [ ] **Missing features (heavyweight):** OAuth/OIDC authentication, vector-index versioning, `expires_at` purge enforcement, extensible observability/metrics hooks
- [ ] At-risk dependencies: abstract TuringDB behind a repository interface; version-gate graspologic-native / fastmcp with tests
- [ ] Test-coverage gaps closed: concurrent multi-tenant isolation, large-document ingestion, rebuild-under-query, sparse crash recovery, lease/timeout, extraction failure modes

**Thrust 3 — CI + git hooks (modeled on Aura)**

- [ ] `lefthook.yml` with fast `pre-commit` (ruff format/check, file-size cap) and `pre-push` (import/compile check, fast pytest subset, `docker compose config`)
- [ ] `.github/workflows/ci.yml` job matrix: lint (ruff), unit tests (pytest), dockerized integration + E2E score gate, compose validation, supply-chain scan (pip-audit)
- [ ] No-skip-as-green discipline: a skipped test tier fails the gate rather than passing it green
- [ ] Heavy gates (full E2E, real-doc E2E, coverage) live in CI; hooks stay fast enough not to be habitually bypassed

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

## Constraints

- **Tech stack**: Python 3.11–3.14, FastMCP 3.4–4, TuringDB 1.35, ruff (line-length 100, E501 ignored), pytest — [established; changes are themselves audited concerns, not free choices]
- **Architecture — under revision this milestone**: CLAUDE.md invariant #2 holds TuringDB canonical with SQLite FTS/vectors as rebuildable projections. The chosen heavyweight swaps (external search engine + external vector DB + S3 staging) deliberately revise this. See Key Decisions — treat each swap as a first-class architecture change with a migration + rollback path, not a drop-in.
- **Tenant isolation**: every read/write explicitly scoped by `user_identifier`, fail-closed on empty — non-negotiable through all swaps — [CLAUDE.md invariant #1]
- **Durability**: TuringDB data, SQLite job DB, staged files, audit/span JSONL live on the shared `/turing` volume — [containers share it because TuringDB loads vectors from server-side CSV]
- **GPU dependency**: embed/rerank sidecars are GPU-mandatory for the full stack — [CI must degrade gracefully on GPU-less runners]

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Full-scope stabilization: address every category in CONCERNS.md | User chose "Everything in CONCERNS.md" over stabilization-only | — Pending |
| Heavyweight external swaps (search engine, vector DB, S3, OAuth/OIDC) rather than pragmatic in-architecture mitigations | User chose "Full heavyweight swaps"; accepts revising the TuringDB-canonical / projections invariant | — Pending (⚠ architecture pivot — sequence with migration + rollback) |
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
*Last updated: 2026-07-11 after initialization*
