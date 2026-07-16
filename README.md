# turing_AgentMemory_MCP

ArcadeDB-backed Agent Memory MCP server with provider-agnostic embedding and
rerank integrations, memory lifecycle tools, document ingest, and cited
retrieval.

> **Status:** pre-1.0. The core pipeline is tested end to end, but production
> deployments must provide TLS and bind authenticated principals to allowed
> `user_identifier` values. Review [known limitations](docs/limitations.md)
> before deployment.

## Quick Start

The reference Compose stack uses local CUDA embedding and rerank sidecars. It
requires an NVIDIA GPU visible to Docker.

```powershell
git clone https://github.com/chetto1983/turing_AgentMemory_MCP.git
Set-Location turing_AgentMemory_MCP
Copy-Item .env.example .env
docker compose up -d turing-agentmemory-mcp
docker compose ps
Invoke-RestMethod http://127.0.0.1:8095/health
```

The MCP endpoint is `http://127.0.0.1:8095/mcp/`. The first start downloads
revision-pinned model files; later starts reuse Docker model-cache volumes.

## Documentation

- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [Configuration](docs/configuration.md)
- [MCP API](docs/mcp-api.md)
- [Operations](docs/operations.md)
- [Security](docs/security.md)
- [Performance](docs/performance.md)
- [Documentation index](docs/README.md)

- Agent memory tools:
  `memory_search`, `memory_get_context`, `memory_store_message`,
  `memory_store_messages`,
  `memory_get`, `memory_list`, `memory_update`, `memory_delete`,
  `memory_add_entity`, `memory_add_preference`, `memory_add_fact`.
- Document tools for ingestion, repair, deletion, and retrieval:
  `document_ingest_text`, `document_ingest_file`, `document_reindex_text`,
  `document_ingest_status`, `document_ingest_cancel`, `document_ingest_retry`,
  `document_delete`, `document_search`.
- ArcadeDB graph edges for ownership and context:
  `(:User)-[:HAS_MEMORY]->(:Memory)`,
  `(:User)-[:HAS_DOCUMENT]->(:Document)-[:HAS_CHUNK]->(:Chunk)`,
  `(:Chunk)-[:NEXT_CHUNK]->(:Chunk)`.
- ArcadeDB native `LSM_VECTOR` HNSW indexes for memory and chunk retrieval.
- Identity scope is explicit on every read/write through `user_identifier`.
- OpenAI-compatible retrieval provider path:
  embeddings at `EMBED_BASE_URL` for `EMBED_DIMENSIONS`-dimensional vectors,
  then optional rerank at `RERANK_BASE_URL` for final seed ordering.
- Optional GLiNER/GLiNER2 entity detection can annotate stored memories and
  documents, with redaction before graph writes and vector embedding when
  enabled.
- Optional governance hooks provide pattern redaction before persistence,
  content-free audit JSONL, and `expires_at` retention filtering on memory and
  document reads.
- Optional MCP bearer-token auth gates HTTP/SSE clients when
  `AGENTMEMORY_AUTH_TOKEN` or `AGENTMEMORY_AUTH_TOKENS` is set.
- Hybrid retrieval combines vector similarity with lexical exact token, phrase,
  ID, error-code, and file-path matching.
- PDFium extracts page-aware text from PDFs. Microsoft MarkItDown converts
  Office, spreadsheet, HTML, and other supported files before the existing
  chunking/citation pipeline.

## Why It Is A Separate Repo

Neo4j-style memory packages and ArcadeDB expose different graph/vector behavior.
This repo is a clean ArcadeDB-native MCP instead of a compatibility shim for one
upstream memory implementation or one model provider.

## Verify With Docker

```powershell
docker compose build
docker compose run --rm e2e
```

The MCP service expects an ArcadeDB server reachable at `ARCADEDB_URL`.
ArcadeDB's native `LSM_VECTOR` HNSW index and Lucene full-text serve vector and
lexical retrieval directly from the database, so there is no server-side CSV
vector loading and no shared volume requirement between the MCP and database
containers. The MCP container's own app-state (document job queue, staging,
tenant registry, audit/span JSONL) is mounted at `/bertoni` via `BERTONI_HOME`.

