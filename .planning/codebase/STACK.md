# Technology Stack

**Analysis Date:** 2026-07-16

## Languages

**Primary:**
- Python 3.11–3.14 - All source code, CLI tools, and test suites (pyproject.toml specifies support for Python 3.11, 3.12, 3.13, 3.14)

## Runtime

**Environment:**
- Python 3.14 slim (Docker image for standardized deployment: `python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1`)
- Docker & Docker Compose for containerized stack orchestration

**Package Manager:**
- pip (installed via hatchling build system)
- Lockfile: Not used — version pinning is declared in `pyproject.toml` (build-backend: hatchling>=1.27)

## Frameworks

**Core:**
- fastmcp 3.4–4 - Model Context Protocol (MCP) server framework. Provides tool definitions, transport layers (stdio/HTTP/SSE), and resource management (`src/turing_agentmemory_mcp/server.py`)
- starlette - Web framework for HTTP response handling (JSON serialization for `/health` and custom routes in MCP server)

**Testing:**
- pytest 8.2+ - Test runner and framework (config in `pyproject.toml:tool.pytest.ini_options`, testpaths=tests, pythonpath=src)
- pytest-cov 7.1.0 - Coverage reporting (dev extra)

**Build/Dev:**
- hatchling 1.27+ - Python build backend and package manager (build-system)
- ruff 0.15.21 - Unified linting and code formatting (enforces E, F, I, B, UP rules; line-length 100; E501 ignored)
- lefthook 2.1.10 - Git hook framework for pre-commit/pre-push validation (dev extra)

## Key Dependencies

**Critical (Core Functionality):**
- ArcadeDB 26.7.1 - Sole canonical graph + native vector (`LSM_VECTOR`/HNSW) + native Lucene full-text database. Accessed via thin stdlib `urllib` HTTP/JSON client (`src/turing_agentmemory_mcp/arcadedb_client.py`). Stores graph, vector indexes, and full-text indexes for all tenant data with ACID guarantees. Per-tenant physical separation at the database level.

**Infrastructure & Processing:**
- graspologic-native 1.3.1 - Leiden hierarchical community detection algorithm for entity-fact graph clustering (`src/turing_agentmemory_mcp/community_detection.py`)
- markitdown 0.1.6–0.2 (with pdf, docx, pptx, xlsx extras) - Universal document format converter (Microsoft Office, PDF, HTML, markdown, etc. to markdown) (`src/turing_agentmemory_mcp/document_processing.py`)
- pypdfium2 4.30–5 - PDF text extraction with page-level awareness (`src/turing_agentmemory_mcp/document_processing.py`)

**Optional (Entity Extraction, dev extra: `gliner`):**
- gliner 0.2.27+ - Named entity recognition framework (base library)
- gliner2 1.3.2 - GLiNER v2 model suite with typed entity support
- gliner2-onnx - ONNX runtime acceleration for GLiNER2

## Configuration

**Environment:**
- `.env.example` defines all runtime configuration (in repo root; sensitive defaults marked for production override)
- Key config sources:
  - `ARCADEDB_URL`, `ARCADEDB_USER`, `ARCADEDB_PASSWORD` - ArcadeDB connection
  - `EMBED_BASE_URL`, `EMBED_DIMENSIONS`, `EMBED_MODEL` - Embedding provider
  - `RERANK_BASE_URL`, `RERANK_MODEL` - Reranking provider
  - `GLINER_ENABLED`, `GLINER_BASE_URL`, `GLINER_MODEL` - Entity extraction
  - `BERTONI_HOME` - Application state directory (default /bertoni)
  - `AGENTMEMORY_*` - MCP server behavior (fusion, tenant routing, auth, observability)

**Build:**
- `pyproject.toml` - Project metadata, dependencies, version, entry points, pytest config, ruff config
- `Dockerfile` - Multi-stage Python 3.14 image with editable install, read-only layer for production
- `docker/llama-provider.Dockerfile` - llama.cpp-based embedding/reranking sidecar (CUDA GPU-required)
- `docker/gliner-provider.Dockerfile` - GLiNER2 HTTP entity extraction provider sidecar (CPU-capable)
- `compose.yaml` - Complete 8+ service stack (ArcadeDB, embedding, reranking, GLiNER, MCP server, Lab UI, E2E test runner)

**Formatting & Linting:**
- `.ruff.lint` configured in `pyproject.toml`:
  - select: E (pycodestyle), F (pyflakes), I (isort), B (flake8-bugbear), UP (pyupgrade)
  - ignore: E501 (line too long)
  - target-version: py311
  - line-length: 100 characters
- Pre-push hook validation (lefthook) runs:
  1. `python -m ruff format --check src tests scripts` (formatting check)
  2. `python -m ruff check src tests scripts` (linting)
  3. `bash scripts/check-file-size.sh` (600 LOC per-file cap)

## Platform Requirements

**Development:**
- Python 3.11 or higher
- Docker & Docker Compose
- NVIDIA GPU + CUDA (for local embedding/reranking sidecars; CPU-only fallback available but with degraded performance)
- Disk space for model caches (HuggingFace models ~500MB each for embedding/reranking)

**Production:**
- Python 3.11+ runtime (or Docker Compose stack as reference deployment)
- Docker & Docker Compose (reference architecture)
- NVIDIA GPU with CUDA + Docker GPU support (`nvidia-docker` or native Docker GPU support)
- Persistent volumes for:
  - ArcadeDB databases (`arcadedb-data`)
  - Application state: tenant registry, job queue, document staging, audit JSONL (`bertoni-data`)
  - Model cache for HuggingFace models (`agentmemory-llama-cache`, `agentmemory-gliner-cache`)

---

*Stack analysis: 2026-07-16*
