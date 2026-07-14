# External Integrations

**Analysis Date:** 2026-07-14

## APIs & External Services

**Agent protocol:**
- FastMCP - memory/document tools and health boundary in `src/turing_agentmemory_mcp/server.py`, `src/turing_agentmemory_mcp/server_memory_tools.py`, and `src/turing_agentmemory_mcp/server_document_tools.py`.
  - SDK/Client: `fastmcp>=3.4,<4`; proxy/client use is in `src/turing_agentmemory_mcp/file_pipe.py`.
  - Auth: `AGENTMEMORY_AUTH_TOKEN(S)`, client ID, and scope variables consumed by `src/turing_agentmemory_mcp/server.py`.

**Graph and vector database:**
- ArcadeDB 26.7.1 - active canonical graph/vector store (`compose.yaml`, `src/turing_agentmemory_mcp/store_core.py`).
  - SDK/Client: custom stdlib HTTP/JSON `ArcadeDBClient` with retry and session transactions in `src/turing_agentmemory_mcp/arcadedb_client.py`.
  - Auth: `ARCADEDB_USER` and `ARCADEDB_PASSWORD`; endpoint/database use `ARCADEDB_URL` and `ARCADEDB_DATABASE`.
- TuringDB 1.35 - retained coexistence and legacy benchmark service, not the active production store connection (`docker/turingdb.Dockerfile`, `src/turing_agentmemory_mcp/server.py`).
  - SDK/Client: `turingdb==1.35` from `pyproject.toml`.
  - Auth: optional `TURINGDB_AUTH_TOKEN` documented in `docs/configuration.md`.

**AI providers:**
- OpenAI-compatible embeddings - `POST /v1/embeddings` via `OpenAICompatibleEmbedder` in `src/turing_agentmemory_mcp/embeddings.py`.
  - SDK/Client: stdlib `urllib`; local llama.cpp provider from `docker/llama-provider.Dockerfile` and `compose.yaml`.
  - Auth: `EMBED_API_KEY` or shared `PROVIDER_API_KEY`, with configurable header/scheme in `src/turing_agentmemory_mcp/provider_config.py`.
- OpenAI-compatible rerank - `POST /v1/rerank` via `OpenAICompatibleReranker` in `src/turing_agentmemory_mcp/rerank.py`.
  - SDK/Client: stdlib `urllib`; reference llama.cpp sidecar in `compose.yaml`.
  - Auth: `RERANK_API_KEY` or shared `PROVIDER_API_KEY` (`src/turing_agentmemory_mcp/provider_config.py`).
- GLiNER/GLiNER2 - entity/relation extraction in `src/turing_agentmemory_mcp/entity_extraction.py` and `src/turing_agentmemory_mcp/memory_extraction.py`.
  - SDK/Client: private HTTP sidecar or optional in-process packages from `pyproject.toml`.
  - Auth: none detected; endpoint is `GLINER_BASE_URL`.
- Hugging Face MemoryArena data - evaluation downloads from fixed URLs in `src/turing_agentmemory_mcp/memoryarena.py`.
  - SDK/Client: stdlib `urllib`.
  - Auth: none detected; `MEMORYARENA_JSONL` provides a local override.

## Data Storage

**Databases:**
- ArcadeDB - authoritative active graph/vector backend.
  - Connection: `ARCADEDB_URL`, `ARCADEDB_DATABASE`, `ARCADEDB_USER`, `ARCADEDB_PASSWORD`.
  - Client: `src/turing_agentmemory_mcp/arcadedb_client.py`; bootstrap: `src/turing_agentmemory_mcp/arcadedb_schema.py`.
- SQLite FTS5 - sparse lexical projection.
  - Connection: `AGENTMEMORY_SPARSE_PATH` defaulted in `src/turing_agentmemory_mcp/server.py`.
  - Client: Python `sqlite3` in `src/turing_agentmemory_mcp/sparse_index.py`.
- SQLite - durable asynchronous document queue.
  - Connection: `AGENTMEMORY_DOCUMENT_JOB_PATH` constructed in `src/turing_agentmemory_mcp/document_job_manager.py`.
  - Client: `src/turing_agentmemory_mcp/document_jobs.py` and `src/turing_agentmemory_mcp/document_jobs_schema.py`.

**File Storage:**
- Local/persistent filesystem only - staging/upload/file-pipe paths are implemented by `src/turing_agentmemory_mcp/document_job_manager.py`, `src/turing_agentmemory_mcp/file_upload.py`, and `src/turing_agentmemory_mcp/file_pipe.py`.
- Docker named volumes persist database and model data in `compose.yaml`; no cloud object-storage client is detected.

