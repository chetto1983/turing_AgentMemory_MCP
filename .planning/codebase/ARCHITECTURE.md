<!-- refreshed: 2026-07-16 -->
# Architecture

**Analysis Date:** 2026-07-16

## System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                     FastMCP Server Layer                     │
│         `src/turing_agentmemory_mcp/server.py`               │
│  (MCP tool definitions, auth, tenant resolution)             │
├──────────────────┬──────────────────┬───────────────────────┤
│ Memory Tools     │  Document Tools  │  Tenant Router        │
│ `server_memory   │  `server_doc     │  `tenant_router.py`   │
│  _tools.py`      │  _tools.py`      │  (25+ MCP tools)      │
└────────┬─────────┴────────┬─────────┴──────────┬────────────┘
         │                  │                     │
         ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│              Tenant Provisioning Layer                       │
│  `tenant_identity.py` / `tenant_registry.py`                 │
│  `tenant_provisioning.py` / `tenant_router.py`               │
│                                                               │
│  - Opaque tenant identity derivation (HMAC-SHA256)           │
│  - Single-flight provisioning with retry logic               │
│  - LRU view cache with idle TTL eviction                     │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                   Store Facade & Mixins                      │
│      `store.py` (TuringAgentMemory thin facade)              │
│  Composed from 8 mixin modules (each ≤600 LOC)               │
│                                                               │
│  - `store_core.py` — init, ArcadeDB primitives, span/audit   │
│  - `store_memory_write.py` — store/batch-store/add-* writes  │
│  - `store_memory_read.py` — get/search-memory operations     │
│  - `store_documents.py` — document/chunk write/read          │
│  - `store_evidence.py` — entity/fact/edge operations         │
│  - `store_chunking.py` — text chunking and prep              │
│  - `store_rebuild.py` — community/index rebuild              │
│  - `store_utils.py` — bootstrap, helpers, lifecycle          │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│              Retrieval & Ranking Stack                       │
│  Multi-signal fusion with graceful degradation               │
│                                                               │
│  - `hybrid.py` — Lexical + vector similarity blend           │
│  - `retrieval_fusion.py` — Weighted reciprocal-rank fusion   │
│  - `rerank.py` — Cross-encoder reranking (threshold guards)  │
│  - `sparse_index.py` — SQLite FTS5 fallback (optional)       │
│  - `search_controls.py` — Validation, bounds, fusion config  │
│  - `temporal_graph.py` — Entity/fact projection + filtering  │
│  - `community_detection.py` — Leiden clustering              │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│            Async Document Ingestion Pipeline                 │
│                                                               │
│  - `document_job_manager.py` — Worker thread, heartbeat/     │
│    lease, store_factory integration                          │
│  - `document_jobs.py` — SQLite job queue with idempotency    │
│  - `document_processing.py` — File format detection,         │
│    MarkItDown + PDFium conversion, chunking                  │
│  - `file_upload.py` — Staged upload store + verify           │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│         External Integrations & Backends                     │
│                                                               │
│  - ArcadeDB 26.7.1 (sole canonical backend via HTTP)         │
│  - OpenAI-compatible embeddings provider (optional local)    │
│  - OpenAI-compatible reranking provider (optional)           │
│  - GLiNER2 entity extraction (via HTTP sidecar)              │
│  - Governance (redaction, audit, retention)                  │
│  - Observability (span recording, runtime signals)           │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| **MCP Server** | FastMCP app bootstrap, tool registration, auth, tenant resolution, span/audit dispatch | `server.py` |
| **Memory Tools** | 14+ MCP tool decorators for memory lifecycle (store/batch/get/search/update/list/delete) | `server_memory_tools.py` |
| **Document Tools** | 7+ MCP tool decorators for document ingestion, upload, status, query | `server_document_tools.py` |
| **Tenant Identity** | Validate user_identifier, derive opaque HMAC-based database names | `tenant_identity.py` |
| **Tenant Registry** | Persist tenant lifecycle state (name, digest, fingerprint, ready status) in SQLite | `tenant_registry.py` |
| **Tenant Provisioner** | Bootstrap schema/indexes, verify manifest, mark ready on first use | `tenant_provisioning.py` |
| **Tenant Router** | Single-flight first-use resolution, LRU view cache (128 default), idle TTL eviction | `tenant_router.py` |
| **Store Facade** | Unified memory/document/entity operations, compose 8 sibling mixins | `store.py` |
| **Store Core** | ArcadeDB init/bootstrap, query/write primitives, span/audit sanitization | `store_core.py` |
| **Memory Write** | store_message, store_messages, add_fact, add_entity, add_session batch writes | `store_memory_write.py` |
| **Memory Read** | get_memory, list_memories, get_entity, list_entities, temporal filtering | `store_memory_read.py` |
| **Memory Search** | search_memories combining channels (dense, BM25, entity, graph, community) | `store_memory_queries.py` |
| **Document Write** | create_document, add_chunk (with chunking logic) | `store_documents.py` |
| **Document Read** | get_document, get_chunk, list_chunks, list_documents | `store_documents.py` |
| **Document Search** | search_documents with metadata filters, page/section awareness, rerank | `store_documents_queries.py` |
| **Evidence** | Entity/fact/temporal projection, edge creation in graph | `store_evidence.py` |
| **Chunking** | Text segmentation, semantic boundary detection | `store_chunking.py` |
| **Rebuild** | Community detection, entity/fact re-extraction, incremental updates | `store_rebuild.py` |
| **Hybrid Search** | Dense vector + lexical BM25 blending (rank-based or intersection) | `hybrid.py` |
| **Retrieval Fusion** | Weighted reciprocal-rank fusion over 6+ ranking channels | `retrieval_fusion.py` |
| **Reranking** | Cross-encoder scoring, threshold guards, margin preservation | `rerank.py` |
| **Sparse Index** | SQLite FTS5 full-text, optional fallback for BM25 | `sparse_index.py` |
| **Temporal Graph** | Entity/fact context normalization, valid_from/valid_to filtering | `temporal_graph.py` |
| **Community Detection** | Leiden clustering (graspologic-native), incremental rebuild | `community_detection.py` |
| **ID Generation** | Stable, deterministic, content-derived IDs for idempotency | `ids.py` |
| **Document Jobs** | SQLite queue, idempotency keys, status tracking | `document_jobs.py` |
| **Ingest Manager** | Worker thread lifecycle, lease/heartbeat, retry logic, store resolution | `document_job_manager.py` |
| **Document Processing** | File format detection, MarkItDown + PDFium conversion, page-aware extraction | `document_processing.py` |
| **File Upload** | Staging store, chunk order verification, SHA-256 validation | `file_upload.py` |
| **ArcadeDB Client** | Thin stdlib-urllib HTTP/JSON wrapper, transaction session, connection pooling | `arcadedb_client.py` |
| **Embeddings** | OpenAI-compatible wrapper, dimension validation, batch inference | `embeddings.py` |
| **Reranker** | OpenAI-compatible cross-encoder, score margin preservation | `rerank.py` |
| **Entity Extraction** | GLiNER2 HTTP provider, batch processing, optional redaction | `entity_extraction.py`, `gliner_provider.py` |
| **Memory Extraction** | Fact/entity mention detection from stored memories via GLiNER2 | `memory_extraction.py` |
| **Governance** | Content redaction, audit event JSONL, retention filtering, expires_at enforcement | `governance.py` |
| **Observability** | Span recording, runtime status signals, latency instrumentation | `observability.py` |

