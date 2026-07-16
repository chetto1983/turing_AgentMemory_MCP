# Codebase Structure

**Analysis Date:** 2026-07-16

## Directory Layout

```
turing_agentmemory_mcp/
├── src/
│   └── turing_agentmemory_mcp/
│       ├── __init__.py                    # Package marker (minimal exports)
│       │
│       ├── cli.py                         # CLI entry point (serve, e2e-score, lab, file-pipe)
│       │
│       ├── server.py                      # FastMCP app creation, auth, env bootstrap
│       ├── server_memory_tools.py          # 14+ memory_* MCP tool decorators
│       ├── server_document_tools.py        # 7+ document_* MCP tool decorators
│       │
│       ├── store.py                       # Facade: TuringAgentMemory(...)
│       ├── store_core.py                  # Mixin: init, ArcadeDB primitives, span/audit
│       ├── store_memory_write.py           # Mixin: store_message, store_messages, add_*
│       ├── store_memory_read.py            # Mixin: get_memory, list_memories, get_entity
│       ├── store_memory_queries.py         # SQL query builders for memory operations
│       ├── store_documents.py              # Mixin: create_document, add_chunk
│       ├── store_documents_queries.py      # SQL query builders for document operations
│       ├── store_evidence.py               # Mixin: entity/fact/edge operations
│       ├── store_chunking.py               # Mixin: text chunking, semantic boundaries
│       ├── store_rebuild.py                # Mixin: community detection, entity re-extraction
│       ├── store_retrieval_queries.py      # SQL query builders for search/retrieval
│       ├── store_utils.py                  # Mixin: bootstrap, utility methods, lifecycle
│       │
│       ├── tenant_identity.py              # Opaque tenant database name derivation (HMAC)
│       ├── tenant_registry.py              # SQLite tenant metadata (name, digest, status)
│       ├── tenant_provisioning.py          # Database bootstrap, schema, manifest
│       ├── tenant_router.py                # Single-flight provisioning, LRU view cache
│       ├── tenant_binding.py               # TenantBinding: tenant identity verification
│       │
│       ├── hybrid.py                       # Dense vector + lexical BM25 blending
│       ├── retrieval_fusion.py             # Weighted reciprocal-rank fusion over 6+ channels
│       ├── rerank.py                       # Cross-encoder reranking, threshold guards
│       ├── sparse_index.py                 # SQLite FTS5 BM25 fallback/channel
│       ├── sparse_encoder.py               # Sparse vector encoding for lexical channel
│       ├── search_controls.py              # Search parameter validation, bounds, fusion config
│       ├── temporal_graph.py               # Entity/fact context, valid_from/valid_to filtering
│       ├── community_detection.py          # Leiden clustering (graspologic-native)
│       │
│       ├── document_jobs.py                # SQLite job queue schema, idempotency keys
│       ├── document_jobs_schema.py         # Job table DDL, status enums
│       ├── document_job_manager.py         # Worker thread lifecycle, lease/heartbeat
│       ├── document_processing.py          # File format detection, MarkItDown + PDFium
│       ├── file_upload.py                  # Staging store, chunk verification, SHA-256
│       ├── file_pipe.py                    # Stdio proxy for allowlisted local files
│       │
│       ├── arcadedb_client.py              # Thin stdlib-urllib HTTP/JSON client
│       ├── arcadedb_schema.py              # Schema DDL, vector index versioning
│       │
│       ├── embeddings.py                   # OpenAI-compatible embeddings wrapper
│       ├── entity_extraction.py            # EntityProcessor protocol, HTTP implementation
│       ├── gliner_provider.py              # GLiNER2 ONNX local implementation
│       ├── gliner_provider_http.py         # GLiNER2 HTTP sidecar implementation
│       ├── gliner_provider_extraction.py   # Extraction logic (batch, filtering)
│       ├── memory_extraction.py            # Fact/entity mention extraction from stored memories
│       │
│       ├── ids.py                          # Stable/deterministic ID generation
│       ├── models.py                       # Dataclasses: MemoryItem, DocumentHit, etc.
│       ├── governance.py                   # Redaction, audit events, retention filtering
│       ├── observability.py                # Span recording, runtime signals
│       ├── provider_config.py              # Environment-based factory functions
│       │
│       ├── gate_guard.py                   # Deployment gate checks (CI)
│       ├── e2e_score.py                    # End-to-end deterministic correctness test
│       ├── e2e_score_check.py              # Individual scenario checks
│       ├── e2e_score_scenarios.py          # 10 test scenarios
│       ├── e2e_score_stubs.py              # Stub embedding/rerank providers
│       │
│       ├── lab.py                          # Web UI backend (HTTP + WebSocket)
│       ├── memoryarena.py                  # Lab memory exploration helper
│       ├── utcp.py                         # UTCP schema export for CLI integration
│       │
│       └── frontend/
│           ├── __init__.py                 # Frontend static files marker
│           ├── index.html                  # Lab UI HTML
│           ├── styles.css                  # Lab UI styling
│           └── app.js                      # Lab UI JavaScript
│
├── tests/
│   ├── test_hybrid_search.py               # Hybrid (dense + lexical) tests
│   ├── test_retrieval_fusion.py            # Multi-channel fusion tests
│   ├── test_store_*.py                     # Unit tests per store mixin
│   ├── test_entity_extraction.py
│   ├── test_community_detection.py
│   ├── test_document_processing.py
│   ├── test_document_job_manager.py
│   ├── test_tenant_router.py
│   ├── test_arcadedb_client.py
│   └── ... (30+ test files, pytest discovery pattern)
│
├── scripts/
│   ├── check-file-size.sh                  # Enforce ≤600 LOC per file
│   ├── e2e_score.py                        # E2E gate (deterministic 10/10 threshold)
│   └── ... (utility scripts)
│
├── docs/
│   ├── architecture.md                     # Authoritative architecture overview
│   └── ... (other docs)
│
├── docker/
│   ├── Dockerfile.gliner                   # GLiNER2 ONNX sidecar
│   ├── Dockerfile.embed                    # Embedding/rerank llama.cpp sidecar
│   └── ... (other Dockerfiles)
│
├── .github/
│   ├── workflows/
│   │   ├── test.yml                        # CI: lint, format, pytest, e2e-score
│   │   └── ... (other workflows)
│   └── ... (other GitHub config)
│
├── pyproject.toml                          # Build, test, lint config (ruff, pytest)
├── compose.yaml                            # Docker Compose: 8-service stack
├── Dockerfile                              # Production Dockerfile (Python 3.14-slim)
├── .env.example                            # Template for all required env vars
├── CLAUDE.md                               # This project's instructions for Claude
├── README.md                               # Project overview, setup
├── CHANGELOG.md                            # Version history and breaking changes
└── ... (git, GitHub, CI config)
```

