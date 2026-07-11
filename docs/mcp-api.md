# MCP API

All tools use MCP. Generate a machine-readable schema for the supported public
surface with:

```powershell
turing-agentmemory-mcp utcp-manual
```

## Identity Contract

Every read and write accepts `user_identifier`, defaulting to `default` for
local development. Production callers must replace that default with an
identifier derived from authenticated application identity.

The same identifier must be used for create, search, update, delete, job status,
cancel, and retry. A tenant mismatch is reported as an unknown resource instead
of exposing another tenant's state.

## Memory Tools

| Tool | Purpose |
|---|---|
| `memory_store_message` | Store one conversation episode. |
| `memory_store_messages` | Store an ordered, duplicate-safe batch. |
| `memory_get` | Fetch one active memory by ID. |
| `memory_list` | List active memories with metadata and date filters. |
| `memory_update` | Update mutable content or metadata. |
| `memory_delete` | Soft-delete one memory. |
| `memory_search` | Return ranked records with optional score explanation. |
| `memory_get_context` | Return prompt-ready bounded context. |
| `memory_add_entity` | Store a named entity record. |
| `memory_add_preference` | Store an explicit user preference. |
| `memory_add_fact` | Store a subject-predicate-object fact. |
| `memory_rebuild_communities` | Rebuild the derived Leiden projection. |
| `memory_rebuild_vector_projection` | Re-embed active canonical records. |
| `memory_runtime_status` | Return content-free pipeline readiness. |

Use stable `memory_id` values when the application has a durable source key.
Search before retrying a write after an ambiguous transport failure.

## Document Tools

| Tool | Purpose |
|---|---|
| `document_ingest_text` | Synchronously ingest text that is already normalized. |
| `document_ingest_file` | Durably enqueue a local file and return a job. |
| `document_ingest_status` | Read tenant-scoped job state and result. |
| `document_ingest_cancel` | Cancel queued work or request cooperative cancellation. |
| `document_ingest_retry` | Requeue a failed job from durable staging. |
| `document_reindex_text` | Replace one document with normalized text. |
| `document_delete` | Soft-delete a document and hide its chunks. |
| `document_search` | Search cited chunks with optional filters and explanation. |

### Asynchronous file ingest

`document_ingest_file` returns after the file is staged:

```json
{
  "job_id": "docjob_...",
  "document_id": "manual-2026-07",
  "status": "queued",
  "stage": "queued",
  "progress_current": 0,
  "progress_total": 0,
  "attempt": 0,
  "max_attempts": 3,
  "result": {}
}
```

Poll `document_ingest_status` with the returned `job_id`. Valid states are:

| Status | Meaning |
|---|---|
| `queued` | Durable and waiting for a worker or retry time. |
| `running` | Claimed under a renewable lease. |
| `cancel_requested` | The worker will stop at a safe boundary. |
| `succeeded` | Canonical ingest returned successfully; inspect `result`. |
| `failed` | Attempts ended or the input was invalid; inspect safe error fields. |
| `canceled` | Work stopped and staged bytes were removed. |

Progress is stage-level. PDF jobs report extracted page totals during indexing;
they do not expose per-embedding-request progress.

### Remote file transport

`document_ingest_file` can only read paths visible to its runtime. The local
file-pipe proxy preserves the same tool name for agent clients and streams host
bytes through these lower-level tools:

| Tool | Purpose |
|---|---|
| `document_upload_begin` | Declare filename, size, digest, scope, and metadata. |
| `document_upload_chunk` | Append one ordered base64 chunk. |
| `document_upload_commit` | Verify the upload and enqueue it durably. |
| `document_upload_abort` | Remove an incomplete upload. |

The server defaults to 512 KiB chunks and a 128 MiB file limit. Both are
configurable. The commit response is an asynchronous job, not an ingested
document.

## Search Filters

Memory search and context support session, memory type, source, tags, creation
time, update time, threshold, and result limit. Document search supports
`document_id`, source, tags, creation time, update time, threshold, and limit.

Set `explain=true` when diagnosing retrieval. Explanation fields describe
ranking signals; they are not calibrated probabilities.

## Errors and Retries

- Validation and tenant mismatches are non-retryable until the caller fixes the
  request.
- Provider responses with HTTP 429, 500, 502, 503, 504, or 529 are retried with
  bounded backoff by provider clients.
- Document jobs retry transient conversion or indexing failures up to
  `max_attempts`.
- Do not retry a successful job. Reusing the same tenant, document identity, and
  digest returns the existing idempotent job.
- Error messages in job state are intentionally safe and do not contain raw
  provider responses, tokens, or local paths.
