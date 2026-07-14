# Codebase Structure

**Analysis Date:** 2026-07-14

## Directory Layout

```text
turing_AgentMemory_MCP/
|-- .github/                    # CI/repository automation
|-- .planning/                  # GSD state, phases, and codebase maps
|-- baseline/                   # Frozen benchmark evidence
|-- docker/                     # Sidecar image definitions
|-- docs/                       # User/operator docs and dated designs
|-- scripts/                    # Benchmarks, evaluations, checks, spikes
|-- skills/turing-agentmemory/  # Distributable agent integration skill
|-- src/turing_agentmemory_mcp/ # Installable Python package
|   `-- frontend/               # Static Lab UI
|-- tests/                      # Primary pytest suite/helpers
|-- pyproject.toml              # Package and tool configuration
|-- compose.yaml                # Local service topology
|-- Dockerfile                  # Main MCP image
`-- Makefile                    # Development command aliases
```

## Directory Purposes

**`src/turing_agentmemory_mcp/`:**
- Purpose: Production MCP delivery, memory/document domain logic, retrieval, providers, persistence, operations, and evaluation support.
- Contains: Flat concern modules and `src/turing_agentmemory_mcp/frontend/` assets.
- Key files: `src/turing_agentmemory_mcp/cli.py`, `src/turing_agentmemory_mcp/server.py`, `src/turing_agentmemory_mcp/store.py`, `src/turing_agentmemory_mcp/arcadedb_client.py`

**`tests/`:**
- Purpose: Unit, integration, regression, architecture, deployment, benchmark, and provider tests.
- Contains: `test_*.py` modules and underscore-prefixed shared fakes/helpers.
- Key files: `tests/conftest.py`, `tests/test_auth.py`, `tests/test_store_arcadedb_core.py`, `tests/test_document_job_manager.py`

**`docs/`:**
- Purpose: Operator/integrator documentation and dated design records.
- Contains: Core docs, `docs/publication/`, and `docs/superpowers/` specifications/plans.
- Key files: `docs/mcp-api.md`, `docs/configuration.md`, `docs/deployment.md`, `docs/operations.md`, `docs/security.md`

**`scripts/`:**
- Purpose: Quality gates, benchmarks, evaluations, and isolated experiments.
- Contains: Python/shell entry points and `scripts/spike/` prototypes.
- Key files: `scripts/benchmark.py`, `scripts/agent_quality_eval.py`, `scripts/e2e_score.py`, `scripts/run-fast-tests.sh`

**`skills/turing-agentmemory/`:**
- Purpose: Package the agent usage contract independently of implementation.
- Contains: Skill, references, evaluation cases, license, and readme.
- Key files: `skills/turing-agentmemory/SKILL.md`, `skills/turing-agentmemory/references/mcp-tools.md`, `skills/turing-agentmemory/references/architecture.md`

**`baseline/`:**
- Purpose: Preserve benchmark corpora, questions, manifests, results, and notes.
- Contains: Named/versioned backend baselines.
- Key files: `baseline/03-turingdb/BASELINE.md`, `baseline/04-arcadedb/NOTES.md`

## Key File Locations

**Entry Points:**
- `src/turing_agentmemory_mcp/cli.py`: Installed console dispatcher.
- `src/turing_agentmemory_mcp/server.py`: FastMCP/dependency factory.
- `src/turing_agentmemory_mcp/file_pipe.py`: Allowlisted host-file proxy.
- `src/turing_agentmemory_mcp/lab.py`: Local Lab server.
- `scripts/`: Evaluation and benchmark programs.

**Configuration:**
- `pyproject.toml`: Packaging, dependencies, pytest, coverage, Ruff, and console script.
- `compose.yaml`: Runtime service graph; treat deployment configuration as potentially sensitive.
- `.env.example`: Safe variable-name/example documentation; never read actual `.env*` files.
- `Dockerfile`, `docker/`: Main and sidecar images.
- `lefthook.yml`, `Makefile`: Hooks and named workflows.

**Core Logic:**
- `src/turing_agentmemory_mcp/store.py`: Stable store facade.
- `src/turing_agentmemory_mcp/store_core.py`: Construction/bootstrap/shared primitives.
- `src/turing_agentmemory_mcp/store_memory_write.py`, `src/turing_agentmemory_mcp/store_memory_read.py`: Memory lifecycle.
- `src/turing_agentmemory_mcp/store_documents.py`: Document lifecycle/search.
- `src/turing_agentmemory_mcp/store_search.py`, `src/turing_agentmemory_mcp/store_evidence.py`: Retrieval pipeline.
- `src/turing_agentmemory_mcp/arcadedb_client.py`: Database adapter.
- `src/turing_agentmemory_mcp/document_job_manager.py`: Async ingestion.

