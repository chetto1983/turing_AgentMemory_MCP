# Codebase Concerns

**Analysis Date:** 2026-07-16

## Tech Debt

**Unbounded Document Transaction Ingest**

- Issue: Each document commits as a single managed `begin`/`command`/`commit-retry-N` ArcadeDB transaction with no batch splitting. A large document could cause unbounded memory growth during graph payload submission.
- Files: `src/turing_agentmemory_mcp/store_core.py:8–24`, `src/turing_agentmemory_mcp/store_documents.py`
- Impact: Document ingest latency grows linearly with size; no backpressure if payload exceeds ArcadeDB or network limits. G220 PDF (~30 MB, 841 chunks) required 114 seconds total.
- Design decision: Documented as accepted for this milestone (CHANGELOG.md, Removed section). Splitting would require per-chunk "searchable only after fully committed" status guard, judged riskier than documenting unbounded-per-document.
- Fix approach: Post-stabilization task: implement bounded batching with interim status guards or fallback to streaming/chunked commit if provider load becomes observable.

**SQLite-FTS5 Single-Writer Constraint**

- Issue: `SparseIndex` (`src/turing_agentmemory_mcp/sparse_index.py`) uses SQLite FTS5, which does not support concurrent writes. Only one thread may call `upsert_many` or `delete_many` at a time.
- Files: `src/turing_agentmemory_mcp/sparse_index.py:127–145`
- Impact: Contention under concurrent document indexing. The reference Compose stack starts one document worker, so this is not yet visible; multi-worker deployments may experience queueing on lexical index writes.
- Mitigation: `SparseIndex` is gated by `fusion_enabled`; disabling fusion eliminates this bottleneck. Fallback to ArcadeDB's native Lucene full-text is always available.
- Fix approach: Use a dedicated SQLite write thread or switch to a multi-writer full-text index backend if concurrent lexical indexing becomes critical.

## Known Bugs

**Cascading Heartbeat Expiry During Long Provider Calls**

- Symptoms: A document job's lease may expire during a blocking provider call (conversion, embedding) if the heartbeat thread cannot renew fast enough, leaving the job orphaned mid-ingest.
- Files: `src/turing_agentmemory_mcp/document_job_manager.py:214–232`, `src/turing_agentmemory_mcp/document_job_manager.py:317–338`
- Trigger: Long-running provider (e.g., embedding a large document, slow rerank endpoint, network latency spike), default lease 900s, default heartbeat 15s. If provider takes >900s and heartbeat thread stalls, lease expires before next renewal.
- Workaround: Increase `AGENTMEMORY_DOCUMENT_JOB_LEASE_SECONDS` or reduce provider timeout when heartbeat renewal is slow.
- Permanent fix: Detect provider-blocking scenarios and extend lease proactively or implement provider-agnostic timeouts that fail cleanly rather than orphaning jobs.

**Staged File Cleanup on Process Crash**

- Symptoms: If the MCP process crashes during the indexing stage (after staging but before job succeeds/cancels), staged files remain on disk indefinitely.
- Files: `src/turing_agentmemory_mcp/document_job_manager.py:340–346`
- Trigger: Process OOM, unhandled exception, Docker stop-kill sequence during `ingest_document_text`.
- Workaround: Manual cleanup of `${AGENTMEMORY_DOCUMENT_STAGING_ROOT}` after restart or implement a startup scan that discards orphaned staging directories older than 2x lease time.
- Fix approach: On MCP startup, scan staging root and purge directories for jobs older than lease expiry + grace period.

## Security Considerations

**Tenant Isolation Relies on Application-Level Predicates**

