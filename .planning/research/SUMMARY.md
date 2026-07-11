# Project Research Summary

**Project:** Turing AgentMemory MCP -- Stabilization Milestone
**Domain:** Backend infra migration + full concern-remediation + CI/hooks discipline for an existing Python/FastMCP Agent Memory MCP server
**Researched:** 2026-07-11
**Confidence:** MEDIUM-HIGH (stack/pitfalls/architecture research are cross-checked web sources on ArcadeDB specifics, MEDIUM; CI/hooks research is HIGH, directly grounded in this repo + the Aura precedent; all four files were originally scoped for TuringDB+ArcadeDB *coexistence* and are reframed below per PROJECT.md's authoritative decision to cut TuringDB entirely)

> **Reframing note:** The underlying research files (STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md) were written under a "TuringDB and ArcadeDB coexist behind a driver abstraction" premise. That premise is **superseded**. PROJECT.md now specifies: **cut TuringDB entirely, ArcadeDB is the sole backend, direct-port `store.py`, no abstraction layer, no coexistence, no data migration (fresh start).** This summary re-frames every finding accordingly. Do not resurrect "driver interface / `backends/` package / dual-backend CI matrix / repository-per-backend conformance suite" language from ARCHITECTURE.md when planning phases. What *does* carry forward unchanged: the call-site inventory of `store.py`'s ~40 TuringDB-query methods (still the map of what needs porting), the ID-portability analysis (`stable_id()` portable, `vector_id()` int-join is TuringDB-only and gets deleted, not ported), and the vector+full-text strategy (ArcadeDB native `LSM_VECTOR` + native Lucene, no external search/vector service).

## Executive Summary

This is a stabilization milestone on an already-functioning, substantial Python MCP server (`store.py` is the ~3900-line central module). The milestone has four thrusts: (1) make the Docker Compose stack a reliable one-command deployment, (2) replace TuringDB with ArcadeDB as the sole backend via a direct port, plus close every item in CONCERNS.md, (3) install CI + git-hook discipline mirrored from the Aura project (lefthook + GitHub Actions, no-skip-as-green), and (4) spike deeper UTCP protocol support early to de-risk it.

The backend swap is a **direct port, not an abstraction exercise**: `store.py` stops importing `turingdb` and starts issuing ArcadeDB SQL directly -- same file, same business logic (fusion weights, redaction, chunking, retry), new query bodies. This is deliberately less architecture work than the original coexistence design (no `backend.py` Protocol, no `backends/turingdb_backend.py` + `backends/arcadedb_backend.py` split, no dual-backend conformance suite, no `AGENTMEMORY_BACKEND` env switch) -- but it inherits every technical finding about *what ArcadeDB can and can't do* from that research: native `LSM_VECTOR` HNSW subsumes the need for a dedicated vector DB, native Lucene full-text is real and ACID-integrated but changes tokenization behavior from the current SQLite FTS5 (a ranking-quality risk, not a correctness risk), and ArcadeDB's real ACID transactions are a genuine upgrade over TuringDB's non-atomic per-statement batching. Because there's no coexistence, there's no "TuringDB driver stays the safe reference implementation" fallback -- the single hard gate that de-risks this is the **migration-correctness gate**: snapshot the current TuringDB retrieval baseline with `e2e_score.py` + `real_document_benchmark.py` before touching anything, then require the ported ArcadeDB code to meet-or-exceed that baseline before TuringDB is removed from the codebase and compose stack.

The other three thrusts are comparatively lower-risk and largely independent of the backend port: Garage replaces the now-archived MinIO CE for S3-compatible document staging, FastMCP's already-pinned `OAuthProxy`/`OIDCProxy` replaces static bearer tokens with real OIDC (zero new dependency), and the CI/hooks work (lefthook + GitHub Actions, no-skip-as-green, GPU-tier compile-floor degradation) can ship immediately and independently of both the Docker and ArcadeDB thrusts. The main risks across the whole milestone are the same shape repeated: things that "compile and pass unit tests" but silently regress a property that's expensive to test (retrieval ranking quality after the ArcadeDB port, tenant isolation if `user_identifier` scoping is treated as backend-provided rather than mandatory, CI reporting green while a gated tier was silently skipped). Each of these gets an explicit, non-negotiable exit gate below.

## Key Findings

### Recommended Stack

ArcadeDB (Docker image `arcadedata/arcadedb:26.7.1`) becomes the sole canonical backend, accessed via a thin hand-rolled `arcadedb_client.py` over its HTTP/JSON API using stdlib `urllib` -- matching this codebase's existing pattern for all other provider integrations (`embeddings.py`, `rerank.py`) and avoiding a new HTTP client dependency. Garage (`dxflrs/garage:v2.2.0+`) replaces local-filesystem document staging via boto3's `endpoint_url` override, because MinIO CE was formally archived in April 2026. FastMCP's already-pinned `OIDCProxy`/`OAuthProxy` (built into `fastmcp>=3.4,<4`, no new dependency) replaces `StaticTokenVerifier`, backed by a self-hosted Keycloak (26.7.0) IdP. No dedicated external vector DB (Qdrant/Weaviate/Milvus) and no dedicated external search engine (Elasticsearch/OpenSearch) are needed -- ArcadeDB's native `LSM_VECTOR` (JVector/HNSW) and native Lucene full-text subsume both for this project's scale, keeping the "one-command Docker stack" goal from ballooning into 4+ stateful services.

**Core technologies:**
- ArcadeDB 26.7.1 -- sole canonical backend (graph + vector + full-text, ACID multi-model) -- replaces TuringDB entirely
- Garage v2.2.0+ -- S3-compatible object storage for document staging -- MinIO CE is dead/archived
- FastMCP `OIDCProxy`/`OAuthProxy` (already in the pinned range) -- real OAuth/OIDC auth -- zero new dependency
- Keycloak 26.7.0 -- self-hosted OIDC IdP -- most direct FastMCP integration precedent
- stdlib `urllib`-based ArcadeDB HTTP client -- matches existing provider-client convention, avoids a new at-risk dependency
- lefthook v2.1.10 + GitHub Actions -- CI/hooks tooling, mirrored from the Aura project

### Expected Features / Scope (stabilization milestone -- "features" below map to PROJECT.md's four thrusts)

**Must have (Thrust 2, backend port -- non-negotiable exit criteria):**
- Full direct port of `store.py`'s ~40 TuringDB-query call sites to ArcadeDB SQL (graph CRUD, vector search, per-tenant vector index equivalent)
- `stable_id()` remains the only ID crossing into ArcadeDB records (stored as an indexed property, never substituted with ArcadeDB's native RID)
- `vector_id()` (the TuringDB int-join workaround) is deleted, not ported -- ArcadeDB returns the vertex directly, no join needed
- Migration-correctness gate: ArcadeDB retrieval quality meets-or-exceeds the pre-removal TuringDB baseline on `e2e_score.py` + `real_document_benchmark.py`
- One ArcadeDB database per tenant (physical isolation) while `user_identifier` scoping remains mandatory in every query (defense-in-depth, not replaced by DB-level isolation)
- CLAUDE.md invariants #2 (TuringDB canonical), #4 (submit-before-match), #6 (`load_graph` after restart) updated/retired; #1 (tenant scope) and #3 (stable IDs) preserved

**Must have (Thrust 1, Docker):**
- `docker compose up` brings up a healthy, reproducible stack from clean checkout, including the new ArcadeDB service (replacing TuringDB in compose)
- Real document flows end-to-end through the dockerized MCP; E2E score gate green against the dockerized stack

**Must have (Thrust 3, CI/hooks):**
- lefthook pre-commit (ruff format/check, file-size cap with allowlist) and pre-push (compile smoke, fast pytest subset, `docker compose config --quiet`)
- GitHub Actions: lint, unit test, dockerized-integration+E2E, compose-validation, pip-audit jobs
- No-skip-as-green pytest discipline (markers + `conftest.py` session-finish backstop)
- GPU sidecar tiers degrade to a compile-only floor on hosted runners, never silently skip

**Should have (spike-gated, Thrust 4):**
- Deeper UTCP protocol support -- findings-gated; do not commit to a build until the spike verdict is in

**Defer:**
- Live TuringDB->ArcadeDB data migration/export tooling -- explicitly out of scope (fresh start, no production data to preserve)
- Repository/driver abstraction layer, dual-backend conformance suite, `AGENTMEMORY_BACKEND` switch -- explicitly rejected by the direct-port decision
- Real GPU-live E2E tier on hosted runners, coverage-floor ratchet, mutation testing, Windows CI lane -- v2+/flag-for-roadmap-decision

### Architecture Approach

`store.py` keeps its current shape as the domain/business-logic module but stops building TuringDB query strings inline (`VECTOR SEARCH ... MATCH ...`, `CHANGE SUBMIT`, `LOAD VECTOR FROM csv`) and instead issues ArcadeDB SQL directly (SQL is ArcadeDB's most-documented dialect with first-class `LSM_VECTOR`/`SEARCH_INDEX()` support -- pick it consistently, don't mix in Cypher/Gremlin). Because this is a direct port with no abstraction seam, there is no `backend.py` Protocol or `backends/` package -- the ~40 call sites currently building TuringDB query strings get rewritten in place to build ArcadeDB SQL instead. The BM25 sparse layer (`sparse_index.py`) is a separate decision: keep it, or adopt ArcadeDB's native Lucene full-text. Research recommends **adopting ArcadeDB native full-text** (per PROJECT.md's explicit resolution -- no separate external search engine, ACID-integrated with graph/vector writes, retires the SQLite-FTS5 outbox prepare/commit/replay crash-consistency class of bug entirely) but flags analyzer/tokenizer selection as a first-class decision that must be validated against golden queries before it's trusted, because a Lucene analyzer mismatch changes BM25 ranking silently, with no test failure.

**Major components (post-port):**
1. `store.py` -- business logic (fusion, redaction, chunking, retry/idempotency) + direct ArcadeDB SQL query bodies (was: TuringDB query bodies) -- same file, same central-exception status per CLAUDE.md
2. `arcadedb_client.py` (new) -- thin stdlib-`urllib` HTTP/JSON wrapper over ArcadeDB's `/api/v1/command`, `/api/v1/query`, `/api/v1/begin`/`/commit` -- the sole ArcadeDB connectivity surface
3. ArcadeDB itself -- one database per tenant, native `LSM_VECTOR` (HNSW/JVector) for vectors on the same vertex used for graph traversal, native Lucene full-text (analyzer TBD-validated) -- replaces TuringDB + the SQLite FTS5 projection
4. `document_job_manager.py`/`document_jobs.py` -- unchanged interface, now writing through the ArcadeDB-backed `store.py`; multi-worker ingestion sequenced after the port since ArcadeDB's isolation model (real ACID/MVCC) behaves differently under concurrent writers than TuringDB's per-statement submission
5. `server.py` -- gains OIDC wiring (`OIDCProxy`) deriving `user_identifier` from verified token claims; storage-layer change is otherwise invisible to this boundary

### Critical Pitfalls (reframed for direct-port, no-coexistence)

1. **No parity gate = silent retrieval-quality regression (the single most consequential pitfall).** A functioning ArcadeDB port (writes/reads/unit tests pass) can still be materially worse at the thing that matters -- ranking quality -- because analyzer mismatches, vector quantization differences, and SQL-vs-Cypher-vs-TuringDB-dialect traversal differences don't fail tests, they just rank worse. **Avoid by:** snapshotting the TuringDB baseline via `e2e_score.py` + `real_document_benchmark.py` *before* the port begins, then requiring the ArcadeDB result to meet-or-exceed it as the literal exit criterion for removing TuringDB -- not "runs without crashing."
2. **Deterministic ID drift if ArcadeDB's native RID leaks into "stable" IDs.** ArcadeDB RIDs (`#12:34`) are not stable across compaction/backup/restore. **Avoid by:** `stable_id()` remains the only identifier stored as an indexed property and used for vector correlation; never substitute ArcadeDB's native record identity into ID-generation logic.
3. **Tenant isolation becomes backend-dependent if per-database isolation is treated as sufficient.** "ArcadeDB isolates tenants at the DB level, so we don't need to filter" silently drops invariant #1 from a contract into an accidental property. **Avoid by:** `user_identifier` scoping stays mandatory in every query regardless of per-tenant-database isolation; run the existing concurrent multi-tenant isolation test suite (CONCERNS.md gap) against the ported code before trusting it.
4. **CI reports green without proving gated tiers actually ran** (skip semantics vs. exit-code-0, GPU tier silently substituting a stub without an assertion). **Avoid by:** assert `skipped == 0` (or an explicit reviewed allowlist) per gated tier; GPU tier either runs on a real GPU runner and asserts `nvidia-smi` succeeded inside the container, or explicitly runs the existing stub floor (`E2E_USE_EXTERNAL_EMBED`/`E2E_USE_EXTERNAL_RERANK`) with a visible marker.
5. **Garage/S3 staging reproduces the exact upload-session leak it was meant to fix, just relocated.** Persisting session metadata (fixing the in-memory-dict half) without an `AbortIncompleteMultipartUpload` bucket lifecycle rule just moves the leak from RAM growth to unbounded storage cost, invisible from inside the app. **Avoid by:** ship both halves together -- TTL'd session persistence AND the bucket-side lifecycle rule -- in the same change.
6. **OIDC migration that keeps a client-supplied `user_identifier` authoritative alongside the new verified-token identity.** The natural mistake is adding OIDC validation *in addition to* rather than *instead of* the client-supplied tenant field, leaving a straightforward cross-tenant bypass. **Avoid by:** once OIDC is authoritative, `user_identifier` is derived server-side from verified token claims only; test that a valid token for tenant A with a client-supplied `user_identifier="tenant-b"` is rejected/overridden.

## Implications for Roadmap

Based on research, suggested phase structure. **Backend-port sequencing below reflects the direct-port model** (no interface-extraction step, no dual-backend anything) -- the S3/OAuth/batch-embedding/multi-worker-ingestion/vector-versioning items are **no longer gated on any interface-extraction milestone** and can run in parallel with, or after, the ArcadeDB port with no ordering dependency on it.

### Phase 1: CI + git-hook discipline (Thrust 3, P1 slice)
**Rationale:** Zero dependency on Docker or the backend port; ships immediately and starts paying down risk (catching regressions) for every subsequent phase.
**Delivers:** `lefthook.yml` (pre-commit: ruff format/check + file-size cap w/ allowlist; pre-push: compile smoke, fast pytest subset, `docker compose config --quiet`); `.github/workflows/ci.yml` (lint, unit-test, compose-validation, pip-audit jobs, all GPU-free); pytest `docker_integration`/`gpu_live` markers + `conftest.py` no-skip-as-green backstop; ruff pin tightened `>=0.9` -> `==0.15.17`.
**Avoids:** Pitfall -- CI reports green without proving gated tiers ran; file-size cap shipping without an allowlist (would immediately fail on `store.py`, 3891 LOC).

### Phase 2: Snapshot the TuringDB retrieval baseline
**Rationale:** Must happen *before* any ArcadeDB code touches the live stack -- this is the yardstick every later phase is measured against, and it is worthless if captured after the port has already started drifting behavior.
**Delivers:** A recorded, versioned run of `scripts/e2e_score.py` and `scripts/real_document_benchmark.py` against the current TuringDB-backed stack -- the numeric baseline the migration-correctness gate compares against.
**Avoids:** No parity gate = silent regression -- this phase exists solely to make that gate possible.

### Phase 3: Stand up ArcadeDB as a compose service (parallel with the port design)
**Rationale:** Docker Compose plumbing (image, healthcheck, volume) is independent of the query-porting work and de-risks Thrust 1's "one-command stack" goal early.
**Delivers:** `arcadedb` service in `compose.yaml` (image `arcadedata/arcadedb:26.7.1`, healthcheck, data volume), `arcadedb_client.py` (thin stdlib-`urllib` HTTP/JSON driver), a smoke test confirming basic graph+vector+full-text ops work against a fresh container.
**Uses:** ArcadeDB 26.7.1, stdlib `urllib` (STACK.md).

### Phase 4: Direct-port `store.py`'s query bodies to ArcadeDB SQL
**Rationale:** The core of Thrust 2. No abstraction layer, no TuringDB driver left running alongside it -- this phase replaces the ~40 TuringDB-query call sites in place.
**Delivers:** `store.py` issuing ArcadeDB SQL for all graph CRUD, vector search (native `LSM_VECTOR`), and (research-resolved) native Lucene full-text with an explicitly validated analyzer choice, replacing `sparse_index.py`'s SQLite FTS5 projection. `vector_id()` deleted; `stable_id()` is the sole cross-record identifier, stored as an indexed ArcadeDB property.
**Implements:** ARCHITECTURE.md's call-site inventory (still valid as a checklist) and vector+full-text strategy, minus the abstraction/dual-backend framing.
**Avoids:** ArcadeDB RID leaking into ID generation; Lucene analyzer mismatch changing BM25 ranking silently (validate against golden queries in this phase, not after).

### Phase 5: Tenancy -- one ArcadeDB database per tenant
**Rationale:** Ship after the core port is functionally working, so isolation-topology bugs aren't tangled up with query-porting bugs (mirrors the original research's "don't bundle driver delivery with isolation hardening" guidance, still valid even without a driver abstraction).
**Delivers:** Per-tenant ArcadeDB database provisioning, with `user_identifier` scoping still mandatory in every query as defense-in-depth (never replaced by DB-level isolation). Run the concurrent multi-tenant isolation test suite (CONCERNS.md gap) against the ported code.
**Avoids:** Tenant isolation becoming backend-dependent.