## Pattern Overview

**Overall Pattern:** Multi-tenant, ArcadeDB-backed memory/document service with multi-signal retrieval fusion.

**Key Characteristics:**
- **Protocol-based pluggability:** Embedder, Reranker, EntityProcessor, MemoryExtractor, SpanRecorder, Redactor, AuditSink, CommunityDetector interfaces enable swapping implementations without code change.
- **Environment-driven configuration:** Every integration bootstraps from env vars via factories (e.g., `store_from_env()`, `embeddings_from_env()`); zero hardcoded credentials.
- **User-scoped isolation:** Every operation requires explicit `user_identifier` parameter; no implicit cross-tenant access.
- **Async document pipeline:** Durable SQLite queue with worker thread, heartbeat/lease tracking, idempotency per tenant/document_id/filename/sha256.
- **Multi-signal retrieval:** Memory and document search fuse up to 6+ ranking channels (dense vector, BM25, entity, graph, community) with weighted reciprocal-rank fusion.
- **Temporal-spatial memory:** Facts and entities carry `valid_from`/`valid_to`, `observed_at`, speaker, session_id; graph supports time-scoped queries.
- **Opaque tenant identity:** Tenants are identified by HMAC-derived opaque database names; raw user_identifiers never appear in logs/registry/audit unless explicitly disclosed.

