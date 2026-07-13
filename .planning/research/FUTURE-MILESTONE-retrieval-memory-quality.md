---
status: research-findings
purpose: Seed material for a FUTURE milestone (retrieval & memory quality). NOT part of the current ArcadeDB-port stabilization milestone.
created: 2026-07-13
source: Phase 3 (TuringDB retrieval baseline) hands-on measurement + code-grounded competitive scan of mem0, neo4j-labs/agent-memory, supermemory
consumed_by: /gsd-new-milestone (later)
---

# Retrieval & Memory Quality — Findings & Next-Milestone Candidates

## Scope note (read first)

These findings surfaced while capturing the Phase 3 retrieval baseline. They are **candidates for a future milestone**, deliberately kept out of the current milestone (ArcadeDB port / stabilization). Nothing here should be pulled forward: the port lands first, and ArcadeDB's native graph traversal + vector + full-text is the *ideal* substrate for most of these ideas — better than bolting them onto the TuringDB stack we are retiring.

Everything below is grounded in code we actually read (our store, and the three peer repos cloned to `d:/tmp/memory-research`).

---

## 1. What Phase 3 measurement revealed about our own retrieval

### 1.1 Document retrieval has NO graph fusion — it is dense + BM25 + rerank
`document_search` → `store.search_documents` (`store_documents.py:470`) runs exactly:
1. **Dense** vector search over `(:Chunk)` (`VECTOR SEARCH IN document_index`, line 507),
2. **Lexical** BM25 (`lexical_score`, line 555),
3. **Hybrid blend** (`blend_hybrid_score`, line 559),
4. **Rerank** (`_rerank_documents`, `store_search.py:470`) with `apply_rerank_guard`.

The **only** graph touch is *after* ranking: `_chunk_context` (`store_chunking.py:81`) follows `(:Chunk)-[:NEXT_CHUNK]->(:Chunk)` to attach the neighbouring chunk as citation context. It does **not** influence ranking.

By contrast, **memory** retrieval (`_search_memory_fused`, `store_search.py:187` → `fuse_rankings`) runs weighted RRF over `{bm25, episode-dense, fact-dense, entity-dense, graph, community(Leiden)}`. Entities come from GLiNER; facts are `SUBJECT_OF`/`OBJECT_OF` triples; communities from Leiden.

**The asymmetry is the headline finding:** the entire knowledge-graph + GLiNER machinery is wired to *memories only*. Document chunks get none of it. Grepping `store_documents.py`/`store_chunking.py` for entity/extract/community returns nothing.

### 1.2 In document search the reranker is the dominant lever — and the baseline one was weak
Because doc ranking rests on only three signals, the cross-encoder reranker is the final and most decisive reordering step. The baseline `Qwen3-Reranker-0.6B` showed the classic weak-reranker signature on a real Italian corpus (12 docs, ~120 grounded questions, Granite multilingual embedder):

- recall@20 ≈ **0.78** (the embedder gets the right chunk into the pool) but
- recall@1 ≈ **0.07**, MRR@20 ≈ 0.13–0.28 (it fails to lift that chunk to the top).

