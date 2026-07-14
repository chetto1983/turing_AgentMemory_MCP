# Technology Stack

**Analysis Date:** 2026-07-14

## Languages

**Primary:**
- Python 3.11+ - Server, storage, ingestion, retrieval, CLI, scripts, and tests in `src/turing_agentmemory_mcp/`, `scripts/`, and `tests/`; supported versions are declared in `pyproject.toml`.

**Secondary:**
- JavaScript, HTML, CSS - Browser-native AgentMemory Lab in `src/turing_agentmemory_mcp/frontend/`.
- Shell, Make, YAML - Automation and configuration in `scripts/`, `Makefile`, `compose.yaml`, `lefthook.yml`, and `.github/`.

## Runtime

**Environment:**
- CPython >=3.11; CI uses Python 3.12 in `.github/workflows/ci.yml`, while `Dockerfile` uses Python 3.14 slim.
- Docker Engine with Compose runs the reference topology in `compose.yaml`; NVIDIA GPU access is required for its local embedding/rerank sidecars (`docs/deployment.md`).

**Package Manager:**
- pip with Hatchling >=1.27 from `pyproject.toml`.
- Lockfile: missing; direct dependencies are constrained in `pyproject.toml`, and container bases are digest-pinned in `Dockerfile` and `docker/*.Dockerfile`.

## Frameworks

**Core:**
- FastMCP >=3.4,<4 - MCP serving, client proxy, auth, and tool registration in `src/turing_agentmemory_mcp/server.py`, `src/turing_agentmemory_mcp/server_memory_tools.py`, `src/turing_agentmemory_mcp/server_document_tools.py`, and `src/turing_agentmemory_mcp/file_pipe.py`.
- TuringDB 1.35 - retained daemon/benchmark/coexistence runtime in `pyproject.toml`, `docker/turingdb.Dockerfile`, and `src/turing_agentmemory_mcp/e2e_score_stubs.py`; new canonical store queries use ArcadeDB through `src/turing_agentmemory_mcp/arcadedb_client.py`.

**Testing:**
- pytest >=8.2 and pytest-cov 7.1.0 - test tiers under `tests/` and a 78% CI coverage floor in `.github/workflows/ci.yml`.

**Build/Dev:**
- Hatchling - Python build backend configured in `pyproject.toml`.
- Ruff 0.15.21 - formatting/import/lint checks configured in `pyproject.toml`, `lefthook.yml`, and `.github/workflows/ci.yml`.
- Lefthook 2.1.10 - parallel local Git gates in `lefthook.yml`.
- Docker BuildKit and GitHub Actions - images and CI in `Dockerfile`, `docker/`, and `.github/workflows/`.

## Key Dependencies

**Critical:**
- `fastmcp>=3.4,<4` - public MCP protocol boundary (`src/turing_agentmemory_mcp/server.py`).
- `markitdown[pdf,docx,pptx,xlsx]>=0.1.6,<0.2` and `pypdfium2>=4.30,<6` - document conversion (`src/turing_agentmemory_mcp/document_processing.py`).
- `graspologic-native==1.3.1` - Leiden community detection (`src/turing_agentmemory_mcp/community_detection.py`).
- `turingdb==1.35` - legacy/coexistence evaluation runtime; do not introduce new production queries through it (`src/turing_agentmemory_mcp/server.py`).

**Infrastructure:**
- ArcadeDB 26.7.1 - active graph/vector backend from `compose.yaml`, accessed by `src/turing_agentmemory_mcp/arcadedb_client.py`.
- Python SQLite/FTS5 - sparse projection and durable jobs in `src/turing_agentmemory_mcp/sparse_index.py` and `src/turing_agentmemory_mcp/document_jobs.py`.
- Optional `gliner`, `gliner2`, and `gliner2-onnx` extras - in-process extraction in `src/turing_agentmemory_mcp/entity_extraction.py`.
- `fast_gliner==0.2.1` and llama.cpp CUDA server - extraction, embedding, and rerank sidecars from `docker/gliner-provider.Dockerfile`, `docker/llama-provider.Dockerfile`, and `compose.yaml`.

## Configuration

**Environment:**
- Environment variables are documented in `docs/configuration.md` and read at boundaries including `src/turing_agentmemory_mcp/server.py`, `src/turing_agentmemory_mcp/provider_config.py`, and `src/turing_agentmemory_mcp/arcadedb_client.py`.
- `.env.example` exists as a template; Compose reads repository-root environment configuration through `compose.yaml`. Never commit or inspect `.env` contents.
- Use `ARCADEDB_*`, `EMBED_*`, `RERANK_*`, `GLINER_*`, and `AGENTMEMORY_*` families for database, providers, extraction, and application controls (`docs/configuration.md`).

**Build:**
- `pyproject.toml`, `Dockerfile`, `docker/*.Dockerfile`, `compose.yaml`, `Makefile`, and `lefthook.yml` define builds and developer gates.

## Platform Requirements

**Development:**
- Use Python >=3.11, pip, Git, Bash-compatible scripts, and `pip install -e ".[dev]"` (`README.md`).
- Use Docker Compose for live ArcadeDB integration; GPU hardware is optional for deterministic tests but required for the reference real embedding/rerank stack (`.github/workflows/ci.yml`, `docs/deployment.md`).
- Preserve Ruff's 100-column/Python 3.11 rules and run commands from `Makefile` and `lefthook.yml`.

**Production:**
- Reference target is single-node Compose with persistent database/data/model volumes in `compose.yaml`.
- Run the non-root image from `Dockerfile`; place TLS termination and tenant-binding authorization in a gateway because the application provides neither (`docs/deployment.md`).
- Keep ArcadeDB and provider endpoints private, persist queue/staging paths, and keep embedding dimensions consistent with every vector index (`docs/configuration.md`).

---

*Stack analysis: 2026-07-14*
