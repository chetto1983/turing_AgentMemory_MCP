---
phase: 03-turingdb-retrieval-baseline
plan: 02
subsystem: retrieval-baseline
status: complete-with-deviations
tags: [baseline, retrieval, real-document-benchmark, e2e-score, reranker-swap, arc-01]

# Dependency graph
requires:
  - "03-01: --frozen-questions loader (available for Phase 6 replay; NOT used in this capture run)"
provides:
  - "baseline/03-turingdb/real-document-benchmark.json (D-01 raw benchmark output, BGE reranker)"
  - "baseline/03-turingdb/e2e-results.json (D-02 real-provider e2e score)"
  - "baseline/03-turingdb/capture-provider-env.txt (D-11 live provider config + snapshot SHA ab7abd0)"
affects: [03-03-artifact-assembly, ARC-09-migration-correctness-gate]

# Tech tracking
tech-stack:
  added:
    - "bge-reranker-v2-m3 (Q8_0 GGUF, gpustack@3093af03) as the reranker — replaces Qwen3-Reranker-0.6B"
  patterns:
    - "Reproducible model pinning: added a compose model-init provision(url, sha256, path) for BGE (sha a43c7c9b...)"

key-files:
  created:
    - baseline/03-turingdb/real-document-benchmark.json
    - baseline/03-turingdb/e2e-results.json
    - baseline/03-turingdb/capture-provider-env.txt
  modified:
    - compose.yaml   # reranker swap: model-init provision + agentmemory-rerank --model + RERANK_MODEL default

key-decisions:
  - "Reranker swapped Qwen3-Reranker-0.6B -> bge-reranker-v2-m3-Q8_0 (USER-DIRECTED, mid-phase). BGE decisively beats Qwen3 at matched checkpoints (MRR 0.53 vs 0.13; recall@1 0.36-0.50 vs 0.07). This changes the baselined stack: Phase 6 (ARC-09) MUST use the same reranker for a valid comparison."
  - "Question generation used a local Ollama cloud model (gemma4:31b-cloud via http://127.0.0.1:11434/v1/chat/completions) instead of the plan's OpenRouter inclusionai/ling-2.6-flash (no OpenRouter key available; user-directed). Retrieval-critical providers (embed+rerank) remained REAL GPU sidecars, so baseline validity holds."
  - "Reduced to 5 questions/file + search-concurrency 3 (plan pinned 10/file, conc 4) to keep wall-clock tractable after discovering the §1.3 full-scan + a self-inflicted TuringDB bloat."
---

## What was captured

