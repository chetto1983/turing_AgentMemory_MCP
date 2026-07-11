<!-- GSD:project-start source:PROJECT.md -->

## Project

**Turing AgentMemory MCP — Stabilization Milestone**

An Agent Memory MCP server (`turing_agentmemory_mcp`) that exposes memory-lifecycle
and document tools over FastMCP, stores canonical graph + vector records in a graph+vector
database, and serves tenant-scoped, cited retrieval. It is currently TuringDB-backed and
**migrates to ArcadeDB as its sole backend this milestone** (chosen on licensing —
Apache-2.0). Provider integrations
(embedding, rerank, GLiNER2 entity extraction) are OpenAI-compatible HTTP endpoints.
This milestone hardens an already-built system: it stands the **entire infrastructure
up on Docker as a reliable one-command stack**, works through **every concern** in the
codebase audit, and installs **CI plus pre-commit / pre-push hooks** modeled on the
Aura project's engineering discipline.

**Core Value:** The system must remain correct and tenant-isolated under stabilization: after every
change, a real document flows end-to-end through the dockerized MCP (async job →
truthful terminal state → canonical chunks → scoped cited search → staged bytes removed)
and the deterministic E2E score gate stays green. Stabilization that breaks retrieval
correctness or tenant isolation is a failure, not progress.

### Constraints

