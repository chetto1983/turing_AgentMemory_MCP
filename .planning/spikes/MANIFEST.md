# Spike Manifest

## Idea

Give **document retrieval** an entity/graph channel on ArcadeDB, closing the
doc↔memory GraphRAG asymmetry. Today `search_documents` (`store_documents.py`)
runs only native dense (`vectorNeighbors`) + native lexical (`SEARCH_INDEX`),
merged by `blend_hybrid_score` → `_rerank_documents` — **no entity/graph
channel**, and it doesn't even use the `retrieval_fusion` RRF layer that
`memory_search` uses. Entities/`MENTIONS` edges exist only for `Memory`
vertices; document `Chunk`s never get entity extraction. This spike produces a
**findings-only verdict** on whether/how to add a graph channel to document
retrieval on the ArcadeDB substrate. Any build is gated on the verdict. Runs
**parallel to Phase 7** (TuringDB removal) and must not touch the irreversible cut.

## Requirements

Design decisions that emerge from spiking (non-negotiable for a real build).

- Reuse the existing `EntityProcessor` (GLiNER HTTP sidecar) — no new extractor.
- Reuse `stable_id()` for entity/edge identity (invariant #3); tenant-scope every
  query on `user_identifier` (invariant #1).
- Keep the throwaway spike isolated in its own ArcadeDB database
  (`spike_docgraphrag`); never touch production tenant data.
- **Entity resolution must not key on the GLiNER type label** (001): GLiNER
  type-drift on a shared surface (`arcadedb` → product/library/framework) splits
  one entity into many and collapses the cross-doc bridge (3× fewer bridges).
  Resolve name-normalized at minimum; ideally an enrichment/disambiguation pass.
  Note: the *existing memory* graph (`temporal_graph.py:137`) has this latent bug too.
- **Use ArcadeDB object-notation `MATCH`** on 26.7.1 (`{type:...,as:...}.out(){...}`);
  the ArcadeDB GraphRAG doc's Cypher-arrow syntax fails live (001).
- **The graph channel must be MULTI-HOP** (002): single-hop co-mention ≈ the
  existing Lucene channel; the lift comes from N-hop entity bridges reaching
  lexically-invisible answers. Expansion needs hop decay / per-hop caps / tuned
  RRF weight or it injects noise.
- **Native `vector.fuse` (RRF) is available on 26.7.1** (002) for dense+sparse
  server-side fusion; the graph channel stays a MATCH feeding the Python RRF.
- Every channel fused via `fuse_rankings` must agree on candidate identity
  `(candidate_id, kind, content, source_memory_id, ...)` (002).

## Spikes

| # | Name | Type | Validates | Verdict | Tags |
|---|------|------|-----------|---------|------|
| 001 | doc-entity-graph-substrate | standard | Chunk→Entity `MENTIONS` extraction + cross-doc SQL traversal on live ArcadeDB | ✓ VALIDATED | graph, arcadedb, gliner |
| 002 | doc-graph-channel-fusion | standard | Entity-anchored graph channel fused into document_search (Python RRF vs native `vector.fuse`) | ✓ VALIDATED | fusion, retrieval, arcadedb |
| 003 | doc-graphrag-quality-signal | standard | Lift vs the dense+lexical+rerank baseline on the frozen 60-question yardstick | PENDING | benchmark, quality |
