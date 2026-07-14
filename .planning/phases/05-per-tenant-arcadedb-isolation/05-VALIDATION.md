---
phase: 05
slug: per-tenant-arcadedb-isolation
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-14
updated: 2026-07-14
---

# Phase 05 — Validation Strategy

> Pre-execution validation contract for all 8 plans and 18 tasks. `pending` means the
> implementation has not run yet; Nyquist compliance here means every planned task has a
> concrete automated sampling gate and no unresolved `MISSING`/Wave-0 dependency.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` and `tests/conftest.py` |
| **Quick run command** | `python -m pytest -q tests/test_tenant_identity.py tests/test_tenant_registry.py tests/test_tenant_query_scope.py tests/test_tenant_router.py` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | Task-focused unit gates target <30 seconds; live ArcadeDB and full-suite commands are explicit wave/phase gates |

---

## Sampling Rate

- **After every task commit:** Run that task's exact `<automated>` command from the map below.
- **After Wave 1:** Run identity, registry, and complete query-scope tests.
- **After Wave 2:** Run provisioning, client-transport, and schema tests.
- **After Wave 3:** Run router and direct store-core tests.
- **After Wave 4:** Run server routing, runtime pipeline, and foreground tool tests.
- **After Wave 5:** Run document job, upload/file-pipe, manager, and MCP ingest tests.
- **After Wave 6 / before `$gsd-verify-work`:** Run the pinned live isolation module, then the full pytest, Ruff, Compose, file-size, and deterministic E2E gates from 05-08 Task 3.
- **Max feedback latency:** Focused unit sampling targets 30 seconds; intentionally live/full gates occur only at their declared execution boundary.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | Test Ownership | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|----------------|--------|
| 05-01-01 | 01 | 1 | ARC-07 | T-05-01-01/02/03 | RED proves exact opaque Unicode identity, HMAC naming, strict key loading, and no raw-identity retention | unit/TDD RED | `python -m pytest tests/test_tenant_identity.py -q 2>&1 \| rg "NotImplementedError"` | Task creates `tests/test_tenant_identity.py` before the gate | pending |
| 05-01-02 | 01 | 1 | ARC-07 | T-05-01-01/02/03/04 | GREEN accepts valid `Cf`/`Co`/`Cn`, rejects only locked invalid classes, and derives the full keyed name | unit/TDD GREEN | `python -m pytest tests/test_tenant_identity.py -q && python -m ruff check src/turing_agentmemory_mcp/tenant_identity.py tests/test_tenant_identity.py && bash scripts/check-file-size.sh` | Prior task owns test | pending |
| 05-02-01 | 02 | 1 | ARC-07 | T-05-02-01/02/03/04 | RED covers durable pseudonymous registry metadata, transitions, concurrency, corruption, and leakage | unit/TDD RED | `python -m pytest tests/test_tenant_registry.py -q 2>&1 \| rg "NotImplementedError"` | Task creates `tests/test_tenant_registry.py` before the gate | pending |
| 05-02-02 | 02 | 1 | ARC-07 | T-05-02-01/02/03/04 | GREEN proves fail-closed reopen and atomic provisioning-to-ready persistence | unit/TDD GREEN | `python -m pytest tests/test_tenant_registry.py -q && python -m ruff check src/turing_agentmemory_mcp/tenant_registry.py tests/test_tenant_registry.py && bash scripts/check-file-size.sh` | Prior task owns test | pending |
| 05-03-01 | 03 | 1 | ARC-07, TEST-05 | T-05-03-04 | RED must name unsafe endpoint/staging builders, not merely any failing assertion | static/unit TDD RED | `python -m pytest tests/test_tenant_query_scope.py -q 2>&1 \| rg "projection_edge_statements\|has_chunk_edge_statement\|next_chunk_edge_statement\|stage_vector_statement\|vector_version\|community_replace_sqlscript"` | Task creates `tests/test_tenant_query_scope.py` before the gate | pending |
| 05-03-02 | 03 | 1 | ARC-07, TEST-05 | T-05-03-01/02 | Memory/document/projection edge source and target subqueries bind the same tenant | unit/TDD GREEN | `python -m pytest tests/test_tenant_query_scope.py tests/test_store_arcadedb_memory.py tests/test_store_arcadedb_documents.py -q` | Prior task plus existing suites | pending |
| 05-03-03 | 03 | 1 | ARC-07, TEST-05 | T-05-03-01/03/04 | Rebuild/version/staging builders and future catalog entries retain explicit tenant scope | unit/TDD GREEN | `python -m pytest tests/test_tenant_query_scope.py tests/test_store_arcadedb_rebuild.py tests/test_store_arcadedb_retrieval.py -q && python -m ruff check src/turing_agentmemory_mcp/store_memory_queries.py src/turing_agentmemory_mcp/store_documents_queries.py src/turing_agentmemory_mcp/store_rebuild_queries.py src/turing_agentmemory_mcp/store_retrieval_queries.py tests/test_tenant_query_scope.py` | Prior task plus existing suites | pending |
| 05-04-01 | 04 | 2 | ARC-07 | T-05-04-01/02/03/04/05 | RED covers ready-last ordering, fault boundaries, distinct-clock contenders, retry classification, and missing-ready incidents | unit/TDD RED | `python -m pytest tests/test_tenant_provisioning.py -q 2>&1 \| rg "NotImplementedError"` | Task creates `tests/test_tenant_provisioning.py` before the gate | pending |
| 05-04-02 | 04 | 2 | ARC-07 | T-05-04-01/02/03/04/05 | GREEN reconciles create races and sources manifest `created_at` from the durable registry winner | unit/integration TDD GREEN | `python -m pytest tests/test_tenant_provisioning.py tests/test_arcadedb_client_transport.py tests/test_arcadedb_schema.py -q && python -m ruff check src/turing_agentmemory_mcp/tenant_provisioning.py src/turing_agentmemory_mcp/arcadedb_client.py src/turing_agentmemory_mcp/arcadedb_schema.py tests/test_tenant_provisioning.py && bash scripts/check-file-size.sh` | Prior task plus existing suites | pending |
| 05-05-01 | 05 | 3 | ARC-07 | T-05-05-02/03/04 | RED covers immutable views, per-key single flight, failure fan-out, bounded cache, and resolver validation ordering | unit/TDD RED | `python -m pytest tests/test_tenant_router.py -q 2>&1 \| rg "NotImplementedError"` | Task creates `tests/test_tenant_router.py` before the gate | pending |
| 05-05-02 | 05 | 3 | ARC-07 | T-05-05-01/02/03/04/05 | `_StoreCore`, `TenantRouter`, and `StaticStoreResolver` share central validation before any activity; tenant-local state stays isolated | unit/TDD GREEN | `python -m pytest tests/test_tenant_router.py tests/test_store_arcadedb_core.py -q && python -m ruff check src/turing_agentmemory_mcp/tenant_router.py src/turing_agentmemory_mcp/store_core.py tests/test_tenant_router.py tests/test_store_arcadedb_core.py && bash scripts/check-file-size.sh` | Prior task plus existing direct-store suite | pending |
| 05-06-01 | 06 | 4 | ARC-07 | T-05-06-03/04/05 | Production assembly fails closed on naming/config errors and global health never provisions a tenant | integration | `python -m pytest tests/test_tenant_server_routing.py tests/test_runtime_pipeline.py -q && docker compose config --quiet && python -m ruff check src/turing_agentmemory_mcp/server.py tests/test_tenant_server_routing.py tests/test_runtime_pipeline.py` | Task creates `tests/test_tenant_server_routing.py`; existing runtime suite | pending |
| 05-06-02 | 06 | 4 | ARC-07 | T-05-06-01/02/03 | Every foreground tenant-bearing tool resolves exactly once and preserves exact identity | integration | `python -m pytest tests/test_tenant_server_routing.py tests/test_server_batch_tool.py tests/test_document_ingest_file.py tests/test_document_file_pipe.py -q && python -m ruff check src/turing_agentmemory_mcp/server.py src/turing_agentmemory_mcp/server_memory_tools.py src/turing_agentmemory_mcp/server_document_tools.py tests/test_tenant_server_routing.py && bash scripts/check-file-size.sh` | Prior task plus existing tool suites | pending |
| 05-07-01 | 07 | 5 | ARC-07, TEST-05 | T-05-07-01/03/04 | Upload/job ownership validates once without transformation before filesystem or SQLite mutation | unit/integration | `python -m pytest tests/test_document_jobs.py tests/test_document_file_pipe.py -q && python -m ruff check src/turing_agentmemory_mcp/document_jobs.py src/turing_agentmemory_mcp/file_upload.py tests/test_document_jobs.py tests/test_document_file_pipe.py` | Existing suites extended by task | pending |
| 05-07-02 | 07 | 5 | ARC-07, TEST-05 | T-05-07-02/03/05 | Each claimed job resolves its own exact tenant store after the foreground resolver contract is stable | unit/integration | `python -m pytest tests/test_document_job_manager.py tests/test_document_ingest_file.py tests/test_document_jobs.py tests/test_document_file_pipe.py -q && python -m ruff check src/turing_agentmemory_mcp/document_job_manager.py tests/test_document_job_manager.py tests/test_document_ingest_file.py && bash scripts/check-file-size.sh` | Existing suites extended by task | pending |
| 05-08-01 | 08 | 6 | ARC-07, TEST-05 | T-05-08-01/02/04/06 | Live pinned ArcadeDB proves A/B/C physical plus predicate isolation, foreign-ID denial, and no identity leakage | live integration | `python -m pytest tests/test_arcadedb_physical_tenant_isolation.py -q -k "physical and not lifecycle_chaos"` | Task creates live module before the gate | pending |
| 05-08-02 | 08 | 6 | ARC-07, TEST-05 | T-05-08-03/04/05 | Live lifecycle gate covers first-use races, cache reuse, missing-ready failure, restart recovery, and real-file routing | live integration | `python -m pytest tests/test_arcadedb_physical_tenant_isolation.py -q` | Prior task owns live module | pending |
| 05-08-03 | 08 | 6 | ARC-07, TEST-05 | T-05-08-04 | Full repository/deployment/E2E gate confirms operational contracts without skip-as-green | full/quality/E2E | `python -m pytest -q && python -m ruff check src tests scripts && docker compose config --quiet && bash scripts/check-file-size.sh && python scripts/e2e_score.py --out e2e-results.json` | Existing gates plus prior live module | pending |

*Status: `pending` is intentional pre-execution state; no row claims implementation tests have passed.*

---

## Wave 0 Requirements

Existing pytest/Ruff/Compose/file-size/E2E infrastructure covers the phase. No plan contains
`<automated>MISSING</automated>`, so no separate Wave 0 scaffold is required. New focused test
modules are created inside their owning RED or implementation task before that task's automated
gate runs. Therefore `wave_0_complete: true` records complete planned test ownership, not completed
feature implementation.

---

## Manual-Only Verifications

All phase behaviors have automated verification. A local live test may explicitly skip only when
Docker/ArcadeDB is unavailable; under `CI=true`, the existing `tests/conftest.py` no-skip-as-green
policy turns that dependency absence or skip into a failure.

---

## Validation Sign-Off

- [x] All 18 tasks have an explicit `<automated>` verification command.
- [x] Sampling continuity: every task is sampled; no three-task window lacks automation.
- [x] Wave 0 completeness: zero `MISSING` references and every new test file has an owning task.
- [x] Dependency/wave sampling follows the approved six-wave graph, including 05-06 before 05-07.
- [x] No watch-mode flags.
- [x] Fast feedback is focused per task; live/full commands are isolated to declared phase gates.
- [x] `nyquist_compliant: true` reflects complete planned coverage; task statuses remain pending until execution.

**Approval:** approved 2026-07-14 for execution planning; implementation results pending.