- Risk: Physical database separation (one ArcadeDB database per tenant) provides first defense. But every query in `store_memory_queries.py`, `store_documents_queries.py`, etc. requires explicit `WHERE user_identifier = :identifier` predicate. One missed predicate in a future change could cross-tenant read.
- Files: `src/turing_agentmemory_mcp/store_memory_queries.py`, `src/turing_agentmemory_mcp/store_documents_queries.py`, `src/turing_agentmemory_mcp/store_memory_write.py`, `src/turing_agentmemory_mcp/store_memory_read.py`, `src/turing_agentmemory_mcp/store_documents.py`
- Current mitigation: `test_arcadedb_tenant_isolation.py` runs concurrent three-tenant workloads and foreign-ID attacks; `_require_user` guard rejects foreign identifiers before any database call. Static catalog test (`test_every_public_store_method_requires_user`) fails if a public method omits the guard.
- Recommendations: 
  1. Audit every SQL statement for mandatory `user_identifier` predicate at review time.
  2. Use a database role/proxy that drops all queries without the `user_identifier` WHERE clause.
  3. Implement query logging that flags any statement matching `FROM.*WHERE` without an identifier predicate.

**No Built-In Per-Tenant Rate Limiting or Quota**

- Risk: No API-level rate limiting on memory adds, document ingests, or search queries. A single tenant could exhaust disk (large vector index), CPU (expensive searches), or GPU (embedding batches).
- Files: `src/turing_agentmemory_mcp/server.py`, `src/turing_agentmemory_mcp/server_memory_tools.py`, `src/turing_agentmemory_mcp/server_document_tools.py`
- Impact: Denial of service (DoS) against other tenants in a shared deployment.
- Current mitigation: MCP bearer tokens are static; true auth/quota binding is a deployment responsibility (see `docs/security.md`).
- Recommendations:
  1. Deploy a reverse proxy with per-tenant rate limiting (e.g., 100 requests/min per tenant).
  2. Track ingested memory count and document bytes per tenant, enforce limits.
  3. Implement search query cost estimation and reject expensive queries.

**Soft Deletion Not Secure Erasure**

- Risk: `expires_at` filtering and soft deletes hide records from active retrieval but do NOT erase old backups, storage blocks, or WAL files. GDPR right-to-be-forgotten or privacy compliance may require cryptographic erasure or overwrite.
- Files: `src/turing_agentmemory_mcp/governance.py`, `src/turing_agentmemory_mcp/store_core.py`
- Documented in `docs/security.md:49–62` but easy to misinterpret.
- Recommendations:
  1. Use full-disk encryption (LUKS, BitLocker, cloud-provider KMS) for volumes holding `bertoni-data` and `arcadedb-data`.
  2. Implement cryptographic key rotation and per-tenant key isolation if compliance requires it.
  3. Document backup retention policy and test restore procedures against that policy.

## Performance Bottlenecks

**Large Document Unbounded Graph Payloads**

- Problem: A 30 MB PDF with 841 chunks commits one transaction with unbounded `CREATE VERTEX Chunk ... CREATE EDGE NEXT_CHUNK ...` statements. ArcadeDB HTTP payloads have no explicit size limit; a very large document could saturate network or trigger HTTP 413 (Payload Too Large).
- Files: `src/turing_agentmemory_mcp/store_documents.py`, `src/turing_agentmemory_mcp/document_processing.py`
- Cause: No chunking of graph statements; entire document graph batched in one `_write_many` transaction.
- Performance baseline: G220 operating instructions (30 MB, 830 pages) indexing stage observed ~24s; Italian Constitution (3.4 MB, 506 pages) ~11s.
- Improvement path:
  1. Measure payload size before submission; log warnings above 10 MB.
  2. Implement request-size limiting in ArcadeDB HTTP client (set Content-Length limits).
  3. Split multi-chunk documents into batches bounded by byte size or statement count, with retry logic.

**Entity Extraction Unbounded on Conversational Memory**

- Problem: `memory_extraction.py` calls GLiNER2 extraction on memory batches during `store_messages` or community rebuild. No input-size limit before calling the remote extractor. A single large-text memory entry could create a large entity graph, impacting search quality and ranking latency.
- Files: `src/turing_agentmemory_mcp/memory_extraction.py`, `src/turing_agentmemory_mcp/entity_extraction.py`
- Cause: Batch size for entity extraction not configurable; depends on provider latency and GPU memory.
- Improvement path:
  1. Add `GLINER_MAX_TEXT_CHARS_PER_CALL` limit (e.g., 4096 chars) and split oversized texts before calling extraction.
  2. Log entity count per memory and warn if exceeds threshold.
  3. Implement per-tenant entity cap during rebuild.

