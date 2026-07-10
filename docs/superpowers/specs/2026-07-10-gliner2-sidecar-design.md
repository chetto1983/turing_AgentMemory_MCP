# GLiNER2 Entity Extraction Sidecar

## Purpose

Add the revision-pinned `lion-ai/gliner2-base-v1-onnx` export of `fastino/gliner2-base-v1` to the production memory pipeline and validate it through the direct-MCP LoCoMo benchmark. The extractor must run locally, reuse a persistent model cache, preserve GPU capacity for embedding and reranking, and fail visibly if entity extraction is unavailable.

## Context

The repository already has a `GLiNEREntityProcessor`, but Compose leaves it disabled and the product image does not install a shared local inference runtime. The FastGLiNER2 ONNX runtime returns flat entity records with scores and character spans; the sidecar must preserve the existing normalized metadata contract.

The direct benchmark starts an additional MCP stdio process inside the product container. Loading the 205M model inside each MCP process would duplicate model memory. The NVIDIA RTX A2000 Laptop GPU has 4 GB and already serves Granite embedding and Qwen reranking, so GLiNER2 will run on CPU in one shared sidecar.

## Decision

Run the exact `fastino/gliner2-base-v1` ONNX export, `lion-ai/gliner2-base-v1-onnx`, in a dedicated CPU-only `agentmemory-gliner` service through FastGLiNER2. Every HTTP and stdio MCP process will call this shared service. The service loads the commit-pinned model once, exposes readiness and batch extraction endpoints, and stores model files in a named Hugging Face cache volume.

Rejected alternatives:

- In-process MCP inference duplicates the model for the HTTP server and each direct stdio benchmark process.
- GPU inference competes with the two required CUDA llama.cpp sidecars and leaves insufficient headroom on the 4 GB device.
- Silent fallback to no extraction violates the requirement that the benchmark use GLiNER2.

## Components

### FastGLiNER2 provider

Add a digest-pinned Python sidecar image that installs `fast_gliner==0.2.1`. It runs as a non-root user with a read-only root filesystem and writes only to temporary mounts and the model cache.

The provider loads `lion-ai/gliner2-base-v1-onnx` at immutable revision `5551729ccc76b30395bc9600f2348ec52a87cead` during startup on CPU. Its initial resource envelope is 4 CPUs and 4 GB RAM. It exposes only the Compose network; no host port is required.

The HTTP server runs one inference worker so it loads one model instance. FastGLiNER2 accepts one GLiNER2 text per inference, so the sidecar serializes each incoming batch internally while preserving input order. Concurrent MCP requests may queue at the provider, but they cannot create additional model copies.

The provider API has two endpoints:

- `GET /health` returns success only after the requested model is loaded. The response identifies the model and device.
- `POST /extract` accepts `texts`, `labels`, `threshold`, `include_confidence`, and `include_spans`. It calls `batch_extract_entities()` and returns one result per input text in input order.

The API rejects empty label sets, malformed payloads, and result-count mismatches. Provider failures return a non-2xx response with a concise error message and are logged without conversation content.

### MCP entity processor

Add an HTTP-backed GLiNER2 processor selected by `GLINER_BACKEND=gliner2_http`. It uses:

- `GLINER_BASE_URL=http://agentmemory-gliner:8080`
- `GLINER_MODEL=lion-ai/gliner2-base-v1-onnx`
- the existing `GLINER_LABELS`, `GLINER_THRESHOLD`, `GLINER_REDACT`, and metadata settings

The processor supports both `process(text)` and `process_many(texts)`. It flattens the official nested GLiNER2 response into the existing entity metadata contract:

```json
{
  "label": "person",
  "text": "Tim Cook",
  "start": 10,
  "end": 18,
  "score": 0.92
}
```

Normalization accepts `confidence` as the score field, validates spans against the source text, preserves input order, and applies the existing redaction behavior after normalization.

### Batch store path

`memory_store_messages` processes one MCP batch through `process_many()` before embedding. Single-message and document paths continue to use `process()` unless they already hold a natural batch.