**Query/Schema:**
- `src/turing_agentmemory_mcp/arcadedb_schema.py`: Schema/index bootstrap.
- `src/turing_agentmemory_mcp/store_memory_queries.py`: Memory statements.
- `src/turing_agentmemory_mcp/store_documents_queries.py`: Document statements.
- `src/turing_agentmemory_mcp/store_retrieval_queries.py`: Dense/Lucene statements.
- `src/turing_agentmemory_mcp/store_rebuild_queries.py`: Projection rebuild statements.

**Testing:**
- `tests/conftest.py`: Shared pytest setup.
- `tests/test_store_arcadedb_*.py`: Store tests by concern.
- `tests/test_arcadedb_*.py`: Client/schema/integration tests.
- `tests/test_document_*.py`: Upload/processing/job/ingest tests.
- `tests/_*_shared.py`, `tests/_*_fake.py`: Non-collected reusable support.

## Naming Conventions

**Files:**
- Use lowercase snake case: `src/turing_agentmemory_mcp/retrieval_fusion.py`.
- Prefix store concerns with `store_`: `src/turing_agentmemory_mcp/store_memory_write.py`.
- Name query companions `<concern>_queries.py`: `src/turing_agentmemory_mcp/store_documents_queries.py`.
- Name tests `test_<behavior>.py`: `tests/test_batch_memory_dedup.py`.
- Prefix shared test support `_`: `tests/_retrieval_arcadedb_shared.py`.
- Use dated kebab-case design records: `docs/superpowers/specs/2026-07-11-gpu-search-throughput-design.md`.

**Directories:**
- Use lowercase functional names: `src/`, `tests/`, `scripts/`, `docs/`.
- Use numbered backend labels for baselines: `baseline/03-turingdb/`, `baseline/04-arcadedb/`.
- Keep installable Python under `src/turing_agentmemory_mcp/`.

## Where to Add New Code

**New Memory Feature:**
- Primary code: Narrowest matching `src/turing_agentmemory_mcp/store_memory_*.py`, `src/turing_agentmemory_mcp/store_search.py`, or `src/turing_agentmemory_mcp/store_evidence.py`.
- Tool: `src/turing_agentmemory_mcp/server_memory_tools.py`.
- Queries: `src/turing_agentmemory_mcp/store_memory_queries.py` or `src/turing_agentmemory_mcp/store_retrieval_queries.py`.
- Tests: `tests/test_<feature>.py` or matching `tests/test_store_arcadedb_<concern>.py`.

**New Document Feature:**
- Primary code: `src/turing_agentmemory_mcp/store_documents.py` or `src/turing_agentmemory_mcp/store_chunking.py`.
- Async workflow: `src/turing_agentmemory_mcp/document_job_manager.py`, `src/turing_agentmemory_mcp/document_jobs.py`, or `src/turing_agentmemory_mcp/document_processing.py`.
- Tool/tests: `src/turing_agentmemory_mcp/server_document_tools.py`, then the matching `tests/test_document_*.py`.

**New Provider/Integration:**
- Implementation: Focused peer of `src/turing_agentmemory_mcp/embeddings.py`, `src/turing_agentmemory_mcp/rerank.py`, or `src/turing_agentmemory_mcp/memory_extraction.py`.
- Wiring: `src/turing_agentmemory_mcp/store_core.py` or `src/turing_agentmemory_mcp/server.py`.
- Tests: `tests/test_<provider>.py`.

**New Database Operation:**
- Transport: `src/turing_agentmemory_mcp/arcadedb_client.py`.
- Schema: `src/turing_agentmemory_mcp/arcadedb_schema.py`.
- Query: Matching `src/turing_agentmemory_mcp/store_*_queries.py`.
- Domain use: Matching store mixin; keep `src/turing_agentmemory_mcp/store.py` thin.

**Utilities:**
- Shared store helpers: `src/turing_agentmemory_mcp/store_utils.py` only when genuinely cross-mixin.
- Shared typed values: `src/turing_agentmemory_mcp/models.py`.
- Evaluation-only helpers: `src/turing_agentmemory_mcp/e2e_score_*.py`, `src/turing_agentmemory_mcp/benchmark_*.py`, or `scripts/`.

## Special Directories

**`.planning/`:**
- Purpose: GSD state, requirements, phase artifacts, and maps.
- Generated: Partially.
- Committed: Yes, subject to repository policy.

**`src/turing_agentmemory_mcp/frontend/`:**
- Purpose: Static assets served by `src/turing_agentmemory_mcp/lab.py`.
- Generated: No.
- Committed: Yes.

**`baseline/`:**
- Purpose: Curated frozen comparison evidence.
- Generated: Source results may be generated; selected baselines are curated.
- Committed: Yes.

**`.benchmarks/`, `.pytest_cache/`, `.ruff_cache/`, `.test-tmp-master-merge/`:**
- Purpose: Local outputs, caches, and temporary test state.
- Generated: Yes.
- Committed: No.

**`.worktrees/`:**
- Purpose: Local isolated Git worktrees.
- Generated: Yes.
- Committed: No.

---

*Structure analysis: 2026-07-14*
