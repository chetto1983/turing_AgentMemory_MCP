# External Integrations

**Analysis Date:** 2026-07-11

## APIs & External Services

**Embedding Providers:**
- OpenAI-compatible HTTP API (local or remote)
  - Base URL: `EMBED_BASE_URL` (default: `http://agentmemory-embed:8080`)
  - Model: `EMBED_MODEL` (default: `mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M`)
  - Dimensions: `EMBED_DIMENSIONS` (default: 768)
  - Batch size: `EMBED_BATCH_SIZE` (default: 128)
  - Optional API key: `EMBED_API_KEY` with header `EMBED_API_KEY_HEADER` and scheme `EMBED_API_KEY_SCHEME`
  - Used in: `src/turing_agentmemory_mcp/embeddings.py` (OpenAICompatibleEmbedder)

**Reranking Providers:**
- OpenAI-compatible HTTP API (local or remote)
  - Base URL: `RERANK_BASE_URL` (default: `http://agentmemory-rerank:8080`)
  - Model: `RERANK_MODEL` (default: `Qwen3-Reranker-0.6B-q8_0.gguf`)
  - Candidate limit: `RERANK_CANDIDATE_LIMIT` (default: 50)
  - Min score threshold: `RERANK_PROVIDER_MIN_SCORE` (default: 0)
  - Blending factor: `RERANK_BLEND` (default: 1)
  - Optional API key: `RERANK_API_KEY` with header `RERANK_API_KEY_HEADER` and scheme `RERANK_API_KEY_SCHEME`
  - Used in: `src/turing_agentmemory_mcp/rerank.py` (OpenAICompatibleReranker)

**Entity Extraction (GLiNER):**
- GLiNER HTTP provider (optional)
  - Base URL: `GLINER_BASE_URL` (default: `http://agentmemory-gliner:8080`)
  - Model: `GLINER_MODEL` (default: `lion-ai/gliner2-base-v1-onnx`)
  - Enabled: `GLINER_ENABLED` (default: 1 when fusion enabled)
  - Timeout: `GLINER_TIMEOUT_SECONDS` (default: 900)
  - Labels and thresholds configurable via env
  - Used in: `src/turing_agentmemory_mcp/memory_extraction.py` (HTTPMemoryExtractor), `src/turing_agentmemory_mcp/gliner_provider.py`

**Fallback Cloud Providers:**
- Optional shared credentials for any OpenAI-compatible provider
  - `PROVIDER_API_KEY` - Cloud provider API key
  - `PROVIDER_API_KEY_HEADER` - Authentication header name
  - `PROVIDER_API_KEY_SCHEME` - Auth scheme (e.g., Bearer)

## Data Storage

**Primary Database:**
- TuringDB (1.35)
  - Connection: `TURINGDB_URL` (default: `http://turingdb:6666`)
  - Optional auth token: `TURINGDB_AUTH_TOKEN`
  - Graph: `TURINGDB_GRAPH` (default: `agent_memory`)
  - Home directory: `TURINGDB_HOME` (default: `/turing`, shared volume)
  - Python client: `turingdb` package
  - Accessed in: `src/turing_agentmemory_mcp/store.py` (TuringAgentMemory), `src/turing_agentmemory_mcp/server.py:156`
  - Vector indexes (configured dimensions, default 768):
    - `TURINGDB_MEMORY_INDEX` - Episode/memory vectors
    - `TURINGDB_DOCUMENT_INDEX` - Document chunk vectors
    - `TURINGDB_ENTITY_INDEX` - Entity vectors
    - `TURINGDB_FACT_INDEX` - Fact vectors
    - `TURINGDB_COMMUNITY_INDEX` - Community vectors

**Local SQLite Databases:**
- Sparse full-text search index
  - Path: `AGENTMEMORY_SPARSE_PATH` (default: `/turing/data/agent-memory-fts.sqlite3`)
  - Used in: `src/turing_agentmemory_mcp/sparse_index.py` (SparseIndex)

- Document job queue (async ingest)
  - Path: `AGENTMEMORY_DOCUMENT_JOB_PATH` (default: `/turing/data/agent-memory-document-jobs.sqlite3`)
  - Lease duration: `AGENTMEMORY_DOCUMENT_JOB_LEASE_SECONDS` (default: 900)
  - Heartbeat: `AGENTMEMORY_DOCUMENT_JOB_HEARTBEAT_SECONDS` (default: 15)
  - Poll interval: `AGENTMEMORY_DOCUMENT_JOB_POLL_SECONDS` (default: 1)
  - Max attempts: `AGENTMEMORY_DOCUMENT_JOB_MAX_ATTEMPTS` (default: 3)
  - Used in: `src/turing_agentmemory_mcp/document_job_manager.py`, `src/turing_agentmemory_mcp/document_jobs.py`