Swapping to **`bge-reranker-v2-m3`** (Q8, multilingual, ~same 4 GB VRAM footprint) — a single-variable change, embedder held constant — produced a dramatic early A/B on the hardest document (Italian ML Wikipedia page, Qwen3's worst at MRR 0.07):

| Same doc, same question style | Qwen3-0.6B | bge-reranker-v2-m3 |
|---|---|---|
| recall@1 | 0.067 | **0.500** |
| recall@20 | ~0.50 | **1.000** |
| MRR@20 | ~0.07 | **0.661** |

Also noted: a possible llama.cpp output bug affecting **Qwen3-Rerank** ([ggml-org/llama.cpp#16407](https://github.com/ggml-org/llama.cpp/issues/16407)) — worth confirming whether the baseline reranker was partly mis-scoring, independent of model size.

**Takeaways for a future milestone:** (a) reranker quality is high-leverage for document retrieval; (b) the doc-vs-memory graph asymmetry is a real, closable gap; (c) we already built the exact tool to measure these fairly — the D-08 `--frozen-questions` path (Phase 3, `real_document_benchmark_scoring.py`) enables airtight same-question A/B with providers held constant.

### 1.3 Document search does an O(all-chunks) full scan per query — a real scale bottleneck
While profiling the baseline run's slow searches (~150–430 s/query) we found the GPU **idle at P8 / ~10 W / 29 % util** — the latency is entirely CPU/DB-side, not compute. Root cause in `search_documents` (`store_documents.py:534`): after the bounded vector search, it iterates **`_active_chunk_rows(...)` — every active chunk for the tenant** — merges them all into the candidate set, and computes `lexical_score` on each. On a ~1600-chunk corpus (one 830-chunk PDF) that's a full linear scan **per query**, single-tenant-serialized, so it gets *worse* under concurrency (contention), not better. This is the "linear search over all documents, no pagination" scale limit called out in the architecture notes, now confirmed empirically.

Implications:
- The reranker/GPU is **not** the doc-retrieval bottleneck at this corpus size; the lexical full-scan is. Adding rerank slots or search concurrency does nothing (or hurts).
- **The ArcadeDB port should fix this for free**: native filtered-ANN + a Lucene full-text index means the lexical (BM25) channel becomes an *indexed* query, not a Python scan over all chunks. Worth an explicit benchmark in the port (ARC-09) and a hard requirement in the future retrieval milestone (bound candidate generation; never materialize the full chunk set).
- Until then, benchmark wall-clock scales with `n_chunks × n_queries`; reduce corpus size or question count to speed measurement, not concurrency.

### 1.4 Dedup exists at the document level only — not chunk / near-dup / memory
`ingest_document_text` (`store_documents.py:101–110`) dedups **whole documents**: `stable_id("doc", user_identifier, title, text[:128])` + a `text_hash` make an identical re-ingest **idempotent** (metadata update, zero new chunks). Gaps: (a) **no chunk-level cross-document dedup** — two different documents sharing identical passages (legal boilerplate is the poster child) store those chunks redundantly, inflating the index and the §1.3 scan; (b) **exact-hash only** — no near-duplicate/semantic dedup, so a lightly-edited re-upload isn't recognized; (c) **memories are append-only** with no consolidation at all. (a) and (c) are the strongest levers and feed Theme **T1** (mem0 ADD/UPDATE/DELETE, supermemory contradiction resolution, neo4j `dedupe_entities`). Note for the record: the multi-run TuringDB bloat that motivated §1.3's discovery was *not* a dedup failure — it was a per-run fresh `user_identifier` scope (a new tenant each run, correct isolation), a test-harness artifact.

---

## 2. Competitive scan — best fuseable ideas (code-grounded)

Three peers, read at the implementation level. Each contributes something distinct.

### mem0 (`mem0/`) — write-time fact management
- **ADD/UPDATE/DELETE consolidation** (`memory/main.py:_add_to_vector_store` L837–1164; `configs/prompts.py` update-memory prompt): on every write, LLM-extract atomic facts → vector-search top-10 existing in scope → LLM emits per-fact `event ∈ {ADD,UPDATE,DELETE,NONE}`; UPDATE keeps the same ID, contradictions DELETE. Full history via `db.add_history` (reversible).
- **Cheap guardrails**: md5 exact-dedup skips the LLM (`main.py` L963–982); UUID→sequential-int remap so the model can't invent/corrupt IDs (L891–896).
- **Entity-link boost with IDF-like down-weighting** (`_compute_entity_boosts` L1691–1771): `1/(1 + 0.001·(n_linked-1)²)` so a promiscuous entity contributes less; capped by `ENTITY_BOOST_WEIGHT=0.5`.
- **Magnitude-aware additive fusion + query-adaptive BM25 sigmoid** (`utils/scoring.py`): normalizes BM25 logistically, fuses `(semantic+bm25+entity)/max_possible` with an adaptive denominator, gates on the semantic threshold. (Ours discards score magnitude in RRF.)
- **Extraction-time temporal grounding** (`prompts.py` additive-extraction L524–540): resolve "yesterday"/"last week" to absolute dates against an explicit Observation Date; per-record `expiration_date` filter.

### neo4j-labs/agent-memory (`neo4j-agent-memory/`) — graph-native peer
- **GLiREL zero-shot relation extraction** (`extraction/gliner_extractor.py:876`): typed edges (KNOWS, EMPLOYED_BY, LOCATED_AT) from GLiNER spans, **local, no LLM**. Directly enables an entity/relation graph over *chunks* — the doc gap in §1.1.
- **Multi-stage extraction pipeline** (`extraction/pipeline.py`): spaCy→GLiNER→LLM as stages with UNION/INTERSECTION/CONFIDENCE/CASCADE/FIRST_SUCCESS merge; `ConditionalPipeline` skips expensive stages by predicate (cheap NER first, LLM only when coverage is thin).
- **POLE+O typed entity model** (`schema/models.py`): closed top types (PERSON/OBJECT/LOCATION/EVENT/ORGANIZATION) + curated subtypes, materialized as multi-label nodes `(:Entity:OBJECT:VEHICLE)` (`graph/queries.py:217`) so a label scan filters subtype for free. (Ours: free-form GLiNER label strings.)
- **Reasoning/procedural memory** (`memory/reasoning.py`): `(:ReasoningTrace)-[:HAS_STEP]->(:ReasoningStep)`, tool traces, `(:ReasoningStep)-[:TOUCHED]->(:Entity)` one-hop audit edges, `get_similar_traces` (vector search over past successful steps → imitation prompting). We have no procedural memory.
- **Dry-runnable consolidation jobs + composite resolver** (`memory/consolidation.py`, `resolution/composite.py`): `dedupe_entities` (vector kNN, same-type, skip existing `:SAME_AS`), Exact→Fuzzy→Semantic resolver with Union-Find batch clustering, `:ConsolidationRun` audit nodes, `dry_run=True` default. Relationship-level temporal invalidation (`SUPERSEDED_BY` + `valid_until`).

### supermemory (`supermemory/`) — design via schema/API (engine is a closed cloud service; internals inferred from `packages/validation/schemas.ts`, `packages/memory-graph/`)
- **Static vs dynamic memory tiers + always-on profile lane** (`schemas.ts:264 isStatic`; retrieval modes `profile|query|full`): stable identity facts injected unconditionally, *bypassing* similarity fusion. (Ours fuses everything → durable facts can rank out.)
- **Version-chain contradiction resolution** (`schemas.ts:239-266`): `updates|extends|derives` relations, `parentMemoryId`/`rootMemoryId` linked list, `isLatest`; search returns latest + attaches version-distance context.
- **Temporal forgetting with audited reason** (`isForgotten`,`forgetAfter`,`forgetReason`): soft-forget tied to *contradiction*, not just TTL, with a reasoned tombstone.
- **Two-stage retrieval**: Document `summaryEmbedding` coarse gate → chunk search inside survivors, with independent `documentThreshold` + `chunkThreshold`.
- **Contextual-chunk embedding + Matryoshka vectors** (`schemas.ts:110,119`): embed title/summary-enriched text (return raw text); truncated-dim ANN then full-dim rerank.
- **Unified RAG+memory provenance**: `(Memory)-[DERIVED_FROM]->(Chunk)`, one query returns memories *plus* their source chunks with prev/next context windows.

---

## 3. Candidate milestone themes (ranked by impact × effort)

| # | Theme | Core ideas (source) | Impact | Effort | Depends on port? |
|---|-------|--------------------|--------|--------|------------------|
| **T1** | **Memory consolidation & fact lifecycle** | write-time ADD/UPDATE/DELETE (mem0) · md5+int-remap guardrails (mem0) · version-chain supersession + soft-forget-with-reason (supermemory) · dry-run dedupe jobs + composite resolver (neo4j) | **High** | Med-High | Yes |
| **T2** | **GraphRAG for documents** (close the doc/memory asymmetry) | GLiREL relations over chunk spans (neo4j) · entity-link boost with IDF down-weighting (mem0) · Memory↔Chunk `DERIVED_FROM` provenance (supermemory) · reuse `fuse_rankings` on docs | **High** (relational/multi-hop) / Low (single-passage) | Med-High | Yes |
| **T3** | **Retrieval-quality upgrades** (mostly drop-in) | reranker → bge-reranker-v2-m3 (piloted in Phase 3) · contextual-chunk + Matryoshka embeddings (supermemory) · summary-embedding two-stage gate (supermemory) · magnitude-aware fusion + BM25 sigmoid (mem0) | Med-High | **Low-Med** | Partly |
| **T4** | **New memory types & lanes** | reasoning/procedural memory + `:TOUCHED` audit + similar-trace imitation (neo4j) · static/dynamic profile lane always-prepended (supermemory) · extraction-time temporal grounding (mem0/supermemory) | Med-High | Med-High | Yes |
| **T5** | **Entity model & extraction pipeline** | POLE+O typed typology w/ multi-label materialization (neo4j) · multi-stage cascade extraction spaCy→GLiNER→LLM (neo4j) | Med (foundation) | Low-Med | Yes |

**Quick-win candidates (could even be small stabilization follow-ups, not a full milestone):** the reranker upgrade (T3 — already piloted, decisive), md5 exact-dedup + reversible history (T1), extraction-time temporal grounding (T4), per-record expiry filter.

---

## 4. Suggested sequencing (inside the future milestone)

1. **Foundation** — T5 (typed entities + cascade extraction) and the T2 ingestion piece (GLiREL over chunks) build the graph substrate documents currently lack.
2. **Fusion** — extend `fuse_rankings` to documents (T2) on top of that substrate; add entity-link IDF boost.
3. **Lifecycle** — T1 consolidation in the write path (needs history/tombstones first for reversibility).
4. **Quality** — T3 drop-ins (contextual/Matryoshka embeddings, two-stage gate, fusion math) A/B'd continuously.
5. **New capabilities** — T4 reasoning memory + profile lane last (largest surface, write-amplification risk).

Rationale: substrate → fusion → lifecycle → tuning → new types. Each stage is independently shippable and measurable.

---

## 5. Evaluation approach (already have the tooling)

- **Same-question A/B**: freeze a question set via the D-08 `--frozen-questions` path (`real_document_benchmark.py`) and hold providers constant, so a change is measured on identical inputs (this is how the reranker A/B should be finalized).
- **Regression gate**: the deterministic E2E score gate (`scripts/e2e_score.py`) must stay green through every change.
- **Never mix configs**: per CLAUDE.md, do not compare across mismatched embed/rerank/model configs, and re-embed when the embedding model changes.
- **Cost budgeting**: T1/T4 add LLM calls per write; T2 adds GLiNER/GLiREL + community detection per chunk (one 30 MB PDF was **830 chunks**) — measure ingestion-time cost, not just retrieval quality.

---

## 6. Open questions / risks

- **Consolidation safety** (T1): an over-eager UPDATE/DELETE can clobber a still-valid fact. Mandate tombstones + reversible history; keep auto-merge thresholds conservative (homonym risk, e.g. two different "John Smith").
- **Ingestion cost** (T2/T5): per-chunk entity+relation extraction and Leiden over a large doc-entity graph (O(n^1.5)) is a real GPU/time investment. Gate by document type / on-demand.
- **Fusion calibration** (T3): magnitude-aware additive fusion is scale-sensitive vs RRF's rank-robustness — treat as an experiment behind the E2E gate, not a wholesale RRF replacement.
- **Domain fit** (T5): POLE+O is investigation-flavored; general chat entities (CONCEPT/EMOTION) squash into OBJECT — adapt the typology to our domain.
- **Benchmark vs reality**: the current grounded-passage benchmark under-measures T2's value (graph fusion helps multi-hop/relational/global queries, which this benchmark doesn't contain). Add a relational/multi-hop eval set before judging T2.

---

## 7. Sources

- Our code: `store_documents.py`, `store_search.py`, `store_chunking.py`, `retrieval_fusion.py`, `real_document_benchmark*.py`, `compose.yaml`.
- Phase 3 baseline artifacts: `baseline/03-turingdb/` (and the BGE re-baseline in progress).
- Peer repos (shallow clones under `d:/tmp/memory-research/`): `mem0ai/mem0`, `neo4j-labs/agent-memory`, `supermemoryai/supermemory` — specific file/line citations inline in §2.
- llama.cpp Qwen3-rerank output bug: ggml-org/llama.cpp#16407.
