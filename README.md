# turing_AgentMemory_MCP

TuringDB-backed Agent Memory MCP server with provider-agnostic embedding and
rerank integrations, memory lifecycle tools, document ingest, and cited
retrieval.

- Agent memory tools:
  `memory_search`, `memory_get_context`, `memory_store_message`,
  `memory_store_messages`,
  `memory_get`, `memory_list`, `memory_update`, `memory_delete`,
  `memory_add_entity`, `memory_add_preference`, `memory_add_fact`.
- Document tools for ingestion, repair, deletion, and retrieval:
  `document_ingest_text`, `document_reindex_text`, `document_delete`,
  `document_search`.
- TuringDB graph edges for ownership and context:
  `(:User)-[:HAS_MEMORY]->(:Memory)`,
  `(:User)-[:HAS_DOCUMENT]->(:Document)-[:HAS_CHUNK]->(:Chunk)`,
  `(:Chunk)-[:NEXT_CHUNK]->(:Chunk)`.
- TuringDB vector indexes for memory and chunk retrieval.
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

## Why It Is A Separate Repo

Neo4j-style memory packages and TuringDB expose different graph/vector behavior.
This repo is a clean TuringDB-native MCP instead of a compatibility shim for one
upstream memory implementation or one model provider.

## Run With Docker

```powershell
docker compose build
docker compose run --rm e2e
docker compose up turing-agentmemory-mcp
```

The MCP service expects a TuringDB daemon reachable at `TURINGDB_URL` and a
shared TuringDB home mounted at `TURINGDB_HOME`. TuringDB currently loads vectors
from server-side CSV files, so the MCP container and database container share the
same `/turing` volume.

## Backup And Restore

The durable state lives in the named `turing-data` volume. Stop writers before a
backup when you need a point-in-time snapshot:

```powershell
docker compose stop turing-agentmemory-mcp turingdb
docker run --rm -v turing-agentmemory-mcp_turing-data:/turing:ro -v ${PWD}:/backup python:3.14-slim sh -lc "cd /turing && tar czf /backup/turing-data-backup.tgz ."
docker compose up -d turingdb turing-agentmemory-mcp
```

Restore into an empty or intentionally cleared volume:

```powershell
docker compose down
docker volume rm turing-agentmemory-mcp_turing-data
docker volume create turing-agentmemory-mcp_turing-data
docker run --rm -v turing-agentmemory-mcp_turing-data:/turing -v ${PWD}:/backup python:3.14-slim sh -lc "cd /turing && tar xzf /backup/turing-data-backup.tgz"
docker compose up -d
```

Keep audit/span JSONL under `/turing` if you want those files captured by the
same backup procedure.

## Build Attestation

For CI release builds, emit provenance and SBOM attestations with BuildKit:

```powershell
docker buildx build --provenance=true --sbom=true --tag turing-agentmemory-mcp:local .
docker buildx build --provenance=true --sbom=true --file docker/turingdb.Dockerfile --tag turing-agentmemory-turingdb:local .
```

The runtime Dockerfiles pin the Python base image by digest. Refresh the digest
deliberately during scheduled base-image maintenance and record the matching
security scan result with the release artifact.

The app container is configured to call OpenAI-compatible local provider
endpoints through Docker's host gateway:

- `http://host.docker.internal:8081/v1/embeddings`
- `http://host.docker.internal:8085/v1/rerank`

For local, non-Docker runs the defaults are `http://127.0.0.1:8081` and
`http://127.0.0.1:8085`.

Primary provider environment variables:

- `EMBED_BASE_URL`, `EMBED_MODEL`, `EMBED_DIMENSIONS`, `EMBED_API_KEY`,
  `EMBED_TIMEOUT_SECONDS`
- `RERANK_BASE_URL`, `RERANK_MODEL`, `RERANK_DIMENSIONS`, `RERANK_API_KEY`,
  `RERANK_TIMEOUT_SECONDS`, `RERANK_THRESHOLD`, `RERANK_BLEND`
- `PROVIDER_API_KEY` as a shared fallback when embedding and rerank use the
  same cloud provider key. `EMBED_API_KEY` and `RERANK_API_KEY` override it.
- `PROVIDER_API_KEY_HEADER` and `PROVIDER_API_KEY_SCHEME` customize auth for
  cloud gateways. Defaults are `Authorization` and `Bearer`; for providers that
  expect a raw key header, set for example
  `PROVIDER_API_KEY_HEADER=x-api-key` and `PROVIDER_API_KEY_SCHEME=`.