## Directory Purposes

**`src/turing_agentmemory_mcp/`:**
- **Purpose:** All Python source code for the AgentMemory MCP server
- **Contains:** FastMCP app, store layers, tenant routing, retrieval, document pipeline, integrations
- **Key files:** `server.py` (entry), `store.py` (facade), `tenant_*.py` (routing layer)

**`tests/`:**
- **Purpose:** pytest test suite (discovery: test_*.py)
- **Contains:** Unit tests per module, integration tests, E2E harness imports
- **Pattern:** 30+ test files, one per major module or concern
- **Config:** `pyproject.toml:tool.pytest.ini_options` (testpaths=tests, pythonpath=src)

**`scripts/`:**
- **Purpose:** Utility and gate-check scripts
- **Key files:**
  - `e2e_score.py` — Deterministic correctness gate (10/10 threshold, must-pass before commit)
  - `check-file-size.sh` — Enforce ≤600 LOC per .py file (DEEP REFACTOR ON TOUCH constraint)

**`docs/`:**
- **Purpose:** Long-form documentation
- **Key files:**
  - `architecture.md` — Authoritative system design (MUST READ before major changes)

**`docker/`:**
- **Purpose:** Specialized Dockerfiles for sidecars
- **Key files:**
  - `Dockerfile.gliner` — GLiNER2 ONNX extraction service (CPU)
  - `Dockerfile.embed` — llama.cpp embedding/reranking service (GPU)