**Caching:**
- Docker model-cache volumes in `compose.yaml`; no Redis or Memcached integration is detected.

## Authentication & Identity

**Auth Provider:**
- Custom FastMCP static bearer tokens.
  - Implementation: `auth_from_env()` builds `StaticTokenVerifier` in `src/turing_agentmemory_mcp/server.py`; production gateways must bind principals to permitted `user_identifier` values (`docs/deployment.md`).
- ArcadeDB uses HTTP Basic auth in `src/turing_agentmemory_mcp/arcadedb_client.py`; AI providers accept bearer/custom API-key headers through `src/turing_agentmemory_mcp/provider_config.py`.

## Monitoring & Observability

**Error Tracking:**
- None detected in `pyproject.toml` or `src/turing_agentmemory_mcp/`.

**Logs:**
- Optional content-free audit JSONL via `AGENTMEMORY_AUDIT_JSONL` in `src/turing_agentmemory_mcp/governance.py`.
- Optional span JSONL/stderr via `AGENTMEMORY_OBSERVABILITY_JSONL` and `AGENTMEMORY_OBSERVABILITY_STDERR` in `src/turing_agentmemory_mcp/observability.py`.
- `/health` reports database, provider, fusion, and worker readiness in `src/turing_agentmemory_mcp/server.py`; service health checks live in `compose.yaml`.

## CI/CD & Deployment

**Hosting:**
- Single-host Docker Compose reference deployment using `Dockerfile`, `docker/*.Dockerfile`, and `compose.yaml`; no managed-cloud manifest is detected.

**CI Pipeline:**
- GitHub Actions runs Ruff, pytest/coverage, Compose validation, `pip-audit`, and live ArcadeDB E2E in `.github/workflows/ci.yml`.
- CodeQL scans Python in `.github/workflows/codeql.yml`; dependency updates and local gates use `.github/dependabot.yml` and `lefthook.yml`.

## Environment Configuration

**Required env vars:**
- Database: `ARCADEDB_URL`, `ARCADEDB_DATABASE`, `ARCADEDB_USER`, `ARCADEDB_PASSWORD` (`src/turing_agentmemory_mcp/arcadedb_client.py`).
- Embedding: `EMBED_BASE_URL`, `EMBED_MODEL`, `EMBED_DIMENSIONS`; credential fields are optional for local providers (`src/turing_agentmemory_mcp/embeddings.py`).
- Rerank: `RERANK_BASE_URL`, `RERANK_MODEL` when enabled (`src/turing_agentmemory_mcp/rerank.py`).
- Extraction/fusion: `GLINER_*` and `AGENTMEMORY_FUSION_ENABLED` (`src/turing_agentmemory_mcp/server.py`).
- Storage: `TURINGDB_HOME` plus queue/staging/sparse overrides where deployment defaults differ (`docs/configuration.md`).
- File proxy: `AGENTMEMORY_REMOTE_MCP_URL` and required `AGENTMEMORY_FILE_PIPE_ROOTS` (`src/turing_agentmemory_mcp/file_pipe.py`).

**Secrets location:**
- Local Compose configuration uses an uncommitted repository-root `.env` created from `.env.example`; never copy its contents (`docs/configuration.md`).
- CI/production credentials must be environment-injected; no Vault/KMS/managed secret-store SDK is detected in `pyproject.toml`.

## Webhooks & Callbacks

**Incoming:**
- FastMCP `/mcp/` plus custom `GET /health` from `src/turing_agentmemory_mcp/server.py`; GLiNER private extraction/health HTTP routes are served by `src/turing_agentmemory_mcp/gliner_provider_http.py`.
- No third-party webhook receiver is detected.

**Outgoing:**
- ArcadeDB `/api/v1/...` calls from `src/turing_agentmemory_mcp/arcadedb_client.py`.
- `/v1/embeddings`, `/v1/rerank`, and GLiNER extraction calls from `src/turing_agentmemory_mcp/embeddings.py`, `src/turing_agentmemory_mcp/rerank.py`, `src/turing_agentmemory_mcp/entity_extraction.py`, and `src/turing_agentmemory_mcp/memory_extraction.py`.
- Remote MCP proxy calls from `src/turing_agentmemory_mcp/file_pipe.py`; no event-driven outbound webhook delivery is detected.

---

*Integration audit: 2026-07-14*
