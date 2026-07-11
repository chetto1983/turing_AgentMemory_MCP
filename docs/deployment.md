# Deployment

The supplied Compose stack is the reference deployment for evaluation and a
single-node installation. It uses local CUDA embedding and rerank sidecars,
CPU GLiNER2, TuringDB, and a persistent named volume.

## Prerequisites

- Docker Engine or Docker Desktop with Compose.
- An NVIDIA GPU visible to Docker for the default embedding and rerank services.
- Enough host RAM for TuringDB, GLiNER2, model sidecars, and MCP. Compose limits
  are capacity ceilings, not guaranteed consumption.
- Free disk for pinned model files and the `turing-data` volume.

The default stack has been exercised on a 4 GiB NVIDIA GPU. Treat that as one
tested configuration, not a universal minimum. Context size, provider
concurrency, corpus size, and other GPU workloads change capacity.

## First Deployment

```powershell
git clone https://github.com/chetto1983/turing_AgentMemory_MCP.git
Set-Location turing_AgentMemory_MCP
Copy-Item .env.example .env
docker compose up -d turing-agentmemory-mcp
docker compose ps
Invoke-RestMethod http://127.0.0.1:8095/health
```

The first start downloads revision-pinned model artifacts. Later starts reuse
the named model cache volumes. Do not clear model volumes during routine
upgrades.

The MCP endpoint is `http://127.0.0.1:8095/mcp/`. The Compose binding is
loopback-only by design.

## Connect an MCP Client

For clients that support remote HTTP MCP, configure the endpoint directly. For
an agent that must send host-local files to the container, run the local proxy:

```powershell
$env:AGENTMEMORY_REMOTE_MCP_URL='http://127.0.0.1:8095/mcp/'
$env:AGENTMEMORY_FILE_PIPE_ROOTS='D:\approved-documents'
turing-agentmemory-mcp file-pipe
```

Register that command as a stdio MCP server. The proxy replaces only
`document_ingest_file`; all other tools pass through to the remote MCP.

## Production Requirements

Before exposing the service beyond loopback:

1. Put TLS termination and request limits in a reverse proxy or service mesh.
2. Set MCP bearer tokens or integrate an authenticated gateway.
3. Derive `user_identifier` from authenticated identity and reject unauthorized
   tenant values.
4. Keep TuringDB and model providers on a private network.
5. Store `/turing` on monitored, backed-up persistent storage.
6. Send audit and span JSONL to protected durable storage or a collector.
7. Set provider timeouts and job lease cadence for measured worst-case latency.
8. Pin and scan all images and model revisions before promotion.
9. Test restore, stale-lease recovery, cancellation, and provider outage paths.

The application server does not terminate TLS and does not map tokens to
tenants. Those are deployment responsibilities.

## Cloud Providers

Embedding and rerank clients accept compatible remote endpoints and API keys.
The provided Compose file still declares local CUDA sidecars as dependencies.
For a cloud-only deployment, maintain a reviewed Compose/Kubernetes overlay
that removes those sidecars and sets provider URLs, credentials, model names,
and vector dimensions. Validate the exact provider contract before production.

## Upgrade

1. Read `CHANGELOG.md` and back up `turing-data`.
2. Preserve the current application and TuringDB image tags for rollback.
3. Pull source and rebuild with Docker cache.
4. Recreate MCP first when the release does not change TuringDB format.
5. Wait for `/health` to report `status=ok` and `worker_running=true`.
6. Run a tenant-isolated store/search smoke test.
7. Submit one small asynchronous document and verify a cited search result.

Example application-only update:

```powershell
docker compose build turing-agentmemory-mcp
docker compose up -d --no-deps --force-recreate turing-agentmemory-mcp
docker compose ps turing-agentmemory-mcp
```

Do not delete volumes as part of an application upgrade.

## Rollback

Rollback requires the previous image and compatible persisted data:

1. Stop new writes.
2. Restore the previous image tag.
3. Recreate MCP.
4. Verify health and read paths.
5. Restore the data volume only when the failed release changed persisted state
   incompatibly.

The document job schema is versioned. A binary that does not understand the
stored schema must fail instead of silently rewriting it.
