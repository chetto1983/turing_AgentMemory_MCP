# Codebase Concerns

**Analysis Date:** 2026-07-11

## Tech Debt

**Upload Session Memory Leak:**
- Issue: `DocumentUploadStore._sessions` dictionary keeps in-memory state of active uploads but never explicitly cleans up abandoned sessions. If uploads are initiated but not completed, the session objects persist in memory indefinitely.
- Files: `src/turing_agentmemory_mcp/file_upload.py` (lines 56, 84-92, 172-175)
- Impact: Long-running servers with many partial uploads can experience memory exhaustion. Session state is lost on server restart.
- Fix approach: Implement automatic session cleanup (TTL-based expiry) or persist session state to SQLite like `DocumentIngestManager` does with `DocumentJobStore`.

**Single Document Worker Thread:**
- Issue: `DocumentIngestManager` runs document processing in a single daemon thread (`_thread`), created at line 277-282.
- Files: `src/turing_agentmemory_mcp/document_job_manager.py` (lines 25-57, 273-282, 291-315)
- Impact: Document ingestion throughput is limited to one document at a time. High-volume document uploads will queue and take significantly longer.
- Fix approach: Implement a thread pool or async worker pattern to process multiple documents concurrently. Update job leasing to support multi-worker scenarios with proper lock management.

**Stale Vector Accumulation:**
- Issue: Vector rebuilds add new vectors to indexes but do not remove old vectors from previous builds. Over time, indexes accumulate stale entries.
- Files: `src/turing_agentmemory_mcp/store.py` (lines 322-328 for rebuild tool), overall vector lifecycle management
- Impact: Index size grows indefinitely; retrieval scores may be affected if stale vectors are returned; storage and performance degrade.
- Fix approach: Implement versioned namespacing for vector indexes or add explicit stale vector cleanup on rebuild. Document required operational procedures.

**Soft Deletion Incomplete Erasure:**
- Issue: Records are marked with status="deleted" in the graph but backups, storage blocks, and historical versions remain untouched.
- Files: `src/turing_agentmemory_mcp/store.py` (lines 1574-1603 for memory deletion, 1783-1804 for document deletion)
- Impact: Deleted sensitive data may remain recoverable from backups or old storage blocks, creating data retention/privacy risks.
- Fix approach: Document retention policy and backup management separately. Implement optional hard-delete with audit logging, or enforce backup rotation in deployment docs.

**Thread Safety Gap in Upload Store:**
- Issue: `DocumentUploadStore._sessions` dict is accessed and modified without synchronization primitives (no locks).
- Files: `src/turing_agentmemory_mcp/file_upload.py` (lines 56, 84, 107, 148, 172-174, 178-183)
- Impact: In multi-threaded deployments, concurrent uploads could cause race conditions (lost updates, KeyError, or data corruption).
- Fix approach: Add `threading.Lock()` around all `_sessions` access. Verify deployment is single-threaded or upgrade to thread-safe session management.

**Cooperative Cancellation Blocking:**
- Issue: Document job cancellation is cooperative. If a converter or TuringDB call blocks indefinitely, the worker won't observe the cancellation request.
- Files: `src/turing_agentmemory_mcp/document_job_manager.py` (lines 217-220 check for cancellation, but only between operations)
- Impact: Canceled jobs may continue processing. Blocking provider calls are not interruptible.
- Fix approach: Add timeout wrappers around provider calls (document conversion, indexing). Implement signal-based interruption or use asyncio with proper cancellation tokens.

## Known Bugs

**Vector Rebuild Does Not Clean Stale Indexes:**
- Symptoms: Over time after multiple vector rebuilds, indexes grow and may contain duplicate or outdated vectors.
- Files: `src/turing_agentmemory_mcp/store.py` (memory_rebuild_vector_projection at line 322)
- Trigger: Run memory_rebuild_vector_projection multiple times on the same data.
- Workaround: Manually drop old vector indexes and rebuild from scratch. Document this in operational runbooks.

**Upload Session State Lost on Restart:**
- Symptoms: In-progress file uploads become unrecoverable if the server restarts. Clients receive "upload_id is unknown" errors.
- Files: `src/turing_agentmemory_mcp/file_upload.py` (lines 56, 84-92)
- Trigger: Server restart during active file upload.
- Workaround: Retry the entire upload from the beginning after restart. Consider storing staging area in persistent location before complete commit.

**Session Expiry Not Enforced in Upload Store:**
- Symptoms: Clients can hold upload IDs indefinitely. No timeout removes abandoned sessions.
- Files: `src/turing_agentmemory_mcp/file_upload.py` (no TTL mechanism on _sessions)
- Trigger: Begin upload, then never complete or discard for an extended period.
- Workaround: Implement external cleanup script or restart the server periodically.

