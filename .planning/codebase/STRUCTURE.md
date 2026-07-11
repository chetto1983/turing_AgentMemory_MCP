
# Codebase Structure

**Analysis Date:** 2026-07-11

## Directory Layout

```
turing_AgentMemory_MCP/
├── src/
│   └── turing_agentmemory_mcp/          # Main package (Python 3.11+)
│       ├── __init__.py                   # Package exports
│       ├── server.py                     # FastMCP app, tool registration, HTTP routes
│       ├── cli.py                        # CLI entry point (serve, e2e-score, lab, etc.)
│       ├── store.py                      # TuringAgentMemory core store logic (250+ lines)
│       ├── models.py                     # Immutable dataclasses (MemoryItem, DocumentHit, etc.)
│       │
│       ├── retrieval_fusion.py           # Weighted reciprocal-rank fusion, RRF algorithm
│       ├── temporal_graph.py             # Entity/fact projections, temporal normalization
│       ├── community_detection.py        # Leiden clustering, entity-fact graph
│       ├── hybrid.py                     # Hybrid search (dense + lexical blending)
│       ├── rerank.py                     # OpenAI-compatible cross-encoder reranking
│       ├── sparse_index.py               # SQLite FTS5 full-text search backend
│       ├── search_controls.py            # Query validation, threshold guards, fusion weights
│       │
│       ├── document_job_manager.py       # Async ingest queue, worker thread, lease mgmt
│       ├── document_jobs.py              # DocumentIngestJob model, DocumentJobStore (SQLite)
│       ├── document_processing.py        # File format detection, MarkItDown+PDFium conv.
│       ├── file_upload.py                # Chunked upload staging, sha256 verification
│       ├── file_pipe.py                  # Stdio proxy for streaming local files to remote MCP
│       │
│       ├── embeddings.py                 # Embedder Protocol, OpenAICompatibleEmbedder
│       ├── entity_extraction.py          # EntityProcessor Protocol, default impl
│       ├── memory_extraction.py          # MemoryExtractor Protocol, HTTPMemoryExtractor, GLiNER2
│       ├── gliner_provider.py            # GLiNER HTTP server, request/response handling
│       │
│       ├── governance.py                 # Redactor, AuditSink Protocols, impls
│       ├── observability.py              # SpanRecorder Protocol, RuntimeSignals
│       ├── provider_config.py            # Env var readers, provider URL/model validation
│       │
│       ├── ids.py                        # Stable ID generation, canonicalization
│       ├── benchmark.py                  # Microbenchmark utilities for perf analysis
│       ├── admin_repair.py               # TuringDB vector index repair/recovery tools
│       ├── e2e_score.py                  # Deterministic 10/10 correctness test harness
│       ├── agent_quality_eval.py         # Real-agent memory/doc retrieval eval benchmark
│       ├── lab.py                        # Web UI server for manual exploration
│       ├── utcp.py                       # UTCP (Universal Tool Calling Protocol) schema gen
│       │
│       └── frontend/
│           └── __init__.py               # Frontend assets (if any)
│
├── tests/
│   ├── test_store_entity_processing.py   # Entity extraction in store layer
│   ├── test_retrieval_filters.py         # Date/tag/session filters
│   ├── test_retrieval_fusion.py          # RRF algorithm correctness
│   ├── test_fused_memory_search.py       # Multi-channel memory search
│   ├── test_hybrid_search.py             # Dense + lexical blending
│   ├── test_rerank.py                    # Cross-encoder reranking guards
│   ├── test_search_controls.py           # Query validation, weights validation
│   ├── test_batch_memory.py              # Batch store_messages, refresh_communities
│   ├── test_temporal_graph.py            # Temporal normalization, entity projection
│   ├── test_community_detection.py       # Leiden clustering, community rebuild
│   ├── test_memory_extraction.py         # GLiNER2 fact/entity extraction
│   ├── test_entity_extraction.py         # Entity processor integration
│   ├── test_embeddings.py                # Embedder protocol, dimension consistency
│   ├── test_sparse_index.py              # SQLite FTS5 index, insert/query
│   │
│   ├── test_document_jobs.py             # DocumentJobStore SQLite state machine
│   ├── test_document_job_manager.py      # Async worker, lease heartbeat, retry logic
│   ├── test_document_processing.py       # MarkItDown, PDFium conversion
│   ├── test_document_ingest_file.py      # End-to-end file ingest flow
│   ├── test_document_file_pipe.py        # Stdio file proxy
│   │
│   ├── test_server_batch_tool.py         # FastMCP batch message tool
│   ├── test_auth.py                      # MCP bearer-token auth
│   │
│   ├── test_governance.py                # Redaction, audit JSONL
│   ├── test_observability.py             # Span recording, runtime signals
│   │
│   ├── test_ids.py                       # Stable ID, vector ID generation
│   ├── test_models.py                    # MemoryItem, DocumentHit serialization
│   │
│   ├── test_agent_quality_eval.py        # Real-agent benchmark
│   ├── test_lab.py                       # Web UI routes
│   ├── test_gliner_provider.py           # GLiNER HTTP server
│   ├── test_runtime_pipeline.py          # Full memory/document/search pipeline
│   ├── test_real_document_benchmark.py   # Real PDF/Office document corpus
│   │
│   ├── test_compose_config.py            # docker-compose.yaml validation
│   ├── test_docker_hardening.py          # Dockerfile security checks
│   ├── test_warning_filters.py           # Pytest warning config
│   ├── test_utcp_manual.py               # UTCP schema generation
│   ├── conftest.py                       # Pytest fixtures, TuringDB test server
│   └── test_backboard_*.py               # Integration tests for external frameworks
│
├── docs/
│   ├── README.md                          # Documentation index
│   ├── architecture.md                    # Architecture decisions and rationale
│   ├── configuration.md                   # Environment variables, provider setup
│   ├── deployment.md                      # Docker, Kubernetes, systemd examples
│   ├── mcp-api.md                         # Tool signatures and semantics
│   ├── operations.md                      # Operational monitoring, scaling
│   ├── security.md                        # Auth, redaction, isolation, compliance
│   ├── performance.md                     # Benchmarks, tuning, limits
│   └── limitations.md                     # Known issues, pre-1.0 caveats
│
├── skills/
│   └── [Claude Code skill definitions]   # If project uses Claude Code skills
│
├── docker/
│   ├── Dockerfile.turing-agentmemory-mcp # Main service image
│   ├── Dockerfile.gliner-embed           # GLiNER2 entity extraction sidecar
│   ├── Dockerfile.rerank                 # Cross-encoder reranking sidecar
│   └── Dockerfile.turingdb               # TuringDB database server
│
├── scripts/
│   ├── [utility scripts]                 # Build, test, CI/CD helpers
│   └── [benchmark/profiling tools]
│
├── .github/
│   ├── workflows/                        # GitHub Actions CI/CD
│   └── PULL_REQUEST_TEMPLATE.md
│
├── .planning/
│   └── codebase/                         # GSD codebase analysis documents
│       ├── ARCHITECTURE.md               # This file's companion
│       ├── STRUCTURE.md                  # Directory layout and naming
│       └── [other GSD analysis files]
│
├── pyproject.toml                        # Build metadata, dependencies, pytest config
├── compose.yaml                          # Docker Compose stack (MCP + TuringDB + sidecars)
├── Dockerfile                            # Single-service Docker image
├── Makefile                              # Build shortcuts
├── CLAUDE.md                             # Project-specific Claude Code context
├── README.md                             # Quick start, overview
├── CONTRIBUTING.md                       # Contribution guidelines
├── CHANGELOG.md                          # Version history
├── SECURITY.md                           # Security policy
├── SUPPORT.md                            # Support and feedback
├── LICENSE                               # MIT license
├── .env.example                          # Environment template (NO SECRETS)
└── .gitignore
```