Entity metadata remains attached to each memory. Search continues to append extracted labels and values to the lexical/rerank text. Original content remains the embedding input when redaction is disabled.

## Compose And Cache

Compose adds `agentmemory-gliner` and a persistent `agentmemory-gliner-cache` volume. The provider uses that volume for `HF_HOME`, `XDG_CACHE_HOME`, and model artifacts, so container recreation does not download the model again.

The MCP service depends on `agentmemory-gliner` with `condition: service_healthy` and enables the HTTP backend by default. Health checks use readiness cadence and a startup grace period long enough for the first cached or uncached model load. There is no benchmark wall-clock timeout. Individual failed provider calls are bounded network operations and surface as MCP tool errors instead of silently skipping extraction.

## Failure Semantics

- MCP startup waits for a healthy GLiNER2 provider.
- Runtime provider errors fail the current memory write. The store does not write graph rows or vectors for a batch that has not completed extraction.
- A provider response with the wrong number of results fails the batch before embedding.
- Benchmark monitoring checks evaluator progress, all Compose health states, GPU activity, and TuringDB corruption signals on a regular cadence.
- The interrupted `20260710T090210Z` run is diagnostic only and cannot be reported as a completed benchmark.

## Security And Privacy

All extraction stays on the local Compose network. The provider has no host port and receives no external API credentials. Logs include counts, latency, model identity, and failures, but never raw memory text or extracted values.

## Test Strategy

Implementation follows red-green-refactor in these slices:

1. Add failing normalization tests using the real GLiNER2 nested response shape, including confidence, spans, missing labels, and malformed spans.
2. Add failing HTTP processor tests for single and batch extraction, ordering, redaction, provider errors, and result-count mismatches.
3. Add failing store tests proving `memory_store_messages` uses one batch extraction call and makes no write when extraction fails.
4. Add provider contract tests for health and `/extract` without loading model weights in unit tests.
5. Add Compose hardening tests for the pinned FastGLiNER package, CPU-only service, model revision, cache volume, health dependency, non-root/read-only settings, and enabled model configuration.
6. Run an integration probe against the real cached model and verify entity metadata through a direct MCP call.

## Benchmark Validation

After implementation:

1. Build and start the full repository stack without disabling the frontend/lab service.
2. Verify Granite produces 768-dimensional embeddings on CUDA, Qwen reranking is called on CUDA, and GLiNER2 returns real entities from the CPU sidecar.
3. Run the full cached Backboard LoCoMo dataset through MCP stdio with a fresh scope: 10 conversations, 5,882 turns, and 1,540 non-adversarial questions.
4. Require zero ingest errors, zero search errors, and healthy services throughout the run.
5. Restart TuringDB and MCP, then rerun a saved conversation with `--skip-ingest` and require identical retrieval metrics.
6. Scan TuringDB logs and persisted vector indexes for corruption after restart.

The direct runner measures evidence retrieval. Mem0's published 66.88% is GPT-4.1-judged answer accuracy, so it is not a valid numerical baseline for this retrieval metric. A claim that the product beats Mem0 requires the same answer-generation and judge contract; retrieval results will be reported separately until that comparable evaluation is run.

## Acceptance Criteria

- Every product memory write uses `lion-ai/gliner2-base-v1-onnx`, the ONNX export of `fastino/gliner2-base-v1`, when GLiNER2 is enabled.
- Direct HTTP and stdio MCP processes share one cached model instance.
- Model cache survives container recreation and no benchmark restart redownloads model files.
- Entity metadata from the real model is searchable and follows the existing metadata schema.
- Embedding and reranking remain on GPU; GLiNER2 remains CPU-only.
- Unit, integration, Compose, direct-MCP, restart-persistence, and full benchmark validations pass with fresh evidence.

## References

- [ONNX model card](https://huggingface.co/lion-ai/gliner2-base-v1-onnx)
- [GLiNER2 reference implementation](https://github.com/fastino-ai/GLiNER2)
- [FastGLiNER2 runtime](https://github.com/talmago/fast_gliner)
