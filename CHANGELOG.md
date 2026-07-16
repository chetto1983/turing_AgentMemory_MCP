# Changelog

All notable changes are recorded here. The project follows semantic versioning
after the first stable release; pre-1.0 releases may change interfaces.

## Unreleased

### Added

- Durable asynchronous document ingestion with SQLite job state, staging,
  idempotency, renewable leases, cancellation, retry, and safe progress.
- Transparent MCP file pipe for allowlisted host files.
- Page-aware PDFium extraction for born-digital PDFs.
- Bounded batched embedding, graph writes, and vector loads for large documents.
- Fused retrieval across dense, BM25, entity, fact, graph, community, and rerank
  channels.
- Native Leiden community detection and GLiNER2 sidecar integration.
- UTCP manual export, runtime health, audit hooks, and content-free spans.
- Vector quarantine repair command and local AgentMemory Lab.
- Committed TuringDB retrieval baseline (`baseline/03-turingdb/`): a
  reproducible ARC-01 yardstick with provider config, corpus manifest, frozen
  questions, per-check e2e results with inflation caveats, and a git snapshot
  SHA, captured before the ArcadeDB port begins so Phase 6 (ARC-09) can diff
  meet-or-exceed correctness and retrieval quality against a fixed baseline.
- ARC-07 physical tenant isolation: exact validated tenant identifiers now map
  through keyed HMAC identities to separate manifest-verified ArcadeDB
  databases, with ready-last provisioning and bounded immutable-view caching.
- ARC-07 gap closure: `tenant_binding.py`'s `TenantBinding` recomputes the same
  keyed HMAC-SHA-256 digest used to name a tenant's database and verifies a
  caller-supplied `user_identifier` against it in constant time, with a
  fail-closed `TenantBindingError` that names only the opaque database name.

### Changed

- `_StoreCore._require_user` is now instance-bound: a store returned by
  `TenantRouter.resolve` carries a `TenantBinding` and rejects a
  valid-but-foreign `user_identifier` before any client call, span, or audit
  event; unbound stores (`StaticStoreResolver`, direct construction) keep
  delegating to the central exact validator unchanged (ARC-07).
- ARC-07 gap closure: all 18 public store methods that accept
  `user_identifier` (`add_entity`/`add_preference`/`add_fact`,
  `update_memory`/`delete_memory`, `get_context`/`delete_document` were
  previously unguarded) now call the binding-aware guard as their first
  statement, and the six span-wrapped methods (`store_message`,
  `store_messages`, `ingest_document_text`, `reindex_document_text`,
  `search_documents`, `search_memory`) run the guard before opening their
  span, so a rejected foreign identifier emits zero telemetry. A static
  catalog test (`test_every_public_store_method_requires_user`) fails if a
  future public method omits the guard.
- ARC-07 gap closure: `_StoreCore._span` and `_audit` now sanitize every
  attribute dict and audit event through `tenant_binding.sanitize_tenant_attributes`
  before it reaches the shared observer or audit sink -- store spans and
  audit events now carry the opaque `tenant_database` correlation instead of
  the raw `user_identifier`, and an unbound store omits tenant identity
  entirely. **Consumer-visible contract change:** audit events no longer
  include a `user_identifier` field; a caller that previously read it should
  read the opaque `tenant_database` correlation instead (present only for a
  bound store). `operation`, `resource_type`, `resource_id`, `success`, and
  `details` are unchanged.

### Fixed

- Submit dependent TuringDB graph batches separately so later chunk batches can
  match the document and previous chunk nodes.
- Tolerate missing `NEXT_CHUNK` schema during retrieval.
- Retry transient embedding and rerank provider failures.
- Prevent oversized document graph payloads from returning HTTP 413.
- Preserve warning visibility while filtering only explicitly understood
  third-party deprecations.

### Security

- Tenant-scope all job status, cancel, retry, upload, memory, and document
  operations.
- Verify upload size, order, chunk limit, and SHA-256 before durable staging.
- Remove staged bytes after success or cancellation and sanitize persisted job
  errors.
- TEST-05 live isolation coverage: concurrent three-tenant workloads, foreign-ID
  attacks, first-use races, cache eviction, missing-ready failure, a real
  ArcadeDB restart, and asynchronous file ingestion prove physical plus
  predicate isolation against the pinned server image.

### Removed

- Removed the `turingdb==1.35` dependency and all TuringDB-only code and
  tooling: the `turingdb`/`turingdb-volume-init` Compose services and
  `docker/turingdb.Dockerfile`; the legacy `benchmark.py`/`benchmark_stages.py`/
  `benchmark_memoryarena.py`/`benchmark_schema.py`/`agent_quality_eval.py`
  harness cluster (superseded by `scripts/e2e_score.py` and
  `scripts/real_document_benchmark.py`) and their CLI wiring/tests; the
  `repair-vector-index` command and `admin_repair.py` (TuringDB CSV-vector
  quarantine has no ArcadeDB equivalent -- use `memory_rebuild_vector_projection`
  instead); the `sys.modules["turingdb"]` Windows test-import stub. Renamed the
  live application-state paths for forward-consistency with the coming product
  rebrand: `TURINGDB_HOME` to `BERTONI_HOME` (default `/turing` to `/bertoni`,
  Compose volume `turing-data` to `bertoni-data`), `TURINGDB_GRAPH` to
  `AGENTMEMORY_GRAPH`, and `TURINGDB_EMBED_DIMENSIONS` to `EMBED_DIMENSIONS`.
  Deleted the dead `TURINGDB_URL` and `TURINGDB_{MEMORY,DOCUMENT,ENTITY,FACT,
  COMMUNITY}_INDEX` connection variables (superseded by `ARCADEDB_*`). ArcadeDB
  is now the sole canonical backend; CLAUDE.md's invariants are updated
  accordingly.
- Retired the legacy SQLite-FTS5 outbox's write path (`prepare`/`commit_batch`/
  `replay`/`discard_prepared`) from memory writes, memory updates/deletes, and
  community rebuild -- lexical retrieval was already fully served by the
  native sparse-vector and Lucene channels, so the outbox write calls were
  dead weight (and, on a fresh deployment volume with fusion enabled, an
  unhandled crash) rather than a second source of truth.
- Removed the dead `AGENTMEMORY_DOCUMENT_GRAPH_BATCH_CHUNKS`/`_BYTES`
  transaction-size knobs (and the `document_graph_batch_chunks`/
  `document_graph_batch_bytes` constructor params they wired into) -- a
  TuringDB-era workaround for a submit-before-match visibility gap that does
  not exist under ArcadeDB's single-managed-transaction ingest (D-08); the
  values were validated and stored but never consulted, so every document was
  already committed as one unbounded transaction regardless of the setting.
  Wiring them into real batch splitting would have opened a partial-
  document-visible-mid-ingest window with no status guard to close it, which
  was judged riskier than documenting unbounded-per-document as the accepted
  design for this milestone.

## 0.1.0

Initial pre-release implementation of TuringDB-backed AgentMemory MCP.