**`.github/workflows/`:**
- **Purpose:** CI/CD pipeline definitions
- **Key files:**
  - `test.yml` — On-push lint, format, pytest, e2e-score gate

**Root config files:**
- **`pyproject.toml`:** Package metadata, dependencies, pytest/ruff config (line-length 100, E501 ignored)
- **`compose.yaml`:** Production-ready 8-service stack (ArcadeDB, sidecars, MCP, volumes)
- **`Dockerfile`:** Multi-stage build for production image
- **`.env.example`:** All required env vars (template for deployment)

## Key File Locations

**Entry Points:**
- `src/turing_agentmemory_mcp/cli.py:main()` — Command dispatcher (serve, e2e-score, lab, file-pipe)
- `src/turing_agentmemory_mcp/server.py:create_mcp_app()` — FastMCP app factory
- `src/turing_agentmemory_mcp/server.py:store_from_env()` — Legacy single-store factory

**Configuration:**
- `.env.example` — Template for all env vars (ARCADEDB_URL, EMBED_BASE_URL, AGENTMEMORY_*)
- `pyproject.toml` — Build config, dependencies, pytest/ruff rules
- `src/turing_agentmemory_mcp/provider_config.py` — Env-based factory functions for integrations

**Core Logic (Store):**
- `src/turing_agentmemory_mcp/store.py` — Facade (TuringAgentMemory)
- `src/turing_agentmemory_mcp/store_core.py` — Base __init__, ArcadeDB primitives
- `src/turing_agentmemory_mcp/store_memory_write.py` — Memory creation/update
- `src/turing_agentmemory_mcp/store_memory_read.py` — Memory queries and retrieval
- `src/turing_agentmemory_mcp/store_documents.py` — Document creation, chunking
- `src/turing_agentmemory_mcp/store_documents_queries.py` — Document search queries

**Tenant Isolation:**
- `src/turing_agentmemory_mcp/tenant_identity.py` — HMAC-based opaque database names
- `src/turing_agentmemory_mcp/tenant_router.py` — Single-flight provisioning, LRU cache
- `src/turing_agentmemory_mcp/tenant_provisioning.py` — Database bootstrap, manifest

**Retrieval Stack:**
- `src/turing_agentmemory_mcp/hybrid.py` — Dense + lexical blending
- `src/turing_agentmemory_mcp/retrieval_fusion.py` — Weighted RRF fusion
- `src/turing_agentmemory_mcp/rerank.py` — Cross-encoder reranking
- `src/turing_agentmemory_mcp/sparse_index.py` — SQLite FTS5 BM25 channel

**Document Pipeline:**
- `src/turing_agentmemory_mcp/document_job_manager.py` — Async worker, heartbeat/lease
- `src/turing_agentmemory_mcp/document_processing.py` — File conversion (PDFium, MarkItDown)
- `src/turing_agentmemory_mcp/file_upload.py` — Staging store, SHA-256 verification

**Testing:**
- `tests/test_*.py` — Unit + integration tests (pytest discovery)
- `src/turing_agentmemory_mcp/e2e_score.py` — E2E gate harness (10/10 deterministic)

## Naming Conventions

**Files:**
- Snake_case for all module names: `embeddings.py`, `document_processing.py`, `community_detection.py`
- Test files: `test_<module>.py` (e.g., `test_store_memory_write.py`, `test_retrieval_fusion.py`)
- Private concern mixins: `store_<concern>.py`, `store_<concern>_queries.py` (e.g., `store_memory_write.py`, `store_memory_queries.py`)
- Provider implementations: `<provider>_<implementation>.py` (e.g., `gliner_provider.py`, `gliner_provider_http.py`)

**Directories:**
- Snake_case: `src/`, `tests/`, `scripts/`, `docs/`, `docker/`, `.github/`
- No abbreviations or compound words unless industry standard