## Layers

**MCP Server Layer:**
- Purpose: Accept RPC calls from Claude/clients, route to store via tenant resolver, serialize responses, span/govern each call.
- Location: `src/turing_agentmemory_mcp/server.py`, `server_memory_tools.py`, `server_document_tools.py`
- Contains: FastMCP app setup, 25+ decorated `@app.tool()` functions, optional bearer-token auth, custom routes (`/health`), tool-span dispatch.
- Depends on: TuringAgentMemory store (or StoreResolver), DocumentUploadStore, DocumentIngestManager, provider config.
- Used by: MCP clients (Claude, browser, CLI); external callers over HTTP/SSE/stdio.

**Tenant Routing Layer:**
- Purpose: Map opaque, case-sensitive user_identifiers to ArcadeDB databases, cache tenant-bound store views, single-flight provisioning on first use.
- Location: `tenant_identity.py`, `tenant_registry.py`, `tenant_provisioning.py`, `tenant_router.py`
- Contains: HMAC-SHA256 derivation, SQLite registry, manifest verification, LRU view cache with idle TTL, single-flight Futures, retry backoff.
- Depends on: ArcadeDBClient, schema bootstrap.
- Used by: MCP server layer, document ingest worker, health/status routes.

**Store Core Layer:**
- Purpose: Unified memory/document/entity operations with consistent vector indexing, graph edges, temporal projection, span/audit sanitization.
- Location: `src/turing_agentmemory_mcp/store.py` (facade), `store_core.py` (base), 8 sibling mixins (each ≤600 LOC by design).
- Contains: TuringAgentMemory class (composed MRO), ArcadeDB query/write/transaction primitives, span/audit choke points, bootstrap helpers.
- Depends on: ArcadeDBClient, Embedder, Reranker, EntityProcessor, MemoryExtractor, CommunityDetector, SparseIndex, Observability, Governance.
- Used by: MCP API layer, document ingest worker, admin/repair tools, E2E test harness.

**Retrieval Stack Layer:**
- Purpose: Multi-signal ranking, temporal filtering, entity/fact graph traversal, community contextualization, optional reranking.
- Location: `hybrid.py`, `retrieval_fusion.py`, `rerank.py`, `sparse_index.py`, `search_controls.py`, `temporal_graph.py`, `community_detection.py`.
- Contains: Weighted RRF, entity mention projection, Leiden clustering, BM25 fallback, cross-encoder scoring, margin preservation.
- Depends on: Models, ID utilities, search validation.
- Used by: TuringAgentMemory mixin methods (`search_memories`, `search_documents`, memory_get_context aggregation).

**Async Document Pipeline Layer:**
- Purpose: Async, durable, resumable file upload and conversion into chunked graph structure.
- Location: `document_job_manager.py`, `document_jobs.py`, `document_processing.py`, `file_upload.py`.
- Contains: DocumentIngestManager (worker + queue), DocumentJobStore (SQLite), ConvertedDocument, MarkItDown+PDFium drivers, staging root.
- Depends on: TuringAgentMemory store (for graph injection), store resolver (for tenant-scoped writes), DocumentProcessing utilities.
- Used by: MCP tools `document_upload_*`, `document_ingest_file`, CLI e2e/benchmark scenarios.

