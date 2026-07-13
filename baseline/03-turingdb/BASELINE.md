# Phase 3 TuringDB Retrieval Baseline (ARC-01 Committed Artifact)

## What This Is

This is the committed yardstick against which Phase 6 (ARC-09) diffs the ArcadeDB
port. It captures the CURRENT TuringDB-backed stack's retrieval quality and e2e
correctness score, with concrete provider config, corpus manifest, frozen
questions, run parameters, and git snapshot SHA — captured before any
ArcadeDB-touching code lands (SC#3).

**This capture deviated heavily, and deliberately, from the plan that scoped it.**
The reranker was swapped mid-phase (user-directed), question generation used a
different provider than planned, and the corpus/question counts were reduced for
tractable wall-clock. All deviations are recorded below and MUST be replicated
by Phase 6 for a valid comparison (same reranker, same corpus, same frozen
questions).

## Provider Configuration (D-11)

Captured verbatim from `baseline/03-turingdb/capture-provider-env.txt`:

| Role | Model | Dimensions | Endpoint |
|---|---|---|---|
| Embedder | `mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M` | 768 | `http://agentmemory-embed:8080` |
| Reranker | `bge-reranker-v2-m3-Q8_0.gguf` | — | `http://agentmemory-rerank:8080` |

**Reranker swap (user-directed, mid-phase):** the plan originally targeted
`Qwen3-Reranker-0.6B`; it was replaced with `bge-reranker-v2-m3-Q8_0` after a
single-variable A/B (embedder held constant) showed BGE decisively better at
every matched checkpoint (MRR 0.53 vs 0.13; recall@1 0.36-0.50 vs 0.07;
Wikipedia doc: recall@1 0.07→0.50, recall@20 0.50→1.00, MRR 0.07→0.66).
`compose.yaml` now pins BGE (model-init provision + `--model` + `RERANK_MODEL`
default); Qwen3 remains provisioned for easy revert. **Phase 6 MUST use BGE**,
not Qwen3, for a valid comparison against this baseline.

**GLiNER: OFF.** GLiNER entity extraction is never wired into the e2e container
in this stack; this baseline reflects retrieval (embed + rerank) quality only,
no entity-extraction signal.

**Mode:** the D-02 e2e run used real GPU-backed embed and rerank sidecars
(`E2E_USE_EXTERNAL_EMBED=1 E2E_USE_EXTERNAL_RERANK=1`), confirmed in the
captured artifact (`agentmemory-embed:8080` / `agentmemory-rerank:8080`, not a
`127.0.0.1` stub).

## Corpus (D-05 / D-06)

- **Root used:** `D:/tmp/baseline-corpus` (external path, not committed —
  Phase 6 must re-point `--root` at an equivalent local corpus; see
  `corpus-manifest.json` for the exact file identity via sha256).
- **12 curated files:**
  - 7 originals: `Costituzione.pdf`, `G220_op_instr_0824_en-US.pdf` (30 MB),
    `Clienti.xlsx`, `Diario-ultimo.epub`, `Corso Base Robot.docx`, `Robot.pptx`,
    and a **fetched HTML snapshot** of
    `it.wikipedia.org/wiki/Apprendimento_automatico` (the corpus's original
    `.url` shortcut carried only a link; MarkItDown does not fetch URLs, so a
    real HTML snapshot was substituted for genuine webpage-format coverage).
  - 5 real Italian legislation PDFs extracted from
    `test/normattiva/pdf_vigente/Codici.zip` (a DPR, 3 Decreti Legislativi, a
    Regio Decreto; 200-750 KB each).
- **Formats:** `.docx .epub .html .pdf .pptx .xlsx` — all four D-04 formats
  (PDF / XLSX / EPUB / HTML) plus DOCX/PPTX extras are covered.
- **Manifest:** `baseline/03-turingdb/corpus-manifest.json` — field-subset
  extraction only (`filename`, `suffix`, `bytes`, `sha256`, `page_count`; plus
  `sheet_count: null` for the one `.xlsx` file, a documented gap — no existing
  code in this repo computes an XLSX sheet count, so none was hand-rolled).
  **No whole-file bytes are committed anywhere in this tree (D-06).**

## Frozen Questions (D-08)

- `baseline/03-turingdb/frozen-questions.json` — `questions_by_document` keyed
  by `filename` (12 files x 5 questions = 60 rows), each row
  `{source_id, question, answer, evidence_quote}`, produced by
  `gemma4:31b-cloud` against the actual corpus text.
- Round-trips cleanly through
  `scripts/real_document_benchmark_scoring.py::load_frozen_questions`.
- **Phase 6 replays via** `--frozen-questions baseline/03-turingdb/frozen-questions.json`
  on `scripts/real_document_benchmark.py`, which bypasses question
  re-generation so the ArcadeDB-ported stack is asked the EXACT SAME questions
  as this baseline — required for a like-for-like comparison.

## Run Parameters (D-11, actual values — differ from the plan's original pins)

| Flag | Value used | Plan's original pin |
|---|---|---|
| `--root` | `D:/tmp/baseline-corpus` | (open input, D-05) |
| `--top-k` | `20` | 20 |
| `--chunk-bytes` | `524288` | 524288 |
| `--poll-seconds` | `10` | 10 |
| `--search-concurrency` | `3` | 4 |
| `--question-count` | `5` (per file) | 10 |
| `--question-model` | `gemma4:31b-cloud` | `inclusionai/ling-2.6-flash` (OpenRouter) |
| `--question-url` | `http://127.0.0.1:11434/v1/chat/completions` (local Ollama) | OpenRouter endpoint |
| `--scope` | default (unset) | default |
| `--mcp-url` | `http://127.0.0.1:8095/mcp/` | — |

Question generation moved to a local Ollama model because no OpenRouter API key
was available; question count and concurrency were reduced to keep wall-clock
tractable after a self-inflicted TuringDB bloat inflated one full-scan latency
path ~60x mid-run (fixed by wiping the `turing-data` volume before the final
capture). Retrieval-critical providers (embed + rerank) remained real GPU
sidecars throughout, so this substitution does not affect retrieval-quality
validity — only the question-generation provider changed.

## Snapshot Git SHA

**`ab7abd0`** (captured in `baseline/03-turingdb/capture-provider-env.txt` at
capture time). This baseline reflects the repository state at this commit;
`compose.yaml`'s reranker swap (BGE) is included in this snapshot.

## D-01 Real-Document Benchmark Results

12 docs, 60 questions, 0 search errors, all ingestion jobs `succeeded`.

| Metric | Full corpus (60 q, 12 docs) | Docs where scoped search works (7 docs, 35 q) |
|---|---|---|
| MRR@20 | 0.349 | **~0.60** |
| recall@1 | 0.300 | ~0.50 |
| recall@20 | 0.450 | **~0.77** |
| latency mean | 5.4 s (clean DB) | — |

The full-corpus column is **deflated by a confirmed stack bug** (see "Known
Stack Bug" below): the 5 normattiva legal PDFs scored a flat 0.000 not from
poor retrieval but because document-scoped search returns empty results for
their long `document_id` values. **The meaningful retrieval-quality number for
this stack is ~0.60 MRR@20 / ~0.77 recall@20** (the 7-doc column) — Phase 6
should compare against this number, not the deflated full-corpus aggregate,
until the document_id bug is fixed.

## D-02 E2E Score Gate Results (real providers) — AS OBSERVED

| Field | Value |
|---|---|
| verdict | `FAILED_SCORE_GATE` (expected/accepted per D-07 — real providers do not clear the 10/10 stub-tuned threshold; frozen as-is, not treated as a script bug) |
| score | **9.474** |
| score_gate | `10/10` |
| check_count | **19** (no fail-fast collapse — all 19 scenarios ran) |
| turingdb_version | `1.35` |
| providers | real: `agentmemory-embed:8080`, `agentmemory-rerank:8080` (confirmed non-stub in the artifact) |

### Per-check table (transcribed as observed from `e2e-results.json`)

| # | Check | `ok` | `detail` | Note |
|---|---|---|---|---|
| 1 | `turingdb_starts_schema_embed_and_rerank_contracts` | true | (config dict) | pass |
| 2 | `mcp_exposes_expected_tool_surface` | true | true | pass |
| 3 | `memory_store_message_writes_scoped_memory` | true | true | pass |
| 4 | `memory_store_messages_batches_idempotent_searchable_writes` | true | true | pass |
| 5 | `memory_search_retrieves_alice_exact_top1` | true | true | pass |
| 6 | `memory_search_does_not_leak_bob` | true | true | pass — vacuous-`all()` risk shape (D-07 candidate), NOT triggered this run (collection non-empty) |
| 7 | `memory_search_hybrid_exact_code_match_explains_lexical_score` | true | true | pass |
| 8 | `memory_get_context_returns_prompt_ready_context` | true | true | pass |
| 9 | `memory_store_message_is_idempotent_and_memory_list_filters_metadata` | true | true | pass |
| 10 | `memory_get_and_update_return_structured_metadata` | true | true | pass |
| 11 | `memory_delete_hides_memory_from_get_and_search` | true | true | pass — vacuous-`all()` risk shape (D-07 candidate), NOT triggered this run |
| 12 | `document_ingest_text_writes_chunks` | **true** | **false** | **CONFIRMED false-passing (D-07)** — reported `ok=true` while its own assertion evaluated `false` |
| 13 | `document_search_retrieves_exact_top1_with_citation_and_neighbor_context` | **false** | — (`IndexError: list index out of range`) | **CONFIRMED genuine failure**, consistent with the document_id lookup bug (see below) |
| 14 | `document_search_hybrid_exact_code_match_explains_lexical_score` | **true** | **false** | **CONFIRMED false-passing (D-07)** |
| 15 | `document_ingest_text_is_idempotent_for_same_payload` | **true** | **false** | **CONFIRMED false-passing (D-07)** |
| 16 | `document_reindex_text_replaces_old_chunks_and_metadata` | **true** | **false** | **CONFIRMED false-passing (D-07)** — also the hardcoded `chunk_count==2` check |
| 17 | `document_delete_hides_document_from_search` | true | true | pass |
| 18 | `memoryarena_bucket_sample_retrieves_answer_context` | true | true | pass |
| 19 | `restart_preserves_memory_and_document_retrieval` | true | true | pass |

18/19 report `ok=true`; 1/19 (`#13`) reports a confirmed genuine failure. Score
= 18/19 * 10 = 9.474, matching the captured `score`.

## Known Inflation Caveats (D-07) — TWO SEPARATE PHENOMENA, kept separate per Pitfall 5

### Phenomenon (a): stub-mode `HashingEmbedder` limitation — this baseline uses real providers

Phase 1's completion note documented an 18/19 (score 9.474) result attributed to
"a pre-existing `HashingEmbedder`-stub limitation on one semantic
document-search check" under the CI-default stub embedder. This D-02 capture
uses **real** granite embeddings + **real** BGE reranking throughout — if
phenomenon (a) were the only inflation source, this run would score 19/19.
It did not: the run still lands at 18/19 raw (9.474), with the actual failure
this time being check #13, `document_search_retrieves_exact_top1...`
(an `IndexError`, not a semantic-quality shortfall). This on its own confirms
phenomenon (a) alone does not fully account for the score gap — see (b).

### Phenomenon (b): D-07 harness `check()`/chunk-count inflation — NOT fixed by real providers, CONFIRMED AS OBSERVED in this run

`e2e_score_scenarios.py`'s `check()` helper is specified to compute
`"ok": bool(detail)` (current source, `src/turing_agentmemory_mcp/e2e_score_scenarios.py:39-51`).
In THIS captured run, **four checks report `ok: true` while their own `detail`
field is literally `false`** (checks #12, #14, #15, #16 in the table above:
`document_ingest_text_writes_chunks`,
`document_search_hybrid_exact_code_match_explains_lexical_score`,
`document_ingest_text_is_idempotent_for_same_payload`,
`document_reindex_text_replaces_old_chunks_and_metadata`). This is not a
hypothesis — it is a fact directly readable from the committed
`e2e-results.json`, and it means the harness that scored this checkpoint (at
snapshot `ab7abd0`) reported passes for assertions that did not hold.

Applying the CORRECT `ok = bool(detail)` semantics to these 4 checks, the
**true pass count for this run is 18 − 4 = 14**, plus the 1 confirmed hard
failure (#13) = 5 non-passing of 19. This closely matches D-07's own **"~14/19"**
figure referenced in `03-RESEARCH.md` as a low-confidence [ASSUMED] estimate —
this capture independently CONFIRMS that figure.

The RESEARCH.md [ASSUMED] vacuous-`all()` candidates (`memory_search_does_not_leak_bob`,
`memory_delete_hides_memory_from_get_and_search`, checks #6 and #11) did **NOT**
trigger false-passing in this run — their underlying collections were
non-empty, so `ok=true, detail=true` is a genuine pass here. They remain a
structural risk (an empty collection would silently pass), but they are **not**
part of the confirmed false-passing set for this specific captured run. Do not
conflate them with the four confirmed false-passing checks above.

### Chunk-count non-cancellation caveat

Two of the confirmed false-passing checks hardcode exact `chunk_count` values
(`document_ingest_text_writes_chunks == 3`, `document_reindex...chunk_count == 2`).
Phase 4's re-chunking work (ARC-04/ARC-05) may legitimately change these
numbers for reasons unrelated to a regression. Because this baseline records
BOTH the harness-reported `ok` and the underlying `detail` per check, Phase 6
**must diff PER-CHECK against this table, not just the aggregate score** — an
unchanged aggregate score across phases could hide a chunk-count-driven flip
that this harness bug renders invisible at the aggregate level.

### Confirmed hard failure (not inflation — a genuine, separate finding)

Check #13, `document_search_retrieves_exact_top1_with_citation_and_neighbor_context`,
fails with `IndexError: list index out of range`. This is consistent with the
document-scoped search bug found during capture (03-02) — see "Known Stack Bug"
below.

## Known Stack Bug: document-scoped search fails for long `document_id` values (found in 03-02, NOT fixed here)

`document_search(document_id=<118-char normattiva id>)` returns 0 hits; the
identical query WITHOUT the `document_id` filter returns 20 hits; short IDs
(e.g. the Costituzione document) work correctly. Chunks ARE indexed and
retrievable — this is a stored-vs-queried `document_id` length/truncation
mismatch, not a missing-data bug.

This bug **deflates** the D-01 full-corpus MRR@20/recall@20 numbers above: the
5 normattiva PDFs scored a flat 0.000, not because retrieval quality is poor,
but because document-scoped search cannot find their chunks at all. On the 7
documents where scoped search works, quality is **~0.60 MRR@20 / ~0.77
recall@20** — use these numbers, not the deflated full-corpus aggregate, as the
true retrieval-quality yardstick for this stack.

Must be fixed in or before the ArcadeDB port (ARC-09); also tracked in
`.planning/research/FUTURE-MILESTONE-retrieval-memory-quality.md`, alongside a
related finding that `document_search` does an O(all-chunks) Python full scan
(`store_documents.py:534`) rather than an indexed lookup — ArcadeDB's native
indexed search is expected to fix both the correctness bug and the scan-cost
issue as part of the port.

## Reproduction

### Host benchmark (D-01)

```powershell
docker compose up -d turingdb agentmemory-embed agentmemory-rerank agentmemory-gliner turing-agentmemory-mcp
docker compose ps   # confirm all report healthy before proceeding

PYTHONPATH=src PROVIDER_API_KEY=ollama python scripts/real_document_benchmark.py `
  --root "D:/tmp/baseline-corpus" --mcp-url http://127.0.0.1:8095/mcp/ `
  --output "D:/tmp/real-document-benchmark.json" `
  --top-k 20 --chunk-bytes 524288 --poll-seconds 10 --search-concurrency 3 `
  --question-count 5 --question-model gemma4:31b-cloud `
  --question-url http://127.0.0.1:11434/v1/chat/completions --env-file .env
```

To replay this baseline's EXACT frozen questions (Phase 6 comparison run),
add:

```powershell
  --frozen-questions baseline/03-turingdb/frozen-questions.json
```

### Docker e2e, real providers (D-02)

```powershell
docker compose run --rm -e E2E_USE_EXTERNAL_EMBED=1 -e E2E_USE_EXTERNAL_RERANK=1 `
  -e EMBED_BASE_URL=http://agentmemory-embed:8080 -e EMBED_DIMENSIONS=768 `
  -e EMBED_MODEL=mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M `
  -e RERANK_BASE_URL=http://agentmemory-rerank:8080 -e RERANK_MODEL=bge-reranker-v2-m3-Q8_0.gguf `
  e2e --out /work/e2e-results.json
```

## Committed Artifact Inventory

- `BASELINE.md` (this file) — D-10/D-11 human-readable manifest
- `corpus-manifest.json` — D-06 manifest-only corpus record (no bytes)
- `frozen-questions.json` — D-08 Phase-6 replay contract
- `e2e-results.json` — raw D-02 real-provider e2e output (verbatim capture)
- `real-document-benchmark.json` — raw D-01 benchmark output (verbatim capture)

## Deviations from the Original Plan (carried forward from 03-02's capture)

1. **Reranker swap** Qwen3-Reranker-0.6B → BGE-v2-m3-Q8_0 (user-directed
   mid-phase). Changes the baselined stack — Phase 6 MUST match.
2. **Question generation** via local Ollama `gemma4:31b-cloud` instead of the
   plan's OpenRouter `inclusionai/ling-2.6-flash` (no OpenRouter key
   available). Retrieval-critical providers (embed + rerank) stayed real GPU
   sidecars, so retrieval-quality validity holds.
3. **Curated corpus** with a fetched HTML snapshot substituted for a `.url`
   shortcut (MarkItDown does not fetch URLs).
4. **5 questions/file, `--search-concurrency 3`** (plan pinned 10/4) — reduced
   for tractable wall-clock after a self-inflicted TuringDB volume bloat.
5. Output written to a local temp path then copied into `baseline/` (Windows
   IDE-watcher file-lock workaround); no effect on content.
6. The `turing-data` volume was wiped before the final capture run (repeated
   re-ingests had bloated it ~5x, inflating one full-scan latency path ~60x:
   431 s → 7 s per search after the wipe).
