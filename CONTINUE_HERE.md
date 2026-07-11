# Continue Here

This handoff is for the next workstation with a 12 GiB NVIDIA GPU.

## Repository State

- Target branch: `master`
- Feature branch merged: `feature/fused-temporal-memory`
- Durable asynchronous document ingest commit: `a2b399a`
- The public test corpus is intentionally ignored by `test/*`.
- `.env` and `.benchmarks` are ignored and must not be committed.

After pulling, confirm the exact head and clean state:

```powershell
git branch --show-current
git log -8 --oneline
git status --short
```

## Verified Before Handoff

- Full suite before the directory runner: `352 passed`.
- Directory benchmark helper tests: `4 passed`.
- Ruff passed for the new runner and helper tests.
- MCP, TuringDB, embedding, rerank, and GLiNER containers were healthy.
- Successful jobs removed all durable staging files.

### G220 real MCP test

- File: `G220_op_instr_0824_en-US.pdf`
- Bytes: `30,376,574`
- PDF pages: `830`
- Text pages: `828`
- Chunks: `841`
- Time to `queued`: `3.737 s`
- Time to `succeeded`: `114.174 s`
- Immediate search: 3 cited hits, including page-aware chunks.

### Italian legal document real MCP test

- File: `documento.pdf`
- Bytes: `3,386,217`
- PDF pages: `506`
- Text pages/chunks: `504 / 504`
- Time to `queued`: `1.021 s`
- Time to `succeeded`: `41.132 s`
- Immediate search: 3 cited hits; top hit contained Articles 1-3 on page 12.

These are observations from one run, not SLAs or a Mem0 comparison.

## Seven-File Corpus

The directory `D:\turing_AgentMemory_MCP\test` contained:

| File | Type | Bytes | Local conversion |
|---|---|---:|---|
| `Clienti.xlsx` | XLSX | 331,239 | MarkItDown, 603,136 chars |
| `Corso Base Robot.docx` | DOCX | 18,061 | MarkItDown, 1,752 chars |
| `Diario-ultimo.epub` | EPUB | 2,183,946 | MarkItDown, 65,378 chars |
| `documento.pdf` | PDF | 3,386,217 | PDFium, 506 pages |
| `G220_op_instr_0824_en-US.pdf` | PDF | 30,376,574 | PDFium, 830 pages |
| `Robot.pptx` | PPTX | 21,673,578 | MarkItDown, 25,720 chars |
| `wIKIPEDIA.url` | URL shortcut | 144 | MarkItDown, 139 chars |

All seven formats converted successfully. `Clienti.xlsx` may contain personal
or commercial data. Do not publish its questions, evidence, previews, or local
benchmark artifact.

## Directory Benchmark Status

Runner:

```text
scripts/real_document_benchmark.py
```

Test:

```text
tests/test_real_document_benchmark.py
```

Intended benchmark:

- ingest every supported file through remote MCP upload tools;
- use one isolated tenant and stable document IDs;
- generate 10 grounded questions per file with
  `inclusionai/ling-2.6-flash`;
- run 70 MCP `document_search` calls at `top_k=20`;
- report MRR@20 and recall@1/@3/@5/@10/@20 per file and overall;
- checkpoint only under ignored `.benchmarks`.

The first live attempt stopped before any upload or ingest. Ling returned an
`evidence_quote` that was not an exact normalized substring of the source. The
runner retried and failed with:

```text
BENCHMARK_FAILED evidence_quote must be an exact substring of its source passage
```

No benchmark JSON checkpoint was written and no seven-file benchmark tenant was
created by that attempt.

## First Task on the 12 GiB GPU PC

Make evidence grounding deterministic before rerunning:

1. Let Ling generate `source_id`, question, and answer.
2. Select the exact evidence quote in code from the labeled source passage,
   using answer/question token overlap across contiguous source sentences.
3. Reject weak overlap instead of accepting a paraphrase.
4. Keep the exact source substring as the retrieval gold evidence.
5. Add tests for punctuation, Unicode, spreadsheet rows, repeated short files,
   and no-overlap failure.

Do not weaken the benchmark by accepting arbitrary paraphrased evidence.

## Configure the New Machine

Copy secrets manually; never copy or commit the old `.env` through Git.

```powershell
Copy-Item .env.example .env
docker compose up -d turing-agentmemory-mcp
docker compose ps
Invoke-RestMethod http://127.0.0.1:8095/health
nvidia-smi
```

The last verified runtime health reported cloud provider identities:

```text
embedding: qwen/qwen3-embedding-4b, dimensions 768
rerank: cohere/rerank-4-pro
```

For a local-GPU benchmark, explicitly restore the Compose-local provider values
before ingesting a fresh scope:

```text
EMBED_BASE_URL=http://agentmemory-embed:8080
EMBED_MODEL=mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M
EMBED_DIMENSIONS=768
RERANK_BASE_URL=http://agentmemory-rerank:8080
RERANK_MODEL=Qwen3-Reranker-0.6B-q8_0.gguf
```

Do not compare scopes embedded by different models. Use a new
`user_identifier`, record `/health`, GPU memory, provider revisions, and all
benchmark parameters.

## Run After Fixing Evidence Grounding

```powershell
$env:PYTHONPATH='src'
python scripts\real_document_benchmark.py `
  --root "D:\turing_AgentMemory_MCP\test" `
  --mcp-url "http://127.0.0.1:8095/mcp/" `
  --question-model "inclusionai/ling-2.6-flash" `
  --question-count 10 `
  --top-k 20 `
  --search-concurrency 4 `
  --poll-seconds 10
```

The source content is sent to the configured embedding provider. Sampled
passages are sent to the question model. Confirm authorization before processing
`Clienti.xlsx`.

## Acceptance Gate

Do not call the directory benchmark complete until:

- all 7 jobs are `succeeded`;
- each job has a positive chunk count;
- all 70 questions are present and grounded in exact source evidence;
- all 70 searches completed or have explicit errors;
- per-file and aggregate MRR/recall are in the artifact;
- staging contains no files after success;
- the full test suite and Ruff pass;
- provider identity and GPU telemetry are recorded;
- publication docs use the measured result without unsupported competitor
  claims.

## Publication Work Already Added

The branch includes documentation for architecture, deployment, configuration,
MCP API, operations, security, performance, limitations, contributing, support,
release checks, and Hacker News preparation.

Hacker News explicitly discourages generated or AI-edited comments. The file
`docs/publication/HACKER_NEWS.md` is a fact sheet and writing prompt, not text to
paste into HN. The maintainer must write the discussion in their own voice and
must not solicit votes or comments.