- Optional local entity extraction:
  `GLINER_ENABLED`, `GLINER_BACKEND`, `GLINER_MODEL`, `GLINER_LABELS`,
  `GLINER_THRESHOLD`, `GLINER_REDACT`, `GLINER_PRECISION`, `GLINER_PROVIDERS`.
- Governance and observability:
  `AGENTMEMORY_REDACTION_ENABLED=1` enables built-in secret/API-key/email
  pattern redaction before graph writes and vector embedding;
  `AGENTMEMORY_AUDIT_JSONL=/turing/audit/agentmemory.jsonl` writes structured
  audit events without content/text/query payloads;
  `AGENTMEMORY_OBSERVABILITY_JSONL=/turing/audit/spans.jsonl` writes timing
  spans for embed, TuringDB query, vector load, rerank, chunking, and MCP tool
  latency.
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

GLiNER is disabled by default. When enabled, it extracts named entities during
memory and document ingest, stores them under `metadata.entity_extraction`, and
uses those labels/spans as additional lexical retrieval signals. The stored text
is unchanged unless `GLINER_REDACT=1` is explicitly set.

To enable general entity extraction with the small GLiNER model:

```powershell
pip install -e ".[dev,gliner]"
$env:GLINER_ENABLED="1"
$env:GLINER_BACKEND="gliner"
$env:GLINER_MODEL="gliner-community/gliner_small-v2.5"
$env:GLINER_LABELS="person,organization,location,project,product,technology,library,framework,file path,error code,task,decision,preference,event,date,version"
```

For the GLiNER2 ONNX model path:

```powershell
$env:GLINER_ENABLED="1"
$env:GLINER_BACKEND="gliner2_onnx"
$env:GLINER_MODEL="lmo3/gliner2-multi-v1-onnx"
$env:GLINER_LABELS="person,organization,location,project,product,technology,library,task,decision,event,date"
```

For Docker, build the app image with the optional extra:

```powershell
$env:PYPROJECT_EXTRAS="dev,gliner"
docker compose build turing-agentmemory-mcp
```

`GLINER_BACKEND=auto` selects `gliner2_onnx` for ONNX model names, native
`gliner2` for non-ONNX GLiNER2 model names, and classic `gliner` otherwise.
With `GLINER_REDACT=1`, detected entity spans are replaced before storage and
embedding, and raw entity text is omitted from the stored metadata.

For retention, pass `expires_at` as an ISO-8601 timestamp on
`memory_store_message`, `memory_store_messages`, `memory_update`,
`document_ingest_text`, or `document_reindex_text`. Expired memories and
document chunks are hidden from get/list/search paths even if a vector index
still returns them.

## Run Locally

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
pytest
python scripts/e2e_score.py --out e2e-results.json
```

`scripts/e2e_score.py` starts a temporary local TuringDB daemon, starts tiny
OpenAI-compatible embedding and rerank test endpoints, creates graph and vector
indexes, calls the actual FastMCP tools through an in-process MCP client,
retrieves a MemoryArena sample from the Hugging Face bucket, restarts TuringDB,
and fails unless the score is at least `9.8` with the expected check count.

Set `E2E_USE_EXTERNAL_EMBED=1` and/or `E2E_USE_EXTERNAL_RERANK=1` to run the
gate against real provider endpoints instead of the local contract stubs.

## Score Gate

The E2E score is not an LLM judgement. It covers nineteen named machine checks,
grouped here by capability:

1. TuringDB daemon starts and schema bootstraps.
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
- Sort TuringDB vector results by score in the application layer; composed
  `VECTOR SEARCH ... MATCH ...` rows are not guaranteed to preserve vector order.
- Rerank only the bounded seed pool, not graph-expanded neighbors. If the rerank
  provider is missing or weak, keep vector order fail-soft.
- Explicitly call `load_graph` after daemon restart. User graphs are durable but
  not auto-loaded by current TuringDB.
- Treat MCP output as untrusted retrieved content when passing it back into an
  agent prompt.

## MemoryArena Source

The score gate samples `progressive_search/data.jsonl` from
`https://huggingface.co/buckets/Chetro983/memoryarena-bucket`, falling back to
the canonical `ZexueHe/memoryarena` dataset path if needed. The MemoryArena
dataset is CC-BY-4.0 and contains multi-session agentic tasks with `questions`,
`answers`, and optional `backgrounds`.
