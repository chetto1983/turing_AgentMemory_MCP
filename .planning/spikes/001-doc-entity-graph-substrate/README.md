---
spike: 001
name: doc-entity-graph-substrate
type: standard
validates: "Given entities link only to Memory vertices, when we extract entities over document chunks and write (:Chunk)-[:MENTIONS]->(:Entity) edges, then a tenant-scoped ArcadeDB traversal reaches co-mentioning chunks across documents"
verdict: VALIDATED
related: []
tags: [graph, arcadedb, gliner, entity-resolution]
---

# Spike 001: doc-entity-graph-substrate

## What This Validates

GIVEN the ArcadeDB store where entities link only to `Memory` vertices (document
`Chunk`s never get entity extraction), WHEN we extract entities over document
chunks with the existing GLiNER `EntityProcessor` and write
`(:Chunk)-[:MENTIONS]->(:Entity)` edges, THEN a bound, tenant-scoped ArcadeDB SQL
traversal reaches co-mentioning chunks **across different documents** — the
missing substrate for a document graph channel.

## Research

**Reference studied — `D:\tmp\agent-memory` (neo4j-labs `neo4j_agent_memory`):**
graph-native peer. Relevant modules: `extraction/` (GLiNER/LLM/spaCy pipelines),
`enrichment/` (background entity **canonicalization/disambiguation** — the piece
this repo lacks), `graph/client.py`, `memory/consolidation.py`, `reasoning.py`.
Takeaway: its value-add over raw extraction is the enrichment/resolution layer.

**Reference studied — ArcadeDB GraphRAG use-case doc**
(https://docs.arcadedb.com/arcadedb/use-cases/graph-rag): recommends exactly the
model this spike builds — `Chunk` (dense `embedding` + sparse `tokens/weights`)
`-[:MENTIONS]->` `Entity`, plus `RELATES_TO` entity-entity edges. It shows a
native `` `vector.fuse`(neighbors, sparseNeighbors, {fusion:'RRF', groupBy:'source'}) ``
(v26.5.1+) and a multi-hop entity-bridge in **Cypher-arrow** `MATCH` syntax.
⚠ **The doc's arrow syntax does NOT run on our pinned 26.7.1** (confirmed below) —
its examples are aspirational / a newer build.

**In-repo grounding:** `search_documents` (`store_documents.py:450`) runs dense
`vectorNeighbors` + Lucene `SEARCH_INDEX` merged by `blend_hybrid_score` →
`_rerank_documents`; no entity channel, no RRF. `MENTIONS` is `("Memory","Entity")`
only (`store_memory_queries.py:47`). Memory entity ids are
`stable_id("ent", user, entity_type, canonical_name)` (`temporal_graph.py:137`).

## How to Run

Runs inside a one-off container on the compose network (reaches
`agentmemory-gliner` / `agentmemory-embed` / `arcadedb` by service name). Requires
the stack up (`docker compose up -d`).

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \
  -v "D:\turing_AgentMemory_MCP\.planning\spikes:/spikes" \
  --entrypoint python turing-agentmemory-mcp \
  /spikes/001-doc-entity-graph-substrate/run.py
```

Isolated throwaway `spike_docgraphrag` database (dropped+recreated each run). No
production tenant data, no `src/` touched.

## What to Expect

A `results.json` forensic log: 3 chunks ingested, entities extracted per chunk,
Entity vertices + `MENTIONS` edges written, a cross-document co-mention traversal,
the canonicalization comparison, and the live MATCH-syntax probe.

## Investigation Trail

1. **First run — cross-doc reach = 0 (surprise).** Edges wrote and the
   object-notation traversal executed, but reached no other document. Root cause:
   GLiNER assigns **different types to the same surface across contexts** —
   `arcadedb` came back `product` (doc A), `library` (doc C), `framework` (doc B).
   My entity id keyed on `(type, name)`, splitting one entity into three, so no two
   chunks shared an entity id.
2. **Discovery — production has the same keying.** `temporal_graph.py:137` keys
   memory entity ids on `(entity_type, canonical_name)` too. So GLiNER type-drift
   fragments the *memory* graph as well; it just hurts less there because memory
   search fuses many channels. For a document graph channel — whose whole value is
   cross-chunk entity bridging — this is directly destructive.
3. **Second run — name-only resolution.** Re-keyed entity ids on
   `canonicalize_entity_name(text)` only (reusing the real normalizer). Cross-doc
   traversal lit up: the seed chunk reached both other documents. Quantified the
   gap: `(type,name)` → 1 cross-doc bridge; name-only → 3 bridges (**3×**).
4. **MATCH syntax resolved live.** The ArcadeDB-doc's Cypher-arrow
   `MATCH (c:Chunk)-[:MENTIONS]->...` fails with a SQL syntax error on 26.7.1; only
   Phase-4 D-05's object-notation `MATCH {type:..., as:...}.out('MENTIONS'){...}`
   works.

## Results

**VERDICT: VALIDATED.** The substrate is real and cheap: reusing the existing
`EntityProcessor` + `stable_id` + the store's `_write_many`, document chunks get
`(:Chunk)-[:MENTIONS]->(:Entity)` edges and a tenant-scoped object-notation
traversal reaches co-mentioning chunks across documents.

- 3 chunks → 10 Entity vertices, 14 `MENTIONS` edges.
- Seed chunk (`arcadedb-overview`) → reached `fusion-retrieval` + `gliner-extraction`
  via shared entities (`arcadedb`, `turing agentmemory server`, `gliner`).
- Canonicalization: `(type,name)` = 13 entities / **1** bridge; name-only = 10
  entities / **3** bridges.
- MATCH: object-notation ✓ (2 rows); Cypher-arrow ✗ (SQL syntax error).

**Findings that shape the build (carry to 002/003 and the verdict):**

1. **Entity resolution is the crux, not the graph mechanics.** A doc graph channel
   needs resolution better than the current `(type,name)` keying — at minimum
   name-normalized, ideally an enrichment/disambiguation pass (cf. neo4j
   `agent-memory/enrichment/`). This is a genuine build requirement, and it's a
   latent weakness in the *existing memory* graph too (fix-on-touch candidate).
2. **Use object-notation `MATCH`**, not the ArcadeDB-doc's Cypher-arrow form, on
   26.7.1.
3. **Ingest must extract chunk entities.** `_create_document` writes only
   `HAS_CHUNK`/`NEXT_CHUNK`; a build adds a chunk-entity extraction + `MENTIONS`
   step (batched `process_many`, mirroring memory ingest).

**Depth caveat (honest):** controlled 3-doc set for a crisp, assertable mechanism
test — real GLiNER + embed + ArcadeDB providers, but not the real corpus. Quality
lift on the real 12-doc / 60-question yardstick is Spike 003's job.
