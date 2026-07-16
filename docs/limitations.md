# Known Limitations

This project is pre-1.0. Review these constraints before production use.

- Static MCP tokens authenticate clients but do not authorize tenant IDs. A
  gateway must bind identity to `user_identifier`.
- The reference Compose stack is single-node and starts one document worker.
- Job progress is stage-level, not per chunk or provider batch.
- Cancellation is cooperative. A blocking provider or ArcadeDB call may finish
  before the worker observes cancellation.
- PDFium extracts selectable PDF text. The default path does not provide a full
  OCR, chart, infographic, or table-understanding pipeline.
- MarkItDown conversions are in-process and format quality depends on the source
  document and its optional dependencies.
- Soft deletion removes records from active retrieval but does not erase old
  backups or storage blocks.
- Vector rebuild adds active vectors to the selected index; operational plans
  must account for stale vector cleanup or use a fresh namespace when required.
- `/health` is content-free readiness, not a complete Prometheus metrics
  endpoint.
- The provided deployment does not terminate TLS.
- Default local embedding and rerank sidecars require an NVIDIA GPU visible to
  Docker. Cloud-only deployment needs a reviewed orchestration override.
- Retrieval scores combine heterogeneous signals and are not probabilities.
- No benchmark result in this repository establishes superiority over Mem0 or
  another product without a controlled, published comparative protocol.

Near-term engineering priorities are richer extraction behind a sidecar
interface, queue age and duration metrics, tested multi-worker concurrency,
stronger principal-to-tenant policy integration, and repeatable comparative
evaluation.