## Directory Purposes

**src/turing_agentmemory_mcp:**
- Purpose: Main package; all user-facing and internal logic
- Contains: Server/store/retrieval/ingest/integration modules
- Key files: `server.py` (entry), `store.py` (core), `models.py` (types)

**tests:**
- Purpose: Unit + integration test suite (39 test files, pytest)
- Contains: Module-level tests, end-to-end scenarios, benchmark harnesses
- Pattern: `test_<module>.py` mirrors `src/turing_agentmemory_mcp/<module>.py`

**docs:**
- Purpose: Architecture, deployment, security, performance documentation
- Contains: Markdown guides, configuration examples, troubleshooting
- Key: Part of README index; should be updated with each feature

**docker:**
- Purpose: Containerization for MCP, sidecars (GLiNER, reranker), TuringDB
- Contains: Multi-stage Dockerfiles, health checks, volume mounts
- Key: Compose stack orchestrates 4+ containers; used in CI and production

**scripts:**
- Purpose: Build automation, benchmarking, CI/CD helpers
- Contains: Bash/Python utilities for test runner, model download, perf profiling

## Key File Locations

**Entry Points:**
- `src/turing_agentmemory_mcp/cli.py`: CLI main(), routes to serve/e2e-score/lab/repair subcommands
- `src/turing_agentmemory_mcp/server.py:create_mcp_app()`: Programmatic FastMCP app factory
- `pyproject.toml:[project.scripts]`: Defines `turing-agentmemory-mcp` console script

