<!-- refreshed: 2026-07-11 -->
# Architecture

**Analysis Date:** 2026-07-11

## System Overview

The Turing AgentMemory MCP is a multi-layered memory and document retrieval system backed by TuringDB (graph + vector store). It exposes 25+ MCP tools organized around memory storage, retrieval, and document ingestion with temporal-spatial awareness and hybrid ranking.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                           MCP API Layer                                       │
│              `src/turing_agentmemory_mcp/server.py`                          │
│  Memory Tools (store/search/get/list/update/delete), Document Tools,         │
│  Entity/Preference/Fact Tools, Community Rebuild, Projection Rebuild         │
└──────────────────────────┬───────────────────────────────────────────────────┘
                           │
         ┌─────────────────┴──────────────────┬──────────────────┐
         │                                    │                  │
         ▼                                    ▼                  ▼
┌──────────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐
│  Memory Store Layer      │  │  Document Ingest     │  │  Configuration   │
│  `store.py`              │  │  Pipeline            │  │  `server.py`     │
│  TuringAgentMemory class │  │  `document_job_*`    │  │  env() functions │
│  - Memory CRUD           │  │  `document_proc*`    │  │  auth_from_env() │
│  - Search (fused)        │  │  `file_upload.py`    │  │  store_from_env()│
│  - Document CRUD         │  │                      │  │  Database setup  │
│  - Entity/Fact/Pref      │  │  Async Document      │  │  Provider config │
│  - Community ops         │  │  Queue + Worker      │  │                  │
└──────────────┬───────────┘  └──────┬───────────────┘  └──────────────────┘
               │                     │
         ┌─────┴─────────────────────┴────────────────────────────────┐
         │                                                            │
         ▼                                                            ▼
┌──────────────────────────────────────────────────┐  ┌─────────────────────┐
│        Retrieval & Ranking Layer                 │  │  Storage Backend    │
│  - Temporal Graph (`temporal_graph.py`)          │  │  TuringDB Client    │
│  - Entity Detection (`entity_extraction.py`)     │  │  `turingdb` package │
│  - Community Detection (`community_detect*.py`)  │  │                     │
│  - Hybrid Search (`hybrid.py`)                   │  │  - Graph nodes      │
│  - Retrieval Fusion (`retrieval_fusion.py`)      │  │  - Vector indexes   │
│  - Reranking (`rerank.py`)                       │  │  - Multi-index ops  │
│  - Sparse Index (`sparse_index.py` SQLite FTS5) │  │                     │
│  - Search Controls (`search_controls.py`)        │  │  Network: TURINGDB  │
└──────────────────────────────────────────────────┘  │  _URL, auth token   │
                                                      │  Home: /turing vol   │
         ┌─────────────────────────────────────┐     └─────────────────────┘
         │                                     │
         ▼                                     ▼
┌──────────────────────────────────────┐  ┌──────────────────────────┐
│    Integrations & Utilities          │  │   Observable & Audited   │
│  - Embeddings (`embeddings.py`)      │  │  - Observability (`obs.py`)
│    OpenAI-compatible provider        │  │    Span recording, runtime
│  - Memory Extraction (`memory_ext`)  │  │    signals, stage status
│    GLiNER HTTP provider              │  │  - Governance (`govern.py`)
│  - Entity Processor                  │  │    Redaction, audit JSONL
│  - ID Generation (`ids.py`)          │  │    `expires_at` retention
│  - Models & Types (`models.py`)      │  │  - CLI (`cli.py`)
│  - Configuration (`provider_config`) │  │    serve, e2e-score, lab
└──────────────────────────────────────┘  └──────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| **MCP Server** | Route 25+ memory/document/entity/fact/community tools to TuringAgentMemory store | `server.py` |
| **TuringAgentMemory** | Unified store orchestrating all memory/document operations, vector ops, graph edges, retrieval signals | `store.py` |
| **Retrieval Fusion** | Deterministic weighted reciprocal-rank fusion over dense vectors, BM25, entity, graph, community signals | `retrieval_fusion.py` |
| **Temporal Graph** | Entity-fact projections from memory extraction, temporal-spatial metadata normalization | `temporal_graph.py` |
| **Community Detection** | Leiden clustering over entity-fact graph using graspologic-native, incremental rebuild | `community_detection.py` |
| **Document Ingest Manager** | Async queue + worker thread for durably staged file conversion and graph ingestion | `document_job_manager.py` |
| **Document Processing** | File format detection, MarkItDown + PDFium conversion to markdown, chunking prep | `document_processing.py` |
| **Entity Extraction** | Pluggable entity detection (GLiNER HTTP provider default) for memory/document tagging | `entity_extraction.py` |
| **Memory Extraction** | GLiNER2-based fact/entity mention extraction from stored memories when fusion enabled | `memory_extraction.py` |
| **Embedder** | OpenAI-compatible embeddings provider, dimensional consistency checks | `embeddings.py` |
| **Reranker** | OpenAI-compatible cross-encoder reranking with threshold guards and margin preservation | `rerank.py` |
| **Sparse Index** | SQLite FTS5 full-text search fallback/channel for hybrid retrieval | `sparse_index.py` |
| **Hybrid Search** | Blends vector similarity (dense), lexical exact-token/phrase/path/error-code matching | `hybrid.py` |
| **ID Generation** | Stable, canonical, vector-ready ID generation from content and scope | `ids.py` |
| **Governance** | Redaction policies before persistence, audit event JSONL, retention filtering | `governance.py` |
| **Observability** | Span recording, runtime stage signals, performance instrumentation | `observability.py` |

