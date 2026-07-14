# Codebase Concerns

**Analysis Date:** 2026-07-14

## Tech Debt

**Unbounded document transaction:**
- Issue: Each document is materialized through one `_write_many` transaction; transaction-size controls are absent because no document-level publication guard makes chunked commits atomic to readers.
- Files: `src/turing_agentmemory_mcp/store_core.py`, `src/turing_agentmemory_mcp/store_documents.py`
- Impact: Large documents create large statement batches, long transactions, high memory use, and expensive conflict retries.
- Fix approach: Add an ingest generation or `searchable` state, write bounded batches, then atomically publish the completed generation.

**Large mixed-responsibility modules:**
- Issue: Several production modules exceed 500 lines and mix orchestration, persistence, transformation, and policy.
- Files: `src/turing_agentmemory_mcp/store_documents.py`, `src/turing_agentmemory_mcp/store_search.py`, `src/turing_agentmemory_mcp/store_memory_write.py`, `src/turing_agentmemory_mcp/document_jobs.py`, `src/turing_agentmemory_mcp/utcp.py`
- Impact: Changes have broad regression surfaces and parallel work is conflict-prone.
- Fix approach: Extract narrow query adapters and domain services behind the existing store facade, preserving tenant scope and transaction characterization tests.

**Coarse document progress:**
- Issue: Progress is stage-level rather than per page, chunk, or provider batch.
- Files: `src/turing_agentmemory_mcp/document_job_manager.py`, `src/turing_agentmemory_mcp/document_jobs.py`, `src/turing_agentmemory_mcp/server_document_tools.py`
- Impact: Operators cannot distinguish healthy long jobs from stalled operations.
- Fix approach: Add monotonic batch counters, queue age, and per-stage duration telemetry.

## Known Bugs

**No confirmed reproducible defect detected:**
- Symptoms: Not detected in inspected source or current limitation documentation.
- Files: `docs/limitations.md`, `tests/`
- Trigger: Not applicable.
- Workaround: Treat documented pre-1.0 limitations as production constraints and run live integration tiers before releases.

## Security Considerations

**Authentication does not authorize tenants:**
- Risk: A valid static-token client can supply another tenant's `user_identifier`; the server does not bind tenant IDs to authenticated principals.
- Files: `src/turing_agentmemory_mcp/server.py`, `src/turing_agentmemory_mcp/server_memory_tools.py`, `src/turing_agentmemory_mcp/server_document_tools.py`, `docs/security.md`
- Current mitigation: Static-token authentication exists, data paths require explicit tenant scope, and docs require an identity-binding gateway.
- Recommendations: Enforce principal-to-tenant policy at the tool boundary and add adversarial cross-principal integration tests.

**Transport and durable-data protection:**
- Risk: The reference service does not terminate TLS; graph, sparse index, staged documents, audit data, and backups contain sensitive context without application-layer encryption.
- Files: `compose.yaml`, `docs/security.md`, `docs/deployment.md`, `src/turing_agentmemory_mcp/document_job_manager.py`
- Current mitigation: Containers are hardened, sidecars lack host ports, staging is cleaned after success/cancel, and audit/span records exclude raw text.
- Recommendations: Terminate TLS, enforce network policy, encrypt volumes/backups, minimize file-pipe allowlists, and apply retention to failed staging and audit metadata.

**Soft deletion is not erasure:**
- Risk: Deleted or expired content may remain in storage blocks, stale projections, backups, or failed-job staging.
- Files: `src/turing_agentmemory_mcp/store_documents.py`, `src/turing_agentmemory_mcp/store_rebuild.py`, `src/turing_agentmemory_mcp/document_job_manager.py`, `docs/security.md`
- Current mitigation: Active retrieval filters records and exact scoped delete tools exist.
- Recommendations: Define and test hard-erasure/compaction across graph, projections, staging, and backups.

**Prompt-injection boundary:**
- Risk: Stored chunks can contain instructions that downstream agents may execute or prioritize incorrectly.
- Files: `skills/turing-agentmemory/SKILL.md`, `skills/turing-agentmemory/references/integration-patterns.md`, `docs/security.md`
- Current mitigation: The bundled skill defines retrieved evidence as untrusted.
- Recommendations: Preserve evidence delimiters and never place retrieved text in system/developer instruction channels.

