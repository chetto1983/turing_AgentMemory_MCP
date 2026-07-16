# Configuration

Compose reads `.env` from the repository root. Start from `.env.example`, keep
the resulting `.env` out of version control, and inject production secrets from
a secret manager.

## ArcadeDB

ArcadeDB is the canonical tenant store. The production MCP service does not set
`ARCADEDB_DATABASE`: `TenantRouter` derives a separate opaque database for every
exact `user_identifier`.

| Variable | Default | Purpose |
|---|---|---|
| `ARCADEDB_URL` | `http://127.0.0.1:2480` outside Compose | Shared ArcadeDB server endpoint. |
| `ARCADEDB_USER` | `root` | Privileged account used for first-use database provisioning. |
| `ARCADEDB_PASSWORD` | empty outside Compose | ArcadeDB credential. Override the documented development value for every non-loopback deployment. |
| `ARCADEDB_TIMEOUT_SECONDS` | `30` | HTTP request timeout. |
| `ARCADEDB_MAX_ATTEMPTS` | `3` | Bounded retry attempts for retryable transport/server failures. |
| `ARCADEDB_RETRY_BASE_SECONDS` | `0.5` | Client retry backoff base. |
| `ARCADEDB_COMMIT_RETRIES` | `3` | Whole-transaction retries for ArcadeDB MVCC conflicts. |
| `ARCADEDB_MEMORY_INDEX` | derived | Memory vector index name inside each tenant database. |
| `ARCADEDB_DOCUMENT_INDEX` | derived | Document vector index name inside each tenant database. |
| `ARCADEDB_ENTITY_INDEX` | derived | Entity vector index name inside each tenant database. |
| `ARCADEDB_FACT_INDEX` | derived | Fact vector index name inside each tenant database. |
| `ARCADEDB_COMMUNITY_INDEX` | derived | Community vector index name inside each tenant database. |

`ARCADEDB_DATABASE` is accepted only by the explicitly database-bound
compatibility constructor. It is not a production tenant-data fallback and
must not be added to the `turing-agentmemory-mcp` Compose service.

The image is pinned to `arcadedata/arcadedb:26.7.1`. ArcadeDB databases persist
on the `arcadedb-data` named volume.

## Physical Tenant Routing

| Variable | Compose default | Purpose |
|---|---|---|
| `AGENTMEMORY_TENANT_NAMING_KEY` | required, no fallback | Strict-base64 HMAC key containing at least 32 decoded bytes. |
| `AGENTMEMORY_TENANT_REGISTRY_PATH` | `/bertoni/data/agent-memory-tenant-registry.sqlite3` | Durable pseudonymous lifecycle registry. |
| `AGENTMEMORY_TENANT_CACHE_CAPACITY` | `128` | Maximum immutable tenant views retained by the local LRU. |
| `AGENTMEMORY_TENANT_CACHE_IDLE_TTL_SECONDS` | `900` | Idle seconds before a cached view is evicted. |
| `AGENTMEMORY_TENANT_PROVISION_ATTEMPTS` | `3` | Bounded first-use provisioning attempts. |
| `AGENTMEMORY_TENANT_PROVISION_BACKOFF_BASE_SECONDS` | `0.25` | Provisioning backoff base. |
| `AGENTMEMORY_TENANT_PROVISION_BACKOFF_MAX_SECONDS` | `2.0` | Provisioning backoff ceiling. |

Generate a dedicated key with:

```powershell
python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Inject the printed value as `AGENTMEMORY_TENANT_NAMING_KEY`. Do not reuse an
authentication token or provider credential. The key is immutable for this
milestone: changing it derives different database names, and startup rejects a
registry whose stored key fingerprint does not match. Rotation, historical
keyrings, and tenant database rename/migration require future migration tooling;
do not rotate the value in place.

Cache capacity and TTL bound only local view reuse. Eviction never drops or
closes a tenant database. Retry counts and backoffs must remain finite; raising
them increases first-request latency during an outage.

`BERTONI_HOME` (default `/bertoni`) supplies the application-state root, and
`AGENTMEMORY_GRAPH` (default `agent_memory`) supplies the graph telemetry label
and default ArcadeDB index-name prefix.

## Registry Backup and Recovery

The registry contains only opaque database names, digests, lifecycle states,
and timestamps. It never stores raw `user_identifier`, but it is required
durable control state.

- Back up the registry and ArcadeDB volumes on a coordinated schedule. Capture
  the SQLite registry with an application-consistent snapshot while the MCP is
  stopped, or with a SQLite-aware backup that includes committed WAL state.
- Back up the naming key separately in the deployment secret manager. Recovery
  requires the same key, registry, and ArcadeDB tenant databases.
- On registry corruption or loss, stop the MCP and restore a matching backup.
  Do not create a blank registry over existing tenant databases: immutable
  manifests will not reconcile with invented lifecycle timestamps.
- If a `ready` registry row points to a missing database, resolution fails
  closed. Restore that database from ArcadeDB backup and verify the manifest;
  do not delete the row or allow automatic empty reprovisioning.
- Provisioning and health diagnostics use opaque database names and key
  fingerprints. An operator with an exact identifier and the deployment key can
  compute the expected name locally without adding a reversible tenant catalog.

There is no production tenant offboarding or database-deletion API.

## Layered Health

`/health` returns `200` only when global router readiness is true. Inspect these
layers independently:

- `runtime.arcadedb`: reachability of the shared ArcadeDB server;
- `runtime.registry`: registry schema, naming version, and key fingerprint;
- `runtime.router`: configured cache bounds plus cached and in-flight counts;
- `document_ingest`: background-worker state and durable job counts.

Tenant manifest/database reconciliation occurs on tenant resolution. One broken
tenant therefore fails its own operation without making every tenant unhealthy.

## Embedding and Rerank Providers

The embedding provider must expose OpenAI-compatible `POST /v1/embeddings`; the
reranker must expose `POST /v1/rerank`.

| Variable | Default | Purpose |
|---|---|---|
| `EMBED_BASE_URL` | `http://127.0.0.1:8081` | Embedding provider URL outside Compose. |
| `EMBED_MODEL` | provider default | Model identifier. |
| `EMBED_DIMENSIONS` | provider-derived | Stored vector width; must match every tenant database. |
| `EMBED_REQUEST_DIMENSIONS` | unset | Optional dimensions field sent to the provider. |
| `EMBED_BATCH_SIZE` | `128` | Texts per request. |
| `EMBED_TIMEOUT_SECONDS` | `60` | Per-request timeout. |
| `EMBED_RETRY_BASE_SECONDS` | `0.5` | Retry backoff base. |
| `RERANK_BASE_URL` | `http://127.0.0.1:8085` | Rerank provider URL outside Compose. |
| `RERANK_MODEL` | provider default | Rerank model identifier. |
| `RERANK_CANDIDATE_LIMIT` | `50` | Maximum seeds sent to rerank. |
| `RERANK_TIMEOUT_SECONDS` | `30` | Per-request timeout. |
| `RERANK_PROVIDER_MIN_SCORE` | `0` | Minimum trusted top provider score. |
| `RERANK_THRESHOLD` | `0` | Application threshold. |
| `RERANK_BLEND` | enabled | Blend seed and provider orders with RRF. |

Provider-specific `EMBED_API_KEY` and `RERANK_API_KEY` override the shared
`PROVIDER_API_KEY`. Changing a model or vector width requires rebuilding every
affected tenant database's vector indexes; never mix vector models in one index.

## Extraction and Fusion