### Phase 6: Migration-correctness gate -- meet-or-exceed the baseline
**Rationale:** The hard exit criterion for the whole backend swap. Nothing downstream (removing TuringDB, updating CLAUDE.md, marking ArcadeDB production-eligible) should happen before this passes.
**Delivers:** `e2e_score.py` + `real_document_benchmark.py` run against the ArcadeDB-backed stack, compared against Phase 2's snapshot within a documented tolerance -- not "runs without crashing."
**Avoids:** No parity gate = silent regression directly -- this phase *is* the mitigation.

### Phase 7: Remove TuringDB + update CLAUDE.md/docs
**Rationale:** Only after Phase 6 passes. Removing the old backend before the gate passes would strand the team with no working system if the port has a hidden regression.
**Delivers:** TuringDB removed from `compose.yaml`, `pyproject.toml`, docs; CLAUDE.md invariants #2/#4/#6 rewritten for ArcadeDB (or retired where ArcadeDB has no equivalent quirk -- e.g., no explicit `load_graph` step, but an equivalent "ArcadeDB connection/database-ready" health check replaces it); invariant #1 and #3 reconfirmed as still enforced.
**Avoids:** Leaving stale TuringDB-specific guidance (submit-before-match, `load_graph` after restart) in CLAUDE.md after it no longer applies.