## Performance Bottlenecks

**Single document worker:**
- Problem: The reference runtime processes one durable document job at a time.
- Files: `src/turing_agentmemory_mcp/document_job_manager.py`, `compose.yaml`, `docs/limitations.md`
- Cause: `DocumentIngestManager` owns one daemon worker and Compose runs one MCP instance.
- Improvement path: Prove multi-worker lease/idempotency behavior, make concurrency configurable, and add backpressure metrics.

**Whole-document conversion and indexing:**
- Problem: Converted text and database statements accumulate for the full document.
- Files: `src/turing_agentmemory_mcp/document_job_manager.py`, `src/turing_agentmemory_mcp/document_processing.py`, `src/turing_agentmemory_mcp/store_documents.py`, `src/turing_agentmemory_mcp/store_core.py`
- Cause: Conversion returns one aggregate and visibility relies on one transaction.
- Improvement path: Stream bounded conversion/embedding batches behind an atomic publication barrier.

**Tenant-wide rebuilds:**
- Problem: Vector and community rebuilds collect and replace projections for an entire tenant.
- Files: `src/turing_agentmemory_mcp/store_rebuild.py`, `src/turing_agentmemory_mcp/community_detection.py`, `src/turing_agentmemory_mcp/store_rebuild_queries.py`
- Cause: Rebuilds are corpus-wide rather than incrementally maintained.
- Improvement path: Add paging, checkpoints, size telemetry, and incremental/offline modes.

## Fragile Areas

**ArcadeDB retry protocol:**
- Files: `src/turing_agentmemory_mcp/arcadedb_client.py`, `src/turing_agentmemory_mcp/store_core.py`
- Why fragile: Concurrent-modification responses must bypass generic HTTP retry and replay the complete begin/body/commit cycle.
- Safe modification: Preserve dedicated conflict classification and whole-transaction replay ownership.
- Test coverage: Mocked and live coverage exists in `tests/test_arcadedb_client_transport.py` and `tests/test_arcadedb_client.py`, but live tests require services.

**Jobs, leases, cancellation, and staging:**
- Files: `src/turing_agentmemory_mcp/document_job_manager.py`, `src/turing_agentmemory_mcp/document_jobs.py`, `src/turing_agentmemory_mcp/file_upload.py`
- Why fragile: SQLite ownership, heartbeat threads, cooperative cancellation, retry files, and cleanup cross process-failure boundaries.
- Safe modification: Preserve lease-owner checks/idempotency and test crash points before and after conversion, commit, success, and deletion.
- Test coverage: State transitions are tested; sustained multi-process races are not established.

**Versioned vector rebuild cleanup:**
- Files: `src/turing_agentmemory_mcp/store_rebuild.py`, `src/turing_agentmemory_mcp/store_rebuild_queries.py`, `src/turing_agentmemory_mcp/arcadedb_schema.py`
- Why fragile: Population, version swap, schema cleanup, and stale-index handling span data transactions and direct DDL.
- Safe modification: Keep live fields untouched until swap and make cleanup interruption-safe.
- Test coverage: `tests/test_store_arcadedb_rebuild.py` covers behavior; live interruption recovery remains a gap.

## Scaling Limits

**Reference deployment:**
- Current capacity: One MCP service and document worker; GLiNER bounds extraction to 32 requests and request threads to 40.
- Limit: No demonstrated multi-node/multi-worker envelope; local SQLite state and GPU sidecars constrain horizontal scaling.
- Scaling path: Coordinate queue/projection state, test multiple lease owners, shard by tenant where appropriate, and publish saturation curves.
- Files: `compose.yaml`, `src/turing_agentmemory_mcp/document_job_manager.py`, `src/turing_agentmemory_mcp/gliner_provider_http.py`, `src/turing_agentmemory_mcp/sparse_index.py`

**Derived document workload:**
- Current capacity: Upload/provider caps exist, but canonical database transactions are unbounded per document.
- Limit: An accepted file can still generate impractical page, chunk, statement, memory, or latency load.
- Scaling path: Enforce derived limits for pages, extracted characters, chunks, and statements before commit.
- Files: `src/turing_agentmemory_mcp/file_upload.py`, `src/turing_agentmemory_mcp/gliner_provider_http.py`, `src/turing_agentmemory_mcp/store_documents.py`

## Dependencies at Risk