## Document Processing

Use `document_ingest_text` when your caller already has clean text. Use
`document_ingest_file` for files that should be staged durably, normalized, and
indexed in the background:

```json
{
  "title": "Machine Runbook",
  "path": "D:\\docs\\runbook.pdf",
  "user_identifier": "alice",
  "source": "ops",
  "tags": ["pdf", "runbook"]
}
```

The tool returns after durable staging, not after conversion and embedding. Its
response contains a `job_id`, `status=queued`, stage, attempt count, and
progress fields. Poll `document_ingest_status` with the same
`user_identifier`; terminal states are `succeeded`, `failed`, and `canceled`.
On success, `result` contains the normal document result including
`document_id`, `chunk_count`, and processing metadata.

Use `document_ingest_cancel` for queued or running work and
`document_ingest_retry` for a failed job whose staged file remains available.
Cancellation of running work is cooperative at conversion/indexing boundaries.
Jobs, leases, attempts, and staged files survive MCP process restarts under
`/bertoni/data`; workers renew their leases on a health cadence while provider or
ArcadeDB calls are in progress.

For a remote/container MCP, the local `turing_agentmemory_mcp.file_pipe` proxy
keeps the same `document_ingest_file` tool name. It allowlists host roots,
streams verified chunks through `document_upload_begin`,
`document_upload_chunk`, and `document_upload_commit`, and never requires a
host filesystem mount in the MCP container. A path passed directly to the
remote MCP must already be local to that server.

PDF processing preserves `<!-- page N -->` markers and uses 4096-character
page-aware chunks. Other supported formats use MarkItDown. Provenance is stored
under `metadata.document_processing`, including converter, original filename,
SHA-256, byte size, transport, and page counts when available.

## AgentMemory Lab

The repo includes a lightweight Memgraph Lab-inspired local console for
benchmark artifacts and graph-shaped inspection:

```powershell
docker compose up -d turing-agentmemory-mcp agentmemory-lab
```

Open `http://127.0.0.1:8096` for the Lab frontend and
`http://127.0.0.1:8095/mcp/` for the MCP HTTP endpoint. The Lab container
mounts the repo read-only at `/work`, reads benchmark JSON from
`/work/.benchmarks`, and runs with the same non-root, read-only, no-new-
privileges hardening as the MCP service.

## Backup And Restore

The MCP's own app-state (job queue, staging, tenant registry, audit/span JSONL)
lives in the named `bertoni-data` volume. ArcadeDB's canonical graph and vector
data lives separately in the `arcadedb-data` volume; back up both for a complete
recovery point, and stop writers before a point-in-time snapshot:

```powershell
docker compose stop turing-agentmemory-mcp
docker run --rm -v turing-agentmemory-mcp_bertoni-data:/bertoni:ro -v ${PWD}:/backup python:3.14-slim sh -lc "cd /bertoni && tar czf /backup/bertoni-data-backup.tgz ."
docker compose up -d turing-agentmemory-mcp
```

Restore into an empty or intentionally cleared volume:

```powershell
docker compose down
docker volume rm turing-agentmemory-mcp_bertoni-data
docker volume create turing-agentmemory-mcp_bertoni-data
docker run --rm -v turing-agentmemory-mcp_bertoni-data:/bertoni -v ${PWD}:/backup python:3.14-slim sh -lc "cd /bertoni && tar xzf /backup/bertoni-data-backup.tgz"
docker compose up -d
```

Keep audit/span JSONL under `/bertoni` if you want those files captured by the
same backup procedure. The same volume also contains the durable document job
SQLite database and staged files, so queued and retryable work is captured by
the backup.

## Vector Projection Repair

ArcadeDB's native `LSM_VECTOR` HNSW index has no server-side CSV vector
directory to quarantine, so there is no standalone repair CLI command. If a
tenant's vector projection needs rebuilding (embedding model/dimension change,
suspected index drift), call the `memory_rebuild_vector_projection` MCP tool for
the affected `user_identifier`, then verify dimensions, finite values, counts,
and a retrieval smoke case before resuming writers.

## Build Attestation

For CI release builds, emit provenance and SBOM attestations with BuildKit:

```powershell
docker buildx build --provenance=true --sbom=true --tag turing-agentmemory-mcp:local .
```

The runtime Dockerfiles pin the Python base image by digest. Refresh the digest
deliberately during scheduled base-image maintenance and record the matching
security scan result with the release artifact.

The Compose stack includes two CUDA llama.cpp GGUF sidecars inside the Compose
network:

- `agentmemory-embed` serves
  `mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M` at
  `http://agentmemory-embed:8080/v1/embeddings`.
- `agentmemory-rerank` serves
  `Mungert/Qwen3-Reranker-0.6B-GGUF` with
  `Qwen3-Reranker-0.6B-q8_0.gguf` at
  `http://agentmemory-rerank:8080/v1/rerank`.

Both sidecars use `ghcr.io/ggml-org/llama.cpp:server-cuda`, run with `gpus: all`,
`--device CUDA0`, and `--gpu-layers all`, and their health checks require both
`nvidia-smi` and llama.cpp `/health` to succeed. Model files are cached in the
`agentmemory-llama-cache` volume.

For local, non-Docker runs the defaults are `http://127.0.0.1:8081` and
`http://127.0.0.1:8085`.

Changing embedding models requires rebuilding vectors for existing memories and
document chunks. New benchmark scopes can be ingested fresh, but do not mix old
vectors and new embedding models when comparing retrieval quality.

Primary provider environment variables:

- `EMBED_BASE_URL`, `EMBED_MODEL`, `EMBED_DIMENSIONS`, `EMBED_API_KEY`,
  `EMBED_TIMEOUT_SECONDS`
- `RERANK_BASE_URL`, `RERANK_MODEL`, `RERANK_DIMENSIONS`, `RERANK_API_KEY`,
  `RERANK_TIMEOUT_SECONDS`, `RERANK_PROVIDER_MIN_SCORE`,
  `RERANK_THRESHOLD`, `RERANK_BLEND`, `RERANK_PRESERVE_SEED_MARGIN`
- `PROVIDER_API_KEY` as a shared fallback when embedding and rerank use the
  same cloud provider key. `EMBED_API_KEY` and `RERANK_API_KEY` override it.
- `PROVIDER_API_KEY_HEADER` and `PROVIDER_API_KEY_SCHEME` customize auth for
  cloud gateways. Defaults are `Authorization` and `Bearer`; for providers that
  expect a raw key header, set for example
  `PROVIDER_API_KEY_HEADER=x-api-key` and `PROVIDER_API_KEY_SCHEME=`.
- Local entity extraction:
  `GLINER_ENABLED`, `GLINER_BACKEND`, `GLINER_MODEL`, `GLINER_BASE_URL`,
  `GLINER_TIMEOUT_SECONDS`, `GLINER_LABELS`, `GLINER_THRESHOLD`, `GLINER_REDACT`,
  `GLINER_PRECISION`, `GLINER_PROVIDERS`.
- Governance and observability:
  `AGENTMEMORY_REDACTION_ENABLED=1` enables built-in secret/API-key/email
  pattern redaction before graph writes and vector embedding;
  `AGENTMEMORY_AUDIT_JSONL=/bertoni/audit/agentmemory.jsonl` writes structured
  audit events without content/text/query payloads;
  `AGENTMEMORY_OBSERVABILITY_JSONL=/bertoni/audit/spans.jsonl` writes timing
  spans for embed, ArcadeDB query, vector load, rerank, chunking, and MCP tool
  latency.
- Asynchronous document ingestion:
  `AGENTMEMORY_DOCUMENT_JOB_PATH`, `AGENTMEMORY_DOCUMENT_STAGING_ROOT`,
  `AGENTMEMORY_DOCUMENT_JOB_LEASE_SECONDS`,
  `AGENTMEMORY_DOCUMENT_JOB_HEARTBEAT_SECONDS`,
  `AGENTMEMORY_DOCUMENT_JOB_POLL_SECONDS`, and
  `AGENTMEMORY_DOCUMENT_JOB_MAX_ATTEMPTS`. Compose defaults keep the database
  and staging root on the shared `bertoni-data` volume.
