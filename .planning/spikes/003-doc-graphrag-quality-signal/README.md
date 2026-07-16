---
spike: 003
name: doc-graphrag-quality-signal
type: standard
validates: "Given a runnable prototype and the frozen-question yardstick, when the graph channel is compared to the dense+lexical baseline on the Italian subset, then the lift is quantified"
verdict: PARTIAL
related: [001, 002]
tags: [benchmark, quality, gliner, italian]
---

# Spike 003: doc-graphrag-quality-signal

## What This Validates

GIVEN a runnable 001+002 prototype and the frozen-question yardstick, WHEN the
graph channel is compared to the dense+lexical baseline on the entity-rich Italian
subset, THEN we quantify the lift the graph channel adds.

Isolation: each frozen question is scored under three configs, all reranked by the
real BGE reranker over the same pool, so the ONLY difference between the two fused
configs is the graph channel:
- `production` = `store.search_documents` (dense+lexical blend → rerank)
- `fused_base` = `fuse_rankings(dense, lexical)` → rerank
- `fused_graph` = `fuse_rankings(dense, lexical, multi_hop_graph)` → rerank

Fast-signal subset (targeted, per user decision): 3 capped Italian docs
(`Corso Base Robot.docx`, ML-`wikipedia`, one `normattiva` decree), 167 chunks,
15 frozen questions. Real granite embed + GLiNER + BGE rerank + ArcadeDB, current
CPU `gliner2-base` sidecar.

## How to Run

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \
  -v "D:\turing_AgentMemory_MCP\.planning\spikes:/spikes" \
  -v "D:\turing_AgentMemory_MCP\baseline\03-turingdb:/baseline" \
  -v "D:\tmp\baseline-corpus:/corpus" \
  --entrypoint python turing-agentmemory-mcp \
  /spikes/003-doc-graphrag-quality-signal/run.py
```

## Investigation Trail

1. **First attempt crashed on ingest** — `ingest_document_text` runs
   `_process_text_for_storage` → GLiNER `process_many` on the **whole document
   text**; a 300-page legal PDF as one payload returns **HTTP 400** from the
   sidecar. The Phase-3 baseline dodged this by running GLiNER off. Real latent
   gap (TEST-08-style). Workaround: Noop the store's ingest-time processor, do
   per-chunk extraction with a dedicated bounded GLiNER client.
2. **CPU extraction was very slow** — 2215 chunks (full 7-doc subset) ran >27 min
   with no verdict. GLiNER is CPU-only by design here (`GLINER_DEVICE=cpu`, slim
   base, no GPU reservation). Cut to a bounded 3-doc / 167-chunk subset for a fast
   signal (user decision: "fast CPU signal first").
3. **Investigated GPU + multilingual** (`onnx-community/gliner_multi-v2.1`) — it's
   GLiNER **v2.1 / Transformers.js** ONNX (weights in `onnx/`); the sidecar is
   **fast_gliner / gliner2** (root `model.onnx`). Not a swap — a sidecar rewrite.
   Deferred pending evidence that Italian NER is actually weak (it isn't — below).

## Results

**VERDICT: PARTIAL.** The graph channel is inert on the existing yardstick, and
Italian entity extraction is adequate on the current model.

### Italian entity yield — multilingual swap NOT warranted

- 167 chunks → **1143 entities, 1637 `MENTIONS` edges, 9.8 entities/chunk**.
- Sample is real Italian domain vocabulary: `albero di decisione`,
  `apprendimento profondo`, `cella robotizzata`, `movimenti del robot`,
  `singolarità`, `raccordi tra i punti`, `clustering`, `simulatori`, `plc`, `tcp`.
- The current `lion-ai/gliner2-base-v1-onnx` handles Italian fine. The only noise
  is Wikipedia HTML chrome (`index.php`, `ultime modifiche`) — a conversion
  artifact, not a language gap. **A multilingual (`gliner_multi-v2.1`) swap is not
  justified by evidence.** (GPU would still speed ingestion — a separate perf win.)

### Graph-channel lift — exactly zero on this benchmark

| Config | MRR@20 | recall@1 | recall@20 |
|---|---|---|---|
| production | 0.767 | 0.733 | 0.80 |
| fused_base | 0.767 | 0.733 | 0.80 |
| fused_graph | **0.767** | **0.733** | **0.80** |

- `delta_mrr20 = 0.0`; **0 of 15 questions improved, 0 regressed.** Per-question
  ranks are identical base-vs-graph on every question. The graph channel added
  ~10% latency (1516 vs 1372 ms mean) for **zero** gain.
- **Why (this is the finding, not a failure):** the frozen questions are
  **single-passage grounded lookups** — the answer sits in one chunk that
  dense+lexical+rerank already retrieve at rank 1-2 (base MRR@20 = 0.767). The
  graph channel's value is **multi-hop / entity-bridged** retrieval (proven in
  002), and **the benchmark contains none of that query shape**, so it structurally
  cannot see the lift. 002 showed the channel helps a lexically-invisible,
  multi-hop answer; 003 shows the standard yardstick doesn't test that capability.

## Signal for the Build (carry to the verdict)

1. **A document graph channel adds ~0 on grounded-passage retrieval** and costs
   latency. Do NOT add it expecting lift on the current `real_document_benchmark`.
2. **Its value is a distinct capability** (multi-hop / cross-chunk / entity-bridged
   questions), which needs (a) a NEW eval containing multi-hop questions to measure,
   and (b) build work: multi-hop expansion + 001 entity resolution + tuned RRF
   weight + hop caps. Gate any build on that eval, not this one.
3. **Italian NER is adequate on the current model** — multilingual swap deferred
   (no evidence of need). GPU sidecar = a separate ingestion-perf concern.
4. **Latent gaps surfaced (fix-on-touch, existing code):** ingest runs GLiNER on
   whole-document text → HTTP 400 on large docs (TEST-08); `temporal_graph.py:137`
   `(type,name)` entity keying fragments the graph (001).

**Honest caveat:** 15 questions / 3 capped docs is a bounded signal, not a full
run. But the zero-lift result is *structural* (benchmark shape, not sample size):
the questions are single-passage, so no subset of them would show graph lift. A
full-corpus run would move the absolute numbers, not this conclusion.