- **Tech stack**: Python 3.11–3.14, FastMCP 3.4–4, TuringDB 1.35, ruff (line-length 100, E501 ignored), pytest — [established; changes are themselves audited concerns, not free choices]
- **Architecture — replaced this milestone**: CLAUDE.md invariant #2 (TuringDB canonical) is superseded — **ArcadeDB becomes the sole canonical backend**; TuringDB is removed. ArcadeDB's native vector + full-text are ACID-consistent with graph writes, retiring the SQLite-FTS5 outbox as a separate rebuildable projection. CLAUDE.md invariants must be updated as part of this milestone. The port must preserve tenant isolation (invariant #1) and stable/deterministic IDs (invariant #3).
- **Tenant isolation**: every read/write explicitly scoped by `user_identifier`, fail-closed on empty — non-negotiable through the port; reinforced by one ArcadeDB database per tenant — [CLAUDE.md invariant #1]
- **Durability**: ArcadeDB data, the SQLite job DB, staged files (moving to Garage/S3), and audit/span JSONL are the durable state; ArcadeDB persists to its own data volume — [server-side CSV vector loading was a TuringDB constraint and no longer applies]
- **GPU dependency**: embed/rerank sidecars are GPU-mandatory for the full stack — [CI must degrade gracefully on GPU-less runners]

<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->

## Technology Stack

## Languages

- Python 3.11+ - All source code and CLI tools (pyproject.toml specifies 3.11–3.14)

## Runtime

- Python 3.14 slim (Docker image for production: `python:3.14-slim`)
- Docker & Docker Compose for orchestration
- pip (installed via hatchling build system)
- Lockfile: No explicit lock file; version pinning is in `pyproject.toml`

## Frameworks

- fastmcp 3.4–4 - Model Context Protocol server framework. Provides MCP tool definitions, transport layers (stdio, HTTP, SSE), and resource management (`src/turing_agentmemory_mcp/server.py`, `src/turing_agentmemory_mcp/file_pipe.py`)
- starlette - Web framework for HTTP response handling, used for JSON responses in MCP health endpoint
- pytest 8.2+ - Test runner and framework (`pyproject.toml:tool.pytest.ini_options`)
- hatchling 1.27+ - Python build backend and package manager
- ruff 0.9+ - Linting and code formatting (enforces E, F, I, B, UP rules; line-length 100)

## Key Dependencies

- turingdb 1.35 - Primary graph + vector database with local CSV vector storage (`src/turing_agentmemory_mcp/store.py`, `src/turing_agentmemory_mcp/server.py`)
- graspologic-native 1.3.1 - Leiden hierarchical community detection algorithm for graph clustering (`src/turing_agentmemory_mcp/community_detection.py:330`)
- markitdown 0.1.6–0.2 (with pdf, docx, pptx, xlsx plugins) - Converts Microsoft Office, spreadsheets, HTML, and other formats to markdown (`src/turing_agentmemory_mcp/document_processing.py:15–18`)
- pypdfium2 4.30–5 - PDF text extraction with page-level awareness (`src/turing_agentmemory_mcp/document_processing.py:22–59`)
- gliner 0.2.27+ - Named entity recognition framework
- gliner2 1.3.2 - GLiNER v2 model suite
- gliner2-onnx - ONNX runtime support for GLiNER2

## Configuration

- `.env.example` in repo root defines all runtime configuration
- Key env vars: `TURINGDB_URL`, `EMBED_BASE_URL`, `EMBED_DIMENSIONS`, `RERANK_BASE_URL`, authentication tokens, document job settings
- Docker Compose exposes templated env var injection via `${VAR_NAME:-default}` syntax (`compose.yaml`)
- `pyproject.toml` - Project metadata, dependencies, build configuration
- `Dockerfile` - Multi-stage build (installs dependencies, copies source, runs editable install)
- `docker/` - Specialized Dockerfiles for TuringDB, llama.cpp (embedding/reranking), and GLiNER services
- `compose.yaml` - Production-ready Docker Compose stack with 8 services and volume management
- `.ruff.lint` configured in `pyproject.toml` with E, F, I, B, UP rules; E501 (line too long) ignored
- No `.prettierrc` or `.eslintrc` (Python project)

## Platform Requirements

- Python 3.11 or higher
- Docker & Docker Compose (for local full-stack deployment)
- NVIDIA GPU + CUDA (for llama.cpp embedding/reranking sidecars)
- Python 3.11+ runtime
- Docker & Docker Compose (reference deployment model)
- NVIDIA GPU with CUDA (embedding and reranking services)
- Shared volume accessible by MCP container and TuringDB container at `/turing`
- Sufficient disk space for vector index CSV files and document staging
- fast_gliner 0.2.1 - For GLiNER entity extraction provider (separate Python 3.12-slim container)

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

## Naming Patterns

- Snake_case for all module names (e.g., `embeddings.py`, `document_processing.py`, `community_detection.py`)
- Test files prefixed with `test_` (e.g., `test_embeddings.py`, `test_models.py`)
- Snake_case for all function names
- Private functions prefixed with underscore: `_internal_helper()`, `_ensure_graph_loaded()`
- Example: `convert_document_to_markdown()`, `aggregate_weighted_edges()`, `rank_hybrid()`
- PascalCase for all class names
- Dataclasses heavily used with descriptive names: `RetrievalCandidate`, `MemoryItem`, `DocumentHit`
- Protocol classes for interfaces: `Embedder`, `ExtractProvider`, `CommunityRebuilder`
- Exception classes inherit from standard exceptions: `class RequestFailure(ValueError)`, `class ProviderFailure(ValueError)`
- Snake_case for all variables and attributes
- Constants: SCREAMING_SNAKE_CASE
- Uses `from __future__ import annotations` in all files
- Pipe union syntax: `str | None`, `list[str]`, `dict[str, object]`
- Generic type hints for collections
- Protocol classes define interfaces: `class Embedder(Protocol):`

## Code Style

- Tool: ruff
- Line length: 100 characters
- No semicolons for statement termination
- Uses `from __future__ import annotations` for forward compatibility
- Tool: ruff
- Configured rules: E (pycodestyle), F (pyflakes), I (isort), B (flake8-bugbear), UP (pyupgrade)
- Ignored: E501 (line too long - manually controlled via 100-char limit)
- Target: Python 3.11+
- Heavily used throughout codebase for data containers
- Use `frozen=True` for immutable data: `@dataclass(frozen=True)` in `models.py`, `embeddings.py`
- Use `slots=True` for performance in performance-critical classes: `@dataclass(frozen=True, slots=True)` in `community_detection.py`
- Default factory for mutable defaults: `field(default_factory=dict)`, `field(default_factory=list)`
- Module-level docstrings present for complex modules
- Minimal inline documentation (code is self-documenting)
- Class docstrings when behavior is non-obvious: `"""Adapt FastGLiNER2's one-text API to the provider batch contract."""` in `gliner_provider.py`
- No mandatory function-level docstrings

## Import Organization

- Relative imports within package: `from .embeddings import Embedder`
- Absolute imports for CLI entry points: `from turing_agentmemory_mcp.utcp import build_utcp_manual`

## Error Handling

- Raise specific exception types with descriptive messages:
- Validation in `__post_init__` for dataclasses:
- Try-except for external API calls and imports:
- Use context managers for resource cleanup (file handles, server connections)

## Logging

## Comments

- Complex algorithmic logic (lexical scoring, community detection)
- Non-obvious performance optimizations
- Workarounds for known issues
- Self-documenting code (types and names convey intent)
- Simple business logic
- Standard patterns (for loops, conditionals)

## Function Design

- Explicit keyword-only arguments for clarity: `def lexical_score(query: str, text: str) -> float:`
- Use keyword-only for optional/configuration parameters: `def convert_document_to_markdown(path: str | Path, *, converter: Any | None = None):`
- Type hints always present
- Return single objects or simple types; avoid tuple unpacking for clarity
- Use dataclasses for complex return values
- Example: `def store_message(...) -> MemoryItem:` returns a data object

## Module Design

- Public APIs exported directly from modules
- Private helpers prefixed with underscore: `_ensure_graph_loaded()`, `_convert_pdfium()`, `_pdfium_document()`
- No `__all__` declarations; rely on naming convention
- `__init__.py` files present but minimal
- No re-exports in `__init__.py` files
- Public dataclass: `ConvertedDocument`
- Private converters: `_markitdown_converter()`, `_pdfium_document()`, `_convert_pdfium()`
- Public main function: `convert_document_to_markdown()`

<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

## System Overview

```text

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

- **Protocol-based pluggability:** Embedder, EntityProcessor, MemoryExtractor, SpanRecorder, Redactor, AuditSink, CommunityDetector interfaces allow swapping implementations without code change
- **Environment-driven configuration:** Factories (`*_from_env()`) build all integrations from env vars; zero hardcoded credentials
- **User-scoped data isolation:** Every operation requires explicit `user_identifier`; no implicit cross-tenant access
- **Async document pipeline:** Durable queue in `DocumentJobStore` (SQLite), worker thread with heartbeat/lease semantics
- **Multi-signal retrieval:** Memory and document search fuse up to 6+ ranking channels (dense vector, BM25, entity, graph, community) with weighted reciprocal-rank fusion
- **Temporal-spatial memory:** Facts and entities carry `valid_from`/`valid_to`, `observed_at`, speaker, session_id; graph supports time-scoped queries

## Layers

- Purpose: Accept RPC calls from Claude/clients, route to store, serialize responses, span + govern each call
- Location: `src/turing_agentmemory_mcp/server.py`
- Contains: FastMCP app setup, 25+ decorated `@app.tool()` functions, auth middleware, custom routes (`/health`)
- Depends on: TuringAgentMemory store, DocumentUploadStore, DocumentIngestManager, provider config
- Used by: MCP clients (Claude, browser, CLI); external callers over HTTP/SSE/stdio
- Purpose: Unified memory/document/entity operations with consistent vector indexing, graph edges, temporal projection
- Location: `src/turing_agentmemory_mcp/store.py`
- Contains: TuringAgentMemory class (250+ lines), graph traversal, chunking, multi-index operations
- Depends on: TuringDB client, Embedder, Reranker, EntityProcessor, MemoryExtractor, CommunityDetector, SparseIndex, observability
- Used by: MCP API layer, document ingest worker, admin repair tools
- Purpose: Multi-signal ranking, temporal filtering, entity/fact graph traversal, community contextualization
- Location: `retrieval_fusion.py`, `temporal_graph.py`, `community_detection.py`, `hybrid.py`, `rerank.py`, `sparse_index.py`, `search_controls.py`
- Contains: Weighted RRF, entity mention projection, Leiden clustering, BM25 fallback, cross-encoder scoring
- Depends on: Models, ID utilities, search validation
- Used by: TuringAgentMemory for memory/document search, memory_get_context aggregation
- Purpose: Async, durable, resumable file upload and conversion into chunked graph structure
- Location: `document_job_manager.py`, `document_jobs.py`, `document_processing.py`, `file_upload.py`
- Contains: DocumentIngestManager (worker + queue), DocumentJobStore (SQLite), ConvertedDocument, MarkItDown+PDFium drivers
- Depends on: TuringAgentMemory store (for graph injection), DocumentProcessing utilities
- Used by: MCP tools `document_upload_*`, `document_ingest_file`, CLI e2e/benchmark scenarios
- Purpose: Bootstrap store, document pipeline, auth, embeddings, observability from environment
- Location: `server.py` factory functions + `provider_config.py`
- Contains: `store_from_env()`, `auth_from_env()`, `document_upload_store_from_env()`, environment validators
- Depends on: dotenv (implied), TuringDB, external provider URLs
- Used by: CLI entry point, FastMCP app creation, test fixtures
- Purpose: Pluggable backends for embeddings, entity extraction, governance, observability
- Location: `embeddings.py`, `entity_extraction.py`, `memory_extraction.py`, `governance.py`, `observability.py`, `gliner_provider.py`, `provider_config.py`
- Contains: Protocol definitions, HTTP client wrappers, SpanRecorder impl, Redactor impl
- Depends on: External HTTP services (EMBED_BASE_URL, RERANK_BASE_URL, GLINER_BASE_URL), optional local models
- Used by: TuringAgentMemory store for inference operations

## Data Flow

### Primary Memory Storage Path

### Primary Document Search Path

### Asynchronous Document Ingestion Path

### Community Rebuild (Fusion Enabled)

- Ephemeral runtime state (search rankings, projected candidates) stored in process memory
- Durable memory/document/entity/fact stored in TuringDB graph + vector indexes
- Upload staging state (temp files, chunks) in `upload_store.staging_root` filesystem + upload job metadata in DocumentJobStore
- Async job state in `DocumentJobStore` SQLite table with worker heartbeat/lease tracking
- Observability (span records, runtime status) optional, buffered in process or streamed to external sink

## Key Abstractions

- Purpose: Scoped conversational memory with temporal metadata and lifecycle
- Examples: `store.py:63`, `models.py:63`
- Pattern: Immutable dataclass with user_identifier, session_id, role, content, tags, metadata, expires_at; serializes to JSON/dict
- Purpose: Search result chunk with citation metadata and context
- Examples: `store.py`, `models.py:87`
- Pattern: Immutable dataclass with chunk_id, document_id, locator (page/section), text, score, context array, metadata
- Purpose: Ranked candidate from one retrieval channel (dense, BM25, entity, graph, community)
- Examples: `models.py:7`, `retrieval_fusion.py`
- Pattern: Immutable with candidate_id, kind, content, evidence sources, raw_score; transformed to FusedRetrievalCandidate by RRF
- Purpose: Scope memory to user/session/timestamp/speaker; normalize temporal formats
- Examples: `temporal_graph.py:19`, `temporal_graph.py:75`
- Pattern: Frozen dataclass with post_init validation; used to build fact/entity projections
- Purpose: Pluggable Protocol-based interfaces for inference backends
- Examples: `embeddings.py:27`, `entity_extraction.py:43`, `memory_extraction.py:143`
- Pattern: Each defines `__call__()` signature; implementations wrap HTTP or local inference; `*_from_env()` factories instantiate from config

## Entry Points

- Location: `src/turing_agentmemory_mcp/cli.py:main()` -> `cli.py:52` (serve branch)
- Triggers: `turing-agentmemory-mcp serve [--transport stdio|http|sse] [--host] [--port]`
- Responsibilities: Boot FastMCP, load store + auth + integrations from env, listen for RPC, route to tools
- `e2e-score`: End-to-end deterministic correctness test (10 scenarios, must score 10/10)
- `agent-quality-eval`: Real-world agent memory/document retrieval benchmark against Aura corpus
- `lab`: Lightweight web UI for manual exploration and debugging
- `utcp-manual`: Generate UTCP (Universal Tool Calling Protocol) schema JSON for CLI integration
- `file-pipe`: Stdio proxy that streams allowlisted local files to remote MCP server
- `repair-vector-index`: Quarantine corrupt TuringDB vector directories, recreate empty indexes
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

### Unvalidated Reranker Scores

### Unbounded Entity Extraction on Long Text

## Error Handling

- **Optional integrations:** Embedding defaults to OpenAICompatibleEmbedder; if provider unreachable, MCP request fails with clear error (not silent degradation)
- **Entity/Fact extraction:** If GLiNER provider fails, memory is stored without entity tagging; reranker/community features degrade gracefully
- **Sparse index (BM25):** If SQLite FTS5 unavailable, hybrid search skips BM25 channel; fusion still runs with remaining channels
- **Community rebuild:** Leiden clustering failure logs warning, skips update; subsequent queries use stale communities
- **Document conversion:** If MarkItDown/PDFium fail, job status = "failed", user can retry or inspect logs
- **Vector index mismatch:** Dimension validation at store init time; ValueError raised immediately (fail-fast)

## Cross-Cutting Concerns

<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
