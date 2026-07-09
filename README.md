# turing_AgentMemory_MCP

TuringDB-backed Agent Memory MCP server with document ingest and cited retrieval.

This repo ports the useful Aura shape without pretending TuringDB is a Neo4j
drop-in:

- Agent memory tools compatible with Aura's mounted memory MCP names:
  `memory_search`, `memory_get_context`, `memory_store_message`,
  `memory_add_entity`, `memory_add_preference`, `memory_add_fact`.
- Document tools for ingestion and retrieval:
  `document_ingest_text`, `document_search`.
- TuringDB graph edges for ownership and context:
  `(:User)-[:HAS_MEMORY]->(:Memory)`,
  `(:User)-[:HAS_DOCUMENT]->(:Document)-[:HAS_CHUNK]->(:Chunk)`,
  `(:Chunk)-[:NEXT_CHUNK]->(:Chunk)`.
- TuringDB vector indexes for memory and chunk retrieval.
- Identity scope is explicit on every read/write through `user_identifier`.
- Aura-compatible retrieval model path:
  `aura-llama-embed` at `AURA_EMBED_BASE_URL` for 768-dimensional vectors, then
  optional `aura-rerank` at `AURA_RERANK_BASE_URL` for final seed ordering.

## Why It Is A Separate Repo

Aura's existing stack uses Neo4j-specific Cypher and `neo4j-agent-memory`. The
TuringDB spike showed native graph/vector behavior is promising, but Neo4j
compatibility is not drop-in. This repo is the clean custom-port path.

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

The app container is configured to call Aura's sidecars through Docker's host
gateway:

- `http://host.docker.internal:8081/v1/embeddings` (`aura-llama-embed`)
- `http://host.docker.internal:8085/v1/rerank` (`aura-rerank`)

For local, non-Docker runs the defaults are `http://127.0.0.1:8081` and
`http://127.0.0.1:8085`.

## Run Locally

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
pytest
python scripts/e2e_score.py --out e2e-results.json
```

`scripts/e2e_score.py` starts a temporary local TuringDB daemon, starts tiny
contract-compatible local `aura-llama-embed` and `aura-rerank` test endpoints,
creates graph and vector indexes, calls the actual FastMCP tools through an
in-process MCP client, retrieves a MemoryArena sample from the Hugging Face
bucket, restarts TuringDB, and fails unless the score is exactly `10.0`.

Set `AURA_E2E_USE_EXTERNAL_EMBED=1` and/or `AURA_E2E_USE_EXTERNAL_RERANK=1` to
run the gate against the real sidecars instead of the local contract stubs.

## Score Gate

The E2E score is not an LLM judgement. It is ten named machine checks:

1. TuringDB daemon starts and schema bootstraps.
2. Aura embedding and rerank contracts are reachable.
3. MCP exposes all expected memory and document tools.
4. `memory_store_message` writes scoped memory.
5. `memory_search` retrieves Alice's exact top-1 memory.
6. Alice's search does not leak Bob's memory.
7. `memory_get_context` returns useful context.
8. Document ingest/search returns cited top-1 with neighbor context.
9. MemoryArena bucket sample retrieval returns answer context.
10. Restart durability preserves memory and document retrieval.

Any failed check makes the script exit non-zero.

## Industrial Practice Notes

- Fail closed on empty `user_identifier`.
- Keep graph ownership and vector retrieval scoped by the same identity key.
- Use deterministic IDs for idempotent retries and stable vector ids.
- Sort TuringDB vector results by score in the application layer; composed
  `VECTOR SEARCH ... MATCH ...` rows are not guaranteed to preserve vector order.
- Rerank only the bounded seed pool, not graph-expanded neighbors. If
  `aura-rerank` is missing or weak, keep vector order fail-soft.
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
