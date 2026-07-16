---
spike: 002
name: doc-graph-channel-fusion
type: standard
validates: "Given the 001 MENTIONS substrate, when an entity-anchored graph-expansion channel is fused with dense+lexical via the real RRF, then document search surfaces an answer chunk that dense+lexical miss"
verdict: VALIDATED
related: [001]
tags: [fusion, retrieval, arcadedb, graphrag]
---

# Spike 002: doc-graph-channel-fusion

## What This Validates

GIVEN the 001 `(:Chunk)-[:MENTIONS]->(:Entity)` substrate, WHEN an entity-anchored
graph-expansion channel is added beside dense (`vectorNeighbors`) + lexical
(Lucene) and fused through the real `retrieval_fusion.fuse_rankings` RRF, THEN
document search returns graph-expanded chunks and can surface an answer chunk that
dense+lexical miss.

**Sharper hypothesis carried from 001:** a *single-hop* co-mention channel ≈ the
lexical channel (a shared single-token entity is also a shared lexical token). The
graph channel's distinct value is *multi-hop* bridging. This spike tests both.

## Research

- Reuses the real `fuse_rankings` (weighted RRF, `retrieval_fusion.py`) — the same
  fusion `memory_search` uses — and the real channel query builders
  `chunk_vector_search_statement` / `chunk_lucene_search_statement`.
- ArcadeDB GraphRAG doc's native `` `vector.fuse`(neighbors, sparseNeighbors,
  {fusion:'RRF'}) `` (claimed v26.5.1+) — probed live here.

## How to Run

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \
  -v "D:\turing_AgentMemory_MCP\.planning\spikes:/spikes" \
  --entrypoint python turing-agentmemory-mcp \
  /spikes/002-doc-graph-channel-fusion/run.py
```

Isolated throwaway `spike_docgraphrag2` database. Query: *"Which nearest neighbor
library does GraphRAG rely on?"*; the answer (`jvector-detail`) shares **no** query
vocabulary and is reachable only by hopping graphrag → arcadedb → jvector.

## Investigation Trail

1. **First run crashed** — `fuse_rankings` enforces identical candidate identity
   across channels; my dense/lexical channels carried chunk *text* as `content`
   while the graph channel carried the doc id → "conflicting candidate identity".
   Fix: consistent `content`/`source_memory_id` per chunk id across channels. This
   is a real contract to respect in a build (every channel must agree on identity).
2. **Second run — hypothesis confirmed.** BFS trace reached the answer at hop 3;
   the answer is invisible to Lucene and mid-pack for dense; the graph channel
   promotes it.

## Results

**VERDICT: VALIDATED** — fusion mechanics work and the *multi-hop* graph channel
adds genuine value.

Answer doc (`jvector-detail`) rank by channel/fusion:

| Channel / fusion | Answer rank |
|---|---|
| lexical (Lucene) only | **miss** (−1) |
| dense only | 4 |
| graph 3-hop only | 3 |
| fused dense+lexical | 4 |
| **fused dense+lexical+graph** | **3** |

- **Multi-hop reaches lexically-invisible answers.** BFS: `graphrag-intro` (h1) →
  `arcadedb-engine` (h2) → `jvector-detail` (h3). Lucene missed it entirely; the
  graph channel surfaced it and fusion promoted 4→3.
- **Single-hop ≈ lexical** (confirmed): the 1-hop co-mention set overlapped the
  lexical result (`graphrag-intro`). Single-hop co-mention adds little over the
  existing Lucene channel; the lift is in the hops.
- **Native `vector.fuse` (RRF) runs on 26.7.1** (`available: true`, 5 rows).
  Phase-4 deferred it by choice — it's an available lever for dense+sparse server-
  side fusion (it does NOT do the graph channel; that stays a MATCH + Python RRF).

**Findings that shape the build (carry to 003 and the verdict):**

1. **Value lives in multi-hop, not single-hop.** A build's graph channel should be
   an N-hop entity-bridge expansion, not a 1-hop co-mention (which the Lucene
   channel already largely covers).
2. **Expansion needs governance.** Unbounded 3-hop BFS pulls broad candidate sets;
   a build needs hop decay, per-hop caps, tuned RRF weight, and the 001
   name-normalized entity resolution — otherwise the channel injects noise.
3. **Native `vector.fuse` is a real option** for the dense+sparse portion; the
   graph channel remains an object-notation MATCH feeding the Python RRF.
4. **Channel-identity contract:** every fused channel must agree on
   `(candidate_id, kind, content, source_memory_id, ...)` — a build integrating a
   new channel into `fuse_rankings` must honor this.

**Honest caveat:** the scenario is constructed so multi-hop wins (small corpus,
answer engineered to be lexically invisible). Whether such multi-hop-reachable
answers actually occur in the real 60-question yardstick — and how often — is
exactly Spike 003's measurement. 002 proves the channel *can* help; 003 measures
*whether it does* on the real corpus.