## Pattern Overview

**Overall:** Service-oriented MCP + configurable store architecture

**Key Characteristics:**
- **Protocol-based pluggability:** Embedder, EntityProcessor, MemoryExtractor, SpanRecorder, Redactor, AuditSink, CommunityDetector interfaces allow swapping implementations without code change
- **Environment-driven configuration:** Factories (`*_from_env()`) build all integrations from env vars; zero hardcoded credentials
- **User-scoped data isolation:** Every operation requires explicit `user_identifier`; no implicit cross-tenant access
- **Async document pipeline:** Durable queue in `DocumentJobStore` (SQLite), worker thread with heartbeat/lease semantics
- **Multi-signal retrieval:** Memory and document search fuse up to 6+ ranking channels (dense vector, BM25, entity, graph, community) with weighted reciprocal-rank fusion
- **Temporal-spatial memory:** Facts and entities carry `valid_from`/`valid_to`, `observed_at`, speaker, session_id; graph supports time-scoped queries

## Layers

**MCP API Layer:**
- Purpose: Accept RPC calls from Claude/clients, route to store, serialize responses, span + govern each call
- Location: `src/turing_agentmemory_mcp/server.py`
- Contains: FastMCP app setup, 25+ decorated `@app.tool()` functions, auth middleware, custom routes (`/health`)
- Depends on: TuringAgentMemory store, DocumentUploadStore, DocumentIngestManager, provider config
- Used by: MCP clients (Claude, browser, CLI); external callers over HTTP/SSE/stdio

**Store Layer:**
- Purpose: Unified memory/document/entity operations with consistent vector indexing, graph edges, temporal projection
- Location: `src/turing_agentmemory_mcp/store.py`
- Contains: TuringAgentMemory class (250+ lines), graph traversal, chunking, multi-index operations
- Depends on: TuringDB client, Embedder, Reranker, EntityProcessor, MemoryExtractor, CommunityDetector, SparseIndex, observability
- Used by: MCP API layer, document ingest worker, admin repair tools

**Retrieval & Ranking Layer:**
- Purpose: Multi-signal ranking, temporal filtering, entity/fact graph traversal, community contextualization
- Location: `retrieval_fusion.py`, `temporal_graph.py`, `community_detection.py`, `hybrid.py`, `rerank.py`, `sparse_index.py`, `search_controls.py`
- Contains: Weighted RRF, entity mention projection, Leiden clustering, BM25 fallback, cross-encoder scoring
- Depends on: Models, ID utilities, search validation
- Used by: TuringAgentMemory for memory/document search, memory_get_context aggregation

**Document Ingest Pipeline:**
- Purpose: Async, durable, resumable file upload and conversion into chunked graph structure
- Location: `document_job_manager.py`, `document_jobs.py`, `document_processing.py`, `file_upload.py`
- Contains: DocumentIngestManager (worker + queue), DocumentJobStore (SQLite), ConvertedDocument, MarkItDown+PDFium drivers
- Depends on: TuringAgentMemory store (for graph injection), DocumentProcessing utilities
- Used by: MCP tools `document_upload_*`, `document_ingest_file`, CLI e2e/benchmark scenarios

