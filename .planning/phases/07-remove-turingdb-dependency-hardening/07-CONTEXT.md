# Phase 7: Remove TuringDB + Dependency Hardening - Context

**Gathered:** 2026-07-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Remove TuringDB **entirely** from the codebase and the Compose stack (ARC-10),
rewrite the CLAUDE.md invariants for the ArcadeDB reality, adopt **Bertoni-based
app-state naming** (forward-consistent with the coming product rebrand), and
**version-gate** `graspologic-native` (DEP-01) and `fastmcp` (DEP-02). After this
phase the stack runs on **ArcadeDB alone**. The removal is **irreversible** and is
hard-gated by the committed Phase-6 GO verdict (`gate_guard.py` reads
`baseline/06-gate/gate-result.json`; nothing here proceeds unless `verdict == GO`).

**In scope:** delete the `turingdb` dependency + all TuringDB-only code/tooling;
rename the live app-state env/volume to a Bertoni identity + delete dead
`TURINGDB_*` connection vars; remove the `turingdb`/`turingdb-volume-init` Compose
services + `docker/turingdb.Dockerfile`; rewrite + extend the invariants and sweep
all docs; add compat-smoke tests for the two at-risk deps + a no-`import turingdb`
guard; prove the cut with the full green suite + `docker compose config --quiet`.

**Out of scope:** the **full `turing → bertoni` package/product rebrand** (its own
dedicated phase — see Deferred); the document-GraphRAG build; the GLiNER GPU
sidecar; and all Phases 8–12 concern work. Do NOT delete the historical
`baseline/03-turingdb/` or `baseline/06-gate/` artifacts (yardstick/gate provenance).

</domain>

<decisions>
## Implementation Decisions

### Cut depth & legacy code
- **D-01 — Full purge (LOCKED):** Remove `turingdb==1.35` from `pyproject.toml`
  (dependency + the "TuringDB-backed…" description + the `turingdb` keyword).
  **Delete** the TuringDB-only code ArcadeDB obsoletes:
  - `repair-vector-index` (the `admin_repair.py` command + its `cli.py` dispatch) —
    it quarantines TuringDB **CSV vector directories**, which do not exist under
    ArcadeDB native HNSW; meaningless on the new backend.
  - The legacy benchmark/eval harnesses that the ArcadeDB `e2e_score.py` +
    `real_document_benchmark.py` supersede: `benchmark.py`, `benchmark_stages.py`,
    `benchmark_memoryarena.py`, `agent_quality_eval.py`, `benchmark_schema.py`
    (and their tests). **Fix-on-touch caveat:** confirm actual supersession/non-use
    before deleting each — never delete something still wired into a live path.
  - Drop `e2e_score.py`'s `turingdb_version` field (baseline field-shape parity is
    no longer needed post-Phase-6) and its `from turingdb import __version__`.
  - Remove the `sys.modules["turingdb"]` stub from `tests/conftest.py` and the ~40
    test files that reference it, plus any test assertions on `turingdb`.
  - Sweep every remaining `turingdb`/`TuringDB`/`TURINGDB` reference in `src/`
    (stale docstrings/comments in `store_core.py`/`store_documents.py`/
    `store_rebuild.py`, plus `server.py`, `provider_config.py`,
    `document_job_manager.py`, `lab.py`, `frontend/`).