**External Integrations Layer:**
- Purpose: Pluggable HTTP backends for embeddings, reranking, entity extraction; durable observability/governance sinks.
- Location: `arcadedb_client.py`, `embeddings.py`, `entity_extraction.py`, `memory_extraction.py`, `rerank.py`, `governance.py`, `observability.py`.
- Contains: Protocol definitions, HTTP client wrappers, span recorder impl, redactor impl, AuditSink impl, ArcadeDB transaction session.
- Depends on: External HTTP services (EMBED_BASE_URL, RERANK_BASE_URL, GLINER_BASE_URL), optional local models.
- Used by: TuringAgentMemory store for inference operations, every span/audit call.

## Data Flow

### Primary Memory Storage Path

1. Caller invokes `memory_store_message()` MCP tool (`server_memory_tools.py:20`)
2. MCP tool resolves tenant store via `TenantRouter.resolve(user_identifier)` → immutable `TenantStoreView` with bound ArcadeDB client
3. Tool calls `store.store_message(user_identifier, session_id, role, content, ...)` → `store_memory_write.py:_MemoryWriteMixin.store_message()`
4. If `memory_extractor` is configured (fusion enabled), delegates to `store_messages()` batch path; otherwise direct write
5. For direct write: Create stable `memory_id` via `ids.stable_id("mem", ...)` → `store_memory_queries.py:memory_create_statement()`
6. Embed content via `self.embedder(content)` → dense vector + lexical tokens/weights (both inline on record)
7. Batch-collect memory edge, entity mentions, fact creation statements → `store_core._write_many()` (one managed ArcadeDB transaction)
8. Transaction commits atomically: graph record created, vector indexed (LSM_VECTOR/HNSW native), Lucene FTS indexed, optional SparseIndex FTS5 written
9. Return `MemoryItem` dataclass with memory_id, created_at, expires_at, tags, metadata

### Primary Document Search Path

1. Caller invokes `search_documents()` tool → `server_document_tools.py:search_documents()`
2. MCP tool resolves tenant store → calls `store.search_documents(user_identifier, query, limit, ...)`
3. Store calls `hybrid.blend_vectors_and_lexical(query, ...)` → dual-channel candidate pool:
   - Dense: `embedder(query)` → ArcadeDB native `SEARCH VECTOR ... IN ... LIMIT`
   - Lexical: `sparse_index.search(query)` (BM25 via SQLite FTS5, optional if fusion enabled)
4. Blend candidates via rank-based or intersection strategy → deduplicated pool
5. Apply `search_controls.validate_search_bounds()` (limit enforcement, offset handling)
6. Optional reranking: `rerank.rerank(candidates[:rerank_candidate_limit])` → cross-encoder scores, threshold guards, margin preservation
7. Apply retention filter: drop expired documents, filter by `expires_at`
8. Build context: for each hit chunk, fetch `NEXT_CHUNK` neighbors via graph traversal → citation locators (page, section)
9. Return `DocumentHit[]` with chunk_id, document_id, text, score, context, locator

### Memory Search with Multi-Signal Fusion

1. Caller invokes `search_memories(query)` tool → calls store method
2. Parallel channel queries (when fusion_enabled=True):
   - **Dense vectors:** `embedder(query)` → ArcadeDB LSM_VECTOR search
   - **BM25 lexical:** `sparse_index.search(query)` via SQLite FTS5
   - **Entity channel:** Extract entities from query via `entity_extraction`, match against Memory records with entity tags
   - **Graph channel:** BFS neighbors of query-matched entities in the fact/entity graph
   - **Community channel:** Leiden communities (cached), candidates from same community as query match
3. Weighted reciprocal-rank fusion: `retrieval_fusion.fuse_rankings(channels, weights={...})`
   - Each channel capped at cap[channel] candidates (default 200)
   - RRF formula: score += weight / (60 + rank) for each candidate at each rank
   - Sort by fused score, then best rank, then candidate_id
4. Optional reranking on fused pool
5. Return top-k `FusedRetrievalCandidate[]` with channel breakdown

### Asynchronous Document Ingestion Path