**Configuration & Initialization Layer:**
- Purpose: Bootstrap store, document pipeline, auth, embeddings, observability from environment
- Location: `server.py` factory functions + `provider_config.py`
- Contains: `store_from_env()`, `auth_from_env()`, `document_upload_store_from_env()`, environment validators
- Depends on: dotenv (implied), TuringDB, external provider URLs
- Used by: CLI entry point, FastMCP app creation, test fixtures

**Integrations Layer:**
- Purpose: Pluggable backends for embeddings, entity extraction, governance, observability
- Location: `embeddings.py`, `entity_extraction.py`, `memory_extraction.py`, `governance.py`, `observability.py`, `gliner_provider.py`, `provider_config.py`
- Contains: Protocol definitions, HTTP client wrappers, SpanRecorder impl, Redactor impl
- Depends on: External HTTP services (EMBED_BASE_URL, RERANK_BASE_URL, GLINER_BASE_URL), optional local models
- Used by: TuringAgentMemory store for inference operations

## Data Flow

### Primary Memory Storage Path

1. Client calls `memory_store_message()` MCP tool with message, user_identifier, session_id (`server.py:265`)
2. MCP layer wraps in `_tool_span()` instrumentation, delegates to `memory.store_message()` (`store.py`)
3. Store generates stable memory ID, creates `:Memory` node with role, content, metadata, tags, expires_at
4. Store embeds content via embedder, writes vector to `memory_index` 
5. Store creates `(:User)-[:HAS_MEMORY]->(:Memory)` edge in TuringDB graph
6. If entity processor configured, entity extraction runs; entities become `:Entity` nodes with `[:MENTIONS]` edges to memory
7. If memory extractor configured (fusion enabled), fact/entity extraction creates `:Fact` nodes with temporal bounds
8. If community rebuild enabled, Leiden detector re-clusters entity-fact graph (async in store or batch)
9. Response serialized as MemoryItem with ID, timestamps, scope, metadata

### Primary Document Search Path

1. Client calls `document_search(query, user_identifier)` MCP tool (`server.py:728`)
2. MCP layer calls `memory.search_documents(query, user_identifier)` (`store.py`)
3. Store generates query embedding via embedder
4. Retrieval pipeline runs in parallel/sequential:
   - **Dense channel:** Vector similarity over `document_index` vectors (top K per user)
   - **BM25 channel:** SQLite FTS5 full-text search if sparse_index configured (lexical matching)
   - **Entity channel:** Hybrid exact-token/phrase matching over entity names and types
   - **Graph channel:** Transitive neighbor edges from chunk entity mentions (1-hop expansion)
   - **Community channel:** Top-K community summaries mentioning entities in query
5. If fusion enabled: Weighted RRF merges 5+ rankings into single scored list (default weights: dense=1.5, BM25=2.0, entity=0.5, graph=0.5, community=0.25)
6. If reranker configured: Top-N candidates re-ranked by cross-encoder, seed margin preserved
7. Results filtered by user_identifier scope, date ranges, tags, document_id filters
8. Response includes chunk text, document title, locator (page/section), context, score details

### Asynchronous Document Ingestion Path

1. Client calls `document_upload_begin()` to start chunked file upload (`server.py:527`)
2. Upload store creates temp staging entry, returns upload_id
3. Client calls `document_upload_chunk()` repeatedly with base64 chunks (sequence-ordered)
4. Upload store appends and checksum-validates each chunk
5. Client calls `document_upload_commit(upload_id)` to finalize (`server.py:573`)
   - Upload store verifies SHA256 matches expected, moves from temp to durable staging
   - DocumentIngestManager enqueues job to DocumentJobStore (SQLite)
   - Returns job_id and `"pending"` status
6. Worker thread polls jobs table, acquires lease, begins conversion:
   - File format detection by extension
   - PDFium for PDFs (page-aware text + page markers), MarkItDown for others
   - Text split into chunks (default 4KB chars, ~1K tokens)
   - Each chunk embeds, creates `:Chunk` node + `[:HAS_CHUNK]` edge to document
   - Chunks linked sequentially with `[:NEXT_CHUNK]` edges for context