## Security Considerations

**Soft Deletion Does Not Purge Backups:**
- Risk: Deleted memories or documents with sensitive data remain in database backups and old storage volumes.
- Files: `src/turing_agentmemory_mcp/store.py` (delete operations at 1541-1603, 1783-1804 use soft delete)
- Current mitigation: Documentation notes soft deletion behavior (`docs/limitations.md` line 16).
- Recommendations: 
  - Implement hard-delete option with comprehensive audit logging
  - Document backup retention and purge procedures
  - Add retention policy enforcement at deployment level
  - Consider data anonymization instead of deletion for compliance scenarios

**Redaction Pattern Coverage:**
- Risk: Regex patterns for secret redaction may not catch all types of secrets (e.g., bearer tokens, custom API key formats, environment-specific patterns).
- Files: `src/turing_agentmemory_mcp/governance.py` (lines 12-16 define SECRET_PATTERNS)
- Current mitigation: Three patterns cover common cases (sk-* format, API key/token/secret keywords, email).
- Recommendations:
  - Audit patterns against actual usage in your organization
  - Add custom patterns via configuration
  - Consider entropy-based secret detection for improved catch rate
  - Log redaction events for audit trail

**Audit Sink May Miss Events on Crash:**
- Risk: Audit events are written asynchronously. If the server crashes between event recording and file flush, audit entries may be lost.
- Files: `src/turing_agentmemory_mcp/governance.py` (JsonlAuditSink.record at lines 76-81)
- Current mitigation: Uses file append mode with newline flushing.
- Recommendations:
  - Add explicit `handle.flush()` after each write to ensure durability
  - Consider buffered writes to a database instead of JSONL for guaranteed delivery
  - Add startup audit verification to detect gaps

**Bearer Token Visibility in Logs:**
- Risk: If bearer tokens are logged before redaction, they may appear in verbose debug logs or error messages.
- Files: `src/turing_agentmemory_mcp/provider_config.py`, `src/turing_agentmemory_mcp/server.py` (authentication setup)
- Current mitigation: Redaction is applied to stored content, but not to live HTTP headers in logs.
- Recommendations:
  - Implement HTTP client logging filters to redact Authorization headers
  - Review all logging statements for credential exposure
  - Use structured logging with field-level masking

## Performance Bottlenecks

**Single-Worker Document Ingestion:**
- Problem: Documents are processed sequentially by a single daemon thread in `DocumentIngestManager._run()`.
- Files: `src/turing_agentmemory_mcp/document_job_manager.py` (lines 273-315 thread management, 291-315 worker loop)
- Cause: Architectural choice to keep worker lifecycle simple; no thread pooling or async workers implemented.
- Improvement path: 
  - Implement thread pool executor with configurable worker count
  - Add per-worker lease management to `DocumentJobStore`
  - Update progress tracking to show per-worker status
  - Consider asyncio-based concurrency for I/O-bound operations

**Vector Search Fetches 4x Limit Before Filtering:**
- Problem: Vector search retrieves `max(limit * 4, limit)` results, then filters by status and expiry. Large result sets have high memory overhead.
- Files: `src/turing_agentmemory_mcp/store.py` (lines 654-665 in search_memory)
- Cause: Early filtering may remove too many results, requiring over-fetching to maintain final result count.
- Improvement path:
  - Push filtering to vector index search (if TuringDB supports predicate pushdown)
  - Use adaptive fetch size based on typical filter rejection rate
  - Add metrics on filter efficiency

**Memory Extraction HTTP Requests Not Batched:**
- Problem: Memory extraction calls are made one at a time for each memory item during creation.
- Files: `src/turing_agentmemory_mcp/store.py` (lines 2283-2405 in _create_memories_batch)
- Cause: HTTPMemoryExtractor interface accepts individual items; no batch mode implemented.
- Improvement path:
  - Modify HTTPMemoryExtractor to accept batch requests
  - Implement request pipelining or chunked batch submission
  - Add batch size configuration

**Chunk Embedding Requires Individual Roundtrips:**
- Problem: Each document chunk requires a separate embedding API call.
- Files: `src/turing_agentmemory_mcp/store.py` (document chunk embedding in _document_graph_queries)
- Cause: No batch embedding support in retrieval pipeline.
- Improvement path:
  - Implement batch embedding endpoints in embedding provider
  - Collect chunks and make single batch request
  - Consider client-side batching with size limits

## Fragile Areas

**Document Job State Machine:**
- Files: `src/turing_agentmemory_mcp/document_jobs.py` (entire state machine logic), `src/turing_agentmemory_mcp/document_job_manager.py` (worker logic)
- Why fragile: Complex state transitions (enqueue → running → convert → index → succeed/fail/cancel) with retry logic. SQLite-backed state can diverge if lease expires mid-operation.
- Safe modification:
  - Add comprehensive state machine tests covering all transitions
  - Document lease renewal strategy for long-running operations
  - Test failure modes: database corruption, lease timeout during conversion, cancellation during indexing
  - Add state validation on startup to detect orphaned jobs
