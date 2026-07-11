# Operations and Recovery

## Health Cadence

Monitor readiness by condition, not by killing long work at an arbitrary elapsed timeout.
At a healthy cadence, record:

- MCP and TuringDB container state, health, and restart count;
- `memory_runtime_status` stages and projection degradation counts;
- embedding, graph query, fusion, and rerank latency;
- GPU utilization and memory for enabled model sidecars;
- document queue counts, lease heartbeat, stage progress, attempts, and errors;
- ingest/search progress and error counts for long benchmark jobs.

Use bounded request deadlines to prevent a single hung provider call. A request deadline is
not permission to terminate an otherwise healthy end-to-end benchmark.

## Degraded Retrieval

When runtime status reports a degraded channel:

1. Preserve the status response and content-free observability evidence.
2. Confirm canonical graph reads and healthy retrieval channels.
3. Avoid destructive repair while writers are active.
4. Tell the caller when missing channels materially reduce confidence.
5. Repair only the affected derived projection.

Do not silently return another tenant, stale cache, or fabricated memory to make the request
appear successful.

## Vector Projection Repair

Embedding model or dimension changes require a vector rebuild. Never mix old and new vector
spaces in a quality comparison.

1. Stop or quiesce writers.
2. Take a durable-state backup.
3. Inspect and quarantine only the corrupt vector directory when required.
4. Start the database and MCP service.
5. Call `memory_rebuild_vector_projection` per tenant.
6. Verify dimensions, finite values, counts, and retrieval smoke cases.
7. Resume writers after readiness is healthy.

## Community Rebuild

Leiden communities are derived. During bulk ingest, disable per-batch refresh and call
`memory_rebuild_communities` once per tenant. A community failure must not corrupt canonical
memories; expose it as degraded derived state.

## Provider Changes

A reranker swap does not require re-embedding, but it does require a fixed-corpus ranking
ablation. An embedding swap requires a fresh index namespace or complete projection rebuild.
Compare MRR/recall on identical questions, filters, candidate depth, and evaluator logic.

Cache model assets and container layers. Verify actual provider/model identity in runtime
status and logs before accepting benchmark results.

## Production Acceptance

Require all of the following before rollout:

- strict tenant-isolation tests;
- duplicate-safe write replay;
- update/delete/expiry visibility tests;
- secret-redaction and content-free audit tests;
- healthy and degraded runtime tests;
- direct MCP end-to-end ingest, retrieve, correct, and forget flow;
- measured retrieval quality and latency against a pinned baseline;
- backup and restore rehearsal.