- MCP auth:
  set `AGENTMEMORY_AUTH_TOKEN` for one static bearer token, or
  `AGENTMEMORY_AUTH_TOKENS=token-a,token-b` for token rotation. Optional
  `AGENTMEMORY_AUTH_CLIENT_ID`, `AGENTMEMORY_AUTH_SCOPES`, and
  `AGENTMEMORY_AUTH_REQUIRED_SCOPES` configure FastMCP static-token metadata and
  scope checks. HTTP clients send `Authorization: Bearer <token>`. Leave these
  unset for local stdio clients and unauthenticated development.
- UTCP manual export:
  optional `AGENTMEMORY_UTCP_SERVER_NAME`, `AGENTMEMORY_UTCP_MCP_COMMAND`, and
  `AGENTMEMORY_UTCP_AUTH_ENV` customize the generated Universal Tool Calling
  Protocol manual for clients or bridges that register MCP-backed UTCP tools.

The HTTP contracts remain OpenAI-compatible: `/v1/embeddings` for embedding and
`/v1/rerank` for rerank. For Claude or other cloud model gateways, point these
URLs at the compatible gateway/proxy and configure the API key/header variables
above.

By default, `RERANK_BLEND=1` combines the fused retrieval and provider orders
with reciprocal-rank fusion. Set `RERANK_BLEND=0` for guarded pure rerank
ordering; `RERANK_PRESERVE_SEED_MARGIN` (`0.05` by default) then keeps the top
hybrid seed when the rerank winner trails it by at least that margin.

Weighted RRF prioritizes direct evidence with `bm25=2.0`,
`episode_dense=1.5`, `fact_dense=0.75`, `entity_dense=0.5`, `graph=0.5`, and
`community=0.25`. Override the complete mapping with
`AGENTMEMORY_FUSION_WEIGHTS` as a JSON object when running a measured ablation.

`RERANK_PROVIDER_MIN_SCORE` defaults to `0` because GGUF ranking logits may be
valid at very small scales. It can be overridden when a
local GGUF reranker returns
provider-specific near-zero scores that should not be trusted as calibrated
relevance. If the provider's top score is below that value, AgentMemory still
calls `/v1/rerank` first, then falls back to deterministic lexical query overlap
for the final rerank order.

## UTCP Manual Export

The server can print a dependency-free UTCP manual for the current MCP tool
surface:

```powershell
turing-agentmemory-mcp utcp-manual > agentmemory.utcp.json
```

For the Docker stdio path used by Codex/Claude-style MCP clients, set the MCP
command as JSON before exporting:

```powershell
$env:AGENTMEMORY_UTCP_MCP_COMMAND='["docker.exe","compose","-f","D:\\turing_AgentMemory_MCP\\compose.yaml","run","--rm","-T","turing-agentmemory-mcp","serve","--transport","stdio"]'
turing-agentmemory-mcp utcp-manual > agentmemory.utcp.json
```

The generated tools use `call_template_type: "mcp"` with
`allowed_communication_protocols: ["mcp"]`. If `AGENTMEMORY_AUTH_TOKEN` is set,
the manual references it as `Bearer ${AGENTMEMORY_AUTH_TOKEN}` and never embeds
the token value.

A UTCP bridge can then load the exported file with a config pointed to by
`UTCP_CONFIG_FILE`, for example:

```json
{
  "manual_call_templates": [
    {
      "name": "agentmemory",
      "call_template_type": "text",
      "file_path": "D:\\turing_AgentMemory_MCP\\agentmemory.utcp.json",
      "allowed_communication_protocols": ["mcp"]
    }
  ]
}
```

The production Compose stack enables `lion-ai/gliner2-base-v1-onnx`, the ONNX
export of `fastino/gliner2-base-v1`, in the CPU-only `agentmemory-gliner`
sidecar. The FastGLiNER2 Rust runtime loads the model at its pinned Hugging Face
revision; HTTP and stdio MCP processes share that single model instance through
`GLINER_BACKEND=gliner2_http` and `GLINER_BASE_URL=http://agentmemory-gliner:8080`.
It is readiness-gated before the MCP service starts. The
`agentmemory-gliner-cache` volume persists the revision-pinned artifacts across
container recreation, and the sidecar has no host port. Embedding and reranking
retain the available GPU memory.

