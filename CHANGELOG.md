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

## 0.1.0

Initial pre-release implementation of TuringDB-backed AgentMemory MCP.
