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

### Removed

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
