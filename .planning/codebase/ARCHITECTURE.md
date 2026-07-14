<!-- refreshed: 2026-07-14 -->
# Architecture

**Analysis Date:** 2026-07-14

## System Overview

```text
MCP clients / CLI / host-file proxy / Lab
                    |
                    v
FastMCP delivery (`server.py`, `server_*_tools.py`)
                    |
          +---------+----------+
          v                    v
`TuringAgentMemory`       durable document jobs
`store.py`, `store_*.py`  (`document_job_manager.py`)
          |                    |
          +---------+----------+
                    v
ArcadeDB + model providers + SQLite projections/staging
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| CLI | Dispatch server, proxy, evaluation, Lab, UTCP, and repair commands | `src/turing_agentmemory_mcp/cli.py` |
| App factory | Build authentication, dependencies, health route, and FastMCP app | `src/turing_agentmemory_mcp/server.py` |
| Tool adapters | Translate MCP memory/document calls to store operations | `src/turing_agentmemory_mcp/server_memory_tools.py`, `src/turing_agentmemory_mcp/server_document_tools.py` |
| Store facade | Stable unified memory/document API composed from private mixins | `src/turing_agentmemory_mcp/store.py` |
| Store core | Own dependency wiring, bootstrap, database primitives, telemetry, audit, and redaction | `src/turing_agentmemory_mcp/store_core.py` |
| Domain mixins | Memory writes/reads, document lifecycle, evidence, search, and rebuilds | `src/turing_agentmemory_mcp/store_memory_write.py`, `src/turing_agentmemory_mcp/store_memory_read.py`, `src/turing_agentmemory_mcp/store_documents.py`, `src/turing_agentmemory_mcp/store_evidence.py`, `src/turing_agentmemory_mcp/store_search.py`, `src/turing_agentmemory_mcp/store_rebuild.py` |
| Database adapter | ArcadeDB HTTP, query/command, sessions, and MVCC retries | `src/turing_agentmemory_mcp/arcadedb_client.py` |
| Document jobs | SQLite queue, staging, leases, conversion, retry, and cleanup | `src/turing_agentmemory_mcp/document_jobs.py`, `src/turing_agentmemory_mcp/document_job_manager.py` |

## Pattern Overview

**Overall:** Layered service with a stable facade, mixin-based domain decomposition, boundary adapters, and a durable background-job path.

**Key Characteristics:**
- Keep FastMCP registration thin; put domain behavior in the matching `src/turing_agentmemory_mcp/store_*.py` mixin.
- Preserve the public `TuringAgentMemory` import in `src/turing_agentmemory_mcp/store.py`; its multiple-inheritance order is architectural.
- Treat ArcadeDB canonical records as authoritative; SQLite in `src/turing_agentmemory_mcp/sparse_index.py` and `src/turing_agentmemory_mcp/document_jobs.py` holds projections/workflow state.
- Require tenant-scoped `user_identifier` through every public tool and store operation.

## Layers

**Delivery Layer:**
- Purpose: MCP transports/tools, CLI, health, file proxy, UTCP, and local Lab.
- Location: `src/turing_agentmemory_mcp/cli.py`, `src/turing_agentmemory_mcp/server.py`, `src/turing_agentmemory_mcp/file_pipe.py`, `src/turing_agentmemory_mcp/lab.py`
- Contains: Argument parsing, decorators, HTTP routes, proxy wiring, static UI serving.
- Depends on: Store/application services.
- Used by: MCP clients, host applications, operators, and evaluations.

**Application/Domain Layer:**
- Purpose: Memory/document lifecycle, tenant filtering, retrieval, governance, and ingestion orchestration.
- Location: `src/turing_agentmemory_mcp/store.py`, `src/turing_agentmemory_mcp/store_*.py`, `src/turing_agentmemory_mcp/document_job_manager.py`
- Contains: Facade/mixins, validation, transactions, retrieval fusion, job lifecycle.
- Depends on: Models, query builders, providers, ArcadeDB, and SQLite.
- Used by: Delivery adapters and document workers.

**Infrastructure Layer:**
- Purpose: Connect domain operations to ArcadeDB, providers, filesystem, SQLite, spans, and audit sinks.
- Location: `src/turing_agentmemory_mcp/arcadedb_client.py`, `src/turing_agentmemory_mcp/arcadedb_schema.py`, `src/turing_agentmemory_mcp/embeddings.py`, `src/turing_agentmemory_mcp/rerank.py`, `src/turing_agentmemory_mcp/observability.py`
- Contains: Clients, schema/query construction, local durable state, telemetry.
- Depends on: Standard library and `pyproject.toml` dependencies.
- Used by: Store core and domain mixins.

## Data Flow

### Primary Request Path

1. `src/turing_agentmemory_mcp/cli.py:25` dispatches `serve`; `src/turing_agentmemory_mcp/server.py:187` constructs the app and store.
2. A tool registered at `src/turing_agentmemory_mcp/server_memory_tools.py:13` or `src/turing_agentmemory_mcp/server_document_tools.py:15` validates and delegates.
3. `src/turing_agentmemory_mcp/store.py:18` resolves the call through its ordered concern mixins.
4. Query builders in `src/turing_agentmemory_mcp/store_*_queries.py` create parameterized ArcadeDB statements.
5. `src/turing_agentmemory_mcp/arcadedb_client.py:76` performs HTTP query/command or managed transaction work; typed results use `src/turing_agentmemory_mcp/models.py`.

### Retrieval Flow

1. `memory_search`/`memory_get_context` enter at `src/turing_agentmemory_mcp/server_memory_tools.py:173` and `src/turing_agentmemory_mcp/server_memory_tools.py:210`.
2. `src/turing_agentmemory_mcp/store_search.py:46` validates filters and chooses fused or non-fused search.
3. `src/turing_agentmemory_mcp/store_evidence.py` collects dense, Lucene/BM25, fact, entity, graph, and community evidence.
4. `src/turing_agentmemory_mcp/retrieval_fusion.py` applies weighted RRF; `src/turing_agentmemory_mcp/rerank.py` guards/blends provider reranking.

### Asynchronous Document Flow

1. Upload/file tools in `src/turing_agentmemory_mcp/server_document_tools.py` stage hash-verified bytes through `src/turing_agentmemory_mcp/file_upload.py`.
2. `src/turing_agentmemory_mcp/document_job_manager.py:47` copies atomically and enqueues an idempotent SQLite job in `src/turing_agentmemory_mcp/document_jobs.py`.
3. Its background thread claims a lease, heartbeats, and converts through `src/turing_agentmemory_mcp/document_processing.py`.
4. An independent store calls document ingestion in `src/turing_agentmemory_mcp/store_documents.py`; terminal job state and cleanup follow.

**State Management:**
- `create_mcp_app` in `src/turing_agentmemory_mcp/server.py` owns the foreground store and optional document manager/worker lifecycle.
- ArcadeDB stores canonical tenant records and native indexes; SQLite stores the job queue and optional sparse projection.
- `threading.Event`, durable leases, and `atexit` cleanup coordinate the worker in `src/turing_agentmemory_mcp/document_job_manager.py`.

## Key Abstractions

**TuringAgentMemory:**
- Purpose: Stable unified domain API.
- Examples: `src/turing_agentmemory_mcp/store.py`, `src/turing_agentmemory_mcp/store_core.py`
- Pattern: Thin facade composed by multiple inheritance from private concern mixins.

**ArcadeDBClient:**
- Purpose: Isolate REST and session transaction behavior.
- Examples: `src/turing_agentmemory_mcp/arcadedb_client.py`, `src/turing_agentmemory_mcp/arcadedb_schema.py`
- Pattern: Adapter with managed transaction callback and bounded MVCC retries.

**RetrievalCandidate/RetrievalEvidence:**
- Purpose: Normalize heterogeneous channels before fusion.
- Examples: `src/turing_agentmemory_mcp/models.py`, `src/turing_agentmemory_mcp/retrieval_fusion.py`
- Pattern: Typed pipeline intermediate.

**DocumentIngestManager/DocumentJobStore:**
- Purpose: Separate request latency from durable conversion/indexing.
- Examples: `src/turing_agentmemory_mcp/document_job_manager.py`, `src/turing_agentmemory_mcp/document_jobs.py`
- Pattern: Durable queue with idempotency, leases, heartbeats, and retries.

## Entry Points

**Installed CLI:**
- Location: `src/turing_agentmemory_mcp/cli.py`
- Triggers: `turing-agentmemory-mcp` console script in `pyproject.toml`.
- Responsibilities: Dispatch all runtime/operator workflows.

**FastMCP Factory:**
- Location: `src/turing_agentmemory_mcp/server.py`
- Triggers: CLI `serve` or direct import.
- Responsibilities: Configure, bootstrap, register tools, start worker, expose `/health`.

**Automation:**
- Location: `scripts/`
- Triggers: Make/CI/operator commands.
- Responsibilities: Benchmarks, evaluations, scoring, spikes, and checks.

## Architectural Constraints

- **Threading:** FastMCP serves requests while `DocumentIngestManager` owns one background thread; worker stores are independent (`src/turing_agentmemory_mcp/document_job_manager.py`).
- **Global state:** Add no module-level mutable service singletons; assemble application-owned instances in `src/turing_agentmemory_mcp/server.py`.
- **Mixin ordering:** Preserve method resolution order in `src/turing_agentmemory_mcp/store.py`; shared attributes/primitives belong in `_StoreCore`.
- **Transactions:** `_write_many` uses one managed ArcadeDB transaction in `src/turing_agentmemory_mcp/store_core.py`; document creation is intentionally one unbounded transaction to prevent partial visibility.
- **Tenant isolation:** Every canonical/derived record and operation must retain `user_identifier`.
- **Projection consistency:** Vector, sparse, fact, entity, and community indexes are derived and rebuildable from canonical ArcadeDB records.

## Anti-Patterns

### Domain Logic in Tool Registration

**What happens:** Persistence or retrieval algorithms are added to `src/turing_agentmemory_mcp/server_*_tools.py`.
**Why it's wrong:** It duplicates store policy and makes non-MCP callers inconsistent.
**Do this instead:** Implement in the matching `src/turing_agentmemory_mcp/store_*.py` mixin and keep tools thin.

### Bypassing the Store Facade

**What happens:** Consumers call private mixins or query builders directly.
**Why it's wrong:** Bootstrap, tenant validation, audit, and runtime signals can be bypassed.
**Do this instead:** Import `TuringAgentMemory` from `src/turing_agentmemory_mcp/store.py`.

### Treating Projections as Canonical

**What happens:** SQLite sparse rows, vector hits, or communities become authoritative.
**Why it's wrong:** They can lag, be disabled, or be rebuilt.
**Do this instead:** Resolve records through tenant-scoped reads in `src/turing_agentmemory_mcp/store_memory_read.py` and `src/turing_agentmemory_mcp/store_documents.py`.

## Error Handling

**Strategy:** Validate boundaries, preserve transaction atomicity, translate provider/transport failures, and persist safe job failure state.

**Patterns:**
- Raise `ValueError` for invalid configuration/input in `src/turing_agentmemory_mcp/server.py`, `src/turing_agentmemory_mcp/search_controls.py`, and domain methods.
- Roll back and retry bounded MVCC conflicts through `src/turing_agentmemory_mcp/arcadedb_client.py`.
- Store tenant-scoped document failure codes in `src/turing_agentmemory_mcp/document_job_manager.py`.
- Return degraded `/health` status instead of crashing when graph readiness fails in `src/turing_agentmemory_mcp/server.py`.

## Cross-Cutting Concerns

**Logging:** Structured spans/runtime stages are in `src/turing_agentmemory_mcp/observability.py`; tool spans originate in `src/turing_agentmemory_mcp/server.py`.
**Validation:** Shared search controls are in `src/turing_agentmemory_mcp/search_controls.py`; store helpers enforce identifiers, sizes, dates, and limits.
**Authentication:** Optional FastMCP static-token auth is wired in `src/turing_agentmemory_mcp/server.py`; tenant authorization remains caller-bound `user_identifier`.
**Governance:** Redaction, retention, and audit live in `src/turing_agentmemory_mcp/governance.py` and are wired by `src/turing_agentmemory_mcp/store_core.py`.

---

*Architecture analysis: 2026-07-14*