Entity extraction runs during memory and document ingest, stores metadata under
`metadata.entity_extraction`, and adds labels/spans to lexical retrieval. The
stored text is unchanged unless `GLINER_REDACT=1` is explicitly set; with
redaction, detected spans are replaced before storage and embedding and raw
entity text is omitted from stored metadata.

Native `gliner`, native `gliner2`, and `gliner2_onnx` backends remain available
for non-Docker development with `pip install -e ".[dev,gliner]`.

For retention, pass `expires_at` as an ISO-8601 timestamp on
`memory_store_message`, `memory_store_messages`, `memory_update`,
`document_ingest_text`, or `document_reindex_text`. Expired memories and
document chunks are hidden from get/list/search paths even if a vector index
still returns them.

Retrieval filters are available on both lifecycle and search paths. Memory
list/search/context can filter by `session_id`, `memory_types`, `source`,
`tags`, `created_after`, `created_before`, `updated_after`, and
`updated_before`. Document search can filter by `document_id`, `source`, `tags`,
and the same created/updated timestamp ranges.

## Run Locally

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
pytest
python scripts/e2e_score.py --out e2e-results.json
```

`scripts/e2e_score.py` connects to the already-running `arcadedb` Compose
service (a dedicated, drop-and-recreate database), starts tiny
OpenAI-compatible embedding and rerank test endpoints, creates graph and vector
indexes, calls the actual FastMCP tools through an in-process MCP client,
retrieves a MemoryArena sample from the Hugging Face bucket, restarts the
ArcadeDB service, and fails unless the score is at least `9.8` with the
expected check count.

`scripts/real_document_benchmark.py` measures real-document memory/document
retrieval quality (MRR, recall, latency) against a corpus of PDFs through the
live MCP tools; results are written as machine-readable JSON under
`.benchmarks/`.

Set `E2E_USE_EXTERNAL_EMBED=1` and/or `E2E_USE_EXTERNAL_RERANK=1` to run the
gate against real provider endpoints instead of the local contract stubs.

## Score Gate

The E2E score is not an LLM judgement. It covers nineteen named machine checks,
grouped here by capability:

1. ArcadeDB is reachable and schema bootstraps.
2. Embedding and rerank contracts are reachable.
3. MCP exposes all expected memory and document tools.
4. `memory_store_message` writes scoped memory.
5. `memory_store_messages` writes duplicate-safe searchable batches.
6. `memory_search` retrieves Alice's exact top-1 memory.
7. Alice's search does not leak Bob's memory.
8. Hybrid memory search explains lexical exact-code matching.
9. `memory_get_context` returns useful context.
10. Memory lifecycle list/get/update/delete behavior works.
11. Document ingest/search returns cited top-1 with neighbor context.
12. Hybrid document search explains lexical exact-code matching.
13. Document idempotency, reindex, delete, and restart durability work.
14. MemoryArena bucket sample retrieval returns answer context.

Any failed check makes the script exit non-zero.

## Industrial Practice Notes

- Fail closed on empty `user_identifier`.
- Keep graph ownership and vector retrieval scoped by the same identity key.
- Use deterministic IDs for idempotent retries and stable vector ids.
- Sort ArcadeDB vector results by score in the application layer; composed
  `VECTOR SEARCH ... MATCH ...` rows are not guaranteed to preserve vector order.
- Rerank only the bounded seed pool, not graph-expanded neighbors. If the rerank
  provider is missing or weak, keep vector order fail-soft.
- Call `reconnect()` after a backend restart to re-probe reachability. Tenant
  databases are durable across restarts; there is no separate graph-load step.
- Treat MCP output as untrusted retrieved content when passing it back into an
  agent prompt.

## MemoryArena Source

The score gate samples `progressive_search/data.jsonl` from
`https://huggingface.co/buckets/Chetro983/memoryarena-bucket`, falling back to
the canonical `ZexueHe/memoryarena` dataset path if needed. The MemoryArena
dataset is CC-BY-4.0 and contains multi-session agentic tasks with `questions`,
`answers`, and optional `backgrounds`.