- Test coverage: `tests/test_document_job_manager.py`, `tests/test_document_jobs.py` provide good coverage of happy path and basic error cases

**Sparse Index Outbox Replay:**
- Files: `src/turing_agentmemory_mcp/sparse_index.py` (lines 219-242 replay logic, 182-217 outbox state management)
- Why fragile: Multi-step outbox lifecycle (prepared → committed → replayed) with manual deletion. If replay crashes mid-transaction, outbox state becomes inconsistent.
- Safe modification:
  - Add idempotency checks on replay to prevent duplicate mutations
  - Test crash scenarios at each transaction boundary
  - Consider write-ahead logging or recovery journal
  - Add validation that prepared batches are either committed or discarded, never orphaned
- Test coverage: `tests/test_sparse_index.py` covers prepare/commit/replay but should add crash-recovery scenarios

**Temporal Graph Projection:**
- Files: `src/turing_agentmemory_mcp/temporal_graph.py` (entire module), `src/turing_agentmemory_mcp/store.py` (lines 2406-2507 in _plan_memory_projections)
- Why fragile: Deterministic ID generation depends on stable entity canonicalization. Small changes to canonicalization rules break existing graph links.
- Safe modification:
  - Establish schema versioning for entity canonicalization
  - Add migration path for old entity IDs when rules change
  - Test that entity merging doesn't create orphaned facts
  - Verify entity link continuity across temporal updates
- Test coverage: `tests/test_store_entity_processing.py` covers entity extraction but temporal graph projection needs dedicated tests

**Query Graph Evidence Collection:**
- Files: `src/turing_agentmemory_mcp/store.py` (lines 1161-1248 in _query_graph_evidence and related methods)
- Why fragile: Depends on consistent entity and fact naming from extraction. If extraction schema changes, graph queries may stop matching entities.
- Safe modification:
  - Add schema version checks to prevent mismatches
  - Test with adversarial entity names (special characters, long names, duplicates)
  - Verify query performance with large entity networks
  - Add fallback retrieval if graph queries return empty
- Test coverage: Graph retrieval integration tests should cover varying entity distributions

## Scaling Limits

**SQLite Single-File Limit:**
- Current capacity: Single SQLite file (AGENTMEMORY_SPARSE_PATH) serves all tenants' full-text search index. No sharding or partitioning.
- Limit: SQLite optimized for up to ~100GB; with many tenants and long content, index file grows quickly. Concurrent write contention increases with user count.
- Scaling path:
  - Migrate sparse index to dedicated full-text search engine (Elasticsearch, MeiliSearch) with per-tenant indexes
  - Implement horizontal sharding by tenant_id if staying with SQLite
  - Add read replicas for search queries separate from write path

**In-Memory Upload Sessions:**
- Current capacity: Limited by available RAM. Typical session ~1MB per active upload (metadata + streaming buffer).
- Limit: 1GB of free RAM = ~1000 concurrent uploads maximum. No eviction policy or auto-cleanup.
- Scaling path:
  - Move upload session state to SQLite for persistence and sharing across processes
  - Implement session TTL with background cleanup
  - Use external blob storage (S3) for staged files instead of local filesystem

**Single TuringDB Graph Instance:**
- Current capacity: All users' memories, documents, entities, facts, communities in one graph namespace.
- Limit: No multi-tenancy isolation at TuringDB level. Query performance degrades as graph grows to millions of nodes/edges.
- Scaling path:
  - Implement tenant-scoped graph namespaces (separate graphs per tier or customer)
  - Add graph sharding by user_identifier prefix
  - Consider temporal data archival to move old memories to separate storage

**Vector Index Memory:**
- Current capacity: Vector indexes held in TuringDB RAM. Typical: 768-1536 dims × 4 bytes × number of vectors.
- Limit: Large production instances (>10M vectors) require significant RAM or disk-backed index.
- Scaling path:
  - Monitor TuringDB memory usage and index sizes
  - Implement vector pruning (remove old or low-relevance vectors)
  - Use approximate nearest neighbor indices if available
  - Consider separate vector database (Pinecone, Qdrant, Weaviate) for massive scale

## Dependencies at Risk

**graspologic-native==1.3.1:**
- Risk: Pinned to specific version. Leiden community detection is critical to memory clustering. Breaking changes in future versions not tested.
- Impact: Security updates in dependencies cannot be applied without testing; maintenance burden if upstream bugs are found.
- Migration plan: 
  - Monitor upstream releases for critical fixes
  - Set up automated testing for new versions before upgrading
  - Consider alternative community detection libraries (igraph, python-louvain) with compatibility layer