### Phase 8 (parallel/after Phase 4, no ordering dependency on it): Garage S3 staging
**Rationale:** Fully independent of the graph/vector backend -- sequence by ops readiness, needs Thrust 1's Docker stack settled (adds a `garage` compose service) but nothing from the ArcadeDB port.
**Delivers:** Garage compose service, boto3-based staging client replacing local-filesystem staging, TTL'd session persistence AND an `AbortIncompleteMultipartUpload` bucket lifecycle rule shipped together, per-tenant object prefixing, checksum verification on upload completion.
**Avoids:** S3 staging reproducing the upload-session leak at the storage layer instead of fixing it.

### Phase 9 (parallel/after Phase 4, no ordering dependency on it): OAuth/OIDC via FastMCP built-ins
**Rationale:** Zero storage-layer coupling -- sequence independently of the backend port, though not simultaneously with it (don't change how identity arrives and how it's enforced in the same window, as a risk-reduction choice, not a hard dependency).
**Delivers:** Keycloak compose service, `OIDCProxy` wired into `server.py`, `user_identifier` derived server-side from verified token claims (never client input once OIDC is authoritative), integration test asserting a client-supplied tenant override is rejected.
**Avoids:** OIDC shipped alongside, not instead of, client-supplied tenant identity.

### Phase 10 (parallel/after Phase 4): Batch embedding, multi-worker document ingestion, vector-index versioning
**Rationale:** These CONCERNS.md tech-debt/missing-feature items are worse if deferred until after the port lands, because ArcadeDB's real ACID/MVCC isolation model surfaces concurrent-modification retries on the currently-unbatched, per-item write pattern more than TuringDB's per-statement submission does. Ship the batching and versioning fixes at the same time as (or immediately after) Phase 4's core port, using a versioned/namespaced vector index and atomic swap from day one rather than porting the current unversioned rebuild bug forward.
**Delivers:** Batched embedding API calls, multi-worker document-ingestion leasing, versioned/namespaced ArcadeDB vector indexes with atomic swap on rebuild completion.
**Avoids:** ArcadeDB's transaction/HNSW-rebuild cost compounding the existing unbatched-write and stale-vector-accumulation bugs.