**Functions:**
- Snake_case: `store_message()`, `convert_document_to_markdown()`, `fuse_rankings()`
- Private functions prefixed with `_`: `_write_many()`, `_ensure_graph_loaded()`, `_pdfium_document()`
- Factories suffixed with `_from_env()`: `store_from_env()`, `embeddings_from_env()`, `tenant_router_from_env()`

**Classes:**
- PascalCase: `TuringAgentMemory`, `RetrievalCandidate`, `DocumentIngestManager`
- Dataclasses: `MemoryItem`, `DocumentHit`, `FusedRetrievalCandidate`, `TemporalProjection`
- Protocols (interfaces): `Embedder`, `EntityProcessor`, `CommunityDetector`, `StoreResolver`, `AuditSink`
- Exception classes: `ProviderFailure`, `RequestFailure`, `ValidationError` (inherit from appropriate base)
- Mixin classes: `_MemoryWriteMixin`, `_DocumentMixin`, `_SearchMixin` (private, internal composition)

**Variables & Constants:**
- Snake_case for variables: `user_identifier`, `memory_index`, `fusion_weights`
- SCREAMING_SNAKE_CASE for module-level constants: `DEFAULT_RRF_K`, `TENANT_NAMING_VERSION`, `MINIMUM_NAMING_KEY_BYTES`

**Type hints:**
- Modern Python 3.11+ syntax (`from __future__ import annotations`)
- Pipe union syntax: `str | None`, `list[str]`, `dict[str, object]`
- Generic types for collections: `Mapping[str, float]`, `Sequence[RetrievalCandidate]`

## Where to Add New Code

**New Memory Feature (e.g., memory_create_tag):**
- Primary implementation: `src/turing_agentmemory_mcp/store_memory_write.py` (add method to `_MemoryWriteMixin`)
- Queries (if any): `src/turing_agentmemory_mcp/store_memory_queries.py` (add query builder function)
- MCP tool: `src/turing_agentmemory_mcp/server_memory_tools.py` (add `@app.tool()` decorated function)
- Tests: `tests/test_store_memory_write.py` (new test_* functions or new file test_<feature>.py)

**New Document Feature (e.g., document_export_markdown):**
- Primary implementation: `src/turing_agentmemory_mcp/store_documents.py` (add method to `_DocumentMixin`)
- Queries: `src/turing_agentmemory_mcp/store_documents_queries.py` (if needed)
- MCP tool: `src/turing_agentmemory_mcp/server_document_tools.py` (add `@app.tool()`)
- Tests: `tests/test_store_documents.py`

**New Retrieval Channel (e.g., semantic_similarity_channel):**
- Channel implementation: New file `src/turing_agentmemory_mcp/<channel_name>.py` (follow Embedder/EntityProcessor protocol)
- Fusion weights config: Add to `search_controls.py:validate_fusion_weights()` (add channel key)
- Integrate into `retrieval_fusion.py:fuse_rankings()` — add channel to rankings dict
- MCP search tool: Already routes through `store.search_memories()` / `store.search_documents()` — no tool change needed
- Tests: `tests/test_<channel_name>.py`

**New Utility/Helper Function:**
- Shared helpers: `src/turing_agentmemory_mcp/store_utils.py` (if store-related) or new `src/turing_agentmemory_mcp/<util_name>.py`
- Keep functions small, focused, reusable
- If new module, update imports in dependent modules (no barrel files; explicit imports)

**New Command or CLI Subcommand:**
- Add to `src/turing_agentmemory_mcp/cli.py:main()` subparser
- Implement logic in separate module: `src/turing_agentmemory_mcp/<command_name>.py`
- Follow pattern of `e2e_score.py`, `lab.py`, `file_pipe.py`

**New Test:**
- Filename: `tests/test_<module>.py` (matches source module name)
- Or: `tests/test_<feature_name>.py` (for cross-module features)
- Pattern: Use pytest discovery (test_*.py), follow `tests/test_*.py` style
- Fixtures: Use pytest conftest.py conventions (create `tests/conftest.py` if needed)