**turingdb==1.35:**
- Risk: Tightly coupled to TuringDB's JSON wire format and query language. Upgrading requires API compatibility testing.
- Impact: Cannot easily switch to alternative graph databases. TuringDB-specific API calls throughout codebase.
- Migration plan:
  - Abstract TuringDB client behind a repository interface
  - Build adapter layer to support alternative backends (Neo4j, ArangoDB)
  - Add integration tests with multiple backends

**fastmcp>=3.4,<4:**
- Risk: Major version constraint allows breaking changes within v3. MCP protocol evolution could require tool signature changes.
- Impact: Compatibility issues if MCP client expectations diverge from library behavior.
- Migration plan:
  - Monitor fastmcp releases for breaking changes
  - Maintain compatibility shim layer for tool definitions
  - Version gate tool features by MCP protocol version

## Missing Critical Features

**Batch Embedding API:**
- Problem: Embedding provider calls are made one-at-a-time for each memory/document chunk. No batch mode.
- Blocks: Efficient large-scale ingestion and reindexing of thousands of documents.

**Multi-Worker Document Ingestion:**
- Problem: Single daemon thread processes documents sequentially.
- Blocks: Parallel document ingestion, load distribution across multiple workers, SLA compliance for document processing latency.

**Expires_at Enforcement on Reads:**
- Problem: Expiry is checked at query time but old expired records remain in storage.
- Blocks: Automatic data lifecycle management, GDPR/compliance-required purging, storage cleanup.

**Hard Delete with Audit:**
- Problem: Soft deletion only hides data; backups and old storage blocks retain sensitive information.
- Blocks: Full data removal for compliance, privacy breach remediation.

**OAuth/OIDC Authentication:**
- Problem: Static bearer tokens only. No identity provider integration.
- Blocks: Enterprise multi-user deployments, audit trail linking actions to individuals, SAML/SSO integration.

**Vector Index Versioning:**
- Problem: No versioning or snapshot support for vector indexes.
- Blocks: A/B testing embedding models, canary deployments, rollback on model quality regression.

**Observability Hooks for Custom Metrics:**
- Problem: SpanRecorder is basic; no extensible metrics system for business KPIs.
- Blocks: Custom monitoring (ingestion latency SLAs, retrieval recall metrics, cost tracking).

## Test Coverage Gaps

**Untested Area: Concurrent Multi-Tenant Queries:**
- What's not tested: Simultaneous searches/writes across multiple user_identifiers in high concurrency scenarios.
- Files: `src/turing_agentmemory_mcp/store.py` (search_memory, store_messages), TuringDB concurrency model not verified.
- Risk: Tenant data isolation bugs could leak one user's memories to another during concurrent operations.
- Priority: High

**Untested Area: Large Document Ingestion:**
- What's not tested: Documents >1GB, or ingestion of thousands of documents in sequence.
- Files: `src/turing_agentmemory_mcp/store.py` (chunk and embed logic), `src/turing_agentmemory_mcp/document_job_manager.py` (worker loop).
- Risk: Memory exhaustion, chunking edge cases (orphaned partial chunks), embedding timeout for massive batches.
- Priority: High

**Untested Area: Vector Index Rebuild with Active Queries:**
- What's not tested: Simultaneous vector rebuild and search operations.
- Files: `src/turing_agentmemory_mcp/store.py` (memory_rebuild_vector_projection at 322-328, search_memory at 599-750).
- Risk: Index corruption, stale or incomplete results during rebuild, query failures.
- Priority: Medium

**Untested Area: Sparse Index Crash Recovery:**
- What's not tested: Server crash during sparse outbox prepare/commit/replay; recovery correctness.
- Files: `src/turing_agentmemory_mcp/sparse_index.py` (prepare, commit, replay methods).
- Risk: Outbox state inconsistency, duplicate or missing mutations on recovery.
- Priority: Medium

**Untested Area: Lease Expiry and Job Timeout:**
- What's not tested: Document job lease expires mid-conversion or mid-indexing; graceful failure recovery.
- Files: `src/turing_agentmemory_mcp/document_job_manager.py` (process_next leasing at 172-196).
- Risk: Job hangs, lease contention, orphaned in-progress jobs.
- Priority: Medium

**Untested Area: Entity Extraction Failure Modes:**
- What's not tested: Memory extractor HTTP timeouts, malformed responses, rate limiting.
- Files: `src/turing_agentmemory_mcp/memory_extraction.py` (HTTPMemoryExtractor request/retry logic).
- Risk: Cascading failures from extraction provider, retry storms, incomplete memory ingestion.
- Priority: Medium

---

*Concerns audit: 2026-07-11*