**Configuration & Initialization:**
- `src/turing_agentmemory_mcp/server.py:store_from_env()`: TuringAgentMemory bootstrap from TURINGDB_URL, TURINGDB_AUTH_TOKEN, etc.
- `src/turing_agentmemory_mcp/server.py:auth_from_env()`: Bearer-token auth setup
- `src/turing_agentmemory_mcp/provider_config.py`: Embedder/reranker URL, model name, dimensions validation
- `.env.example`: Template for all required environment variables (committed, no secrets)

**Core Logic:**
- `src/turing_agentmemory_mcp/store.py:TuringAgentMemory`: Main store class, all memory/document/entity/fact operations
- `src/turing_agentmemory_mcp/retrieval_fusion.py:fuse_rankings()`: Multi-channel RRF algorithm
- `src/turing_agentmemory_mcp/temporal_graph.py`: Entity/fact projection from memory extraction
- `src/turing_agentmemory_mcp/community_detection.py:NativeLeidenDetector`: Graph clustering

**Testing:**
- `tests/conftest.py`: Pytest fixtures (TuringDB test server, store factory)
- `tests/test_runtime_pipeline.py`: Full end-to-end memory store/search/document flow
- `tests/test_real_document_benchmark.py`: Real PDF/Office document corpus evaluation

**Document Ingestion:**
- `src/turing_agentmemory_mcp/document_job_manager.py:DocumentIngestManager`: Worker lifecycle, queue polling
- `src/turing_agentmemory_mcp/document_jobs.py:DocumentJobStore`: SQLite job state machine
- `src/turing_agentmemory_mcp/document_processing.py:convert_document_to_markdown()`: MarkItDown + PDFium conversion
- `src/turing_agentmemory_mcp/file_upload.py:DocumentUploadStore`: Chunked upload staging

**Utilities:**
- `src/turing_agentmemory_mcp/ids.py`: Stable ID, vector ID, canonical name generation
- `src/turing_agentmemory_mcp/models.py`: MemoryItem, DocumentHit, RetrievalCandidate dataclasses
- `src/turing_agentmemory_mcp/search_controls.py`: Query validation, weights validation, threshold guards
- `src/turing_agentmemory_mcp/hybrid.py`: Dense + lexical blending for search

## Naming Conventions

**Files:**
- Module files: `snake_case.py` (e.g., `temporal_graph.py`, `entity_extraction.py`)
- Test files: `test_<module>.py` mirrors module name (e.g., `test_temporal_graph.py`)
- Config/data: `<name>.example`, `<name>.yaml` (e.g., `.env.example`, `compose.yaml`)

**Directories:**
- Package: `snake_case` (e.g., `turing_agentmemory_mcp/`)
- Feature dirs: `<feature>/` for cohesion (e.g., `frontend/` for web assets)
- Metadata: `.` prefix for tooling (e.g., `.github/`, `.planning/`, `.venv/`)

**Functions:**
- Public: `snake_case()` (e.g., `store_message()`, `search_documents()`)
- Private/internal: `_snake_case()` prefix (e.g., `_tool_span()`, `_ensure_user_scoped_vector_search()`)
- Factory: `<type>_from_env()` (e.g., `store_from_env()`, `embedder_from_env()`)
- Converter: `convert_<format>()` (e.g., `convert_document_to_markdown()`)
- Validator: `validate_<thing>()` (e.g., `validate_fusion_weights()`, `validate_search_query()`)

**Classes:**
- PascalCase (e.g., `TuringAgentMemory`, `DocumentIngestManager`, `NativeLeidenDetector`)
- Protocol interfaces: `<Thing>Protocol` is NOT used; just `<Thing>` (e.g., `Embedder`, `EntityProcessor`, `SpanRecorder`)
- Exceptions: `<Thing>Error` or `<Thing>Exception` (e.g., `SparseIndexUnavailable`, `SparseSchemaMismatch`)
- Data models: `<Entity><Type>` (e.g., `MemoryItem`, `DocumentHit`, `RetrievalCandidate`)

