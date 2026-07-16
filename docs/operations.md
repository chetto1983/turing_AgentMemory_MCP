# Operations

## Health

Probe `GET /health`. A healthy response includes:

- `status=ok`;
- graph stage `ready=true`;
- embedding, rerank, extraction, sparse, fusion, and community identities;
- document worker `worker_running=true`;
- queue counts by state.

The endpoint contains no memory or document text. Configure the orchestrator to
restart the service when the process is unavailable, not merely when a provider
channel is degraded.

## Document Queue

Use MCP tools for queue control. Do not edit the SQLite database directly.

1. Poll `document_ingest_status` with the original tenant identifier.
2. Call `document_ingest_cancel` for unwanted queued or running work.
3. Inspect `error_code` and provider health when a job fails.
4. Correct the external condition.
5. Call `document_ingest_retry` only while the durable staged file exists.

A running worker renews its lease. If the process dies, another worker may claim
the job after lease expiry. A claim increments `attempt`; exhausted stale jobs
become `failed` rather than looping forever.

## Logs and Traces

Container logs show service lifecycle and HTTP request metadata. Enable
content-free spans with:

```text
AGENTMEMORY_OBSERVABILITY_JSONL=/bertoni/audit/spans.jsonl
AGENTMEMORY_OBSERVABILITY_STDERR=1
```

Enable audit events with:

```text
AGENTMEMORY_AUDIT_JSONL=/bertoni/audit/agentmemory.jsonl
```

Audit and span outputs omit raw memory text, query text, embeddings, provider
keys, and rerank documents. Protect metadata because identifiers and operation
timing may still be sensitive.

## Backup

Stop writers for a point-in-time archive. Back up both the MCP's own app-state
volume (`bertoni-data`) and ArcadeDB's canonical data volume (`arcadedb-data`):

```powershell
docker compose stop turing-agentmemory-mcp
docker run --rm -v turing-agentmemory-mcp_bertoni-data:/bertoni:ro -v ${PWD}:/backup python:3.14-slim sh -lc "cd /bertoni && tar czf /backup/bertoni-data-backup.tgz ."
docker compose up -d turing-agentmemory-mcp
```

The `bertoni-data` archive contains SQLite FTS, the document queue, staged
retry files, the tenant registry, and audit files stored below `/bertoni`.
ArcadeDB's own canonical graph and vector data lives in `arcadedb-data` and
needs its own backup procedure (see ArcadeDB's backup documentation).

Verify every backup by restoring it into an isolated volume and running scoped
read and search checks. An untested archive is not a recovery plan.

## Restore

Restore only into an empty, intentionally selected volume:

```powershell
docker compose down
docker volume create turing-agentmemory-mcp_bertoni-data-restored
docker run --rm -v turing-agentmemory-mcp_bertoni-data-restored:/bertoni -v ${PWD}:/backup python:3.14-slim sh -lc "cd /bertoni && tar xzf /backup/bertoni-data-backup.tgz"
```

Point a temporary Compose project at the restored volume first. Validate
tenant isolation, queued jobs, and cited document search before replacing
production storage.

## Vector Recovery

ArcadeDB's native `LSM_VECTOR` HNSW index has no server-side CSV vector
directory to quarantine or repair via CLI. If a tenant's vector projection
needs rebuilding (embedding model/dimension change, suspected drift):

1. Stop or quiesce writers and back up `bertoni-data`/`arcadedb-data`.
2. Call the `memory_rebuild_vector_projection` MCP tool for the affected
   `user_identifier`.
3. Verify dimensions, finite values, counts, and a retrieval smoke case.
4. Resume writers after readiness is healthy.

## Common Incidents

### Search returns no results after a successful document job

1. Confirm the job `result.chunk_count` is positive.
2. Search with the exact tenant and document ID.
3. Check graph and embedding stages in `/health`.
4. Check ArcadeDB for active `Chunk` records, not only a `Document` count.
5. Rebuild the tenant vector projection only after canonical chunks are
   confirmed.

### Job remains running

Check that the worker is running and the `updated_at` value advances on the
heartbeat cadence. A dead worker should release the job through lease expiry.
Do not shorten leases below measured provider latency without a faster
heartbeat.

### Provider returns 429 or 5xx

The client retries known transient statuses with bounded backoff. If the job
ultimately fails, restore provider capacity or credentials and use the job retry
tool. Do not broaden tenant scope or silently switch embedding dimensions.

### Model changed

Create new vector index names or rebuild every affected tenant. Update model
identity, dimensions, deployment manifest, and validation evidence together.

## Capacity Signals

Track queue depth, oldest queued age, job duration by stage, provider latency,
provider error rate, ArcadeDB write duration, vector load duration, process RAM,
GPU memory, and disk growth. The current health endpoint exposes queue counts
but is not a complete metrics backend.
