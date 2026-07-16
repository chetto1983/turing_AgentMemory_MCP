# Spike Conventions

Patterns established across the doc-GraphRAG spike sessions. New spikes follow
these unless the question requires otherwise.

## Stack

- **Python**, driving the real `turing_agentmemory_mcp` package (not a reimplementation).
- **Run inside a one-off container on the compose network** so sidecars resolve by
  service name (`agentmemory-gliner`/`-embed`/`-rerank`, `arcadedb`) — none are
  host-published:
  ```bash
  MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \
    -v "D:\turing_AgentMemory_MCP\.planning\spikes:/spikes" \
    --entrypoint python turing-agentmemory-mcp /spikes/NNN-name/run.py
  ```
  Add `-v ...\baseline\03-turingdb:/baseline` and `-v D:\tmp\baseline-corpus:/corpus`
  when a spike needs the frozen questions / corpus.

## Structure

- One `run.py` per spike; forensic output to `results.json` in the spike dir.
- Progress via `print(..., flush=True)`; long runs launched with `run_in_background`
  and stdout redirected to `run.log`.
- Store file-state (`turing_home`) written under the mounted spike dir (the
  container rootfs is read-only; the bind mount is writable). `home-*` is gitignored.

## Patterns

- **Isolated throwaway ArcadeDB database per spike** (`spike_*`), dropped+recreated
  each run: `dataclasses.replace(ArcadeDBClient.from_env(), database=DB)` →
  `client.create_database()` → `TuringAgentMemory(client, turing_home=..., graph=DB)`
  → `store.bootstrap()`. Never touches production tenant data.
- **Reuse real store internals** rather than re-deriving: `store.entity_processor`,
  `store.embedder`, `store.reranker`, `store._write_many`, the
  `chunk_vector_search_statement` / `chunk_lucene_search_statement` builders,
  `retrieval_fusion.fuse_rankings`, and the `real_document_benchmark_scoring`
  helpers (vendored to `_scoring/`).
- **Entity resolution: name-only** (`canonicalize_entity_name`), never `(type,name)`
  — GLiNER type-drift fragments the graph (001).
- **ArcadeDB traversal: object-notation `MATCH`** (`{type:...,as:...}.out('MENTIONS'){...}`)
  on 26.7.1; the Cypher-arrow form fails live (001).
- **Per-chunk (bounded) GLiNER**, never whole-document — the sidecar 400s on large
  payloads (003). Noop the store's ingest-time processor; use a dedicated bounded
  `HTTPGLiNEREntityProcessor` for chunk extraction.

## Tools & Libraries

- ArcadeDB `26.7.1`; native `vector.neighbors` / `vector.sparseNeighbors` /
  `vector.fuse` (RRF) all confirmed live. Graph channel = object-notation MATCH →
  Python `fuse_rankings`.
- GLiNER sidecar: `lion-ai/gliner2-base-v1-onnx` via `fast_gliner` (CPU); adequate
  for Italian (9.8 entities/chunk). Multilingual `gliner_multi-v2.1` is v2.1/
  transformers.js ONNX — NOT loadable by `fast_gliner` without a sidecar rewrite.
