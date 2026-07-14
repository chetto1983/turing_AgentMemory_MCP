# Configuration

Compose reads `.env` from the repository root. Start from `.env.example` and
keep secrets out of version control. Environment variables override application
defaults.

## TuringDB

| Variable | Default | Purpose |
|---|---|---|
| `TURINGDB_URL` | `http://127.0.0.1:6666` outside Compose | TuringDB HTTP endpoint. |
| `TURINGDB_AUTH_TOKEN` | unset | Optional TuringDB credential. |
| `TURINGDB_HOME` | `/turing` | Shared graph, vector, staging, and projection root. |
| `TURINGDB_GRAPH` | `agent_memory` | Canonical graph name. |
| `TURINGDB_MEMORY_INDEX` | derived from graph and dimensions | Base memory vector index. |
| `TURINGDB_DOCUMENT_INDEX` | derived from graph and dimensions | Base document vector index. |
| `TURINGDB_ENTITY_INDEX` | derived from graph and dimensions | Base entity vector index. |
| `TURINGDB_FACT_INDEX` | derived from graph and dimensions | Base fact vector index. |
| `TURINGDB_COMMUNITY_INDEX` | derived from graph and dimensions | Base community vector index. |

Tenant-specific vector index names are derived from the base name and a stable
hash of `user_identifier`.

## Embedding Provider

The provider must expose an OpenAI-compatible `POST /v1/embeddings` endpoint.

| Variable | Default | Purpose |
|---|---|---|
| `EMBED_BASE_URL` | `http://127.0.0.1:8081` | Provider base URL outside Compose. |
| `EMBED_MODEL` | provider default | Model identifier sent to the endpoint. |
| `EMBED_DIMENSIONS` | provider-derived | Stored vector width; must match all indexes. |
| `EMBED_REQUEST_DIMENSIONS` | unset | Optional dimensions field sent to the provider. |
| `EMBED_BATCH_SIZE` | `128` | Texts per provider request. |
| `EMBED_TIMEOUT_SECONDS` | `60` | Per-request timeout. |
| `EMBED_RETRY_BASE_SECONDS` | `0.5` | Retry backoff base. |
| `EMBED_API_KEY` | unset | Provider-specific credential. |
| `EMBED_API_KEY_HEADER` | shared provider setting | Credential header override. |
| `EMBED_API_KEY_SCHEME` | shared provider setting | Credential scheme override. |

Changing model or dimensions requires a fresh vector namespace or a complete
projection rebuild. Do not query indexes containing vectors from two models.

## Rerank Provider

The provider must expose `POST /v1/rerank`.

| Variable | Default | Purpose |
|---|---|---|
| `RERANK_BASE_URL` | `http://127.0.0.1:8085` | Provider base URL outside Compose. |
| `RERANK_MODEL` | provider default | Model identifier. |
| `RERANK_CANDIDATE_LIMIT` | `50` | Maximum seeds sent to rerank. |
| `RERANK_TIMEOUT_SECONDS` | `30` | Per-request timeout. |
| `RERANK_PROVIDER_MIN_SCORE` | `0` | Minimum trusted top provider score. |
| `RERANK_THRESHOLD` | `0` | Application threshold for reranked results. |
| `RERANK_BLEND` | enabled | Blend seed and provider orders with RRF. |
| `RERANK_PRESERVE_SEED_MARGIN` | `0.05` | Guard for pure rerank mode. |
| `RERANK_API_KEY` | unset | Provider-specific credential. |

`PROVIDER_API_KEY`, `PROVIDER_API_KEY_HEADER`, and
`PROVIDER_API_KEY_SCHEME` provide shared fallbacks. Provider-specific values
take precedence.

## Extraction and Fusion

| Variable | Compose default | Purpose |
|---|---|---|
| `GLINER_ENABLED` | `1` | Enable entity and relation extraction. |
| `GLINER_BACKEND` | `gliner2_http` | Extraction backend. |
| `GLINER_BASE_URL` | sidecar URL | GLiNER2 provider URL. |
| `GLINER_MODEL` | pinned ONNX model | Runtime model identity. |
| `GLINER_TIMEOUT_SECONDS` | `900` | Provider timeout. |
| `GLINER_THRESHOLD` | model default | Extraction confidence threshold. |
| `GLINER_REDACT` | disabled | Replace detected spans before storage. |
| `AGENTMEMORY_FUSION_ENABLED` | `1` | Enable multi-channel retrieval. |
| `AGENTMEMORY_SPARSE_PATH` | `/turing/data/agent-memory-fts.sqlite3` | FTS5 projection path. |
| `AGENTMEMORY_FUSION_WEIGHTS` | built-in mapping | Complete JSON weight mapping. |
| `AGENTMEMORY_COMMUNITY_REBUILD_ON_BATCH` | `1` | Refresh communities after batches. |