7. Worker heartbeats lease on progress; if heartbeat fails, job released for retry by another worker
8. On success: job status = `"completed"`, chunk count recorded, file moved to archive
9. On failure (after 3 retries): job status = `"failed"`, stacktrace logged
10. Client can poll `document_ingest_status(job_id)` or wait for completion signal

### Community Rebuild (Fusion Enabled)

1. Triggered by `memory_store_messages(..., refresh_communities=True)` or explicit `memory_rebuild_communities()` call
2. Store queries all user's entities and facts (temporal constraints)
3. Constructs bipartite entity-fact graph: entities as nodes, facts as edges with weights
4. Passes to NativeLeidenDetector (graspologic).optimize_modularity() with seed
5. Returns detected communities; projects to `:Community` nodes with summary text
6. Updates retrieval weights to boost community-level results in subsequent searches

**State Management:**
- Ephemeral runtime state (search rankings, projected candidates) stored in process memory
- Durable memory/document/entity/fact stored in TuringDB graph + vector indexes
- Upload staging state (temp files, chunks) in `upload_store.staging_root` filesystem + upload job metadata in DocumentJobStore
- Async job state in `DocumentJobStore` SQLite table with worker heartbeat/lease tracking
- Observability (span records, runtime status) optional, buffered in process or streamed to external sink

## Key Abstractions

**MemoryItem:**
- Purpose: Scoped conversational memory with temporal metadata and lifecycle
- Examples: `store.py:63`, `models.py:63`
- Pattern: Immutable dataclass with user_identifier, session_id, role, content, tags, metadata, expires_at; serializes to JSON/dict

**DocumentHit:**
- Purpose: Search result chunk with citation metadata and context
- Examples: `store.py`, `models.py:87`
- Pattern: Immutable dataclass with chunk_id, document_id, locator (page/section), text, score, context array, metadata

**RetrievalCandidate:**
- Purpose: Ranked candidate from one retrieval channel (dense, BM25, entity, graph, community)
- Examples: `models.py:7`, `retrieval_fusion.py`
- Pattern: Immutable with candidate_id, kind, content, evidence sources, raw_score; transformed to FusedRetrievalCandidate by RRF

**TemporalProjection & EpisodeContext:**
- Purpose: Scope memory to user/session/timestamp/speaker; normalize temporal formats
- Examples: `temporal_graph.py:19`, `temporal_graph.py:75`
- Pattern: Frozen dataclass with post_init validation; used to build fact/entity projections

**Embedder, EntityProcessor, MemoryExtractor:**
- Purpose: Pluggable Protocol-based interfaces for inference backends
- Examples: `embeddings.py:27`, `entity_extraction.py:43`, `memory_extraction.py:143`
- Pattern: Each defines `__call__()` signature; implementations wrap HTTP or local inference; `*_from_env()` factories instantiate from config

## Entry Points

**HTTP/SSE/stdio MCP Server:**
- Location: `src/turing_agentmemory_mcp/cli.py:main()` -> `cli.py:52` (serve branch)
- Triggers: `turing-agentmemory-mcp serve [--transport stdio|http|sse] [--host] [--port]`
- Responsibilities: Boot FastMCP, load store + auth + integrations from env, listen for RPC, route to tools

**Batch/Lab Utilities:**
- `e2e-score`: End-to-end deterministic correctness test (10 scenarios, must score 10/10)
- `agent-quality-eval`: Real-world agent memory/document retrieval benchmark against Aura corpus
- `lab`: Lightweight web UI for manual exploration and debugging
- `utcp-manual`: Generate UTCP (Universal Tool Calling Protocol) schema JSON for CLI integration
- `file-pipe`: Stdio proxy that streams allowlisted local files to remote MCP server
- `repair-vector-index`: Quarantine corrupt TuringDB vector directories, recreate empty indexes

**Library Use:**
- `from turing_agentmemory_mcp.server import create_mcp_app` → FastMCP app for embedding in ASGI/FastAPI
- `from turing_agentmemory_mcp.store import TuringAgentMemory` → Direct store manipulation in tests or microservices

## Architectural Constraints

