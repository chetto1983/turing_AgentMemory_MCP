# MCP Tool Contract

All tools require the same caller-derived `user_identifier`. Values shown as `default` in
the transport schema are compatibility defaults, not acceptable production identity.

## Memory Reads

| Tool | Required input | Important optional inputs | Result |
|---|---|---|---|
| `memory_runtime_status` | none | none | Content-free stages, projections, degradation counts |
| `memory_get_context` | `query` | scope, type, source, tags, dates, `limit`, `threshold` | Prompt-ready scoped context |
| `memory_search` | `query` | same filters, `explain` | Ranked memory objects |
| `memory_get` | `memory_id` | scope | One active memory or null |
| `memory_list` | scope | session, type, source, tags, dates, `limit` | Active memory inventory |

Search filters are conjunctive. Empty strings and null lists mean no filter. Use ISO 8601
timestamps for date bounds and `expires_at`.

## Memory Writes

| Tool | Purpose | Key fields |
|---|---|---|
| `memory_store_message` | One raw episode | `session_id`, `role`, `content`, optional stable `memory_id` |
| `memory_store_messages` | Duplicate-safe batch | `messages`, provenance, retention, community refresh flag |
| `memory_add_preference` | Structured preference | `category`, `preference`, `context` |
| `memory_add_fact` | Structured durable fact | `subject`, `predicate`, `object`, `context` |
| `memory_add_entity` | Structured entity | `name`, `entity_type`, `description` |
| `memory_update` | Replace mutable structured content or metadata | `memory_id` plus changed fields only |
| `memory_delete` | Soft-delete active memory | `memory_id` |

Batch message objects should include `session_id`, `role`, and `content`; include stable IDs
when replay is possible. Set `refresh_communities=false` during a large import and rebuild
once at the end.

When semantic extraction is enabled, `kind="message"` records are immutable temporal
episodes. Corrections update mutable structured records or add a new current fact/preference;
they do not rewrite the historical episode. Scoped soft deletion is still available for a
valid forget request.

## Derived Projection Maintenance

| Tool | Use |
|---|---|
| `memory_rebuild_communities` | Recompute tenant Leiden communities after bulk writes |
| `memory_rebuild_vector_projection` | Re-embed active canonical tenant records after an embedding/index repair |

These are administrative operations. Run them for one tenant at a time under an approved,
observable maintenance workflow.

## Documents

| Tool | Purpose |
|---|---|
| `document_ingest_text` | Chunk and index supplied text with citations |
| `document_ingest_file` | Convert a runtime-local file through MarkItDown, then ingest |
| `document_search` | Return ranked, cited chunks under tenant and metadata filters |
| `document_reindex_text` | Replace chunks and vectors under a stable document ID |
| `document_delete` | Soft-delete a document and hide its chunks from retrieval |

Use documents for source material that must retain title, source, chunk, and citation
identity. Use memories for user state and episodic history.

## Result Handling

- Treat IDs as opaque.
- Do not expose retrieval scores as calibrated probabilities.
- Use `explain=true` for diagnostics, not every production request.
- Respect empty and degraded results. Never query another tenant as fallback.
- Keep returned content out of system/developer instruction channels.