**Leiden Community Detection Scaling**

- Problem: Community detection is O(n^1.5) for entity count n. `max_cluster_size=100` caps final clusters, but intermediate processing on large entity graphs (thousands of entities) can cause jitter.
- Files: `src/turing_agentmemory_mcp/community_detection.py:100`, `src/turing_agentmemory_mcp/community_detection.py:174–181`
- Cause: Leiden algorithm is built into `graspologic-native`; no intermediate progress or cancellation.
- Improvement path:
  1. Profile Leiden on real entity graphs; measure CPU/RAM vs. entity count.
  2. Implement optional tiered detection (e.g., sample entities under high load).
  3. Add per-tenant entity-rebuild rate limiting to stagger expensive operations.

## Fragile Areas

**MVCC Conflict Retry Loop Complexity**

- Files: `src/turing_agentmemory_mcp/arcadedb_client.py:132–168`
- Why fragile: A commit that loses an optimistic-concurrency race must redo the entire begin→body→commit cycle because ArcadeDB invalidates the session on failure. The retry detection logic (`is_mvcc_conflict`) checks for a specific string marker; any change to ArcadeDB's error message breaks silent detection. The transport layer intentionally does NOT retry MVCC conflicts (see lines 315–318) to avoid masking them behind "Transaction not begun" errors.
- Safe modification:
  1. Never modify retry logic without testing against live `arcadedata/arcadedb:26.7.1` container.
  2. Run `tests/test_arcadedb_client.py` and `tests/test_arcadedb_client_transport.py` after any change.
  3. Do not skip the MVCC conflict guard in the transport-retry loop.
- Test coverage: `test_arcadedb_client_transport.py` tests retryable vs. non-retryable status codes.

**TenantRouter Immutable View Caching**

- Files: `src/turing_agentmemory_mcp/tenant_router.py`
- Why fragile: Tenant store views are cached by `TenantRouter` with an LRU and TTL (hardcoded parameters). Under concurrent first-use of many tenants, the cache may evict an active tenant's view, forcing re-resolve and re-fetch of the manifest. The cache is not thread-safe across Python processes (each MCP process has its own cache); a distributed deployment may see view cache misses and redundant provisioning.
- Safe modification:
  1. Any change to cache size or TTL requires load-testing with concurrent tenant count matching target deployment.
  2. Run `test_arcadedb_tenant_isolation.py` with first-use race scenarios.
  3. Monitor cache hit/miss ratio in production; add metrics if deploying multi-process.
- Test coverage: Concurrent tenant provisioning tested; TTL eviction under load not measured.

**Document Job Lease and Heartbeat Interplay**

- Files: `src/turing_agentmemory_mcp/document_job_manager.py:174–287`, `src/turing_agentmemory_mcp/document_job_manager.py:317–338`, `src/turing_agentmemory_mcp/document_jobs.py`
- Why fragile: Heartbeat thread runs asynchronously and renews the lease; if the main thread blocks on a provider call, the heartbeat may not get CPU time to renew before lease expires. No explicit coordination between heartbeat and main processing loop; both rely on `jobs.renew_lease` idempotency.
- Safe modification:
  1. Test with providers that have known latency variance (e.g., embedding provider with 30–60s variance).
  2. Set heartbeat cadence significantly shorter than expected provider p99 latency.
  3. Log heartbeat renewal failures; do not silently ignore ValueError at line 329–330.
- Test coverage: Basic heartbeat renewal tested; provider latency variance and lease expiry under high load not measured.

**Tenant Identity Validation Exact Unicode**