1. Caller invokes `document_ingest_file(file_path, user_identifier, title, ...)` tool → `server_document_tools.py`
2. MCP verifies file exists, SHA-256, byte count
3. `DocumentUploadStore` stages bytes to `staging_root / idempotency_key / filename`
4. Returns `job_id` immediately (async)
5. Background `DocumentIngestManager` worker thread polls `DocumentJobStore` for pending jobs
6. Worker claims job with expiring, renewable lease → calls `TenantRouter.resolve(stored_user_identifier)` → tenant-bound store
7. `document_processing.convert_document_to_markdown(source_path)` → `ConvertedDocument`:
   - PDFium extracts page-aware PDF text; MarkItDown handles other formats → `pages: list[DocumentPage]` with page_number, section, text
8. Tenant store creates `Document` record (`stable_id("doc", ...)`) → `create_document()` → `store_documents.py`
9. For each page/chunk: Create `Chunk` record with `page_number`, `section_path`, `text` → embed → create `HAS_CHUNK` edge
10. All statements (Document + Chunks + edges) bundled in one `_write_many()` ArcadeDB transaction
11. Job status = "succeeded"; staged bytes removed
12. If error (conversion, embedding, write): retry up to max_attempts; retain staged bytes; job stays eligible
13. Caller polls `document_ingest_status(job_id)` to check completion

### Community Rebuild (Fusion Enabled)

1. After batch writes (e.g., store_messages), if `community_rebuild_on_batch=True`:
2. Call `_refresh_communities_after_batch()` → `store_rebuild.py:_RebuildMixin`
3. Extract entities from newly stored memories via `memory_extractor(content)` → HTTPMemoryExtractor.extract_facts()
4. Project entities/facts into temporal graph → `temporal_graph.py:plan_temporal_projection()`
5. Run Leiden clustering: `community_detector.detect_communities(entity_graph)` → cluster assignments
6. Create `Community` records and `BELONGS_TO` edges in ArcadeDB
7. Embed community summaries → index in community_index (LSM_VECTOR)
8. Return communities for monitoring

**State Management:**
- Ephemeral runtime state (search rankings, projected candidates) stored in process memory
- Durable memory/document/entity/fact stored in tenant ArcadeDB database (graph + vector + FTS)
- Tenant routing cache (bounded LRU + idle TTL) in process memory; cleared on eviction, safe to recreate
- Upload staging state (temp files, chunks) in `DocumentUploadStore.staging_root` filesystem + upload metadata in DocumentJobStore SQLite
- Async job state in `DocumentJobStore` SQLite table with worker heartbeat/lease tracking
- Observability (span records, runtime status) optional, buffered in process memory or streamed to external AuditSink

## Key Abstractions

**MemoryItem:**
- Purpose: Scoped conversational memory with temporal metadata and lifecycle.
- Examples: `store.py` (method signature), `models.py:MemoryItem` (dataclass)
- Pattern: Immutable dataclass (frozen=True) with user_identifier (implicit), session_id, role, content, tags, metadata, expires_at, created_at, memory_id; serializes to JSON dict via `.to_dict()`.

**DocumentHit:**
- Purpose: Search result chunk with citation metadata and context.
- Examples: `store.py`, `models.py:DocumentHit`
- Pattern: Immutable dataclass with chunk_id, document_id, locator (page/section), text, score, context array (list of neighbor chunks), metadata.

**RetrievalCandidate:**
- Purpose: Ranked candidate from one retrieval channel (dense, BM25, entity, graph, community).
- Examples: `models.py:RetrievalCandidate`, `retrieval_fusion.py:fuse_rankings()`
- Pattern: Immutable with candidate_id, kind (str), content, evidence sources, raw_score; transformed to FusedRetrievalCandidate by RRF.

**FusedRetrievalCandidate:**
- Purpose: Multi-channel ranked result after weighted reciprocal-rank fusion.
- Examples: `models.py:FusedRetrievalCandidate`, `retrieval_fusion.py:fuse_rankings()`
- Pattern: Immutable with candidate (RetrievalCandidate), fused_score, best_rank, channels (dict[str, FusionChannelScore]).

**TemporalProjection:**
- Purpose: Scope memory to user/session/timestamp/speaker; normalize temporal formats.
- Examples: `temporal_graph.py:TemporalProjection`, `temporal_graph.py:EpisodeContext`
- Pattern: Frozen dataclass with post_init validation; used to build fact/entity projections; carries valid_from, valid_to, observed_at.

