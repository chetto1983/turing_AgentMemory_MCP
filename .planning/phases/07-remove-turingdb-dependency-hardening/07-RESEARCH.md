# Phase 7: Remove TuringDB + Dependency Hardening - Research

**Researched:** 2026-07-16
**Domain:** Dead-dependency removal, env/volume rename, pytest compat-smoke + grep-gate hardening
**Confidence:** HIGH

## Summary

This is a verification-and-removal phase, not a build phase. Every claim below was checked
directly against the live tree (`git grep`, file reads, one live Python probe of the installed
`fastmcp`/`graspologic-native` packages, and one live `create_mcp_app()` construction) rather
than trusted from CONTEXT.md's hypothesis list. The removal surface is real and mostly matches
CONTEXT.md, with four material corrections the planner needs:

1. **The `sys.modules["turingdb"]` stub is NOT centralized in `tests/conftest.py`.**
   `tests/conftest.py` contains only the no-skip-as-green hookwrapper guard — zero TuringDB
   content. The 2-line stub (`if "turingdb" not in sys.modules: sys.modules["turingdb"] = ...`)
   is copy-pasted independently into **31 individual test/shared-fixture files** (verified by
   exact-pattern grep, not the looser 41-file "any turingdb mention" count). The plan must
   remove it from all 31, not from one central file.