- Files: `src/turing_agentmemory_mcp/tenant_identity.py:29–43`
- Why fragile: User identifiers are validated for control characters, surrogates, and exact byte-level whitespace. But Unicode normalization (NFC vs. NFD vs. NFKC) is not applied. Two visually identical emails `user@example.com` and `user@example.com` (different Unicode representation) would map to different tenants.
- Safe modification:
  1. Document that user_identifier must be exact Unicode (no normalization applied).
  2. Apply normalization in the deployment authentication layer if needed.
  3. Run `test_arcadedb_tenant_isolation.py` with normalization test cases.
- Test coverage: Control character and whitespace rejection tested; Unicode normalization not tested.

## Scaling Limits

**Single Document Worker per Compose Stack**

- Current capacity: One background worker thread per MCP process, one lease holder per job, default 900s lease.
- Limit: Document jobs are serialized; at least one job blocks on a provider call at a time. Multiple jobs cannot embed/extract concurrently without spawning multiple MCP processes.
- Scaling path:
  1. Run multiple MCP instances with shared `AGENTMEMORY_DOCUMENT_JOB_PATH` SQLite (same document queue).
  2. Each instance starts its own worker; they compete for leases via SQLite.
  3. Requires testing `stale-lease-recovery` at scale and monitoring lease collision rate.

**Linear Search Complexity**

- Current: All memory and document search use linear scans over candidates followed by ranking; no pagination or result limits in the MCP API. The store enforces a `limit` parameter (default 20).
- Limit: Search latency grows linearly with total memory/document count per tenant. No indexing beyond native ArcadeDB vector/Lucene.
- Scaling path:
  1. Implement hybrid sparse/dense two-pass retrieval: sparse pass returns top-N lexical candidates, dense pass reranks.
  2. Add pagination (offset/limit) to search APIs.
  3. Cache frequently-retrieved communities or entity neighborhoods.

**Vector Index Rebuild on Model Change**

- Current: Changing embedding model requires manual call to `memory_rebuild_vector_projection` per tenant.
- Limit: No automated detection that provider model/dimensions have changed. Operator must identify drift, run rebuild per tenant, and verify dimensions.
- Scaling path:
  1. Track provider identity and dimensions in manifest; fail if mismatch at query time.
  2. Implement tenant-scoped vector rebuild batching to stagger expensive operations.
  3. Add health check that verifies vector dimensions match provider dimensions.

## Dependencies at Risk

**ArcadeDB 26.7.1 (Sole Canonical Backend)**

- Risk: This milestone chose ArcadeDB as the sole backend (removed TuringDB coexistence). ArcadeDB 26.7.1 is enterprise-grade but less battle-tested than TuringDB in agent memory workloads. If ArcadeDB performance or stability issues emerge, no quick fallback exists.
- Impact: Data corruption, slow vector search, or MVCC conflict storms would require emergency data migration.
- Migration plan:
  1. Export canonical tenant data via UTCP (`scripts/utcp.py`).
  2. Migrate to alternative graph store (e.g., TigerGraph, Neo4j).
  3. Rebuild vector indexes from canonical text.
- Current mitigation: E2E score gate (`scripts/e2e_score.py`) validates correctness on every commit. Performance benchmarks capture baseline (`baseline/03-turingdb/`).

**GPU-Mandatory Embedding/Rerank Sidecars (Default Compose)**

- Risk: Default Compose stack uses local CUDA sidecars (`docker/llama.cpp.Dockerfile`) for embedding and reranking. No GPU = no local model inference, no fallback to CPU.
- Impact: CI runners without GPU cannot run full stack tests. Production deployments on CPU-only hardware cannot use default Compose.
- Mitigation: Cloud-only deployment can swap provider URLs/credentials (see `docs/deployment.md:70–76`). Test suite has stub providers (`e2e_score_stubs.py`).
- Fix approach:
  1. Document CPU-only deployment procedure and test it in CI.
  2. Provide alternative Compose overlay without GPU dependencies.
  3. Measure CPU fallback latency and publish as separate benchmark.

**graspologic-native 1.3.1 (Leiden Community Detection)**

