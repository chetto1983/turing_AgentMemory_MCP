# External Integrations

**Analysis Date:** 2026-07-16

## APIs & External Services

**Embedding (Dense Vector Generation):**
- Service: OpenAI-compatible HTTP embedding provider
  - Default: llama.cpp sidecar (granite-embedding-311m-multilingual-r2-GGUF, 768-dim)
  - Alternative: Any OpenAI-compatible API (e.g., OpenAI, Ollama, vLLM)
  - SDK/Client: `urllib.request` (thin HTTP wrapper in `src/turing_agentmemory_mcp/embeddings.py`)
  - Auth: Optional bearer token via `EMBED_API_KEY`, custom header `EMBED_API_KEY_HEADER`, custom scheme `EMBED_API_KEY_SCHEME`
  - Config env vars:
    - `EMBED_BASE_URL` (default: http://agentmemory-embed:8080)
    - `EMBED_MODEL` (default: mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M)
    - `EMBED_DIMENSIONS` (default: 768)
    - `EMBED_BATCH_SIZE` (default: 128)
    - `EMBED_REQUEST_DIMENSIONS` (optional, must match EMBED_DIMENSIONS if set)
    - `EMBED_TIMEOUT_SECONDS` (implicit, 60s default in `src/turing_agentmemory_mcp/embeddings.py:64`)

**Reranking (Cross-Encoder Relevance Scoring):**
- Service: OpenAI-compatible HTTP reranker
  - Default: llama.cpp sidecar (bge-reranker-v2-m3-Q8_0.gguf)
  - Alternative: Any OpenAI-compatible API
  - SDK/Client: `urllib.request` (thin HTTP wrapper in `src/turing_agentmemory_mcp/rerank.py`)
  - Auth: Optional bearer token via `RERANK_API_KEY`, custom header `RERANK_API_KEY_HEADER`, custom scheme `RERANK_API_KEY_SCHEME`
  - Config env vars:
    - `RERANK_BASE_URL` (default: http://agentmemory-rerank:8080)
    - `RERANK_MODEL` (default: bge-reranker-v2-m3-Q8_0.gguf)
    - `RERANK_CANDIDATE_LIMIT` (default: 50, seed pool size before reranking)
    - `RERANK_PROVIDER_MIN_SCORE` (default: 0, minimum acceptable score)
    - `RERANK_THRESHOLD` (optional, reject candidates below threshold)
    - `RERANK_BLEND` (default: 1, weight in final fusion)
    - `RERANK_PRESERVE_SEED_MARGIN` (optional, preserve margin between reranked and seed pool)
    - `RERANK_TIMEOUT_SECONDS` (optional)

**Entity Extraction (Named Entity Recognition & Linking):**
- Service: GLiNER v2 (entity extraction provider)
  - Default: Local HTTP sidecar with GLiNER2-base-v1-ONNX backend
  - SDK/Client: `urllib.request` (thin HTTP wrapper in `src/turing_agentmemory_mcp/gliner_provider_http.py`)
  - Auth: None (local Docker network in Compose stack)
  - Config env vars:
    - `GLINER_ENABLED` (default: 1, enable/disable feature)
    - `GLINER_BACKEND` (default: gliner2_http, options: gliner2_http, gliner2, gliner2_onnx, none)
    - `GLINER_BASE_URL` (default: http://agentmemory-gliner:8080)
    - `GLINER_MODEL` (default: lion-ai/gliner2-base-v1-onnx)
    - `GLINER_LABELS` (optional, comma-separated entity labels; defaults to `DEFAULT_GLINER_LABELS` in `src/turing_agentmemory_mcp/entity_extraction.py:14–34`)
    - `GLINER_THRESHOLD` (optional, entity confidence threshold)
    - `GLINER_REDACT` (optional, boolean; redact extracted entities before storage)
    - `GLINER_PRECISION` (optional, precision/recall trade-off)
    - `GLINER_TIMEOUT_SECONDS` (default: 900s, long timeout for large batches)

## Data Storage

**Graph + Vector + Full-Text Database:**

**ArcadeDB (Canonical):**
- Type: Multi-model database (graph + native vector HNSW + native Lucene full-text)
- Version: 26.7.1
- Connection: HTTP/JSON API via `urllib.request` (`src/turing_agentmemory_mcp/arcadedb_client.py`)
- Auth: HTTP Basic Auth (username/password)
  - `ARCADEDB_USER` (default: root)
  - `ARCADEDB_PASSWORD` (dev-only default: agentmemory-arcadedb-dev; **MUST be overridden for production**)
- Config:
  - `ARCADEDB_URL` (default: http://127.0.0.1:2480 for local dev; docker: http://arcadedb:2480)
  - `ARCADEDB_GRAPH` (default: agent_memory, graph name per tenant)
  - Vector indexes (LSM_VECTOR HNSW):
    - `ARCADEDB_MEMORY_INDEX` (default: agent_memory_episode_vectors_768)
    - `ARCADEDB_DOCUMENT_INDEX` (default: agent_memory_document_vectors_768)
    - `ARCADEDB_ENTITY_INDEX` (default: agent_memory_entity_vectors_768)
    - `ARCADEDB_FACT_INDEX` (default: agent_memory_fact_vectors_768)
    - `ARCADEDB_COMMUNITY_INDEX` (default: agent_memory_community_vectors_768)
- Per-tenant isolation: Each `user_identifier` gets a separate ArcadeDB database derived from a cryptographic hash (`src/turing_agentmemory_mcp/tenant_identity.py`)
- Data model:
  - `(:User)-[:HAS_MEMORY]->(:Memory)` - Conversational memory with temporal metadata
  - `(:User)-[:HAS_DOCUMENT]->(:Document)-[:HAS_CHUNK]->(:Chunk)` - Ingested documents chunked into retrievable units
  - `(:Memory)-[:MENTIONS_ENTITY]->(:Entity)`, `(:Entity)-[:FACT]->(:Fact)` - Entity-fact graphs for semantic retrieval
  - `(:Community)` - Leiden-clustered entity groups for graph-based contextualization

**Document Pipeline (Durable State):**

**Tenant Registry (SQLite):**
- Path: `${AGENTMEMORY_TENANT_REGISTRY_PATH}` (default: /bertoni/data/agent-memory-tenant-registry.sqlite3)
- Purpose: Pseudonymous tenant lifecycle state (ready/failed), tenant-to-database mapping, schema version
- Env vars:
  - `AGENTMEMORY_TENANT_REGISTRY_PATH`
  - `AGENTMEMORY_TENANT_NAMING_KEY` (HMAC-SHA256 secret for deriving database names; if not set, uses derived deterministic name)
  - `AGENTMEMORY_TENANT_CACHE_CAPACITY` (default: 128, LRU cache for tenant store instances)
  - `AGENTMEMORY_TENANT_CACHE_IDLE_TTL_SECONDS` (default: 900, evict unused tenants after 15min)

**Document Job Queue (SQLite):**
- Path: `${AGENTMEMORY_DOCUMENT_JOB_PATH}` (default: /bertoni/data/agent-memory-document-jobs.sqlite3)
- Purpose: Async document ingestion job queue with lease/heartbeat semantics
- Schema: `DocumentIngestJob` (job_id, user_identifier, document_id, filename, sha256, status, attempt_count, expires_at, created_at, updated_at)
- Env vars:
  - `AGENTMEMORY_DOCUMENT_JOB_PATH`
  - `AGENTMEMORY_DOCUMENT_JOB_LEASE_SECONDS` (default: 900, job lease duration)
  - `AGENTMEMORY_DOCUMENT_JOB_HEARTBEAT_SECONDS` (default: 15, worker heartbeat interval)
  - `AGENTMEMORY_DOCUMENT_JOB_POLL_SECONDS` (default: 1, job polling interval)
  - `AGENTMEMORY_DOCUMENT_JOB_MAX_ATTEMPTS` (default: 3, max retries on failure)

**Document Staging (Local Filesystem):**
- Path: `${AGENTMEMORY_DOCUMENT_STAGING_ROOT}` (default: /bertoni/data/document-ingest)
- Purpose: Temporary storage for uploaded documents during conversion
- Cleanup: Deleted after successful ingestion or after job expiration

**Sparse Index (SQLite FTS5):**
- Path: `${AGENTMEMORY_SPARSE_PATH}` (default: /bertoni/data/agent-memory-fts.sqlite3)
- Purpose: Full-text search fallback channel (not authoritative; ArcadeDB native Lucene is canonical)
- Feature gate: `AGENTMEMORY_FUSION_ENABLED` (default: 1; enables multi-signal retrieval)

## Authentication & Identity

**MCP Authentication (Optional Bearer Token):**
- Framework: FastMCP StaticTokenVerifier
- Env vars:
  - `AGENTMEMORY_AUTH_TOKEN` - Single token (simple, dev use)
  - `AGENTMEMORY_AUTH_TOKENS` - Space/comma-separated token list (production)
  - `AGENTMEMORY_AUTH_CLIENT_ID` (default: agentmemory-client)
  - `AGENTMEMORY_AUTH_SCOPES` - Optional scopes list
  - `AGENTMEMORY_AUTH_REQUIRED_SCOPES` - Scopes required for all requests
- Implementation: `src/turing_agentmemory_mcp/server.py:49–70` (`auth_from_env()`)

**Multi-Tenant User Scoping:**
- Mechanism: Every MCP tool call requires explicit `user_identifier` string
- Validation: `src/turing_agentmemory_mcp/tenant_identity.py` validates identifier format (no empty strings)
- Tenant Database Derivation: HMAC-SHA256(`AGENTMEMORY_TENANT_NAMING_KEY` or deterministic seed, `user_identifier`) → opaque database name
- Per-request scope enforcement: `user_identifier` predicate added to every ArcadeDB query (defense in depth; physical database separation is insufficient alone)
- Env var: `AGENTMEMORY_TENANT_NAMING_KEY` (optional; if missing, uses deterministic formula)

## Observability

**Audit Logging (Content-Free):**
- Format: Line-delimited JSON (JSONL)
- Output: File or off
- Env var: `AGENTMEMORY_AUDIT_JSONL` (file path or "off"; off by default)
- Purpose: Durable record of who accessed what, when (no sensitive content)

**Observability Spans (Timing & Context):**
- Format: Line-delimited JSON (JSONL) or stderr
- Env vars:
  - `AGENTMEMORY_OBSERVABILITY_JSONL` (file path)
  - `AGENTMEMORY_OBSERVABILITY_STDERR` (boolean, write to stderr)
- Purpose: Latency tracking, request tracing, component timing
- Implementation: `src/turing_agentmemory_mcp/observability.py`

## Retrieval & Ranking

**Multi-Signal Fusion (Retrieval Fusion):**
- Framework: Weighted reciprocal-rank fusion (RRF) over up to 6 channels
  - Dense vector similarity (ArcadeDB LSM_VECTOR HNSW)
  - BM25 lexical search (ArcadeDB native Lucene or SQLite FTS5 fallback)
  - Entity mention frequency (memory extraction)
  - Entity-fact graph traversal (semantic neighborhoods)
  - Community contextual boost
  - Reranker cross-encoder score (seed pool only)
- Feature gate: `AGENTMEMORY_FUSION_ENABLED` (default: 1)
- Weights: `AGENTMEMORY_FUSION_WEIGHTS` (optional, custom per-channel weights)
- Implementation: `src/turing_agentmemory_mcp/retrieval_fusion.py`

**Community Detection (Leiden Clustering):**
- Algorithm: Leiden hierarchical community detection (graspologic-native 1.3.1)
- Trigger: Batch write operations when `AGENTMEMORY_COMMUNITY_REBUILD_ON_BATCH=1`
- Config env vars:
  - `AGENTMEMORY_LEIDEN_SEED` (default: 42)
  - `AGENTMEMORY_LEIDEN_RESOLUTION` (default: 1.0)
  - `AGENTMEMORY_LEIDEN_RANDOMNESS` (default: 0.001)
  - `AGENTMEMORY_LEIDEN_ITERATIONS` (default: 2)
  - `AGENTMEMORY_LEIDEN_MAX_CLUSTER_SIZE` (default: 100)
- Purpose: Cluster entities for graph-based retrieval context
- Implementation: `src/turing_agentmemory_mcp/community_detection.py`

## Document Ingestion Pipeline

**File Upload & Async Processing:**
- Entry point: MCP tool `document_ingest_file`
- Flow:
  1. User stages file (local filesystem or file-pipe remote streaming)
  2. Upload manager stores file with SHA-256 checksum
  3. Job enqueued to SQLite document job queue (durable)
  4. Background worker thread processes: format detection → MarkItDown/PDFium conversion → chunking → ArcadeDB ingestion
  5. Job status polled via `document_ingest_status`
  6. Staged bytes removed on success
- Supported formats (via MarkItDown + PDFium):
  - Microsoft Office: DOCX, PPTX, XLSX
  - PDF (page-aware)
  - HTML, Markdown, JSON, YAML, XML
  - Plain text
- Conversion logic: `src/turing_agentmemory_mcp/document_processing.py`
- Manager logic: `src/turing_agentmemory_mcp/document_job_manager.py`
- Job storage: `src/turing_agentmemory_mcp/document_jobs.py`

**File Pipe (Remote File Streaming):**
- CLI command: `turing-agentmemory-mcp file-pipe`
- Purpose: Allow local `file-pipe` process to stream files from host to containerized MCP server (no host mount)
- Implementation: `src/turing_agentmemory_mcp/file_pipe.py`

## Governance & Retention

**Redaction (Pre-Persistence):**
- Scope: Entity extraction (optional)
- Feature: Can redact extracted entities before storing in ArcadeDB
- Env var: `GLINER_REDACT` (entity extraction redaction flag)
- Implementation: `src/turing_agentmemory_mcp/governance.py`

**Retention Filtering:**
- Mechanism: Memory/document records carry `expires_at` timestamp
- Enforcement: Filtered on retrieval (soft delete)
- Implementation: `src/turing_agentmemory_mcp/governance.py:retention_filter()`

## Deployment & Health

**MCP Server Health Endpoint:**
- Route: `GET /health` (HTTP)
- Response: JSON with status, ArcadeDB readiness, tenant router readiness, registry readiness
- Liveliness: Full ArcadeDB probe query on every request (no cached health state)
- Implementation: `src/turing_agentmemory_mcp/server.py` (custom `/health` route)

**Compose Stack Services:**
- `arcadedb` - ArcadeDB 26.7.1 (port 2480, health check via GET /api/v1/ready)
- `turing-agentmemory-mcp` - Main MCP server (port 8080, health check via `/health`)
- `agentmemory-embed` - llama.cpp embedding sidecar (port 8080, GPU-required)
- `agentmemory-rerank` - llama.cpp reranking sidecar (port 8080, GPU-required)
- `agentmemory-gliner` - GLiNER entity extraction sidecar (port 8080, CPU-capable)
- `agentmemory-model-init` - Model download helper (runs once)
- `agentmemory-lab` - Lab UI (port 8096)
- `e2e` (optional profile) - Deterministic E2E score test runner

---

*Integration audit: 2026-07-16*