**Variables:**
- Loop vars: `i`, `j`, `k` (indices); `item`, `candidate`, `chunk` (iterables)
- Config: `SCREAMING_SNAKE_CASE` env vars (e.g., `TURINGDB_URL`, `EMBED_DIMENSIONS`)
- Private module state: `_snake_case` (e.g., `_MISSING`, `_PAGE_MARKER_PATTERN`)

**MCP Tools:**
- Verb_noun format: `memory_store_message()`, `memory_search()`, `document_ingest_file()`, `document_delete()`
- Patterns: `memory_*` (25+ tools), `document_*` (8+ tools), `community_*`, `projection_*`

## Where to Add New Code

**New Memory Tool:**
- Add `@app.tool()` function in `server.py` (copy from existing tool, adjust params)
- Implement logic in `store.py:TuringAgentMemory` (add method, call TuringDB client)
- Add test in `tests/test_runtime_pipeline.py` or new `tests/test_<feature>.py`
- Update docs in `docs/mcp-api.md` with signature, example, scope

**New Retrieval Signal (Search Channel):**
- Implement ranker in `src/turing_agentmemory_mcp/<signal>.py` (return `list[RetrievalCandidate]`)
- Register channel in `store.py:search_memory()` or `search_documents()` retrieval dict
- Add fusion weight to `DEFAULT_FUSION_WEIGHTS` in `store.py` and `search_controls.py`
- Test in `tests/test_fused_memory_search.py` with fixture weights
- Benchmark against real documents in `tests/test_real_document_benchmark.py`

**New Entity/Fact Processor:**
- Implement `EntityProcessor` Protocol in new `src/turing_agentmemory_mcp/<processor>.py`
- Add `<processor>_from_env()` factory in `provider_config.py`
- Wire into `store_from_env()` in `server.py` if enabled by env var
- Test integration in `tests/test_store_entity_processing.py`

**New Integration (Embedder, Reranker, etc.):**
- Implement Protocol (Embedder, Reranker, etc.) in dedicated module or add to existing one
- Add `*_from_env()` factory in `provider_config.py` or module itself
- Wire into `TuringAgentMemory.__init__()` kwargs in `server.py:store_from_env()`
- Test with mock HTTP in `tests/` (avoid external service dependency)

**New Document Format Support:**
- Add detector and converter to `document_processing.py:convert_document_to_markdown()`
- Update `_markitdown_converter()` or add `_convert_<format>()` helper
- Test round-trip (file → markdown text → chunks → embeddings) in `tests/test_document_processing.py`

**New CLI Subcommand:**
- Add sub-parser in `cli.py:main()` (e.g., `sub.add_parser("new-command")`)
- Implement handler function, import from feature module
- Add test in `tests/test_<command>.py` or `conftest.py` fixture

**Utilities (ID gen, validation, etc.):**
- Small utilities: Extend existing module (e.g., `ids.py`, `search_controls.py`)
- Complex utilities: New module `src/turing_agentmemory_mcp/<utility>.py`
- Test in isolated `tests/test_<utility>.py` without TuringDB/HTTP deps

## Special Directories

**`.env.example`:**
- Purpose: Template for required environment variables
- Generated: Manually maintained alongside `provider_config.py`
- Committed: Yes (no secrets; example values only)
- Updates: Add new env var when adding new integration or config option

**`/turing` volume:**
- Purpose: TuringDB home directory (shared mount between MCP and database containers)
- Generated: Created by TuringDB daemon on startup
- Contents: 
  - `data/agent-memory-fts.sqlite3` (sparse index for BM25)
  - Vector CSV files (indexed by TuringDB at runtime)
  - Graph metadata
- Committed: No (runtime data, gitignored)

**`.planning/codebase/`:**
- Purpose: GSD codebase analysis documents (ARCHITECTURE.md, STRUCTURE.md, etc.)
- Generated: Created by `/gsd-map-codebase` skill
- Committed: Yes (living documentation)
- Updates: Re-run `/gsd-map-codebase` after major refactors

**`tests/conftest.py`:**
- Purpose: Shared pytest fixtures, TuringDB test server setup
- Generated: Manually maintained
- Key fixtures: `turingdb_server()`, `store_factory()`, `embedder()`, `reranker()`
- Updates: Add fixture when adding new integration that needs test bootstrapping

**`compose.yaml`:**
- Purpose: Docker Compose orchestration (MCP + TuringDB + sidecars)
- Maintained: Mirrors `Dockerfile.*` and `.env.example`
- Services: 4-5 containers (mcp, turingdb, gliner, rerank, optional extras)
- Updates: Add new service when adding new external integration

---

*Structure analysis: 2026-07-11*