2. **`admin_repair.py` is not a single TuringDB-only unit.** It has three functions; only
   `repair_vector_index` is wired to a CLI command (`repair-vector-index`) and only that one is
   TuringDB-CSV-specific (genuinely meaningless under ArcadeDB HNSW). The other two —
   `repair_sparse_projection` and `repair_community_projection` — are **never called from `cli.py`
   at all**, only exercised by their own unit tests. Live evidence (`store_evidence.py:116-119`)
   further shows the SQLite-FTS5 `SparseIndex` these functions target is **already dead for
   reads** ("the SQLite FTS5 outbox is never consulted for reads ... unlike the retired
   `self.sparse_index is not None` gate"). This makes the whole file, not just the vector-repair
   function, a fix-on-touch candidate — flagged for a planner decision, not silently deleted.
3. **`TURINGDB_GRAPH` is not a dead connection var** the way `TURINGDB_URL` and the five
   `TURINGDB_*_INDEX` vars are. `server.py:129` reads it live (default `"agent_memory"`) and
   feeds it into `self.graph` (store telemetry/span labels) and `index_prefix` (ArcadeDB index
   naming defaults) — it is a naming/telemetry label, not a TuringDB connection detail. D-02's
   literal text lists it for deletion; the live code says it must be **renamed**, not deleted,
   or index-naming defaults and telemetry break.
4. **`docs/architecture.md` is already TuringDB-free** (zero grep hits) — CONTEXT.md's D-03 docs
   sweep list includes it, but it needs no edit. Conversely `docs/publication/HACKER_NEWS.md`
   (public-facing) has TuringDB mentions and is *not* on CONTEXT's list — worth including.

Everything else — the `turingdb==1.35` pyproject dependency, the `turingdb`/`turingdb-volume-init`
Compose services, `docker/turingdb.Dockerfile`, `e2e_score.py`'s `from turingdb import __version__`,
the `benchmark.py`/`benchmark_stages.py`/`benchmark_memoryarena.py`/`benchmark_schema.py`/
`agent_quality_eval.py` cluster, and the `TURINGDB_HOME`/`/turing` app-state paths — is confirmed
exactly as CONTEXT.md describes, with precise line-level evidence recorded below.

**Primary recommendation:** Treat this as five sequenced work streams — (0) confirm the Phase-6
GO gate via `gate_guard.assert_gate_go`, (1) delete the confirmed-dead legacy harness cluster +
its CLI wiring + its ~4 test files, (2) sweep the 31-file test stub + the src-level stale
references + the 3 live `TURINGDB_HOME` read sites + the 1 live `TURINGDB_GRAPH` read site (using
a distinct rename target, not deletion) + compose.yaml/`.env.example`/docs, (3) add the two
compat-smoke tests (extending, not duplicating, `tests/test_warning_filters.py` for FastMCP) plus
one new grep-gate test generalizing the existing `store_core.py`-scoped grep-gate pattern to all
of `src/`, (4) rewrite the CLAUDE.md invariants. Each stream has a concrete, already-proven
verification command (see Validation Architecture).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Dependency removal (`turingdb` pkg, Compose services, Dockerfile) | Build/Infra | — | Packaging and container orchestration concern, not application logic |
| App-state env/volume rename (`/turing`→`/bertoni`) | API/Backend (config loading) | CDN/Static N/A | `server.py`/`document_job_manager.py`/`provider_config.py` read these at process bootstrap |
| Legacy harness deletion (benchmark*/agent_quality_eval/admin_repair) | Build/Infra (CLI + scripts) | — | Operator-run tooling outside the MCP request path |
| Dependency version-gate tests (DEP-01/DEP-02) | API/Backend (test suite) | — | Exercises `community_detection.py` (Leiden) and `server.py` (FastMCP app construction) directly |
| No-`import turingdb` grep-gate | API/Backend (test suite) | — | Scans `src/` tree; a build-time correctness oracle, not a runtime capability |
| CLAUDE.md invariant rewrite | Docs/Governance | — | No code path; governs future planning/execution, cross-cuts every tier |

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ARC-10 | TuringDB removed from codebase and Compose stack; CLAUDE.md invariants updated (ArcadeDB canonical, invariant #2 superseded) | Removal Surface Verification table (per-file DELETE/KEEP/REWRITE verdicts), App-State Rename table, Invariant Rewrite Substrate section, Cut-Proof Gate Wiring section |
| DEP-01 | Version-gate `graspologic-native` with automated compatibility testing before upgrades | DEP-01 Compat-Smoke Test Shape section (exact `hierarchical_leiden` call signature verified live) |
| DEP-02 | Version-gate `fastmcp` (compatibility shim / version-gated tool features) | DEP-02 Compat-Smoke Test Shape section (existing `tests/test_warning_filters.py` extension point verified live) |
</phase_requirements>

## Removal Surface Verification (per-file DELETE / KEEP / REWRITE)

Verified against the live tree with `git grep`, file reads, and import-graph tracing — not
assumed from CONTEXT.md's hypothesis list. `git grep -il turingdb` currently returns **204 files**
project-wide (docs+planning+code+tests); `git grep -c "turingdb\|TuringDB\|TURINGDB"` sums to
**1333 total line matches**. Below is the disposition for every file CONTEXT.md named as a
deletion/edit candidate, plus corrections found during verification.

### Legacy harness cluster — DELETE (confirmed dead, evidence below)

| File | LOC | Verdict | Evidence |
|------|-----|---------|----------|
| `src/turing_agentmemory_mcp/benchmark.py` | 288 | **DELETE** | Only importer is `scripts/benchmark.py` (thin CLI wrapper, itself deletable) and `agent_quality_eval.py` (`from turing_agentmemory_mcp.benchmark import _git_commit`, also deleted). Not referenced by `cli.py`, `ci.yml`, or `Makefile`. `e2e_score.py`'s own docstring calls it "legacy, still-TuringDB-backed" and confirms `real_document_benchmark.py`/`e2e_score.py` supersede it. |
| `src/turing_agentmemory_mcp/benchmark_stages.py` | 460 | **DELETE** | `from turing_agentmemory_mcp.benchmark_schema import ... turingdb_version` (line 15) — imports the exact dead field. Only consumed by `benchmark.py`/`benchmark_memoryarena.py`. |
| `src/turing_agentmemory_mcp/benchmark_memoryarena.py` | 263 | **DELETE** | Imports `turingdb_version` from `benchmark_schema.py` (used in 3 call sites, lines 202/225/253) and `_measure_batch` from `benchmark_stages.py`. Distinct from `memoryarena.py` (KEEP — see below). |
| `src/turing_agentmemory_mcp/benchmark_schema.py` | 117 | **DELETE** | `from turingdb import __version__ as turingdb_version` (line 17, try/except-guarded) — the literal turingdb import CONTEXT.md targets. |
| `src/turing_agentmemory_mcp/agent_quality_eval.py` | 573 | **DELETE** | `from turingdb import __version__ as turingdb_version` (line 330, try/except-guarded); reads `TURINGDB_AGENT_QUALITY_HOME` (line 339, the sole user of that var — this is why `.gitignore`'s `.turingdb/` entry exists and can also be dropped); instantiates `TuringDaemon` (line 343, real subprocess `turingdb start/stop`). Wired to `cli.py`'s `agent-quality-eval` subcommand (line 74-88) — CLI dispatch must be removed too. Not referenced in `ci.yml` (explicit comment: "the other, operator-run benchmark script ... stays outside CI entirely"). |
| `src/turing_agentmemory_mcp/memoryarena.py` | 108 | **KEEP — do not touch** | Imported by `e2e_score_scenarios.py` (kept, live e2e harness) for `answer_marker`/`load_sample`. Zero turingdb references of its own. Easy to conflate with `benchmark_memoryarena.py` by name — they are separate files with separate fates. |
| `scripts/benchmark.py` | 12 | **DELETE** | Thin wrapper: `from turing_agentmemory_mcp.benchmark import main`. Dies when `benchmark.py` is deleted. |
| `scripts/agent_quality_eval.py` | 12 | **DELETE** | Thin wrapper: `from turing_agentmemory_mcp.agent_quality_eval import main`. Dies when `agent_quality_eval.py` is deleted. |
| `tests/test_benchmark.py` | 76 | **DELETE** | Tests `benchmark.py` directly (`turingdb_version="1.35"` literal at line 11). |
| `tests/test_agent_quality_eval.py` | 156 | **DELETE** | Tests `agent_quality_eval.py` directly. |
| `src/turing_agentmemory_mcp/cli.py` | 122 | **REWRITE** | Remove the `agent-quality-eval` subparser (lines 27-34, 74-88) and the `repair-vector-index` subparser (lines 45-51, 108-117; see below). `serve`/`file-pipe`/`e2e-score`/`utcp-manual`/`lab` subcommands are untouched. |

**Not on CONTEXT's list but confirmed clean (no action needed):**
`scripts/real_document_benchmark.py` and `tests/test_real_document_benchmark.py` have **zero**
turingdb references — this is the Phase-6 gate's *kept*, ArcadeDB-era measurement script; do not
confuse it with the doomed `benchmark.py` cluster by name similarity.

### `admin_repair.py` — split verdict, planner decision required

| Function | Wired to CLI? | Verdict | Evidence |
|----------|---------------|---------|----------|
| `repair_vector_index` | Yes — `cli.py` `repair-vector-index` subcommand (lines 45-51, 108-117) | **DELETE** (function + CLI dispatch) | Quarantines a `vector/` directory tree — a TuringDB CSV-vector-storage artifact that does not exist under ArcadeDB's native `LSM_VECTOR`/HNSW index. Meaningless on the new backend, exactly as CONTEXT.md states. |
| `repair_sparse_projection` | **No** — never called from `cli.py`, only from its own unit tests | **Fix-on-touch candidate, flag for planner** | Rebuilds `SparseIndex` (SQLite FTS5) from canonical documents. Live evidence (`store_evidence.py:116-119`) proves `SparseIndex` is never consulted for reads anymore — "the SQLite FTS5 outbox is never consulted for reads ... unlike the retired `self.sparse_index is not None` gate." Already-orphaned code operating on an already-dead read path. Not explicitly named in CONTEXT.md's decision text (which only calls out `repair_vector_index`); recommend deleting alongside it as fix-on-touch dead code, but this is a genuine scope judgment call — flag explicitly rather than silently deleting. |
| `repair_community_projection` | **No** — same as above | **Fix-on-touch candidate, flag for planner** | Generic community-graph rebuild via `CommunityRebuilder` protocol — not TuringDB-specific at all, but equally never wired to any CLI command. Same orphaned-code judgment call as above. |

`tests/test_admin_repair.py` (164 LOC) tests all three functions — if only `repair_vector_index`
is deleted, this file needs a partial rewrite (remove ~40% of it), not a full delete. If the
planner elects to delete the whole file (all three functions), document that as a deliberate
fix-on-touch scope decision in the plan, not an assumption carried from CONTEXT.md.

### `e2e_score.py` / `e2e_score_stubs.py` / `e2e_score_scenarios.py` — REWRITE (not delete)

These are the **kept**, canonical ArcadeDB-era E2E harness (`cli.py`'s `e2e-score` subcommand,
`Makefile`'s `e2e`/`docker-e2e` targets, `ci.yml`'s `dockerized-integration` job). They still
carry TuringDB-only re-exports that must be pruned, not the files themselves.

| File | LOC | Verdict | Evidence |
|------|-----|---------|----------|
| `src/turing_agentmemory_mcp/e2e_score.py` | 193 | **REWRITE** | Line 35: `from turingdb import __version__ as turingdb_version` (top-level, unconditional — this is the actual import that requires the Windows `sys.modules["turingdb"]` stub to exist at all for this module to import). Lines 171-175: writes `"turingdb_version": turingdb_version` into the result dict "for `baseline/03-turingdb` field-shape parity." D-01 explicitly targets dropping both. `run_e2e()` itself already uses `ArcadeE2EBackend`, not `TuringDaemon` — the import is vestigial. |
| `src/turing_agentmemory_mcp/e2e_score_stubs.py` | 306 | **REWRITE** | Line 26: `from turingdb import TuringDB` (top-level). `TuringDaemon` class (lines 171-221) and `wait_rest()` function (lines 41-52) are confirmed **dead** — `TuringDaemon(...)` is instantiated only in `agent_quality_eval.py:343` and `benchmark.py:77`, both deleted in this phase; no test imports `TuringDaemon` directly. `LocalEmbedServer`/`LocalRerankServer`/`free_port`/`ArcadeE2EBackend`/`ARCADEDB_E2E_IMAGE` are all live (imported by `e2e_score.py` and actually used in `run_e2e()`) — keep unchanged. |
| `src/turing_agentmemory_mcp/e2e_score_scenarios.py` | — | **KEEP — no turingdb refs at all** | Zero matches on any turingdb pattern; imports `memoryarena.py` (kept). |

### `store_core.py` / `store_documents.py` / `store_rebuild.py` / `store.py` — REWRITE (comments only)

Confirmed exactly as CONTEXT.md's "Reusable Assets" note states: the store read/write paths were
already ported in Phase 4; every remaining reference is a stale docstring or comment, never a live
`from turingdb import ...`.

| File | Live turingdb import? | Stale references to fix |
|------|------------------------|--------------------------|
| `store_core.py` | No | Module docstring; a comment at line ~317 ("D-10: reconnect is a reachability re-probe, not TuringDB's..."); already has a live grep-gate test (`test_seam_contains_no_turingdb_write_primitives_or_csv_vector_load` in `_store_arcadedb_core_shared.py`, collected via `tests/test_store_arcadedb_core.py`) that already asserts `"from turingdb"` is absent from this one file — use as the direct model for the phase-wide guard (see below). |
| `store_documents.py` | No | Comment at line 11 ("the old TuringDB-shaped byte-budget batch splitter") and line 373 ("TuringDB's submit-before-match visibility gap"). |
| `store_rebuild.py` | No | Comment at line 9 ("instead of the retired TuringDB CSV..."). |
| `store.py` | No | **Module docstring line 1: `"""Canonical TuringDB-backed memory/document store.`** — user-facing, high-visibility, should read "ArcadeDB-backed". |

### Frontend / Lab — REWRITE (UI-visible, not just comments)

| File | Issue | Fix |
|------|-------|-----|
| `src/turing_agentmemory_mcp/lab.py` | `REQUIRED_BENCHMARK_FIELDS` tuple (line 19) requires a `"turingdb_version"` key on every benchmark-JSON row the Lab dashboard validates (`required_ok` check, line 99). This is the exact field D-01 drops from `e2e_score.py`'s output. Also a hardcoded architecture-diagram node: `{"id": "turingdb", "label": "TuringDB", "type": "store", ...}` (line 115) with an edge `{"source": "mcp", "target": "turingdb", "label": "persists"}` (line 129). | Rename the required field (e.g. `turingdb_version`→`backend_version`, or drop the requirement) and update `tests/test_lab.py`'s fixture (line 10) to match. Rename the diagram node id/label to `arcadedb`/`ArcadeDB`. |
| `src/turing_agentmemory_mcp/frontend/app.js` | Line 19: an example Cypher-shaped query string `"MATCH (m:Memory)-[r]->(store:TuringDB) RETURN m,r,store LIMIT 25"` — stale on two counts (TuringDB label AND Cypher syntax; Phase 4 D-05 settled on ArcadeDB's SQL `MATCH {...}` object-notation form, not Cypher). | Replace with an ArcadeDB-shaped example query and an `ArcadeDB` label. |
| `src/turing_agentmemory_mcp/frontend/index.html` | Line 24: `<span>TuringDB</span>` static label in the architecture panel. | Replace with `ArcadeDB`. |
| `tests/test_lab.py` | Line 10: fixture dict includes `"turingdb_version": "test"` to satisfy `REQUIRED_BENCHMARK_FIELDS`. | Update alongside the `lab.py` field rename. |

### Test-stub sweep (the actual 31-file surface — not `tests/conftest.py`)

`tests/conftest.py` contains **only** the no-skip-as-green hookwrapper guard (29 lines total,
verified by full read) — zero turingdb content. The `sys.modules["turingdb"]` stub is duplicated
verbatim in every file below (confirmed by exact-pattern grep for
`if "turingdb" not in sys.modules:`):

```
tests/_arcadedb_physical_isolation_support.py   tests/_store_arcadedb_core_shared.py
tests/_retrieval_arcadedb_shared.py             tests/_documents_arcadedb_shared.py
tests/_batch_memory_shared.py                   tests/test_tenant_binding_enforcement.py
tests/test_tenant_telemetry_pseudonymity.py     tests/test_document_file_pipe.py
tests/test_document_ingest_file.py              tests/test_store_entity_processing.py
tests/test_store_arcadedb_retrieval.py          tests/test_store_arcadedb_rebuild.py
tests/test_store_arcadedb_memory.py             tests/test_store_arcadedb_documents.py
tests/test_runtime_pipeline.py                  tests/test_stable_id_survives_rebuild.py
tests/test_retrieval_filters.py                 tests/test_observability.py
tests/test_fused_memory_search.py               tests/test_community_detection.py
tests/test_batch_memory_write.py                tests/test_batch_memory_dedup.py
tests/test_batch_memory.py                      tests/test_arcadedb_tenant_isolation.py
tests/test_utcp_conformance.py                  tests/test_rerank.py
tests/test_backboard_locomo_runner.py           tests/test_utcp_manual.py
tests/test_server_batch_tool.py                 tests/test_auth.py
```
(31 files.) The exact 2-line pattern is:
```python
if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")
```
It exists **only** because Windows has no `turingdb==1.35` wheel and these test files transitively
import `turing_agentmemory_mcp.store`/`.server`/`.e2e_score`, which (until this phase) chain into
`from turingdb import ...`. Once the legacy harness cluster and `e2e_score.py`/`e2e_score_stubs.py`
imports above are removed AND `turingdb==1.35` is dropped from `pyproject.toml`, nothing in the
import graph these 31 files exercise needs `turingdb` importable — the stub becomes both
unnecessary and, if left in place, actively misleading (masking that the real package is gone).
**Sequencing matters:** remove the stub only after the src-side `from turingdb import ...` call
sites are gone, or these 31 files will start failing on collection.

A further 10 files reference "turingdb" in comments/docstrings only (no stub, no live import) —
lower priority, sweep opportunistically: `tests/test_gate_diff.py`, `tests/test_store_arcadedb_core.py`,
`tests/test_compose_config.py` (see below — this one needs real assertion rewrites, not just a
comment sweep), `tests/test_docker_hardening.py`, `tests/test_gliner_provider_extraction.py`,
`tests/test_entity_extraction_http.py`, `tests/test_entity_extraction.py`, `tests/test_lab.py`,
`tests/test_benchmark.py` (deleted anyway), `tests/test_tenant_server_routing.py`.

### `tests/test_compose_config.py` — REWRITE (assertions, not comments)

This file makes **positive assertions** that `TURINGDB_MEMORY_INDEX`/`TURINGDB_DOCUMENT_INDEX`/
`TURINGDB_ENTITY_INDEX`/`TURINGDB_FACT_INDEX`/`TURINGDB_COMMUNITY_INDEX` env entries and the
`turing-data:/turing` volume mount and `/turing/data/...` paths **are present** in `compose.yaml`
(lines 29-47, 67-72, 24). Every one of these assertions must flip: the five `TURINGDB_*_INDEX`
assertions should become "must NOT be present" (or be deleted, since the vars themselves are
deleted), and the volume/path assertions must be updated to `bertoni-data:/bertoni` and
`/bertoni/data/...` per D-02. This is the primary regression risk for the compose-service removal
— skipping this file's rewrite leaves a stale test asserting removed content, which will fail
loudly (good) but for the wrong stated reason if not updated deliberately.

## App-State Rename Surface (D-02: `/turing`→`/bertoni`)

Every live read site, traced to source line. `TURINGDB_URL` and the five `TURINGDB_*_INDEX` vars
are confirmed **dead in `src/`** (zero read sites found by grep) — safe to delete outright from
compose/`.env.example`/docs with no code change required. `TURINGDB_HOME` and `TURINGDB_GRAPH` are
**live** and need different treatment:

| Env var / path | Live read sites (file:line) | Disposition |
|---|---|---|
| `TURINGDB_HOME` (default `/turing`) | `server.py:130` (`_unbootstrapped_store_from_env`), `server.py:223` (`tenant_router_from_env`), `document_job_manager.py:370` (`document_ingest_manager_from_env`) | **Rename to `BERTONI_HOME`, default `/bertoni`** at all 3 independent call sites (no shared constant — each function calls `os.environ.get(...)` separately; a rename must touch all 3, not one). |
| `TURINGDB_GRAPH` (default `"agent_memory"`) | `server.py:129` only, feeds `self.graph` (store telemetry/span label — `store_core.py` lines 344/433/438/446) and `index_prefix` (ArcadeDB index-name defaults, `server.py:132,170-183`) | **Correction to D-02:** this is NOT a dead TuringDB connection var — it is a live naming/telemetry label. **Rename** (e.g. to `AGENTMEMORY_GRAPH` or `ARCADEDB_GRAPH_NAME` — exact name is Claude's Discretion per D-02's own carve-out), do not delete. Deleting it outright breaks index-naming defaults and span/telemetry labels. |
| `TURINGDB_URL` | **Zero read sites in `src/`** | Dead — delete from compose/.env.example only, no code change. |
| `TURINGDB_{MEMORY,DOCUMENT,ENTITY,FACT,COMMUNITY}_INDEX` (5 vars) | **Zero read sites in `src/`** — `ARCADEDB_*_INDEX` equivalents are the ones actually read (`server.py:169-183`) | Dead — delete from compose/.env.example/`tests/test_compose_config.py` only, no code change. |
| `TURINGDB_EMBED_DIMENSIONS` | `provider_config.py:56`, but **only as a fallback** — `EMBED_DIMENSIONS` (line 53) is already checked first and is the value actually used in `.env.example`/`compose.yaml` today | **Already effectively done.** D-02's "rename TURINGDB_EMBED_DIMENSIONS → EMBED_DIMENSIONS" target already exists as the primary read; only the dead fallback branch (lines 56-58) needs deleting. |
| `/turing/data/agent-memory-fts.sqlite3` (`AGENTMEMORY_SPARSE_PATH` default) | `provider_config.py`-adjacent, built in `server.py:134-139` from `home` (= `TURINGDB_HOME`) | Follows `TURINGDB_HOME`'s rename automatically once that's renamed — same for `AGENTMEMORY_TENANT_REGISTRY_PATH` (`server.py:224-229`), `AGENTMEMORY_DOCUMENT_JOB_PATH`/`AGENTMEMORY_DOCUMENT_STAGING_ROOT` (`document_job_manager.py:369-381`). |
| `TURINGDB_AGENT_QUALITY_HOME` | `agent_quality_eval.py:339` only | Dies with the file (deleted in this phase). Also the reason `.gitignore`'s `.turingdb/` entry (line 13) exists — sweep it too. |

**`compose.yaml` service-level changes** (verified via full-file read, not excerpt):
- Delete `turingdb-volume-init` service entirely (builds `docker/turingdb.Dockerfile`, chowns `/turing`).
- Delete `turingdb` service entirely (the TuringDB daemon container, healthcheck imports `from turingdb import TuringDB`).
- `turing-agentmemory-mcp` service: remove `depends_on: turingdb: condition: service_healthy`; remove all 8 `TURINGDB_*` environment lines; rename `turing-data:/turing` volume mount to `bertoni-data:/bertoni`; rename the 5 `/turing/data/...`-rooted env defaults to `/bertoni/data/...`.
- Top-level `volumes:` section: rename `turing-data:` → `bertoni-data:`.
- **Do NOT touch** (explicitly out of scope per CONTEXT.md's deferred full rebrand): the top-level `name: turing-agentmemory-mcp`, the `turing-agentmemory-mcp` service name itself, any `turing-agentmemory-*`/`turing-agentmemory-mcp:local` image tags, or the `agentmemory-*` service names. Only the TuringDB-specific services/vars/volume and the app-state path prefix move.

`.env.example` changes (verified via `git show HEAD:.env.example` — direct `Read`/`Bash cat` on this
file is blocked by this session's permission settings; use `git show`):
- Delete lines 3-6 (the `TURINGDB_URL`/`TURINGDB_GRAPH`/`TURINGDB_HOME` block and its "transitional... until the later compatibility cleanup" comment — this phase IS that cleanup).
- Rename `/turing/data/agent-memory-tenant-registry.sqlite3` (line 25), `/turing/audit/agentmemory.jsonl` (line 57), `/turing/audit/spans.jsonl` (line 58) to `/bertoni/...`.
- `EMBED_DIMENSIONS=768` (line 28) already present and correctly named — no change needed there.

## Standard Stack

No new runtime dependencies are introduced by this phase. `importlib.metadata` (stdlib) is the
only "new" API surface, already used as a precedent in this exact repo
(`tests/test_warning_filters.py:15`).

### Core (existing, version-gated not newly installed)
| Library | Installed version (verified live) | Pin in `pyproject.toml` | Purpose |
|---------|---------|---------|---------|
| `fastmcp` | 3.4.4 [VERIFIED: `pip show fastmcp` in this repo's `.venv`] | `>=3.4,<4` | MCP server framework — DEP-02 target |
| `graspologic-native` | 1.3.1 [VERIFIED: `pip show graspologic-native` in this repo's `.venv`] | `==1.3.1` | Native Leiden community detection — DEP-01 target |

Both installed versions currently satisfy their pins exactly — the compat-smoke tests should pass
green on today's environment and only fail on a future version bump, which is the point.

### Installation
No new installs. `turingdb==1.35` removal is a deletion from `pyproject.toml`'s `dependencies`
list (line 30), plus the `"turingdb"` keyword (line 13) and the description string (line 8,
"TuringDB-backed Agent Memory MCP..." → "ArcadeDB-backed...").

## Package Legitimacy Audit

No new external packages are installed this phase — only a dependency **removal**
(`turingdb==1.35`, being deleted, not added) and two new pytest tests against **already-pinned,
already-installed** packages (`fastmcp`, `graspologic-native`) via stdlib `importlib.metadata`.
The Package Legitimacy Gate protocol (`gsd-tools query package-legitimacy check`) is not
applicable — there is nothing new to check for slopsquatting/hallucination risk.

**Packages removed due to [SLOP] verdict:** none (not applicable — no legitimacy check needed).
**Packages flagged as suspicious [SUS]:** none.

## Architecture Patterns

### Recommended Sequencing (dependency-ordered, not the plan's wave structure — that's the planner's call)

```
0. Gate check   -- gate_guard.assert_gate_go(Path("baseline/06-gate/gate-result.json"))
                    confirms verdict == "GO" (already committed; this is a precondition
                    assertion, not new infra -- gate_guard.py is fully built + tested in
                    Phase 6, tests/test_gate_artifact_schema.py and
                    tests/test_phase7_gate_guard.py already cover it).
                              |
                              v
1. Delete legacy harness cluster (benchmark.py + 3 siblings + agent_quality_eval.py +
   2 scripts/ wrappers + cli.py dispatch + 2 test files) -- and admin_repair.py's
   repair_vector_index (+ cli.py dispatch) at minimum, with the two orphaned
   admin_repair.py functions flagged as a fix-on-touch decision.
                              |
                              v
2. Strip the now-dead `from turingdb import ...` from e2e_score.py / e2e_score_stubs.py
   (turingdb_version field + TuringDaemon/wait_rest dead code), and the stale
   docstrings/comments in store_core.py/store_documents.py/store_rebuild.py/store.py.
                              |
                              v
3. Remove `turingdb==1.35` from pyproject.toml (dependencies + keyword + description).
                              |
                              v
4. NOW sweep the 31-file sys.modules["turingdb"] stub (step 2/3 already removed every
   src-side reason the stub existed -- doing this before step 2/3 would break collection).
                              |
                              v
5. compose.yaml + .env.example + docker/turingdb.Dockerfile removal, TURINGDB_HOME->
   BERTONI_HOME / TURINGDB_GRAPH->(renamed) at the 4 live read sites, tests/test_compose_config.py
   rewrite.
                              |
                              v
6. Add DEP-01/DEP-02 compat-smoke tests + the src-wide no-import-turingdb grep-gate test.
                              |
                              v
7. docs/README/CHANGELOG/skills sweep + lab.py/frontend UI label fixes.
                              |
                              v
8. CLAUDE.md + .claude/CLAUDE.md invariant rewrite (D-03).
                              |
                              v
9. Cut-proof: full pytest green + `docker compose config --quiet` + E2E score gate green.
```

Step 4 before step 2/3 is a correctness trap: since the stub only exists to satisfy
`from turingdb import ...` calls that are *still in src* at that point, removing the stub first
would break collection on all 31 files until steps 2-3 land. Sequence matters here more than in
a typical additive phase.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Phase-7 entry gate (verify Phase-6 GO verdict) | A new guard/check script | `turing_agentmemory_mcp.gate_guard.assert_gate_go(Path("baseline/06-gate/gate-result.json"))` | Already built, already tested (`tests/test_gate_artifact_schema.py`, `tests/test_phase7_gate_guard.py`), fails closed on missing/malformed/NO_GO, reads fresh (no caching). Confirmed the committed artifact's `verdict` field is `"GO"`. |
| Grep-gate pattern for "no import X remains" | A novel test-authoring approach | Generalize `tests/test_store_arcadedb_core.py`'s existing `test_seam_contains_no_turingdb_write_primitives_or_csv_vector_load` (defined in `tests/_store_arcadedb_core_shared.py`) from one file (`store_core.py`) to a `Path("src").rglob("*.py")` loop asserting `"import turingdb"` / `"from turingdb"` not in any file's text | This exact pattern already exists, is collected, and passes today for its narrower scope — proven idiom in this repo, not a new invention. |
| Version-pin compatibility assertion | A new version-comparison test from scratch | `tests/test_warning_filters.py::test_project_requires_fastmcp_v3` already asserts the literal pin string `'"fastmcp>=3.4,<4"'` is in `pyproject.toml`; `tests/test_warning_filters.py::test_fastmcp_import_is_deprecation_clean` already imports `importlib.metadata.version('fastmcp')` in a subprocess | This file is the natural home to **extend** for DEP-02 (add an installed-version-in-range assertion + an app-construction smoke) rather than create a new, overlapping file. |

**Key insight:** This phase's test-authoring risk is duplicating assertions that already exist
(`test_warning_filters.py` for fastmcp, the `store_core.py`-scoped grep-gate for turingdb-absence).
Both should be extended/generalized, not shadowed by a second, slightly different test asserting
the same thing.

## DEP-01 Compat-Smoke Test Shape (graspologic-native)

Verified live call signature and return shape from `community_detection.py:315-322,153-161`:

```python
# Source: src/turing_agentmemory_mcp/community_detection.py (live call site, verified)
from graspologic_native import hierarchical_leiden

records = hierarchical_leiden(
    edges,                    # list[tuple[str, str, float]] -- (source_id, target_id, weight)
    resolution=1.0,           # float
    randomness=0.001,         # float
    iterations=2,             # int
    max_cluster_size=100,     # int
    seed=42,                  # int
)
# records: Sequence[Any], each record exposes:
#   record.is_final_cluster -> bool
#   record.node             -> str-coercible
#   record.level            -> int-coercible
#   record.cluster          -> str-coercible
```

Recommended smoke test shape (new small test file, e.g. `tests/test_dependency_compat.py`, kept
under 600 LOC alongside DEP-02):

```python
from importlib.metadata import version

def test_graspologic_native_version_is_pinned_supported() -> None:
    assert version("graspologic-native") == "1.3.1"  # matches pyproject.toml's exact pin

def test_graspologic_native_hierarchical_leiden_smoke() -> None:
    from graspologic_native import hierarchical_leiden
    edges = [("a", "b", 1.0), ("b", "c", 1.0)]  # tiny connected triangle-ish graph
    records = hierarchical_leiden(edges, resolution=1.0, randomness=0.001,
                                   iterations=2, max_cluster_size=100, seed=42)
    finals = [r for r in records if bool(r.is_final_cluster)]
    assert finals, "hierarchical_leiden returned no final-cluster records"
    assigned_nodes = {str(r.node) for r in finals}
    assert assigned_nodes == {"a", "b", "c"}
```

No existing test in the repo directly exercises `_native_hierarchical_leiden` with the real
package (existing `test_community_detection.py` tests use a fake/injected backend) — this is
genuinely new test surface, exactly as CONTEXT.md characterizes it.

## DEP-02 Compat-Smoke Test Shape (fastmcp)

`tests/test_warning_filters.py` (32 LOC, verified live) already has two of the three pieces:
`test_project_requires_fastmcp_v3` (pin-string assertion) and
`test_fastmcp_import_is_deprecation_clean` (subprocess `importlib.metadata.version('fastmcp')`
call). Missing: an installed-version-satisfies-range assertion and an app-construction/
tool-registration smoke. Verified live: `create_mcp_app(store=object())` (the exact pattern
`tests/test_auth.py:48` already uses to avoid a real ArcadeDB connection) constructs successfully
and `await app.list_tools()` returns **26** registered tools today.

```python
# Extend tests/test_warning_filters.py rather than duplicate it
from importlib.metadata import version
import asyncio

def test_installed_fastmcp_version_satisfies_pin() -> None:
    major, minor = (int(part) for part in version("fastmcp").split(".")[:2])
    assert (major, minor) >= (3, 4) and major < 4

def test_create_mcp_app_registers_tools_smoke() -> None:
    from turing_agentmemory_mcp.server import create_mcp_app
    app = create_mcp_app(store=object())  # dummy store -- no live ArcadeDB needed, same
                                            # pattern as tests/test_auth.py:48
    tools = asyncio.run(app.list_tools())
    assert len(tools) >= 20  # loose floor -- 26 registered as of this research; a breaking
                              # FastMCP bump that silently drops tool registration must fail this
```

Neither DEP-01 nor DEP-02 tests should use `pytest.skip()` anywhere — both `graspologic-native`
and `fastmcp` are unconditional `pyproject.toml` dependencies (always installed), so there is no
legitimate skip condition. This is how they satisfy "no-skip-as-green": there is no skip path to
guard against in the first place, and if the version check or the smoke call fails, it is a hard
`AssertionError`/exception, never a skip. (Confirmed the guard mechanism itself:
`tests/conftest.py`'s hookwrapper only converts a `skipped` outcome on `integration`/`gpu`-marked
tests into a failure under `CI=true` — these new tests simply never call `pytest.skip`, so the
guard is structurally satisfied by construction, not by opting into a marker.)

## No-`import turingdb` Grep-Gate Guard

**Existing model** (verified live, currently scoped to one file): `tests/_store_arcadedb_core_shared.py`
defines `test_seam_contains_no_turingdb_write_primitives_or_csv_vector_load`, collected via
`tests/test_store_arcadedb_core.py` (confirmed via `pytest --collect-only -k`). It reads
`store_core.py`'s source text and asserts a list of forbidden substrings (including
`"from turingdb"`) are absent.

**Generalization for this phase** — scan all of `src/`, not one file:

```python
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp"

def test_no_turingdb_import_anywhere_in_src() -> None:
    offenders = []
    for path in _SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import turingdb" in text or "from turingdb" in text:
            offenders.append(str(path.relative_to(_SRC_ROOT.parents[1])))
    assert not offenders, f"turingdb import still present in: {offenders}"
```

Place this as a new small test (e.g. `tests/test_no_turingdb_imports.py`) — do not fold it into
`_store_arcadedb_core_shared.py` (that file's existing narrower test should stay, since it also
checks other forbidden TuringDB primitives like `"new_change"`/`"CHANGE SUBMIT"`/`"LOAD VECTOR"`
specific to `store_core.py`'s write path, which is a different, still-valid assertion). This new
test must run **after** step 4 in the sequencing above (all live `from turingdb import ...` call
sites removed) or it will fail immediately and correctly flag unfinished work — which is fine as a
RED-then-GREEN TDD marker for the phase, per this repo's `tdd_mode: true` config.

## Invariant Rewrite Substrate (D-03)

Source facts the new invariants must codify, pulled from Phase 4/5/6 CONTEXT.md and STATE.md
(not re-derived — this phase does not re-investigate the port, only documents it):

| New/changed invariant | Substrate fact | Source |
|---|---|---|
| #2 superseded: ArcadeDB sole canonical backend | Direct port, no abstraction layer, no `AGENTMEMORY_BACKEND` switch — confirmed still true (no such switch exists in `provider_config.py`/`server.py`) | `04-CONTEXT.md` "Locked from prior milestone" |
| #4 retired/replaced: managed transaction + read-your-writes | `_write_many` collapsed into ONE `begin/commit` transaction wrapped in `commit retry N` for MVCC conflicts, replacing TuringDB's per-batch submit-before-match | `04-CONTEXT.md` D-08; confirmed live via `store_core.py`'s `_write`/`_write_many`/`run_in_transaction` |
| #5 retired: no app-layer re-sort of composed VECTOR SEARCH...MATCH | Native HNSW (`LSM_VECTOR`) returns record + score together; the `vector_id` int-join was deleted, not ported | `04-CONTEXT.md` "Delete the vector_id int-join (SC#3)" |
| #6 replaced: reconnect + `/health` probe | `store.py:317` comment: "D-10: reconnect is a reachability re-probe, not TuringDB's [load_graph]"; `/health` gates on a real ArcadeDB probe query, replacing the `graph.ready` stage | `04-CONTEXT.md` D-10 |
| New: MVCC conflict = HTTP 503 `ConcurrentModificationException` → redo whole begin/commit, never blind-retry | STATE.md: "ArcadeDB MVCC conflict signal is HTTP 503 with exception=ConcurrentModificationException; retrying the same commit does not recover (session invalidated), so run_in_transaction redoes the whole begin/body/commit cycle" | STATE.md Accumulated Context (Phase 4) |
| New: native `LSM_VECTOR`+Lucene ACID-consistent with graph writes; SQLite-FTS5 outbox retired | Confirmed live: `store_evidence.py:116-119` — "the SQLite FTS5 outbox is never consulted for reads ... both native ArcadeDB lexical channels are unconditionally available." **Caveat for accurate invariant wording:** the *write*-side outbox (`prepare`/`commit_batch`/`replay`/`discard_prepared`) was removed per CHANGELOG's "Removed" section; but `sparse_index.py`'s `SparseIndex` class itself is **not deleted** — it survives as a `fusion_enabled`-gated memory-search channel with a `.status()` health signal only (`store_core.py:186,226,296,326-328`). The invariant should say the outbox-as-a-second-source-of-truth is retired, not that `sparse_index.py`/`SparseIndex` no longer exists in the codebase. |
| New: one ArcadeDB database per tenant + mandatory `user_identifier` predicate + `TenantBinding` | `05-*` STATE.md entries — physical isolation "never replaces the predicate"; `TenantBinding.verify()` reuses `derive_tenant_database_identity` with `hmac.compare_digest` | STATE.md Accumulated Context (Phase 5) |
| #1 reconfirmed: tenant scope | All 18 public store methods call the binding-aware guard first (STATE.md Phase 5 entry) | STATE.md |
| #3 reconfirmed: stable IDs | `ids.py`'s `stable_id()` stays canonical; ArcadeDB's native RID never leaks into ID/vector-ID logic | `04-CONTEXT.md` "Locked from prior milestone" |

## Cut-Proof Gate Wiring

`gate_guard.py` (131 lines including docstring — actually 80 LOC on inspection) is fully built and
tested by Phase 6. `assert_gate_go(Path("baseline/06-gate/gate-result.json"))` is verified live to
pass against the committed artifact today (`verdict: "GO"` confirmed by direct JSON read). Phase 7
**consumes** this — the plan's entry precondition should be a single call to `assert_gate_go`
(e.g. as a fixture/setup step or a one-line CLI/script invocation at the start of execution), not
new guard infrastructure. `tests/test_gate_artifact_schema.py` and `tests/test_phase7_gate_guard.py`
already comprehensively test `gate_guard.py` itself — no new tests needed for the guard mechanism,
only its invocation as a phase precondition.

"Full green pytest suite" baseline: **882 tests** currently collected (`pytest tests/ --collect-only -q`,
verified live — up from the 364-test baseline recorded at Phase 1). `docker compose config --quiet`
currently validates cleanly (turingdb services still present but syntactically valid; must be
re-verified after their removal). The E2E score gate (`scripts/e2e_score.py`) currently asserts
`score >= 9.8 and check_count == 19` in `ci.yml` (lines 145,140) — dropping `turingdb_version` from
its output JSON does not affect either assertion (CI only checks `.score`/`.check_count`/`.verdict`).

## Common Pitfalls

### Pitfall 1: Removing the test stub before the src-side imports are gone
**What goes wrong:** All 31 test files fail at collection with `ModuleNotFoundError: No module
named 'turingdb'`.
**Why it happens:** The stub exists because `turing_agentmemory_mcp.store`/`.server`/`.e2e_score`
transitively `from turingdb import ...` today; removing the stub without first removing those
imports (and the `turingdb==1.35` pyproject dependency) leaves nothing satisfying the import.
**How to avoid:** Sequence per the Architecture Patterns section — src-side import removal (steps
1-3) strictly before stub removal (step 4).
**Warning signs:** `pytest --collect-only` errors immediately after a stub-removal commit.

### Pitfall 2: Treating `TURINGDB_GRAPH` as a dead connection var like `TURINGDB_URL`
**What goes wrong:** Deleting it outright (as CONTEXT.md's D-02 literal text suggests) silently
changes `index_prefix` derivation and `self.graph`-labeled telemetry to always use the Python
default `"agent_memory"` instead of whatever operators had configured — a behavior change
disguised as a rename, and worse, it happens silently (no error, no test failure) since
`server.py:129`'s `.get("TURINGDB_GRAPH", "agent_memory")` degrades gracefully to the same default
value most deployments already use.
**Why it happens:** The var name superficially looks like the other `TURINGDB_*` connection vars,
but its actual role is a naming label, verified only by tracing `self.graph`'s three downstream
uses in `store_core.py`.
**How to avoid:** Rename it to a non-TuringDB name (planner's choice per D-02's Claude's
Discretion carve-out), update `compose.yaml`/`.env.example` to match, keep the default value
`"agent_memory"` unchanged so no deployment behavior shifts.
**Warning signs:** `index_prefix` silently reverting to a default that doesn't match a previously
customized `TURINGDB_GRAPH` value — would only surface as an ArcadeDB index-name mismatch at
runtime, not a test failure, unless a test explicitly covers a non-default `TURINGDB_GRAPH` value
(none currently does, per `tests/test_compose_config.py`'s current assertions).

### Pitfall 3: Deleting `admin_repair.py` wholesale without flagging the orphan functions
**What goes wrong:** `repair_sparse_projection`/`repair_community_projection` get silently deleted
along with the confirmed-dead `repair_vector_index`, without anyone noticing they were never
CLI-reachable in the first place — losing test coverage for a `CommunityRebuilder` Protocol
pattern that might still be intentional, unexercised-by-design tooling (e.g. reserved for a future
`repair` subcommand that was never finished).
**Why it happens:** CONTEXT.md's decision text only explicitly names "the `admin_repair.py`
command" (singular), which could be read as "the whole file" or "the one wired command."
**How to avoid:** Treat this as an explicit planner decision point (documented in this research's
Removal Surface table above), not a silent side effect of "delete admin_repair.py."
**Warning signs:** A code-review catching a 3-function file being deleted for a 1-function reason.

### Pitfall 4: Missing the `tests/test_compose_config.py` positive-assertion rewrite
**What goes wrong:** After compose.yaml's TuringDB removal, `test_product_service_enables_the_fused_temporal_pipeline`
and `test_product_service_locks_the_physical_tenant_database_contract` fail with assertions like
`assert "TURINGDB_MEMORY_INDEX=..." in environment` — correctly, but if the planner isn't expecting
this, it looks like an unrelated regression rather than the direct, intended consequence of the
env-var deletion.
**Why it happens:** This test file asserts compose.yaml's *current* (TuringDB-inclusive) shape as
correct — it needs updating in the same commit as compose.yaml, not after.
**How to avoid:** Include `tests/test_compose_config.py` explicitly in the compose-rewrite task,
not as a follow-up "fix failing tests" task.
**Warning signs:** Any task that touches compose.yaml without a corresponding task/checklist item
for this test file.

## Runtime State Inventory

This phase's scope is a rename/removal, so the categories are addressed explicitly:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None** — fresh-start milestone (per STATE.md: "Fresh start — no TuringDB→ArcadeDB data migration"); the `turing-data` Docker volume being renamed to `bertoni-data` holds only the current dev/CI environment's already-ArcadeDB-era app state (SQLite job DB, tenant registry, staging, audit/observability JSONL) — nothing TuringDB-shaped lives in it. No data migration needed, only a volume-name/mount-path rename. | Code edit only (env var + compose volume name); confirmed no data migration task needed. |
| Live service config | **None found** — no external service (n8n-style) holds TuringDB config outside git; the only "live config" was the `turingdb`/`turingdb-volume-init` Compose services themselves, which are being deleted, not reconfigured. | None. |
| OS-registered state | **None found** — no Task Scheduler/pm2/launchd/systemd registrations reference "turingdb" or "turing" in this repo's tooling (Compose-only deployment model). | None. |
| Secrets/env vars | `TURINGDB_HOME`/`TURINGDB_GRAPH` are read (not secrets) and need renaming at their 4 live call sites (see App-State Rename Surface table); `TURINGDB_URL` and 5 `TURINGDB_*_INDEX` vars are dead, delete only from compose/.env.example. No secret material (API keys, passwords) has "turingdb" in its name. | Code edit (rename) for `TURINGDB_HOME`/`TURINGDB_GRAPH`; doc/compose sweep only for the 6 dead vars. |
| Build artifacts | `docker/turingdb.Dockerfile`-built image `turing-agentmemory-turingdb:local` is a local build artifact, not a registry-published one — deleting the Dockerfile + Compose service is sufficient; no registry cleanup needed. `.turingdb/` local scratch dir (gitignored, created only by the doomed `agent_quality_eval.py`) becomes dead once that file is deleted — sweep the `.gitignore` entry too. | Delete Dockerfile + compose service; remove now-dead `.gitignore` entry. |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.2+ (installed via `.[dev]`), `pytest-cov==7.1.0` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=tests`, `pythonpath=src`) |
| Quick run command | `python -m pytest tests/test_no_turingdb_imports.py tests/test_dependency_compat.py tests/test_warning_filters.py tests/test_compose_config.py -q` |
| Full suite command | `python -m pytest -m "not integration and not gpu" --cov=src/turing_agentmemory_mcp --cov-fail-under=78 -q` (matches `ci.yml`'s `unit-tests` job exactly) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ARC-10 (removal) | No `import turingdb`/`from turingdb` remains in `src/` | unit (grep-gate) | `pytest tests/test_no_turingdb_imports.py -x` | ❌ Wave 0 — new file, generalizing existing `store_core.py`-scoped pattern |
| ARC-10 (removal) | `turingdb`/`turingdb-volume-init` services absent, compose still valid | integration (compose) | `docker compose config --quiet` | ✅ existing command, re-verify after edit |
| ARC-10 (removal) | Compose env/volume assertions match the renamed reality | unit | `pytest tests/test_compose_config.py -x` | ✅ exists, needs rewrite (see Pitfall 4) |
| ARC-10 (invariants) | CLAUDE.md/`.claude/CLAUDE.md` invariant text updated | manual (docs review) | n/a — human/reviewer verification | n/a |
| ARC-10 (cut proof) | Full suite green post-removal | unit | `python -m pytest -m "not integration and not gpu" --cov=src/turing_agentmemory_mcp --cov-fail-under=78 -q` | ✅ existing CI command |
| ARC-10 (cut proof) | E2E score gate still green on ArcadeDB alone | integration | `python scripts/e2e_score.py --out e2e-results.json` (assert `score>=9.8 and check_count==19`) | ✅ existing script/command |
| ARC-10 (entry gate) | Phase-6 GO verdict enforced before proceeding | unit | `pytest tests/test_gate_artifact_schema.py tests/test_phase7_gate_guard.py -q` (already exist) + one explicit `assert_gate_go(...)` call in the phase's own execution | ✅ gate_guard.py + its tests exist; only the phase-precondition *invocation* is new |
| DEP-01 | `graspologic-native==1.3.1` pin verified + Leiden smoke | unit (no-skip-as-green tier by construction — no `pytest.skip` path) | `pytest tests/test_dependency_compat.py -k graspologic -x` | ❌ Wave 0 — new file |
| DEP-02 | `fastmcp` range verified + app-construction smoke | unit (same tier) | `pytest tests/test_warning_filters.py -x` (extended) | ✅ exists (32 LOC), needs extension not replacement |

### Sampling Rate
- **Per task commit:** the quick run command above (narrow, <5s).
- **Per wave merge:** the full suite command (matches CI exactly, ~1-2 min based on 882 collected tests).
- **Phase gate:** full suite green + `docker compose config --quiet` + E2E score gate green (D-04's explicit "Cut proof" contract) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_no_turingdb_imports.py` — new grep-gate test, generalizing the existing
  `store_core.py`-scoped pattern in `tests/_store_arcadedb_core_shared.py` to all of `src/` (ARC-10).
- [ ] `tests/test_dependency_compat.py` — new file for DEP-01 (graspologic-native version + Leiden
  smoke); DEP-02's version-range assertion + app-construction smoke can live here too, or as an
  extension of `tests/test_warning_filters.py` — planner's call, both are under 600 LOC either way.
- [ ] No new fixtures/conftest needed — `create_mcp_app(store=object())` (existing pattern from
  `tests/test_auth.py:48`) is sufficient for the DEP-02 smoke; no live ArcadeDB required.

*(Framework, `pythonpath`, and `testpaths` are already fully configured — no install/config gap.)*

## Security Domain

### Applicable ASVS Categories

This phase removes attack surface (an entire network-exposed daemon + its dependency) and adds a
narrow supply-chain-drift defense (DEP-01/DEP-02); it does not touch authentication, session
management, or input-validation surfaces.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Unaffected — `auth_from_env()`/bearer-token auth untouched by this phase |
| V3 Session Management | No | Unaffected |
| V4 Access Control | No | Unaffected — `user_identifier` tenant scoping untouched (invariant #1 reconfirmed, not modified) |
| V5 Input Validation | No | No new user-facing input surface added |
| V6 Cryptography | No | No crypto changes |
| V14 Configuration (closest applicable ASVS area) | Yes | Removing the `turingdb`/`turingdb-volume-init` services eliminates one exposed local port (`127.0.0.1:6666`) and one more container image's supply-chain surface (`docker/turingdb.Dockerfile`'s `pip install turingdb==1.35`) entirely — net attack-surface reduction. |

### Known Threat Patterns for this phase's actual change surface

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| A future `graspologic-native`/`fastmcp` version bump silently changes behavior (API removed, return-shape change, deprecation-turned-error) and ships without anyone noticing until a production failure | Tampering (of the dependency contract, not malicious) | DEP-01/DEP-02 compat-smoke tests, run on every CI push, fail loudly on a version bump that breaks the assumed API shape — this IS the standard mitigation this phase implements, not a gap to separately mitigate. |
| A leftover `TURINGDB_URL`/`.env.example` entry pointing at a decommissioned internal hostname (`http://turingdb:6666`) gets copy-pasted into a future deployment's config, causing a startup hang waiting on a DNS name that no longer resolves in the Compose network | Denial of Service (operational, low severity) | Complete removal from `.env.example`/`compose.yaml` (not just commenting out) — verified this phase deletes rather than comments these lines. |
| The 31-file test stub silently continues to mask a real `ModuleNotFoundError` if src-side imports aren't fully cleaned (Pitfall 1) | Tampering (test suite gives false confidence) | Sequencing discipline (src-side removal before stub removal) plus the new grep-gate test as an independent, non-stub-dependent oracle. |

## Sources

### Primary (HIGH confidence — verified live against this repository)
- `git grep`/`Grep` tool across the full tree — file-by-file disposition for every candidate in
  the Removal Surface Verification section.
- `Read` on `cli.py`, `admin_repair.py`, `e2e_score.py`, `e2e_score_stubs.py`, `store_core.py`
  (excerpts), `store_evidence.py`, `server.py`, `provider_config.py`, `document_job_manager.py`,
  `lab.py`, `frontend/app.js`, `frontend/index.html`, `gate_guard.py`, `tests/conftest.py`,
  `tests/test_compose_config.py`, `tests/test_no_skip_as_green_guard.py`,
  `tests/test_warning_filters.py`, `tests/_store_arcadedb_core_shared.py`, `pyproject.toml`.
- `git show HEAD:compose.yaml` / `git show HEAD:.env.example` (direct file reads were denied by
  this session's permission settings for `.env.example`; `git show` was used as the verified
  workaround and returned identical tracked content).
- Live Python probes in this repo's `.venv`: `pip show fastmcp graspologic-native`,
  `create_mcp_app(store=object())` + `asyncio.run(app.list_tools())` returning 26 tools,
  `pytest --collect-only -q` returning 882 collected tests.
- `baseline/06-gate/gate-result.json` — confirmed `verdict: "GO"` directly.

### Secondary (MEDIUM confidence)
- `.planning/phases/04-arcadedb-direct-port/04-CONTEXT.md`, `06-migration-correctness-gate/06-CONTEXT.md`,
  `.planning/STATE.md` Accumulated Context — cited for the Invariant Rewrite Substrate section;
  cross-checked against live code where the claim was checkable (e.g. MVCC 503 handling pattern
  visible in `store_core.py`'s transaction retry wrapper, SparseIndex read-path retirement
  confirmed via `store_evidence.py`).

### Tertiary (LOW confidence)
- None — every claim in this document was either directly verified against the live tree/running
  process, or is explicitly marked as a citation of a prior phase's committed CONTEXT.md/STATE.md
  decision (which is itself a project-internal source of record, not external/unverified).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The exact rename target for `TURINGDB_GRAPH` (e.g. `AGENTMEMORY_GRAPH` vs `ARCADEDB_GRAPH_NAME`) is left as Claude's Discretion per D-02's own carve-out — this research does not pick one. | App-State Rename Surface table | Low — any non-TuringDB name works functionally; only consistency across `compose.yaml`/`.env.example`/`server.py` matters, which the plan must enforce regardless of the exact chosen name. |
| A2 | Whether to delete `admin_repair.py`'s two orphaned functions (`repair_sparse_projection`, `repair_community_projection`) alongside the confirmed-dead `repair_vector_index`, or keep them as unwired-but-tested utility functions, is left as a planner/user decision — this research presents evidence for both readings but does not resolve it. | Removal Surface Verification — `admin_repair.py` split-verdict table | Low-Medium — if kept, `tests/test_admin_repair.py` shrinks by ~1/3 instead of being deleted wholesale; if deleted, a possibly-intentional (if currently unused) repair-tooling surface disappears. Either choice is defensible and reversible; flagging it prevents an unreviewed silent decision either way. |

**If this table is empty:** N/A — see above, two genuine discretion points identified.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; both version-gated packages' installed versions
  directly verified via `pip show` in this repo's own `.venv`.
- Architecture (removal surface, rename surface): HIGH — every disposition traced to a specific
  file:line via `git grep`/`Read`, not inferred from CONTEXT.md's hypothesis list alone; four
  corrections found and documented where live evidence diverged from the hypothesis.
- Pitfalls: HIGH — all four pitfalls are derived from concrete sequencing/scope traps found during
  this verification pass, not generic dependency-removal folklore.

**Research date:** 2026-07-16
**Valid until:** Until this phase executes (removal phases are point-in-time; the live tree will
have changed once Phase 7 lands, invalidating the specific line numbers cited here).