## Special Directories

**`src/turing_agentmemory_mcp/frontend/`:**
- **Purpose:** Static frontend assets for Lab UI
- **Generated:** No (hand-written HTML/CSS/JS)
- **Committed:** Yes
- **Files:** `index.html`, `styles.css`, `app.js`

**`.planning/codebase/`:**
- **Purpose:** Generated codebase documentation (by gsd-codebase-mapper)
- **Generated:** Yes (write-only, not committed)
- **Files:** ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, CONCERNS.md, STACK.md, INTEGRATIONS.md

**`.arcadedb/`:**
- **Purpose:** Local ArcadeDB data directory (docker compose volume mount)
- **Generated:** Yes (by ArcadeDB container)
- **Committed:** No (.gitignore)

**`.benchmarks/`:**
- **Purpose:** Machine-readable benchmark results (JSON)
- **Generated:** Yes (by scripts/e2e_score.py and benchmarks)
- **Committed:** No

**`tests/.test-tmp-*/`:**
- **Purpose:** Temporary test artifacts, staging directories
- **Generated:** Yes (by test suite)
- **Committed:** No

## Mixin Composition Pattern

The `TuringAgentMemory` class in `store.py` is a thin facade that composes 8 sibling mixin modules using Python's MRO (Method Resolution Order):

```python
class TuringAgentMemory(
    _MemoryWriteMixin,      # store_memory_write.py
    _MemoryReadMixin,       # store_memory_read.py
    _SearchMixin,           # store_retrieval_queries.py (implicit via cross-calls)
    _EvidenceMixin,         # store_evidence.py
    _DocumentMixin,         # store_documents.py
    _ChunkingMixin,         # store_chunking.py
    _RebuildMixin,          # store_rebuild.py
    _UtilsMixin,            # store_utils.py
    _StoreCore,             # store_core.py (base)
):
    """Unified memory/document store."""
```

**Design Rationale:**
- Each mixin owns one concern (memory write, document read, evidence, etc.)
- `store_core.py` owns `__init__` and query/write primitives; other mixins reuse via `self._write_many()`, `self._span()`, etc.
- Cross-mixin calls (e.g., `_MemoryWriteMixin.store_message()` calls `self.get_memory()` from `_MemoryReadMixin`) resolve via MRO at runtime
- Max 600 LOC per mixin enforced by `scripts/check-file-size.sh`; files exceeding this trigger a gate failure and require decomposition

**Constraint:** Every source file `*.py` is capped at 600 lines of code (checked by CI). If a module grows past 600 LOC, split it into `<name>_<concern1>.py` + `<name>_<concern2>.py` and import from both.

## File Organization Patterns

**Query Builders:**
- Separate files for query builders: `store_<concern>_queries.py`
- Example: `store_memory_queries.py` contains `memory_create_statement()`, `memory_edge_statement()`, `entity_create_statement()`
- Rationale: Keep SQL/AQL logic isolated, easy to review and test
- Import: Imported by corresponding `store_<concern>.py` mixin

**HTTP Client Wrappers:**
- One file per integration: `<service>_<impl>.py`
- Example: `gliner_provider_http.py` (HTTP implementation of entity extraction)
- Alt impl: `gliner_provider.py` (local ONNX implementation)
- Pattern: Both implement same protocol; swapped via env config

**Job/Queue Infrastructure:**
- Core schema: `<domain>_jobs_schema.py` (DDL, enums)
- Example: `document_jobs_schema.py` (DocumentIngestJob dataclass, status enums)
- Implementation: `<domain>_jobs.py` (store logic, idempotency, queries)
- Manager: `<domain>_job_manager.py` (worker thread, lease, retry)

**E2E Testing:**
- Harness: `e2e_score.py` (orchestrator, scenario dispatch)
- Checks: `e2e_score_check.py` (individual assertions)
- Scenarios: `e2e_score_scenarios.py` (10 deterministic test cases)
- Stubs: `e2e_score_stubs.py` (mock embedding/rerank providers for CI)

---

*Structure analysis: 2026-07-16*