Leiden controls are `AGENTMEMORY_LEIDEN_SEED`,
`AGENTMEMORY_LEIDEN_RESOLUTION`, `AGENTMEMORY_LEIDEN_RANDOMNESS`,
`AGENTMEMORY_LEIDEN_ITERATIONS`, and
`AGENTMEMORY_LEIDEN_MAX_CLUSTER_SIZE`.

## Asynchronous Documents

| Variable | Default | Purpose |
|---|---|---|
| `AGENTMEMORY_DOCUMENT_JOB_PATH` | `$TURINGDB_HOME/data/agent-memory-document-jobs.sqlite3` | Durable queue. |
| `AGENTMEMORY_DOCUMENT_STAGING_ROOT` | `$TURINGDB_HOME/data/document-ingest` | Durable staged files. |
| `AGENTMEMORY_DOCUMENT_JOB_LEASE_SECONDS` | `900` | Claim lifetime without heartbeat. |
| `AGENTMEMORY_DOCUMENT_JOB_HEARTBEAT_SECONDS` | `15` | Lease renewal cadence. |
| `AGENTMEMORY_DOCUMENT_JOB_POLL_SECONDS` | `1` | Idle worker cadence. |
| `AGENTMEMORY_DOCUMENT_JOB_MAX_ATTEMPTS` | `3` | Automatic attempt limit. |
| `AGENTMEMORY_UPLOAD_ROOT` | `/tmp/agentmemory-uploads` | Ephemeral in-progress uploads. |
| `AGENTMEMORY_UPLOAD_MAX_FILE_BYTES` | `134217728` | Declared upload limit. |
| `AGENTMEMORY_UPLOAD_CHUNK_BYTES` | `524288` | Maximum decoded upload chunk. |

Keep the queue and staging root on persistent storage. The upload root may stay
ephemeral because only committed, verified uploads become jobs.

## Local File Pipe

The file pipe runs on the agent host, not in the remote MCP container.

| Variable | Default | Purpose |
|---|---|---|
| `AGENTMEMORY_REMOTE_MCP_URL` | `http://127.0.0.1:8095/mcp/` | Remote MCP endpoint. |
| `AGENTMEMORY_FILE_PIPE_ROOTS` | required | Host path allowlist, separated by `os.pathsep`. |
| `AGENTMEMORY_FILE_PIPE_CHUNK_BYTES` | `524288` | Local transfer chunk size. |
| `AGENTMEMORY_FILE_PIPE_TIMEOUT_SECONDS` | `1800` | MCP transport timeout for transfers. |

Resolved files must remain inside an allowlisted root. Symlink and `..`
escapes fail after canonical path resolution.

## Authentication and Governance

| Variable | Default | Purpose |
|---|---|---|
| `AGENTMEMORY_AUTH_TOKEN` | unset | One static MCP bearer token. |
| `AGENTMEMORY_AUTH_TOKENS` | unset | Comma- or space-separated rotation set. |
| `AGENTMEMORY_AUTH_CLIENT_ID` | `agentmemory-client` | Static-token client metadata. |
| `AGENTMEMORY_AUTH_SCOPES` | unset | Scopes assigned to tokens. |
| `AGENTMEMORY_AUTH_REQUIRED_SCOPES` | unset | Required scopes. |
| `AGENTMEMORY_REDACTION_ENABLED` | disabled | Built-in pattern redaction. |
| `AGENTMEMORY_AUDIT_JSONL` | unset | Content-free audit event file. |
| `AGENTMEMORY_OBSERVABILITY_JSONL` | unset | Span output file. |
| `AGENTMEMORY_OBSERVABILITY_STDERR` | disabled | Emit spans to stderr. |

Authentication is not tenant authorization. Bind authenticated principals to
allowed `user_identifier` values in the application gateway.