**Embedder/Reranker/EntityProcessor:**
- Purpose: Pluggable Protocol-based interfaces for inference backends.
- Examples: `embeddings.py:Embedder`, `entity_extraction.py:EntityProcessor`, `memory_extraction.py:MemoryExtractor`
- Pattern: Each defines a `__call__()` signature; implementations wrap HTTP or local inference; `*_from_env()` factories instantiate from config.

**TenantStoreView:**
- Purpose: Immutable bound context pairing a tenant database with a store instance.
- Examples: `tenant_router.py:TenantStoreView`
- Pattern: Dataclass (frozen=True) with identity (TenantDatabaseIdentity), manifest (TenantManifest), memory (TuringAgentMemory); returned by TenantRouter.resolve().

**TenantBinding:**
- Purpose: Verify caller-supplied user_identifier matches the resolved tenant.
- Examples: `tenant_binding.py:TenantBinding`
- Pattern: Frozen dataclass with digest (HMAC-derived), naming_version, key_fingerprint; `verify()` recomputes and compares via constant-time comparison.

## Entry Points

**MCP Server (`serve` command):**
- Location: `src/turing_agentmemory_mcp/cli.py:10` → `main()` dispatch → `server.py:create_mcp_app()`
- Triggers: `turing-agentmemory-mcp serve [--transport stdio|http|sse] [--host] [--port]`
- Responsibilities: Boot FastMCP app, load store/auth/tenant-router from env, listen for RPC on chosen transport, route calls to MCP tools, start background document worker if production_router.

**Embedded (`create_mcp_app()`):**
- Location: `src/turing_agentmemory_mcp/server.py:256`
- Export: `from turing_agentmemory_mcp.server import create_mcp_app` → usable in FastAPI/ASGI apps
- Customization: pass explicit `store`, `resolver`, `upload_store`, `document_manager` to override defaults.

**Store Direct (`TuringAgentMemory`):**
- Location: `src/turing_agentmemory_mcp/store.py` (facade)
- Export: `from turing_agentmemory_mcp.store import TuringAgentMemory`
- Use case: Direct store manipulation in tests or microservices (no MCP overhead).

**CLI Subcommands:**
- `e2e-score`: End-to-end deterministic correctness test (10 scenarios, must score 10/10)
- `agent-quality-eval`: Real-world agent memory/document retrieval benchmark against Aura corpus
- `lab`: Lightweight web UI for manual exploration and debugging
- `utcp-manual`: Generate UTCP (Universal Tool Calling Protocol) schema JSON for CLI integration
- `file-pipe`: Stdio proxy that streams allowlisted local files to remote MCP server

## Architectural Constraints

- **Threading:** Single-threaded event loop for MCP RPC (FastMCP/Starlette async). DocumentIngestManager spawns one optional background worker thread per manager instance. ArcadeDBClient operations are blocking over HTTP; no explicit async/await at the store layer.
- **Global state:** TuringAgentMemory instance maintains ArcadeDBClient connection (one per tenant store view, per TenantRouter cache entry). DocumentIngestManager holds DocumentJobStore SQLite handle. Embedder/Reranker/EntityProcessor may cache models/state in memory. User-scoped isolation enforced by data model (mandatory user_identifier predicate), not process isolation.
- **Circular imports:** Import tree is acyclic; `server.py` imports from store, retrieval, document, tenant layers; no reverse imports.
- **Vector dimensions:** Must be consistent across embedding provider (EMBED_DIMENSIONS env var), all ArcadeDB native LSM_VECTOR indexes (memory_index, document_index, entity_index, fact_index, community_index), and store initialization. Mismatch raises ValueError at store bootstrap.
- **Tenant isolation:** No built-in tenant separation at transport layer; `user_identifier` scope is application-level. Multi-tenant deployments must map authenticated principals to user_identifiers in the calling (reverse-proxy) layer. Model output must never select the tenant.
- **Transaction semantics:** One `_write_many()` per logical operation (document ingest, batch memory store, entity/fact/edge creation). No per-operation rollback on mid-batch failure; retry re-applies entire batch. Job retry uses idempotency keys to avoid duplicate records.
- **Scale limits:** Linear search complexity over all user's memories/documents (no pagination/offset support; API enforces limit parameter). Leiden clustering O(n^1.5) for entity count n; max_cluster_size caps at 100. SparseIndex (SQLite) is single-writer, no concurrent write access within a store instance (concurrent readers OK).

