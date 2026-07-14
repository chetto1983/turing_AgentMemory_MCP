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
AGENTMEMORY_OBSERVABILITY_JSONL=/turing/audit/spans.jsonl
AGENTMEMORY_OBSERVABILITY_STDERR=1
```

Enable audit events with:

```text
AGENTMEMORY_AUDIT_JSONL=/turing/audit/agentmemory.jsonl
```

Audit and span outputs omit raw memory text, query text, embeddings, provider
keys, and rerank documents. Protect metadata because identifiers and operation
timing may still be sensitive.

## Backup

Stop writers for a point-in-time archive:

```powershell
docker compose stop turing-agentmemory-mcp turingdb
docker run --rm -v turing-agentmemory-mcp_turing-data:/turing:ro -v ${PWD}:/backup python:3.14-slim sh -lc "cd /turing && tar czf /backup/turing-data-backup.tgz ."
docker compose up -d turingdb turing-agentmemory-mcp
```

The archive contains TuringDB data, vectors, SQLite FTS, the document queue,
staged retry files, and audit files stored below `/turing`.

Verify every backup by restoring it into an isolated volume and running scoped
read and search checks. An untested archive is not a recovery plan.

## Restore

Restore only into an empty, intentionally selected volume:

```powershell
docker compose down
docker volume create turing-agentmemory-mcp_turing-data-restored
docker run --rm -v turing-agentmemory-mcp_turing-data-restored:/turing -v ${PWD}:/backup python:3.14-slim sh -lc "cd /turing && tar xzf /backup/turing-data-backup.tgz"
```

Point a temporary Compose project at the restored volume first. Validate graph
load, vector dimensions, tenant isolation, queued jobs, and cited document
search before replacing production storage.

## Vector Recovery

If TuringDB reports vector corruption:

1. Stop writers and back up `/turing`.
2. Run the repair command without `--apply`.
3. Review the reported source and quarantine paths.
4. Apply the repair in a maintenance window.
5. Restart TuringDB and MCP.
6. Rebuild active tenant vector projections.

```powershell
docker compose run --rm -T turing-agentmemory-mcp repair-vector-index --turing-home /turing
docker compose run --rm -T turing-agentmemory-mcp repair-vector-index --turing-home /turing --apply
```

The command quarantines the vector directory. It does not delete canonical
graph data.

## Common Incidents

### Search returns no results after a successful document job

1. Confirm the job `result.chunk_count` is positive.
2. Search with the exact tenant and document ID.
3. Check graph and embedding stages in `/health`.
4. Check TuringDB for active `Chunk` records, not only a `Document` count.
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
provider error rate, TuringDB write duration, vector load duration, process RAM,
GPU memory, and disk growth. The current health endpoint exposes queue counts
but is not a complete metrics backend.