**File Storage:**
- Local filesystem only (no S3/cloud object store)
  - Document staging directory: `AGENTMEMORY_DOCUMENT_STAGING_ROOT` (default: `/turing/data/document-ingest`)
  - Max file size: `AGENTMEMORY_UPLOAD_MAX_FILE_BYTES` (default: 134217728 = 128 MB)
  - Chunk size: `AGENTMEMORY_UPLOAD_CHUNK_BYTES` (default: 524288 = 512 KB)
  - Used in: `src/turing_agentmemory_mcp/file_upload.py` (DocumentUploadStore)

**Caching:**
- None detected. Model caches are managed via Docker volumes in Compose stack

## Authentication & Identity

**Auth Provider:**
- Custom bearer token authentication (built into fastmcp)
  - Single token: `AGENTMEMORY_AUTH_TOKEN`
  - Multiple tokens: `AGENTMEMORY_AUTH_TOKENS` (comma/space-separated)
  - Optional client ID: `AGENTMEMORY_AUTH_CLIENT_ID` (default: `agentmemory-client`)
  - Optional scopes: `AGENTMEMORY_AUTH_SCOPES` (comma/space-separated)
  - Required scopes: `AGENTMEMORY_AUTH_REQUIRED_SCOPES` (gates tool access)
  - Implementation: `src/turing_agentmemory_mcp/server.py:35–56` (StaticTokenVerifier from fastmcp)

**User/Tenant Isolation:**
- User identifier (tenant) is explicit on all read/write operations
- No central identity provider; multi-tenancy via application-level `user_identifier` field
- Each memory, document, and entity record is scoped to a user

## Monitoring & Observability

**Error Tracking:**
- None detected (no Sentry, Datadog, etc.)
- HTTP health check endpoint at `GET /health` returns JSON status
- Used in Docker Compose healthchecks

**Logs:**
- Content-free audit JSONL
  - Path: `AGENTMEMORY_AUDIT_JSONL` (default: `/turing/audit/agentmemory.jsonl`)
  - Redaction enabled: `AGENTMEMORY_REDACTION_ENABLED` (default: 1)
  - Used in: `src/turing_agentmemory_mcp/observability.py`

- Observability spans in JSONL (request/response tracing)
  - Path: `AGENTMEMORY_OBSERVABILITY_JSONL` (default: `/turing/audit/spans.jsonl`)
  - Stderr output: `AGENTMEMORY_OBSERVABILITY_STDERR` (default: 0)
  - Used in: `src/turing_agentmemory_mcp/observability.py`

**Governance & Redaction:**
- Pattern-based redaction on persistence
- Redaction enabled via `AGENTMEMORY_REDACTION_ENABLED`
- Used in: `src/turing_agentmemory_mcp/governance.py`

## CI/CD & Deployment

**Hosting:**
- Docker Compose (reference deployment)
- Services: TuringDB, embedding (llama.cpp), reranking (llama.cpp), GLiNER, MCP server, lab frontend
- Each service has resource limits and healthchecks
- Shared Docker volumes for model caches and TuringDB data

**CI Pipeline:**
- None detected (no GitHub Actions workflows present)
- E2E scoring script available: `scripts/e2e_score.py` (manual invocation)
- Benchmark suite available: `src/turing_agentmemory_mcp/benchmark.py`

**Deployment Transport:**
- HTTP (localhost:8095 in Compose, configurable)
- SSE (Server-Sent Events)
- Stdio (for local MCP clients)

## Environment Configuration

**Required Env Vars:**
- `TURINGDB_URL` - TuringDB connection
- `TURINGDB_GRAPH` - Graph name
- `EMBED_BASE_URL` - Embedding service URL
- `EMBED_DIMENSIONS` - Embedding dimensionality
- `EMBED_BATCH_SIZE` - Batch size for embeddings
- `RERANK_BASE_URL` - Reranking service URL
- `RERANK_CANDIDATE_LIMIT` - Max results to rerank
- `GLINER_BASE_URL` - (if GLINER_ENABLED=1)

**Optional Env Vars:**
- All cloud provider credentials (fallback)
- Authentication tokens and scopes
- Governance redaction settings
- Document job queue parameters
- Leiden community detection parameters (seed, resolution, randomness, iterations)
- Fusion weights for retrieval blending (JSON)

**Secrets Location:**
- Environment variables only (`.env` file in Docker context)
- No `.env` file committed to repo (in `.gitignore`)
- Example configuration: `.env.example`

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- Optional file-pipe MCP proxy
  - `AGENTMEMORY_REMOTE_MCP_URL` - Remote MCP server URL for streaming files
  - `AGENTMEMORY_FILE_PIPE_ROOTS` - Local file system roots to expose
  - Used in: `src/turing_agentmemory_mcp/file_pipe.py`

## MCP API Surface

**Tool Categories:**
- Memory tools (store, retrieve, search, update, delete, add entities/preferences/facts)
- Document ingestion (upload, ingest, reindex, search, delete)
- System operations (health check, rebuild indexes, cancel jobs, repair indexes)

**Resource Types:**
- None detected (MCP tools only, no resources)

---

*Integration audit: 2026-07-11*