- **Threading:** Single-threaded event loop for MCP RPC (FastMCP/Starlette async). DocumentIngestManager spawns one optional background worker thread per manager instance. TuringDB client operations are blocking; no explicit async.
- **Global state:** TuringAgentMemory instance maintains TuringDB client connection (singleton per create_mcp_app). DocumentIngestManager holds DocumentJobStore SQLite handle. Embedder/Reranker/EntityProcessor may cache models in memory. User-scoped isolation enforced by data model, not process isolation.
- **Circular imports:** Import tree is acyclic; `server.py` imports from store, retrieval, document layers; no reverse imports from lower layers to server.
- **Vector dimensions:** Must be consistent across embedding provider (EMBED_DIMENSIONS env var), all TuringDB indexes (memory_index, document_index, entity_index, fact_index, community_index), and store initialization. Mismatch raises ValueError.
- **Tenant isolation:** No built-in tenant separation; `user_identifier` scope is application-level. Multi-tenant deployments must map authenticated principals to user_identifiers in calling layer.
- **Transaction semantics:** TuringDB operations are not transactional; bulk writes (e.g., document chunking) risk partial failure. No rollback on mid-batch failure; job retry re-applies entire batch.
- **Scale limits:** Linear search complexity over all user's memories/documents; no pagination/offset support (API enforces limit parameter). Leiden clustering is O(n^1.5) for entity count n; max_cluster_size caps at 100. SparseIndex (SQLite) is single-writer, no concurrent modifications.

## Anti-Patterns

### Implicit Tenant Scope

**What happens:** Code sometimes omits `user_identifier` check, assuming caller is trusted.
**Why it's wrong:** Without explicit scope validation, code can leak one user's memories to another if caller identity is forged.
**Do this instead:** All MCP tools enforce `user_identifier` parameter; store layer validates in get/search/update/delete operations. See `store.py` for example scope checks in `_ensure_user_scoped_vector_search()`.

### Unvalidated Reranker Scores

**What happens:** Rerank HTTP response scores are used directly without min/max bound checks.
**Why it's wrong:** Reranker may return NaN, infinity, or out-of-range scores; unguarded use causes ranking corruption.
**Do this instead:** `rerank.py` applies `apply_rerank_guard()` to clamp scores to [0, 1] and filter NaN/infinity. Store calls rerank only if configured; missing reranker defaults to fusion result.

### Unbounded Entity Extraction on Long Text

**What happens:** Entity processor called on full memory content without truncation.
**Why it's wrong:** GLiNER inference is O(seq_len^2); memory with 100K+ tokens causes timeout or OOM.
**Do this instead:** `memory_extraction.py` and entity processor calls are optional (controlled by `entity_processor` presence). Fusion mode can disable entity tagging with NoopEntityProcessor. Store truncates to reasonable length before extraction if needed.

## Error Handling

**Strategy:** Fail-open for optional features, fail-closed for core retrieval

**Patterns:**
- **Optional integrations:** Embedding defaults to OpenAICompatibleEmbedder; if provider unreachable, MCP request fails with clear error (not silent degradation)
- **Entity/Fact extraction:** If GLiNER provider fails, memory is stored without entity tagging; reranker/community features degrade gracefully
- **Sparse index (BM25):** If SQLite FTS5 unavailable, hybrid search skips BM25 channel; fusion still runs with remaining channels
- **Community rebuild:** Leiden clustering failure logs warning, skips update; subsequent queries use stale communities
- **Document conversion:** If MarkItDown/PDFium fail, job status = "failed", user can retry or inspect logs
- **Vector index mismatch:** Dimension validation at store init time; ValueError raised immediately (fail-fast)

## Cross-Cutting Concerns

**Logging:** Uses Python stdlib `logging` (or silent if not configured). Key events: tool entry/exit, errors, performance milestones (store time, vector ops time). Observability module allows pluggable span recorder for distributed tracing (see `observability.py:SpanRecorder`).

**Validation:** Search controls enforce query/weights/threshold format/bounds. ID generation validates content non-empty, scope non-empty. Temporal normalization validates ISO 8601 timestamps, handles `Z` and `+HH:MM` offsets. Graph edges validated for schema (e.g., `:User` and `:Memory` must exist before `[:HAS_MEMORY]`).

**Authentication:** Optional bearer-token auth at MCP level (fastmcp StaticTokenVerifier). No auth for store layer; assumes MCP layer or calling code enforces identity → user_identifier binding.

**Redaction:** Optional Redactor interface applied before embedding and graph writes; patterns (e.g., `api-key: \S+`) scrubbed from content. Audit sink records content-free events (operation type, user_identifier, timestamp, status) for compliance.

---

*Architecture analysis: 2026-07-11*
