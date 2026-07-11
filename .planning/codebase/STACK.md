# Technology Stack

**Analysis Date:** 2026-07-11

## Languages

**Primary:**
- Python 3.11+ - All source code and CLI tools (pyproject.toml specifies 3.11–3.14)

## Runtime

**Environment:**
- Python 3.14 slim (Docker image for production: `python:3.14-slim`)
- Docker & Docker Compose for orchestration

**Package Manager:**
- pip (installed via hatchling build system)
- Lockfile: No explicit lock file; version pinning is in `pyproject.toml`

## Frameworks

**Core:**
- fastmcp 3.4–4 - Model Context Protocol server framework. Provides MCP tool definitions, transport layers (stdio, HTTP, SSE), and resource management (`src/turing_agentmemory_mcp/server.py`, `src/turing_agentmemory_mcp/file_pipe.py`)
- starlette - Web framework for HTTP response handling, used for JSON responses in MCP health endpoint

**Testing:**
- pytest 8.2+ - Test runner and framework (`pyproject.toml:tool.pytest.ini_options`)

**Build/Dev:**
- hatchling 1.27+ - Python build backend and package manager
- ruff 0.9+ - Linting and code formatting (enforces E, F, I, B, UP rules; line-length 100)

## Key Dependencies

**Critical:**
- turingdb 1.35 - Primary graph + vector database with local CSV vector storage (`src/turing_agentmemory_mcp/store.py`, `src/turing_agentmemory_mcp/server.py`)
- graspologic-native 1.3.1 - Leiden hierarchical community detection algorithm for graph clustering (`src/turing_agentmemory_mcp/community_detection.py:330`)

**Document Processing:**
- markitdown 0.1.6–0.2 (with pdf, docx, pptx, xlsx plugins) - Converts Microsoft Office, spreadsheets, HTML, and other formats to markdown (`src/turing_agentmemory_mcp/document_processing.py:15–18`)
- pypdfium2 4.30–5 - PDF text extraction with page-level awareness (`src/turing_agentmemory_mcp/document_processing.py:22–59`)

**Optional (dev and GLiNER extras):**
- gliner 0.2.27+ - Named entity recognition framework
- gliner2 1.3.2 - GLiNER v2 model suite
- gliner2-onnx - ONNX runtime support for GLiNER2

## Configuration

**Environment:**
- `.env.example` in repo root defines all runtime configuration
- Key env vars: `TURINGDB_URL`, `EMBED_BASE_URL`, `EMBED_DIMENSIONS`, `RERANK_BASE_URL`, authentication tokens, document job settings
- Docker Compose exposes templated env var injection via `${VAR_NAME:-default}` syntax (`compose.yaml`)

**Build:**
- `pyproject.toml` - Project metadata, dependencies, build configuration
- `Dockerfile` - Multi-stage build (installs dependencies, copies source, runs editable install)
- `docker/` - Specialized Dockerfiles for TuringDB, llama.cpp (embedding/reranking), and GLiNER services
- `compose.yaml` - Production-ready Docker Compose stack with 8 services and volume management

**Linting/Formatting:**
- `.ruff.lint` configured in `pyproject.toml` with E, F, I, B, UP rules; E501 (line too long) ignored
- No `.prettierrc` or `.eslintrc` (Python project)

## Platform Requirements

**Development:**
- Python 3.11 or higher
- Docker & Docker Compose (for local full-stack deployment)
- NVIDIA GPU + CUDA (for llama.cpp embedding/reranking sidecars)

**Production:**
- Python 3.11+ runtime
- Docker & Docker Compose (reference deployment model)
- NVIDIA GPU with CUDA (embedding and reranking services)
- Shared volume accessible by MCP container and TuringDB container at `/turing`
- Sufficient disk space for vector index CSV files and document staging

**Optional:**
- fast_gliner 0.2.1 - For GLiNER entity extraction provider (separate Python 3.12-slim container)

---

*Stack analysis: 2026-07-11*