## Anti-Patterns

### Implicit Tenant Scope

**What happens:** Code path accepts user_identifier as a parameter but then makes subsequent queries/mutations without explicitly binding user_identifier to those operations.

**Why it's wrong:** Cross-tenant access if a different store view (or misrouted store) is used downstream; violates invariant #1.

**Do this instead:** Every method in every `store_<concern>.py` mixin must accept user_identifier as a required (keyword) parameter and pass it to every `_write_many()` or query statement call. See `store_memory_write.py:store_message()` (line 44-54) for the pattern.

### Unvalidated Reranker Scores

**What happens:** RetrievalCandidate raw_score values from hybrid/BM25 channels are fed directly into reranker without bounds checking, causing NaN or infinite fused scores.

**Why it's wrong:** Reranker output may be unbounded or pathological; threshold guards and margin preservation are overridden. Violates the "graceful degradation" contract.

**Do this instead:** All rerank callers validate scores via `rerank.py:_validate_scores()`. Reranker errors are caught and candidates fall back to pre-rerank order. See `rerank.py:rerank()` (lines 45-80) for error handling pattern.

### Unbounded Entity Extraction on Long Text

**What happens:** Call entity_extraction on entire documents or memories without chunking, causing timeout or OOM on provider side.

**Why it's wrong:** GLiNER2 provider has request size limits (typically KB); long text will fail silently or hang.

**Do this instead:** Chunk text into segments ≤1KB before passing to `entity_extraction.extract()`. See `memory_extraction.py:HTTPMemoryExtractor.extract_facts()` (lines 150-180) for the batching pattern.

## Error Handling

**Strategy:** Fail fast on validation, degrade gracefully on optional integrations.

**Patterns:**
- **Optional integrations:** Embedding defaults to OpenAICompatibleEmbedder; if provider unreachable, MCP request fails with clear error (not silent degradation).
- **Entity/Fact extraction:** If GLiNER provider fails, memory is stored without entity tagging; reranker/community features degrade gracefully (fusion_weights adjusted, no-op entity channel).
- **Sparse index (BM25):** If SQLite FTS5 unavailable or outdated, hybrid search skips BM25 channel; fusion still runs with remaining channels (dense + entity + graph + community).
- **Community rebuild:** Leiden clustering failure logs warning, skips update; subsequent queries use stale communities (via cached Community records).
- **Document conversion:** If MarkItDown/PDFium fail, job status = "failed", user can retry or inspect logs; staged bytes retained for debugging.
- **Vector index mismatch:** Dimension validation at store init time via `store_core.py:__init__()` (line 160-180); ValueError raised immediately (fail-fast).
- **Tenant provisioning:** If database creation fails, retry with exponential backoff (3 attempts by default); if manifest verification fails, resolve fails closed (rather than creating empty replacement).

## Cross-Cutting Concerns

**Logging:** Span-based (not stdlib logging); every MCP call and major operation recorded via `_span()` context manager (observability.py). Spans carry opaque tenant_database (not raw user_identifier), operation name, duration, error status.

**Validation:** Input validation at MCP tool boundary (server.py); data validation in store (store_<concern>.py) via dataclass __post_init__; search parameter validation in search_controls.py.

**Authentication:** Optional bearer-token auth via AGENTMEMORY_AUTH_TOKEN(S) env var (off by default); applied at FastMCP level, not per-tenant (tenant is selected by MCP caller supply of user_identifier).

**Audit:** Content-free audit JSONL (governance.py) records operation type, timestamp, opaque tenant_database, result status; no memory/document content or raw user_identifier written to audit log.

**Retention:** expires_at on every MemoryItem, Document, Chunk; filtered out by search/retrieval operations at query time (not batch deletion).

**Redaction:** Optional redaction pipeline (governance.py) applied to content before storage and embedding; redacted version indexed, original discarded.

---

*Architecture analysis: 2026-07-16*