- Risk: Leiden algorithm is a compiled dependency from graspologic. No pure-Python fallback if the library becomes unmaintained or incompatible.
- Impact: Community detection becomes unavailable or requires major refactor.
- Mitigation: Community detection is optional (gated by `fusion_enabled`); disabling it reduces dependency risk.
- Fix approach: Keep local copy of Leiden algorithm reference or implement pure-Python version for low-entity-count fallback.

**MarkItDown 0.1.6–0.2 (Document Format Conversion)**

- Risk: MarkItDown handles Microsoft Office, spreadsheets, HTML, and other formats. No guarantee that all format combinations are tested or supported in production.
- Impact: Document conversion may fail on edge-case file formats; users cannot index certain document types.
- Mitigation: `document_processing.py` wraps conversion errors and marks jobs as non-retryable if conversion fails.
- Fix approach: Run corpus-wide format testing before accepting new document types. Log and monitor conversion failure rates by format.

## Missing Critical Features

**No Multi-Worker Concurrency Testing**

- What's missing: The reference Compose stack starts one document worker. The code supports multiple workers (each claims leases, renews via heartbeat), but concurrent multi-worker races have not been tested at scale.
- Blocks: Scaling document ingestion beyond one concurrent job; high-throughput production deployments.
- Priority: High. Documented as "near-term engineering priority" in `docs/limitations.md:29`.

**No Operator Deletion API**

- What's missing: No `memory_delete_all` or `document_delete_all` tool. Operator must manually delete individual memories or documents to comply with user deletion requests.
- Blocks: Compliance with user deletion at scale; audit trail for deletion requests.
- Priority: Medium. Documented in `docs/architecture.md:173` as explicitly deferred.

**No Tenant Offboarding or Database Deletion**

- What's missing: No API to permanently delete a tenant's database after user deletion. The database persists after all records are soft-deleted.
- Blocks: True data erasure compliance; cleanup of abandoned tenants.
- Priority: Medium-Low. Documented as explicitly deferred this milestone.

**No Cross-Tenant Reporting or Analytics**

- What's missing: No tool to query across tenants (e.g., total memory count, search latency percentiles, embedding model usage). Only per-tenant health is available.
- Blocks: Operator visibility into deployment-wide trends; capacity planning.
- Priority: Low. Documented as deferred.

## Test Coverage Gaps

**Multi-Worker Lease Contention**

- What's not tested: Multiple document workers claiming and renewing leases on the same job queue. Current stack runs one worker; concurrent worker races are not measured.
- Files: `src/turing_agentmemory_mcp/document_jobs.py`, `tests/test_document_jobs.py`
- Risk: Lease collision, missed heartbeats, or job skipping under high concurrency.
- Priority: High. Needed for production multi-worker deployment.

**Provider Latency Variance Under Load**

- What's not tested: Heartbeat renewal when provider calls have high variance (e.g., embedding provider p99 = 60s, p50 = 2s). Lease expiry under real provider conditions.
- Files: `src/turing_agentmemory_mcp/document_job_manager.py`
- Risk: Jobs silently orphaned when provider latency spikes.
- Priority: High. Needed to validate default heartbeat cadence.

**ArcadeDB MVCC Conflict Storm**

- What's not tested: High concurrent write load that triggers repeated MVCC conflicts. Current retry logic is bounded by `ARCADEDB_COMMIT_RETRIES` (default 3); repeated conflicts could exhaust retries.
- Files: `src/turing_agentmemory_mcp/arcadedb_client.py:132–168`
- Risk: Transient write failures under peak load; incomplete document ingestion.
- Priority: Medium. Needed to validate scalability assumptions.

**Large Tenant Entity Graph Performance**

- What's not tested: Community detection and entity extraction on a tenant with 10,000+ entities. Current max_cluster_size = 100; Leiden clustering time and memory growth unknown.
- Files: `src/turing_agentmemory_mcp/community_detection.py`
- Risk: Rebuild blocking or OOM on high-entity-count tenants.
- Priority: Medium. Needed to validate entity graph scaling assumptions.

---

*Concerns audit: 2026-07-16*