The two raw TuringDB baseline numbers (SC#1 / ARC-01) against the CURRENT stack with **real GPU embed+rerank providers**, plus the live provider config (D-11) and snapshot SHA. This is the yardstick Phase 6 diffs the ArcadeDB port against.

### Corpus (`--root`)
`D:\tmp\baseline-corpus` — a curated 12-file set assembled this session (D-05 open input supplied at run time):
- 7 originals: `Costituzione.pdf`, `G220_op_instr_0824_en-US.pdf` (30 MB), `Clienti.xlsx`, `Diario-ultimo.epub`, `Corso Base Robot.docx`, `Robot.pptx`, and a **fetched HTML snapshot** of `it.wikipedia.org/wiki/Apprendimento_automatico` (the corpus's `.url` shortcut carried only the link; MarkItDown does not fetch it, so a real HTML snapshot was substituted for genuine webpage-format coverage).
- 5 real Italian legislation PDFs extracted from `test/normattiva/pdf_vigente/Codici.zip` (a DPR, 3 Decreti Legislativi, a Regio Decreto; 200–750 KB each).
- **All four D-04 formats covered**: PDF, XLSX, EPUB, webpage/HTML (+ DOCX, PPTX extras). Suffix set in the artifact: `.docx .epub .html .pdf .pptx .xlsx`.

### Live provider config (D-11), snapshot SHA `ab7abd0`
```
EMBED : granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M  dims=768  http://agentmemory-embed:8080
RERANK: bge-reranker-v2-m3-Q8_0.gguf                                  http://agentmemory-rerank:8080   (swapped from Qwen3-Reranker-0.6B)
QGEN  : gemma4:31b-cloud (Ollama)                                     http://127.0.0.1:11434/v1/chat/completions
```

### Run commands (verbatim)
**D-01 (host, external MCP client):**
```
PYTHONPATH=src PROVIDER_API_KEY=ollama python scripts/real_document_benchmark.py \
  --root "D:/tmp/baseline-corpus" --mcp-url http://127.0.0.1:8095/mcp/ \
  --output "D:/tmp/real-document-benchmark.json" \
  --top-k 20 --chunk-bytes 524288 --poll-seconds 10 --search-concurrency 3 \
  --question-count 5 --question-model gemma4:31b-cloud \
  --question-url http://127.0.0.1:11434/v1/chat/completions --env-file .env
```
(Ran on a freshly-wiped `turing-data` volume. Output written to `D:\tmp` then copied to `baseline/` to avoid a Windows IDE-watcher `os.replace` lock on rapid checkpoints. Host Python = system `C:\Python313` + `PYTHONPATH=src`; no `.venv` present.)

**D-02 (Docker, real providers):**
```
docker compose run --rm -e E2E_USE_EXTERNAL_EMBED=1 -e E2E_USE_EXTERNAL_RERANK=1 \
  -e EMBED_BASE_URL=http://agentmemory-embed:8080 -e EMBED_DIMENSIONS=768 \
  -e EMBED_MODEL=mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M \
  -e RERANK_BASE_URL=http://agentmemory-rerank:8080 -e RERANK_MODEL=bge-reranker-v2-m3-Q8_0.gguf \
  e2e --out /work/e2e-results.json
```

## Results

### D-01 real-document benchmark (BGE reranker, 12 docs, 60 questions, 0 search errors, all jobs `succeeded`)
| Metric | Full corpus (60 q) | Docs where scoped-search works (7 docs, 35 q) |
|---|---|---|
| MRR@20 | 0.349 | **~0.60** |
| recall@1 | 0.300 | ~0.50 |
| recall@20 | 0.450 | **~0.77** |
| latency mean | 5.4 s (clean DB) | — |

The full-corpus number is **deflated by a stack bug** (below): the 5 normattiva legal PDFs scored a flat 0.000 not from poor retrieval but because document-scoped search returns empty for their long IDs. The meaningful retrieval quality on correctly-measured docs is **~0.60 MRR / ~0.77 recall@20**.

### D-02 e2e score gate (real providers)
| Field | Value |
|---|---|
| verdict | `FAILED_SCORE_GATE` (expected/accepted per D-07 — real providers don't hit the 10/10 stub threshold; frozen as-is) |
| score | **9.474** |
| check_count | **19** (NOT 1 — no fail-fast collapse; all scenarios ran) |
| checks[] | 19 captured verbatim (per-check name/ok/points/detail) |
| turingdb_version | 1.35 |
| providers | real: `agentmemory-embed:8080`, `agentmemory-rerank:8080` (confirmed in artifact — not a `127.0.0.1` stub) |

Capture was NOT gated on the process exit code (exit 1 == the score gate, expected).

## Reranker verdict (Qwen3-0.6B -> BGE-v2-m3)
Single-variable change (embedder held constant). BGE wins decisively at every matched checkpoint; the sharpest illustration is the Italian ML Wikipedia page (Qwen3's worst doc): recall@1 0.07 -> 0.50, recall@20 0.50 -> 1.00, MRR 0.07 -> 0.66. Diagnosis confirmed: Granite embeddings get the right chunk into the pool; the tiny Qwen3 reranker failed to lift it to the top; BGE does. `compose.yaml` now pins BGE (model-init provision + `--model` + `RERANK_MODEL`), with Qwen3 left provisioned for easy revert.

## Deviations (all recorded above; summary)
1. Reranker swap Qwen3->BGE (user-directed; changes the baselined stack — Phase 6 must match).
2. Question-gen via local Ollama `gemma4:31b-cloud` (no OpenRouter key).
3. Curated corpus + fetched HTML snapshot for webpage coverage.
4. 5 q/file + concurrency 3 (from 10/4) for tractable wall-clock.
5. Output relocated to `D:\tmp` (Windows lock) then copied.
6. TuringDB `turing-data` volume wiped before the final run (repeated re-ingests had bloated it ~5x, inflating the §1.3 full-scan latency ~60x: 431 s -> 7 s per search).

## Findings surfaced by this baseline (recorded in .planning/research/FUTURE-MILESTONE-retrieval-memory-quality.md)
- **§1.3 — `document_search` does an O(all-chunks) full scan** (Python `lexical_score` over every chunk via `_active_chunk_rows`, `store_documents.py:534`). GPU idles (P8/10 W) during searches; latency scales with total chunk count (7 s clean vs 431 s bloated). ArcadeDB indexed BM25 fixes it (ARC-09 port benchmark).
- **BUG — document-scoped search fails for long `document_id`s.** `document_search(document_id=<118-char normattiva id>)` returns 0 hits; same query without the filter returns 20; short IDs (costituzione) work. Chunks ARE indexed/retrievable — a stored-vs-queried `document_id` length/truncation mismatch. NOT fixed here (baseline phase; only 03-01 is a permitted code touch) — must be fixed in/before the port; it artificially deflates this baseline.
- **Dedup — document-level exists** (idempotent identical re-ingest via `stable_id` + `text_hash`), but **no chunk-level / near-dup / memory consolidation** (Theme T1).

## Not committed here
Per plan, the `baseline/03-turingdb/` data files land uncommitted; plan 03-03 assembles the full artifact (corpus-manifest, frozen-questions, BASELINE.md) and adds them. `compose.yaml` (reranker swap) is a real tracked change to commit with the phase.

## Self-Check: PASSED
- Both raw artifacts on disk under `baseline/03-turingdb/`; benchmark JSON valid, all 12 jobs `succeeded`, `question_count=60`, `search_error_count=0`.
- Secret scan clean (no `PROVIDER_API_KEY`/`Authorization`/`Bearer`/`sk-` in the benchmark artifact or provider-env capture).
- Live provider config + snapshot SHA `ab7abd0` captured.
- Reranker verdict + three stack findings recorded for the port and the future milestone.