### Phase 11: Docker one-command stack hardening + real-doc E2E (Thrust 1, closes out)
**Rationale:** Depends on ArcadeDB compose service (Phase 3) and Garage/OIDC services (Phases 8-9) all being present in the compose file; this phase is the final integration/verification pass, not new build.
**Delivers:** `docker compose up` brings up a healthy, reproducible stack from a clean checkout (ArcadeDB replacing TuringDB, plus Garage, Keycloak); E2E score gate green against the dockerized stack; a real document verified end-to-end through the dockerized MCP; `docker compose config --quiet` passes; GPU visibility verified from *inside* a container started by `docker compose up`, not just `docker run --gpus all`.
**Avoids:** GPU sidecars silently degrading instead of failing loudly; read-only/non-root hardening breaking new write paths introduced by Garage/ArcadeDB/OIDC only at container runtime, not at test time (re-verify each new integration's actual write path inside the hardened container).

### Phase 12: UTCP spike (Thrust 4, can run early/in parallel -- explicitly de-risking, not blocking)
**Rationale:** PROJECT.md calls this an early, findings-gated spike; it has no dependency on the backend port and can run whenever bandwidth allows, ideally early to de-risk before committing to build work.
**Delivers:** A findings verdict on deeper UTCP protocol support (native serving vs. the current manual `utcp.py` export) validated against real UTCP clients/spec. Any resulting build work is gated on this verdict, not assumed.

### Phase Ordering Rationale

- **CI/hooks (Phase 1) ships first** because it has zero dependencies and starts protecting every subsequent phase immediately -- this mirrors PITFALLS.md's observation that CI/hooks work is independent of Docker and the backend port.
- **The baseline snapshot (Phase 2) must precede any ArcadeDB work that touches the live stack** -- it's the yardstick, and capturing it late means comparing against an already-drifted TuringDB state.
- **Compose plumbing (Phase 3) and query-porting (Phase 4) can overlap** but Phase 4 is the load-bearing phase -- the gate (Phase 6) and removal (Phase 7) cannot happen until it's done and validated.
- **Tenancy hardening (Phase 5) is deliberately sequenced after the core port**, not bundled into it, per PITFALLS.md's guidance (still valid without a driver abstraction) -- keeps the surface area under test smaller per phase.
- **Garage, OIDC, and batching/versioning (Phases 8-10) are explicitly NOT gated on Phase 4 completing** -- this is the key change from the original coexistence-framed research, which sequenced them "in parallel with, depends only on the interface-extraction step." With no interface-extraction step, they depend on nothing from the backend work at all; sequence them by ops/team bandwidth.
- **TuringDB removal (Phase 7) is irreversible and therefore gated last**, strictly after Phase 6's meet-or-exceed check passes -- this is the single most important ordering constraint in the whole roadmap.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 4 (direct port):** ArcadeDB's filtered-ANN capability (`WHERE user_identifier = ... AND status = 'active'` combined with `LSM_VECTOR` search in one query, vs. requiring post-filtering) is asserted from public docs, not verified hands-on in this repo -- verify empirically early in this phase, it determines whether the per-tenant-index-within-shared-DB pattern or single-shared-index-with-predicate-filtering is viable.
- **Phase 4 (full-text):** Lucene analyzer selection needs a deliberate comparison against FTS5's current tokenization on a golden query set -- do not accept ArcadeDB's default analyzer without this check.
- **Phase 5 (tenancy):** ArcadeDB's file-handle/page-cache behavior at high tenant counts (one DB per tenant) is an unverified research gap -- benchmark realistic tenant counts before committing fully to per-database tenancy over a scoped shared-database model at scale.
- **Phase 12 (UTCP spike):** By definition a spike -- findings unknown until executed.

Phases with standard patterns (skip research-phase):
- **Phase 1 (CI/hooks):** Directly modeled on the Aura project's existing, working `lefthook.yml`/`ci.yml` -- well-documented pattern, HIGH confidence.
- **Phase 8 (Garage/S3):** boto3 + `endpoint_url` override is a standard, well-documented integration pattern.
- **Phase 9 (OIDC):** FastMCP's `OIDCProxy` is already in the pinned dependency range with documented usage; verify the exact import path against the resolved version as a first task, but the pattern itself is standard.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | ArcadeDB adequacy verdict rests on cross-checked web sources (GitHub discussions, docs pages), not a hands-on benchmark in this repo -- the research itself recommends a validation spike as Phase 3/4's first task. Garage/Keycloak/FastMCP-OIDC findings are corroborated by multiple independent sources (HIGH-leaning within MEDIUM). |
| Features (scope) | HIGH | Directly sourced from PROJECT.md's authoritative Active requirements and Key Decisions -- not inferred. |
| Architecture | MEDIUM | The call-site inventory and ID-portability analysis are HIGH confidence (read directly from `store.py`/`ids.py`). The coexistence-specific portions (driver Protocol, dual-backend CI matrix, conformance suite) are explicitly superseded and excluded from this summary's roadmap implications. ArcadeDB SQL/transaction-model claims remain MEDIUM (public docs, not yet verified hands-on). |
| Pitfalls | MEDIUM-HIGH | Codebase-grounded pitfalls (TuringDB restart, GPU degradation, read-only hardening, tenant isolation, ID drift) are HIGH confidence -- read directly from `compose.yaml`/CLAUDE.md/CONCERNS.md. ArcadeDB-specific pitfalls (Lucene analyzer mismatch, HNSW rebuild cost, MVCC/isolation collision) are MEDIUM -- cross-checked web sources, no hands-on ArcadeDB precedent in this repo yet. |

**Overall confidence:** MEDIUM-HIGH. Scope and sequencing are HIGH confidence (directly from PROJECT.md). Technical adequacy of ArcadeDB as a sole backend at this project's scale is the single load-bearing MEDIUM-confidence finding across the whole milestone -- treat the validation spike in Phase 3/4 as mandatory, not optional, precisely because there is no coexisting fallback backend to catch a bad assumption late.

### Gaps to Address

- **ArcadeDB filtered-ANN + full-text analyzer behavior is unverified hands-on** -- both must be validated empirically early in Phase 4, before deeper porting work assumes a specific query shape.
- **ArcadeDB per-tenant-database scaling behavior at high tenant counts** is an explicit research gap (flagged, not confirmed) -- benchmark before Phase 5 locks in the per-database pattern as permanent.
- **The exact ordering/scope boundary between Phase 4 (core port) and Phase 10 (batching/versioning)** needs a planning-time decision: PITFALLS.md recommends shipping them together or immediately adjacent, not deferred, but the roadmapper should confirm whether they're one phase or two sequential phases based on actual size once Phase 4's scope is better understood.
- **UTCP spike outcome** is entirely unknown until Phase 12 executes -- do not pre-plan build phases for it.

## Sources

### Primary (HIGH confidence)
- `.planning/PROJECT.md` -- authoritative current scope, Active requirements, Key Decisions (overrides all coexistence framing below)
- Direct codebase reads: `src/turing_agentmemory_mcp/store.py`, `ids.py`, `sparse_index.py`, `compose.yaml`, `CLAUDE.md`, `pyproject.toml`, `Makefile`, `cli.py`, `e2e_score.py`
- `.planning/codebase/{ARCHITECTURE,CONCERNS,STRUCTURE,TESTING,STACK,INTEGRATIONS}.md`
- `D:\Repo\Aura\lefthook.yml`, `D:\Repo\Aura\.github\workflows\ci.yml` -- direct reads, CI/hooks precedent

### Secondary (MEDIUM confidence)
- ArcadeDB official docs (Vector Embeddings, Full-Text Index, Multi-Model Architecture, Postgres protocol plugin), GitHub discussions (`#3140` vector benchmark thread), Jepsen test blog -- cross-checked web sources, not hands-on in this repo
- MinIO archival corroboration (Vonng blog, glukhov.org, `minio/minio` discussion #21667) -- multiple independent sources agree on the April 2026 archival
- Garage HQ docs, FastMCP OAuth Proxy docs, Keycloak release notes, MCP Authorization spec (2025-11-25), AWS multipart-upload lifecycle guidance

### Tertiary (LOW-MEDIUM confidence)
- `arcadedb-python` (third-party Beta client) status -- self-declared by package classifiers, not independently verified; recommendation is to avoid it in favor of the stdlib driver regardless
- Docker Compose GPU-support pitfall commentary -- general community pattern, corroborated by this repo's own `nvidia-smi`-in-healthcheck design but not independently benchmarked

---
*Research completed: 2026-07-11*
*Ready for roadmap: yes*