### App-state naming (Bertoni)
- **D-02 — Adopt Bertoni-based app-state naming NOW (LOCKED):** forward-consistent
  with the coming rebrand. Rename the still-live application-state paths:
  `TURINGDB_HOME` → `BERTONI_HOME`, default `/turing` → `/bertoni`, the
  `turing-data` volume → `bertoni-data`, and `TURINGDB_EMBED_DIMENSIONS` →
  `EMBED_DIMENSIONS` (it's just the embed dim, no backend meaning). **Delete** the
  dead TuringDB connection vars entirely — `TURINGDB_URL`, `TURINGDB_GRAPH`,
  `TURINGDB_{MEMORY,DOCUMENT,ENTITY,FACT,COMMUNITY}_INDEX` — they are superseded by
  `ARCADEDB_*`. Update every `/turing`-rooted path in `compose.yaml`
  (sparse-index, job DB, staging, tenant registry) + `server.py` +
  `document_job_manager.py`. Fresh-start milestone → no data to preserve, so the
  volume/path rename is safe; this supersedes CLAUDE.md's "TURINGDB_HOME remains
  transitional" note.

### Invariants & docs sweep
- **D-03 — Full alignment + new ArcadeDB-era invariants (LOCKED):** Rewrite the
  invariant lists in **both** `CLAUDE.md` and `.claude/CLAUDE.md`:
  - #2 (TuringDB canonical) → **superseded**: ArcadeDB is the sole canonical backend.
  - #4 (per-batch submit-before-match) → **retired/replaced** with the ArcadeDB
    single managed-transaction + read-your-writes model (`run_in_transaction`).
  - #5 (app-layer re-sort of composed `VECTOR SEARCH … MATCH`) → **retired**: native
    HNSW returns record + score together.
  - #6 (`load_graph`/`graph.ready`) → **replaced** with the ArcadeDB reconnect +
    `/health` probe reality.
  - #1 (tenant scope) and #3 (stable IDs) → **reconfirmed** as still enforced.
  - **Codify new invariants** from Phase 4/5: MVCC conflict = HTTP 503
    `ConcurrentModificationException` → redo the whole begin/commit via
    `run_in_transaction`, never blind-retry; native `LSM_VECTOR` + Lucene are
    ACID-consistent with graph writes (SQLite-FTS5 outbox retired); one ArcadeDB
    database per tenant **plus** the mandatory `user_identifier` predicate +
    `TenantBinding` (physical isolation never replaces the predicate).
  - **Docs sweep:** `README.md` ("TuringDB-backed"→ArcadeDB), `docs/architecture.md`,
    `docs/*.md` (configuration/deployment/operations/security/performance/
    limitations), `.env.example`, `skills/turing-agentmemory/` references,
    `CHANGELOG.md` (add the removal entry), and the `pyproject.toml`
    description/keywords.

### Dependency version-gates & cut proof
- **D-04 — pytest compat-smoke + no-import guard (LOCKED):**
  - **DEP-01:** a pytest test asserting the installed `graspologic-native` version
    is within the supported pin (`==1.3.1`) **AND** a real Leiden-clustering API
    smoke (tiny graph → cluster) so an incompatible upgrade fails the gate before
    adoption.
  - **DEP-02:** a pytest test asserting `fastmcp` is within the supported range
    (`>=3.4,<4`) **AND** a FastMCP tool-registration / app-construction smoke so a
    breaking bump is caught.
  - Both live in the **no-skip-as-green** tier (a skipped compat test fails, not
    passes green).
  - **Cut proof:** a guard test asserting **no** `import turingdb` / `from turingdb`
    remains anywhere in `src/` (grep-gate, mirroring existing repo guard patterns);
    removal verified by the **full green pytest suite** + `docker compose config
    --quiet` (turingdb service gone) + the E2E score gate still green on ArcadeDB
    alone. The Phase-7 **entry** is already hard-gated by `gate_guard.py`
    (Phase 6 D-10) — this phase consumes that precondition, it does not rebuild it.

### Claude's Discretion
- The exact set of legacy harnesses to delete vs. any worth keeping — decide by
  actual usage/supersession, never delete a still-wired path (fix-on-touch).
- The precise new Bertoni env-var names + default paths (within D-02 intent) and
  whether the volume rename needs a documented migration note.
- The exact wording of the rewritten/added invariants (within the D-03 contract).
- The concrete shape of the compat-smoke + no-import guard tests (file placement,
  how the version-range assertion reads the installed dist), provided they fail closed.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/ROADMAP.md` §"Phase 7: Remove TuringDB + Dependency Hardening" — goal +
  SC#1 (removed from compose/pyproject/docs), SC#2 (invariant rewrite), SC#3 (dep gates).
- `.planning/REQUIREMENTS.md` — **ARC-10, DEP-01, DEP-02** (this phase's requirements).
- `.planning/PROJECT.md` — direct-port / ArcadeDB-sole-backend decisions; Constraints
  (invariant #2 superseded, #1/#3 preserved).

### The gate that AUTHORIZES this removal (read first — it's the precondition)
- `baseline/06-gate/GATE.md` + `baseline/06-gate/gate-result.json` — the committed
  GO verdict.
- `src/turing_agentmemory_mcp/gate_guard.py` — the hard guard that blocks unless
  `verdict == GO` (already built in Phase 6).
- `.planning/phases/06-migration-correctness-gate/06-CONTEXT.md` — D-10 (the Phase-7
  guard contract).

### The removal surface (what "sweep every reference" means — 414 refs / 97 files)
- Source: `server.py`, `e2e_score.py`, `e2e_score_stubs.py`, `store_core.py`,
  `store_documents.py`, `store_rebuild.py`, `admin_repair.py`, `cli.py`,
  `benchmark.py`, `benchmark_stages.py`, `benchmark_memoryarena.py`,
  `benchmark_schema.py`, `agent_quality_eval.py`, `provider_config.py`,
  `document_job_manager.py`, `lab.py`, `frontend/`.
- Infra: `compose.yaml` (`turingdb` + `turingdb-volume-init` services, `TURINGDB_*`
  env, `turing-data`/`/turing` volume), `docker/turingdb.Dockerfile`,
  `pyproject.toml` (`turingdb==1.35` + description + keywords), `.github/workflows/ci.yml`.
- Tests: ~40 files using the `sys.modules["turingdb"]` stub (start at `tests/conftest.py`).
- Docs: `README.md`, `docs/*.md`, `.env.example`, `CHANGELOG.md`,
  `skills/turing-agentmemory/`.
- **KEEP (historical, do NOT delete):** `baseline/03-turingdb/`, `baseline/06-gate/`.

### Invariants + the Phase 4/5 decisions that reshape them
- `CLAUDE.md` and `.claude/CLAUDE.md` — the invariant lists + milestone constraints.
- `.planning/phases/04-arcadedb-direct-port/04-CONTEXT.md` — native HNSW+Lucene,
  deleted `vector_id` int-join, retired FTS5 outbox, `run_in_transaction`/MVCC,
  reconnect/readiness (what invariants #4/#5/#6 retire toward + the new invariants).
- `.planning/STATE.md` "Accumulated Context" — the Phase-5 registry/binding decisions
  that become the per-tenant-DB + `TenantBinding` invariant.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `gate_guard.py` already implements the entry hard-gate (Phase 6) — do not rebuild it.
- The store read/write paths are ALREADY ported (Phase 4); the surviving `turingdb`
  references in `store_*.py` are stale docstrings/comments, not live calls.
- The `sys.modules["turingdb"]` stub is centralized enough to remove at
  `tests/conftest.py` + the shared `_*_shared.py` fixtures first, then sweep the rest.

### Established Patterns
- No-skip-as-green conftest guard (`tests/conftest.py` under `CI=true`) and the
  600-LOC no-allowlist cap apply to the new compat/guard tests.
- Existing grep-gate test patterns (e.g. the Phase-2 compose grep gate) are the model
  for the no-`import turingdb` guard.

### Integration Points
- Removing the `turingdb` + `turingdb-volume-init` Compose services +
  `docker/turingdb.Dockerfile`; the `/turing`→`/bertoni` rename touches every
  app-state path in `compose.yaml` (sparse, job DB, staging, tenant registry) +
  `server.py` + `document_job_manager.py`.
- `pyproject.toml` dep removal; `.github/workflows/ci.yml` + `lefthook.yml` may carry
  turingdb references to clear.

</code_context>

<specifics>
## Specific Ideas

- The user is renaming the product/repo to **"BertoniAgentMemory."** Phase 7 adopts
  Bertoni-based **app-state env/volume names now** for forward-consistency; the full
  package/product rename is deliberately a **separate** effort (Deferred).
- The user chose the **aggressive debt-clearing** path across the board: full purge of
  legacy TuringDB code, full docs alignment, and codifying new invariants — not a
  minimal removal.

</specifics>

<deferred>
## Deferred Ideas

- **Full `turing → bertoni` package/product rebrand → its OWN dedicated phase/task,
  AFTER Phase 7's cut lands.** Renames `turing_agentmemory_mcp` →
  `bertoni_agentmemory_mcp` (package dir + every import), the `turing-agentmemory-mcp`
  console entrypoint, the `turing-agentmemory` MCP server name + skill, the
  `turing-agentmemory-*` Docker images + Compose services, `pyproject.toml` `name`,
  and all docs — hundreds of references. Kept OUT of the irreversible TuringDB removal
  so the two large changes don't tangle. **Action:** add a ROADMAP phase for it.
- **GLiNER GPU sidecar** (ingestion performance) — CUDA base + `onnxruntime-gpu` + a
  GPU device reservation + `GLINER_DEVICE=cuda`. Its own ingestion-perf concern. Spike
  003 showed the current CPU model handles Italian adequately, so it is **not
  blocking**; parked.
- **Document-GraphRAG build** — gated on a NEW multi-hop eval per the spike verdict
  (`.planning/spikes/001-003`); not this milestone.
- **Two fix-on-touch gaps surfaced by the doc-GraphRAG spike, already mapped to
  requirements:** ingest runs GLiNER on whole-document text → HTTP 400 on large docs
  (**TEST-08**, Phase 9); `temporal_graph.py:137` `(type,name)` entity keying
  fragments the graph (**TEST-03**, Phase 11).

### Reviewed Todos (not folded)
None — `todo.match-phase 7` returned 0 matches.

</deferred>

---

*Phase: 7-Remove TuringDB + Dependency Hardening*
*Context gathered: 2026-07-16*