**Alpha and pinned core ecosystem:**
- Risk: The project is `0.1.0`, pins `turingdb==1.35` and `graspologic-native==1.3.1`, and relies on format-sensitive parser/provider packages.
- Impact: Backend or parser/model changes can block upgrades or alter retrieval quality.
- Migration plan: Test candidate versions, record model revisions in evaluations, and upgrade one family at a time against real-document corpora.
- Files: `pyproject.toml`, `tests/test_arcadedb_client.py`, `tests/test_document_processing.py`, `tests/test_agent_quality_eval.py`

**Optional GLiNER stack:**
- Risk: `gliner`, `gliner2`, and `gliner2-onnx` combine runtimes with different model/hardware behavior; `gliner2-onnx` is unbounded.
- Impact: Resolver, loading, or hardware incompatibilities can break extraction independently of MCP.
- Migration plan: Pin deployment locks, test both sidecar contracts, and retain HTTP as the replacement boundary.
- Files: `pyproject.toml`, `docker/gliner-provider.Dockerfile`, `src/turing_agentmemory_mcp/gliner_provider.py`, `src/turing_agentmemory_mcp/entity_extraction.py`

## Missing Critical Features

**First-class tenant authorization:**
- Problem: Tokens authenticate clients but do not map principals to allowed tenant identifiers.
- Blocks: Safe hostile multi-tenant deployment without an enforcing gateway.
- Files: `src/turing_agentmemory_mcp/server.py`, `docs/security.md`, `docs/limitations.md`

**Complete observability:**
- Problem: `/health` lacks Prometheus metrics, queue age, stage duration, saturation, and provider batch progress.
- Blocks: SLOs, autoscaling, and early detection of stuck ingestion.
- Files: `src/turing_agentmemory_mcp/observability.py`, `src/turing_agentmemory_mcp/server.py`, `docs/limitations.md`

**Rich document understanding:**
- Problem: The default path lacks OCR and structured chart/table understanding; conversion quality varies by format.
- Blocks: Dependable retrieval over scanned or visually structured documents.
- Files: `src/turing_agentmemory_mcp/document_processing.py`, `docs/limitations.md`

## Test Coverage Gaps

**Multi-worker ingestion:**
- What's not tested: Concurrent claims, lease takeover, cancellation, duplicate delivery, and staging cleanup across real worker processes.
- Files: `src/turing_agentmemory_mcp/document_job_manager.py`, `src/turing_agentmemory_mcp/document_jobs.py`, `tests/test_document_job_manager.py`, `tests/test_document_jobs.py`
- Risk: Duplicate indexing, stuck leases, lost retries, or premature deletion.
- Priority: High

**Authorization boundary:**
- What's not tested: Principal-to-tenant policy because no binding layer exists.
- Files: `src/turing_agentmemory_mcp/server.py`, `tests/test_auth.py`, `tests/test_arcadedb_tenant_isolation.py`
- Risk: Authentication can be mistaken for authorization.
- Priority: High

**Crash-consistent recovery:**
- What's not tested: Termination at each database/DDL/version-swap/staging boundary against live infrastructure.
- Files: `src/turing_agentmemory_mcp/store_rebuild.py`, `src/turing_agentmemory_mcp/document_job_manager.py`, `tests/test_store_arcadedb_rebuild.py`, `tests/test_arcadedb_chaos_restart.py`
- Risk: Orphaned schema, stale versions, retry failures, or inconsistent job state.
- Priority: High

**Optional and deselected tiers:**
- What's not tested: The unit job deselects `integration`/`gpu`; unmarked `importorskip` paths such as UTCP can pass without execution.
- Files: `.github/workflows/ci.yml`, `tests/conftest.py`, `tests/test_utcp_conformance.py`, `pyproject.toml`
- Risk: Packaging or provider regressions can escape the 78% fast coverage gate.
- Priority: Medium

**Capacity and quality envelope:**
- What's not tested: Concurrent load, normalized throughput, tail latency, saturation, large-tenant rebuilds, and controlled comparative quality.
- Files: `docs/performance.md`, `scripts/benchmark.py`, `scripts/real_document_benchmark.py`, `scripts/agent_quality_eval.py`
- Risk: Production sizing rests on isolated observations.
- Priority: Medium

---

*Concerns audit: 2026-07-14*