| Variable | Compose default | Purpose |
|---|---|---|
| `GLINER_ENABLED` | `1` | Enable entity and relationship extraction. |
| `GLINER_BACKEND` | `gliner2_http` | Extraction backend. |
| `GLINER_BASE_URL` | sidecar URL | GLiNER2 provider URL. |
| `GLINER_MODEL` | pinned ONNX model | Runtime model identity. |
| `GLINER_TIMEOUT_SECONDS` | `900` | Provider timeout. |
| `AGENTMEMORY_FUSION_ENABLED` | `1` | Enable multi-channel retrieval. |
| `AGENTMEMORY_FUSION_WEIGHTS` | built-in mapping | Complete JSON weight mapping. |
| `AGENTMEMORY_COMMUNITY_REBUILD_ON_BATCH` | `1` | Refresh communities after writes. |

Native ArcadeDB Lucene and vector channels serve retrieval. The configured
`AGENTMEMORY_SPARSE_PATH` is a transitional local compatibility artifact, not a
canonical source or a production lexical read path.

Leiden controls are `AGENTMEMORY_LEIDEN_SEED`,
`AGENTMEMORY_LEIDEN_RESOLUTION`, `AGENTMEMORY_LEIDEN_RANDOMNESS`,
`AGENTMEMORY_LEIDEN_ITERATIONS`, and
`AGENTMEMORY_LEIDEN_MAX_CLUSTER_SIZE`.

## Asynchronous Documents

| Variable | Default | Purpose |
|---|---|---|
| `AGENTMEMORY_DOCUMENT_JOB_PATH` | `/bertoni/data/agent-memory-document-jobs.sqlite3` | Durable tenant-scoped queue. |
| `AGENTMEMORY_DOCUMENT_STAGING_ROOT` | `/bertoni/data/document-ingest` | Durable staged files. |
| `AGENTMEMORY_DOCUMENT_JOB_LEASE_SECONDS` | `900` | Claim lifetime without heartbeat. |
| `AGENTMEMORY_DOCUMENT_JOB_HEARTBEAT_SECONDS` | `15` | Lease renewal cadence. |
| `AGENTMEMORY_DOCUMENT_JOB_POLL_SECONDS` | `1` | Idle worker cadence. |
| `AGENTMEMORY_DOCUMENT_JOB_MAX_ATTEMPTS` | `3` | Automatic attempt limit. |
| `AGENTMEMORY_UPLOAD_ROOT` | `/tmp/agentmemory-uploads` | Ephemeral in-progress uploads. |
| `AGENTMEMORY_UPLOAD_MAX_FILE_BYTES` | `134217728` | Declared upload limit. |
| `AGENTMEMORY_UPLOAD_CHUNK_BYTES` | `524288` | Maximum decoded upload chunk. |

Keep the job database and staging root on persistent application storage. The
upload root may be ephemeral because only committed, verified uploads become
jobs.

## Local File Pipe

The file pipe runs on the agent host, not in the remote MCP container.

| Variable | Default | Purpose |
|---|---|---|
| `AGENTMEMORY_REMOTE_MCP_URL` | `http://127.0.0.1:8095/mcp/` | Remote MCP endpoint. |
| `AGENTMEMORY_FILE_PIPE_ROOTS` | required | Host path allowlist separated by `os.pathsep`. |
| `AGENTMEMORY_FILE_PIPE_CHUNK_BYTES` | `524288` | Local transfer chunk size. |
| `AGENTMEMORY_FILE_PIPE_TIMEOUT_SECONDS` | `1800` | Transfer timeout. |

Resolved files must remain inside an allowlisted root. Symlink and `..` escapes
fail after canonical path resolution.

## Authentication, Governance, and Deferred Work

Static `AGENTMEMORY_AUTH_TOKEN(S)` authenticates an MCP client; it does not
authorize a tenant. The application gateway must bind authenticated principals
to allowed `user_identifier` values. Content-free audit and span destinations
are configured with `AGENTMEMORY_AUDIT_JSONL` and
`AGENTMEMORY_OBSERVABILITY_JSONL`.

OIDC-derived tenant identity, naming-key rotation/migration, tenant offboarding
or deletion, cross-tenant reporting, multi-server placement, and fleet-wide
schema rollout remain explicitly deferred.
