# Phase 3: TuringDB Retrieval Baseline - Research

**Researched:** 2026-07-13
**Domain:** Benchmark-artifact capture / snapshot engineering (no new product behavior)
**Confidence:** HIGH for I/O contracts and Docker mechanics (all verified by direct source read); MEDIUM/LOW where flagged for the D-07 harness-bug diagnosis and any field that depends on values in the (unread, gitignored) local `.env`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** The baseline is a **real** run against the real Dockerized stack with **real GPU embed/rerank providers** — not stub-only. `real_document_benchmark.py` runs against a live MCP + real providers on a real corpus.
- **D-02:** `e2e_score.py` also runs against **real providers** (`E2E_USE_EXTERNAL_EMBED=1` / `E2E_USE_EXTERNAL_RERANK=1`), not the in-process stubs. Consequence: the e2e number becomes provider-dependent, so the exact provider config MUST be pinned in the artifact (see D-11) for Phase 6 to reproduce.
- **D-03:** Windows note — `turingdb` has no Windows wheel; the current TuringDB stack runs under **Docker** to execute both scripts.
- **D-04:** The corpus is a **real Italian, multi-format document set** — PDF, XLSX, EPUB, and webpage/HTML. All four formats are confirmed ingestable (`real_document_benchmark.py:59-70` `SUPPORTED_SUFFIXES`; EPUB via MarkItDown's built-in `_epub_converter.py`, unaffected by `enable_plugins=False`).
- **D-05:** The user provides a **fixed `--root` path** to their existing Italian files. **OPEN INPUT — the path was not yet supplied. The planner/executor MUST obtain it from the user before running.**
- **D-06:** **Persist corpus as manifest + sha256 hashes only** (filenames, sizes, sha256, format, page/sheet counts) — NOT the file bytes.
- **D-07:** The committed e2e score is **known-inflated** (reports ~18/19; true ~14/19) via a `check()` harness bug + a document chunk-count mismatch — NOT embeddings, so switching to real providers does NOT fix it. Decision: **freeze the number as-is**, but additionally record **per-check pass/fail granularity** and explicitly document which checks are known-false-passing. Do NOT fix the harness this phase. Special caveat: the chunk-count check may not "cancel out" across Phase 4's re-chunking — call it out in the manifest.
- **D-08:** `real_document_benchmark.py` generates 10 questions/file via an LLM (nondeterministic). **Freeze the generated questions into the artifact**; Phase 6 **replays those exact questions** (no regeneration). Requires a **minimal additive change to `real_document_benchmark.py` to load a frozen-questions file** — must not alter generation/scoring for the baseline run itself.
- **D-09:** Committed baseline lives in a **top-level `baseline/03-turingdb/`** directory. Because `.benchmarks/` and `e2e-results.json` are gitignored, the artifact must be **force-added**.
- **D-10:** Format = **raw machine-readable JSON** (the scripts' own outputs + frozen questions + corpus manifest) **plus a human-readable manifest** (`baseline/03-turingdb/BASELINE.md`).
- **D-11 (mandatory metadata):** embed + rerank **model IDs, dims, and endpoints**; corpus manifest + sha256 hashes; the **frozen questions**; run params (`--top-k`, `--chunk-bytes`, `--poll-seconds`, `--scope`, `--question-model`, `--question-url`, `--search-concurrency`); the **git SHA** of the snapshot; and the **per-check e2e results** with the inflation caveats from D-07.
- **D-12:** Install this MCP into Claude Code and use the existing `skills/turing-agentmemory` skill to hands-on validate ingest + cited retrieval on the Italian corpus. Supplemental only — not the committed comparable baseline.

### Claude's Discretion

- Number of benchmark runs / variance recording (single frozen run vs N runs) — a single frozen run with pinned inputs is the default.
- Exact manifest schema/field names within the D-11 constraints.

### Deferred Ideas (OUT OF SCOPE)

- Fixing the e2e harness inflation (`check()` bug + chunk-count mismatch) — belongs to Phase 4+, where the CI threshold can be re-baselined.
- Adding EPUB/other-format ingestion improvements — not needed.
- Assembling a committed, self-contained Italian fixture corpus (vs. manifest-only) — declined on size/licensing grounds.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ARC-01 | Snapshot the current TuringDB retrieval baseline (`e2e_score.py` + `real_document_benchmark.py`) before any backend change — the yardstick for the correctness gate | §"Exact invocation against the Dockerized stack", §"Output schemas", §"D-11 reproducibility metadata map" below give the exact commands, exact output shapes, and exact metadata sourcing needed to produce and commit the artifact per SC#1-3. |

</phase_requirements>

## Summary

This is a snapshot/measurement phase, not a build phase: both engines (`scripts/e2e_score.py` and `scripts/real_document_benchmark.py`) already exist, already emit machine-readable JSON, and already accept every CLI knob D-11 requires. The work is (1) running them correctly against the real Dockerized stack with real GPU providers, (2) making one small additive change to `real_document_benchmark.py` to load frozen questions (D-08), and (3) assembling `baseline/03-turingdb/` with the raw JSON outputs, a corpus manifest, and a human-readable `BASELINE.md`.

Three landmines dominate the actual execution risk, and all three are easy to get wrong silently:

1. **`docker compose run --rm e2e` discards its own output.** The `e2e` service's `entrypoint` writes to `/tmp/e2e-results.json` inside the ephemeral container; `--rm` deletes the container (and that file) on exit. The fix is to append a second `--out /work/e2e-results.json` argument (argparse keeps the last value of a repeated flag), landing the file in the bind-mounted repo root (`compose.yaml:585-586`, `.:/work`).
2. **The `e2e` service does not inherit `EMBED_BASE_URL`/`RERANK_BASE_URL`/GLiNER config from the `turing-agentmemory-mcp` service block** — each Compose service has its own isolated `environment:` list, and `e2e`'s only declares 5 unrelated vars (`compose.yaml:587-592`). D-02's "real providers" mode requires explicitly passing `-e EMBED_BASE_URL=... -e RERANK_BASE_URL=...` (pointed at the already-running `agentmemory-embed`/`agentmemory-rerank` services by Compose DNS name) on the `docker compose run` command line. GLiNER is **not** toggled by `E2E_USE_EXTERNAL_*` at all and stays OFF by default in this container (`entity_extraction.py:229`, `_env_bool("GLINER_ENABLED")` defaults false) — the D-02 "real providers" run is real-embed + real-rerank, GLiNER-off, unless GLiNER env vars are also passed explicitly. This must be stated precisely in the D-11 provider-config metadata, not glossed as "real providers."
3. **`real_document_benchmark.py` is at 582/600 LOC** (`wc -l` confirmed) against the repo's hard, no-allowlist 600-LOC pre-commit cap (`scripts/check-file-size.sh:8,28`). The D-08 frozen-questions loader has only ~18 lines of headroom in this file. The loader/validation logic must live in `real_document_benchmark_scoring.py` (288/600 LOC, ample headroom); only a ~8-12 line call-site branch belongs in `real_document_benchmark.py` itself.

A fourth, non-blocking but important finding: if the real embed/rerank providers are unreachable when `e2e_score.py` runs, the run does not degrade gracefully — `run_mcp_checks` never executes at all (`e2e_score.py:93-96`), collapsing the result to `check_count=1`, `score=0.0`. A pre-flight health check on `agentmemory-embed`/`agentmemory-rerank` before invoking `docker compose run --rm e2e` is mandatory, not optional.

**Primary recommendation:** Bring the full stack up with `docker compose up -d`, run `real_document_benchmark.py` from the Windows host (it is an external MCP client, not a container-side script) against the exposed `127.0.0.1:8095` endpoint, then run `docker compose run --rm e2e` with explicit `-e` overrides for the real-provider endpoints and a corrected `--out` path, and assemble `baseline/03-turingdb/` from the two scripts' own JSON outputs — no new benchmark logic is needed, only correct invocation, one additive loader function, and careful metadata capture.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Retrieval-quality measurement (e2e checks) | API / Backend (in-process MCP + self-managed TuringDB) | — | `e2e_score.py` boots its own `TuringDaemon` subprocess and an in-process `fastmcp.Client` against `create_mcp_app(store)` — it does not talk to the `turingdb` or `turing-agentmemory-mcp` Compose services at all (`e2e_score.py:36-97`). |
| Real-document ingest + cited search measurement | API / Backend (live MCP over network) | Browser/CLI (script is an external client) | `real_document_benchmark.py` is a standalone script that connects to the already-running, Dockerized MCP via `fastmcp.Client(mcp_url)` over HTTP (`real_document_benchmark.py:509,320`) — it runs on the host, not inside a container. |
| Question generation (LLM) | External Backend (OpenRouter) | — | `QuestionGenerator` posts to `--question-url` (default `openrouter.ai`) using `PROVIDER_API_KEY` (`real_document_benchmark.py:98-172`). This is orthogonal to the retrieval stack under test. |
| Embed/rerank inference | GPU sidecar containers (`agentmemory-embed`, `agentmemory-rerank`) | — | Both `e2e_score.py` (via D-02 env override) and the live MCP (`turing-agentmemory-mcp` service) call out to these OpenAI-compatible HTTP endpoints; they are never the code under test in this phase. |
| Artifact storage | Database/Storage (git, forced) | — | `baseline/03-turingdb/` is a plain committed directory; no service tier involved — this is a pure documentation/version-control action (D-09). |

## Standard Stack

No new stack. This phase runs the project's own existing tooling:

| Tool | Version (confirmed) | Purpose | Why standard here |
|------|---------|---------|--------------------|
| `docker compose` | project's pinned `compose.yaml` | Bring up TuringDB + embed + rerank + GLiNER + MCP | Only way to exercise the real stack on Windows (D-03) |
| `scripts/e2e_score.py` (→ `src/turing_agentmemory_mcp/e2e_score.py`) | existing, unmodified | Deterministic 19-check MCP scenario score | Already the project's canonical quality gate |
| `scripts/real_document_benchmark.py` + `real_document_benchmark_scoring.py` | existing, +minimal D-08 additive change only | 10-question/file live-MCP retrieval benchmark | Already the project's canonical real-document benchmark |
| `git` | repo's own | `git rev-parse --short HEAD` for the D-11 snapshot SHA | Matches the existing pattern in `benchmark.py:254-269` (`_git_commit`) |

No new packages are introduced by this phase.

### Alternatives Considered

Not applicable — CONTEXT.md's D-01 through D-12 already lock the approach; there is no library/stack choice left to make.

**Installation:** none — no new dependency.

## Package Legitimacy Audit

**Not applicable.** This phase installs no new external packages. The only code change is an additive function in an existing, already-installed module (`real_document_benchmark_scoring.py`). Skip the legitimacy gate.

## Architecture Patterns

### System Architecture Diagram — how the two scripts actually relate to the Compose stack

```
┌─────────────────────────── Windows host ───────────────────────────┐
│                                                                      │
│  scripts/real_document_benchmark.py  (runs HERE, not in a container)│
│    1. reads --root (Italian corpus) directly off local disk         │
│    2. convert_document_to_markdown() locally (pdfium/MarkItDown)    │
│    3. QuestionGenerator -> OpenRouter (external, real API key)      │
│    4. fastmcp.Client("http://127.0.0.1:8095/mcp/")  ───────────┐    │
│                                                                  │    │
└──────────────────────────────────────────────────────────────┼────┘
                                                                  │ HTTP (exposed port)
┌─────────────────────────── Docker Compose network ─────────────▼───┐
│                                                                      │
│  turing-agentmemory-mcp (port 8095->8080)                           │
│    depends_on: turingdb, agentmemory-embed, agentmemory-rerank,     │
│                 agentmemory-gliner  (all service_healthy)           │
│    -> document_upload_* / document_ingest_status / document_search  │
│                                                                      │
│  turingdb (6666)      agentmemory-embed (GPU)   agentmemory-rerank  │
│                        (GPU)      agentmemory-gliner (CPU)          │
│                                                                      │
│  ─────────────────────────────────────────────────────────────     │
│  e2e (profile "e2e", one-off `docker compose run --rm e2e`)         │
│    - spins up its OWN embedded TuringDaemon subprocess              │
│      (does NOT talk to the `turingdb` service above)                │
│    - by default spins up in-process stub embed/rerank HTTP servers  │
│      UNLESS E2E_USE_EXTERNAL_EMBED=1 / E2E_USE_EXTERNAL_RERANK=1    │
│      are passed AND EMBED_BASE_URL/RERANK_BASE_URL are explicitly   │
│      pointed at agentmemory-embed:8080 / agentmemory-rerank:8080    │
│      (its own environment: block does NOT set these — compose.yaml │
│      577-593)                                                       │
│    - GLiNER is never wired for this container regardless of the     │
│      E2E_USE_EXTERNAL_* flags (entity_extraction.py:229)            │
└──────────────────────────────────────────────────────────────────────┘
```

A reader can trace both primary flows end to end: the real-document benchmark enters from the Windows host and crosses into the Docker network only over the exposed MCP HTTP port; the e2e score gate never leaves its own one-off container except to reach the GPU embed/rerank sidecars when D-02's real-provider mode is wired in explicitly.

### Recommended artifact layout (D-09/D-10)

```
baseline/03-turingdb/
├── BASELINE.md                     # human-readable manifest (D-10, D-11 fields)
├── e2e-results.json                # raw output of docker compose run --rm e2e (D-02 real-provider mode)
├── real-document-benchmark.json    # raw output of real_document_benchmark.py (D-01)
├── frozen-questions.json           # extracted per-document questions for Phase 6 replay (D-08)
└── corpus-manifest.json            # filenames + sha256 + format + page/sheet counts, NOT bytes (D-06)
```

`corpus-manifest.json` and `frozen-questions.json` do not need new generation code — both are trivial post-processing extractions from the `documents[]` array already present in `real-document-benchmark.json` (see "Output schemas" below).

### Pattern: additive frozen-questions load path (D-08)

**What:** A `--frozen-questions <path>` CLI flag that, when present, makes `real_document_benchmark.py` load a pre-existing per-file question set instead of calling `QuestionGenerator.generate()` / `parse_generated_questions()` / `select_evidence()` for that file.

**When to use:** Only for the Phase 6 replay run (out of scope for this phase's own execution, but the loader must exist by the end of this phase per D-08). This phase's own baseline run uses the normal generation path (no `--frozen-questions` passed) and then extracts the resulting `questions` from its own output into `frozen-questions.json` for Phase 6 to consume later.

**Exact, minimal hook point** — `scripts/real_document_benchmark.py:406-507` (`run()`), specifically the per-file loop at `:460-507`:

```python
# Current (real_document_benchmark.py:468-473), inside `for path in files:`
questions, usage = await asyncio.to_thread(
    generator.generate,
    filename=path.name,
    passages=passages,
    count=args.question_count,
)
```

Minimal additive change (add ~1-2 lines to argparse at `:73-95`, ~1 line near the imports at `:30-55` to also import the new loader, ~1 line before the loop to build `frozen = load_frozen_questions(Path(args.frozen_questions)) if args.frozen_questions else None`, and replace the block above with):

```python
if frozen is not None:
    questions = frozen[path.name]
    usage = {"frozen": True, "prompt_tokens": 0, "completion_tokens": 0, "attempt": 0}
else:
    questions, usage = await asyncio.to_thread(
        generator.generate, filename=path.name, passages=passages, count=args.question_count,
    )
```

`select_passages(...)` (currently unconditional at `:463-467`) should move inside the `else` branch — it exists only to feed `generator.generate`, and skipping it in frozen mode avoids unnecessary compute and an unnecessary dependency on `converted.text` shape matching a previous run.

**Where the loader itself belongs:** `scripts/real_document_benchmark_scoring.py` (288/600 LOC — ample headroom), a new function alongside the existing `parse_generated_questions`:

```python
def load_frozen_questions(path: Path) -> dict[str, list[dict[str, str]]]:
    """Load a previously-frozen per-file question set (D-08). Raises ValueError on
    schema mismatch so a corrupted/incompatible freeze fails loudly, not silently."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_file = payload.get("questions_by_document")
    if not isinstance(by_file, dict) or not by_file:
        raise ValueError("frozen-questions file has no questions_by_document mapping")
    for filename, rows in by_file.items():
        if not isinstance(rows, list) or not all(
            isinstance(row, dict) and {"source_id", "question", "answer", "evidence_quote"} <= row.keys()
            for row in rows
        ):
            raise ValueError(f"frozen questions for {filename} are malformed")
    return by_file
```

**Recommended frozen-questions.json schema** (matches what Phase 6 will load and what this phase extracts from its own run):

```json
{
  "schema_version": 1,
  "source_benchmark_id": "real-documents-direct-mcp-<timestamp>",
  "questions_by_document": {
    "<filename>": [
      {"source_id": "S1", "question": "...", "answer": "...", "evidence_quote": "..."}
    ]
  }
}
```

Keying by `filename` (not `document_id`) is deliberate: `document_id` is computed as `f"{safe_id(path.stem)}-{sha256[:12]}"` (`real_document_benchmark.py:482`) only *after* `file_digest()` runs later in the same loop iteration than question generation — using `document_id` as the lookup key would force reordering `file_digest()` earlier, a larger diff than necessary. `filename` is already known before the loop body executes and is unique under a fixed `--root` (D-05).

**LOC budget warning:** `real_document_benchmark.py` is 582/600 lines today (`wc -l` verified). `scripts/check-file-size.sh` enforces the 600 cap with **no allowlist** on every tracked `*.py` file (`check-file-size.sh:8,28-30`) via `lefthook` pre-commit. The plan MUST keep the net diff to this file at or under ~15 lines and push all loader/validation logic into `real_document_benchmark_scoring.py` instead, then re-run `bash scripts/check-file-size.sh` as a verification step before committing.

### Anti-Patterns to Avoid

- **Trusting `make docker-e2e` / `docker compose run --rm e2e` as-is for baseline capture.** Its `entrypoint` writes to `/tmp/e2e-results.json`, which is destroyed by `--rm` (see Pitfall 1 below). Always override `--out` to a path under the bind-mounted `/work`.
- **Assuming `E2E_USE_EXTERNAL_EMBED=1` alone is sufficient.** It only stops the container from starting its own stub server; it does nothing to point `EMBED_BASE_URL` at a real endpoint. Both the flag and the URL/dimensions/model env vars must be supplied together.
- **Treating a `FAILED_SCORE_GATE` verdict from `e2e_score.py` as a script bug.** The gate literal (`score >= 9.8 and check_count == 19`, `e2e_score.py:135,153`) is a CI convenience threshold unrelated to whether the *baseline capture* succeeded. D-07 already accepts an inflated-but-frozen score; the plan should capture the JSON regardless of `verdict`/`main()`'s exit code (do not gate the baseline-capture step on `main()`'s process exit code — parse and store the JSON body).
- **Running `real_document_benchmark.py` inside a container.** There is no Compose service for it; it is designed as an external client script run from the operator's machine (confirmed: no `real_document_benchmark` reference anywhere in `compose.yaml`, and `01-CONTEXT.md`/CI decisions explicitly keep it out of CI as an "operator-run tool").

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Corpus manifest generation | A new script to walk `--root` and hash files | Extract `documents[].{filename,suffix,bytes,sha256,conversion.page_count}` directly from `real-document-benchmark.json`'s own output | `real_document_benchmark.py` already computes `sha256`/`bytes` via `file_digest()` (`real_document_benchmark_scoring.py:141-148`) and `page_count` via `conversion.page_count` (`real_document_benchmark.py:486`) for every ingested file — it IS the manifest source of truth already |
| Per-check pass/fail extraction | A parser/reducer over `e2e-results.json` | Just read the existing `checks` array directly | Already full-fidelity: `{name, ok, points, elapsed_ms, detail|error}` per check (`e2e_score_scenarios.py:39-61`); nothing needs to be re-derived |
| Git-SHA capture helper | A new git-shelling function | `git rev-parse --short HEAD` | Already the exact pattern used by `benchmark.py:254-269`'s `_git_commit()` |

**Key insight:** every piece of D-11's mandatory metadata is already a byproduct of the two scripts' existing JSON output or a one-line shell command — this phase is assembly and correct invocation, not new tooling.

## Runtime State Inventory

Not applicable — this phase renames/migrates nothing. Skipped per instructions (greenfield/snapshot phase, no rename/refactor).

## Common Pitfalls

### Pitfall 1: `docker compose run --rm e2e` silently discards the results file
**What goes wrong:** The `e2e` service's `entrypoint` is `["python", "scripts/e2e_score.py", "--out", "/tmp/e2e-results.json"]` (`compose.yaml:584`). `docker compose run --rm` removes the container on exit, and `/tmp` inside that container is never bind-mounted (only `.:/work` is, `compose.yaml:586`) — the JSON file is gone the instant the command finishes.
**Why it happens:** `Makefile`'s `docker-e2e` target (`docker compose run --rm e2e`) is designed for a quick pass/fail check via the printed JSON on stdout (`main()` also `print`s the result, `e2e_score.py:152`) — the file path was never meant to persist for CI's stub-floor use case.
**How to avoid:** Append a second `--out` argument on the command line — Docker appends extra `docker compose run` arguments after the fixed `entrypoint`, and Python's `argparse` keeps the *last* occurrence of a single-value flag, so `docker compose run --rm e2e --out /work/e2e-results.json` actually runs `python scripts/e2e_score.py --out /tmp/e2e-results.json --out /work/e2e-results.json`, landing the file at `/work/e2e-results.json` → the repo root on the host.
**Warning signs:** `docker compose run --rm e2e` exits with output printed to stdout but no `e2e-results.json` appears in the repo afterward.

### Pitfall 2: `E2E_USE_EXTERNAL_EMBED=1` alone does not reach real providers
**What goes wrong:** Setting only the two `E2E_USE_EXTERNAL_*` flags stops the container from spinning up its in-process `LocalEmbedServer`/`LocalRerankServer` (`e2e_score.py:57-67`), but does **not** set `EMBED_BASE_URL`/`RERANK_BASE_URL` to anything — those must already be present in the container's environment, and the `e2e` Compose service's own `environment:` block (`compose.yaml:587-592`) does not define them (unlike the `turing-agentmemory-mcp` service block at `compose.yaml:151-170`, which is a *separate* service with its own isolated env).
**Why it happens:** Each Compose service has an independently scoped `environment:` list; there is no inheritance between `turing-agentmemory-mcp` and `e2e` even though they share the same built image.
**How to avoid:** Pass every needed var explicitly: `docker compose run --rm -e E2E_USE_EXTERNAL_EMBED=1 -e E2E_USE_EXTERNAL_RERANK=1 -e EMBED_BASE_URL=http://agentmemory-embed:8080 -e EMBED_DIMENSIONS=768 -e EMBED_MODEL=mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M -e RERANK_BASE_URL=http://agentmemory-rerank:8080 -e RERANK_MODEL=Qwen3-Reranker-0.6B-q8_0.gguf e2e --out /work/e2e-results.json` (values sourced from `compose.yaml`'s own defaults at `:151-160`/`:159-170`; confirm live values are unchanged via `docker compose exec turing-agentmemory-mcp env | grep -E "EMBED_|RERANK_"` since `.env` can override the compose defaults and is not readable by this research pass).
**Warning signs:** `e2e-results.json`'s first check succeeds but reports `embedding_base_url`/`rerank_base_url` still pointing at `127.0.0.1:<random-port>` (the stub server signature) instead of the `agentmemory-embed`/`agentmemory-rerank` hostnames.

### Pitfall 3: unreachable real providers collapse the e2e run to 1 check, not a partial/degraded run
**What goes wrong:** `run_e2e`'s `start_infra()` (`e2e_score.py:69-91`) only assigns `store_holder["store"]` *after* `store.embedder.embed(...)` and `store.reranker.rerank(...)` both succeed. If the real GPU embed/rerank sidecars are not yet healthy, this raises, `check()` catches it and records exactly one failing check, and the guard `if store is not None:` (`e2e_score.py:94`) skips `run_mcp_checks` (all 18 scenario checks) entirely — the artifact becomes `check_count=1, score=0.0`, not "18/19 checks still ran, 1 failed."
**Why it happens:** The gate is intentionally fail-fast on infra bring-up so a broken provider never masquerades as a partial pass.
**How to avoid:** Verify `agentmemory-embed`/`agentmemory-rerank` report healthy (`docker compose ps` shows `healthy`, per their healthchecks at `compose.yaml:369-374`/`:508-513`) *before* invoking `docker compose run --rm e2e`.
**Warning signs:** `e2e-results.json`'s `check_count` is `1` instead of `19`.

### Pitfall 4: the `real_document_benchmark.py` default `--root` points at a gitignored directory
**What goes wrong:** The script's own default (`--root` = `r"D:\turing_AgentMemory_MCP\test"`, `real_document_benchmark.py:75`) resolves to `test/`, which is gitignored (`.gitignore:18`, `test/*`). D-05's real Italian corpus path is a different, user-supplied directory anyway, but this default is a trap if the operator forgets to pass `--root` explicitly.
**Why it happens:** The default was clearly meant for local ad hoc testing, not baseline capture.
**How to avoid:** Always pass `--root <italian-corpus-path>` explicitly (D-05's open input) and confirm the path exists before the ~10-30 minute run starts (LLM question generation + GPU ingestion for 4+ documents takes real wall-clock time).

### Pitfall 5: two overlapping "harness inflation" phenomena must not be conflated (D-07)
**What goes wrong:** `PROJECT.md` (Phase 1 completion note) documents an **18/19 (score 9.474)** result attributed to "a pre-existing `HashingEmbedder`-stub limitation on one semantic document-search check" — this is the **stub-mode** CI floor, fixed by using real embeddings (which D-02 already mandates for this baseline). CONTEXT.md's **D-07** separately documents a **different, harness-side** inflation ("check() harness bug + document chunk-count mismatch... NOT embeddings, so switching to real providers does NOT fix it... true ~14/19"). These are two distinct claims about two different failure classes and must not be merged into one explanation in `BASELINE.md`.
**Why it happens:** Both produce a similar-looking "not quite 19/19" number, but for unrelated reasons — one is provider quality, the other is checker-logic fragility.
**How to avoid:** Document both explicitly and separately in `BASELINE.md`'s caveats section (see "D-07 candidate false-positive checks" below); do not average or combine them into a single sentence.
**Warning signs:** A future reader assumes "switching to real providers already fixed the D-07 concern" — it does not, by CONTEXT.md's own words.

## Code Examples

### Extracting per-check granularity (D-07) — already emitted, no new code needed

```python
# e2e-results.json top level (src/turing_agentmemory_mcp/e2e_score.py:134-142)
{
  "verdict": "VALIDATED_10_10" | "FAILED_SCORE_GATE",
  "score": <float, 0.0-10.0>,
  "score_gate": "10/10",
  "check_count": <int>,
  "turingdb_version": "<str>",
  "checks": [
    {
      "name": "<check name, e.g. document_ingest_text_writes_chunks>",
      "ok": <bool>,
      "points": 1.0,
      "elapsed_ms": <float>,
      "detail": <whatever the check lambda returned>,   # present when ok
      "error": {"type": "<ExceptionClass>", "message": "<str, truncated to 1000 chars>"}  # present on exception
    },
    ...  # 19 entries total when the run is not aborted early (Pitfall 3)
  ],
  "cleanup": {"stopped": <bool>, "returncode": <int>}
}
```

Simply capture the whole JSON verbatim as `baseline/03-turingdb/e2e-results.json`; every per-check field D-07 needs is already there.

### D-07 candidate false-positive checks (code-verified pattern, interpretation flagged [ASSUMED])

Three checks in `e2e_score_scenarios.py` use `all(... for ... in <possibly-empty-list>)`, which is vacuously `True` over an empty collection — a classic false-positive shape for this style of harness:

- `memory_search_does_not_leak_bob` (`:181-183`) — `all(row["user_identifier"] == "alice" for row in alice_search)` is the check's **entire** condition (not ANDed with anything else); if `alice_search` were ever empty, this check reports `ok: True` while validating nothing.
- `memory_delete_hides_memory_from_get_and_search` (`:330-336`) — the `all(row["id"] != duplicate_first["id"] for row in deleted_search)` clause is one of three ANDed conditions, so it is lower-risk but still has the same shape.
- `document_reindex_text_replaces_old_chunks_and_metadata` (`:515-525`) — same pattern (`all("Monthly maintenance records" not in row["text"] for row in stale_hits)`), also one of several ANDed conditions.

Two checks hardcode an exact `chunk_count`, which is what D-07 calls the "document chunk-count mismatch" — fragile precisely because Phase 4's re-chunking (ARC-04/ARC-05) may legitimately change these numbers without indicating a regression:

- `document_ingest_text_writes_chunks` (`:360-364`) asserts `doc["chunk_count"] == 3`.
- `document_reindex_text_replaces_old_chunks_and_metadata` (`:515-525`) asserts `reindexed_doc["chunk_count"] == 2`.

**[ASSUMED]** These five checks are my best code-level candidates for the "check() harness bug + chunk-count mismatch" and the ~18-vs-~14 gap D-07 references; I could not find a document in this repo that names the exact checks or reproduces the ~14/19 count independently (searched `PROJECT.md`, `CHANGELOG.md`, all `01-*` phase docs, `STATE.md`). This interpretation should be confirmed against whatever the user's own D-07 analysis found before `BASELINE.md`'s caveat text is finalized — see Assumptions Log.

### Exact invocation against the Dockerized stack (Windows host)

```powershell
# 1. Bring up the full stack (turingdb, embed, rerank, gliner, mcp; lab optional)
docker compose up -d turingdb agentmemory-embed agentmemory-rerank agentmemory-gliner turing-agentmemory-mcp
docker compose ps   # confirm all report healthy before proceeding

# 2. Real-document benchmark — runs on the HOST, not in a container (D-01)
#    (requires `pip install -e ".[dev]"` locally so fastmcp/markitdown/pypdfium2 are importable)
python scripts/real_document_benchmark.py `
  --root "<ITALIAN CORPUS PATH — D-05 open input>" `
  --mcp-url "http://127.0.0.1:8095/mcp/" `
  --output "baseline/03-turingdb/real-document-benchmark.json" `
  --top-k 20 `
  --chunk-bytes 524288 `
  --poll-seconds 10 `
  --search-concurrency 4 `
  --question-model "inclusionai/ling-2.6-flash" `
  --question-url "https://openrouter.ai/api/v1/chat/completions" `
  --env-file ".env"

# 3. E2E score gate — runs INSIDE Docker (D-03), real providers (D-02), corrected output path (Pitfall 1)
docker compose run --rm `
  -e E2E_USE_EXTERNAL_EMBED=1 `
  -e E2E_USE_EXTERNAL_RERANK=1 `
  -e EMBED_BASE_URL=http://agentmemory-embed:8080 `
  -e EMBED_DIMENSIONS=768 `
  -e EMBED_MODEL="mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M" `
  -e RERANK_BASE_URL=http://agentmemory-rerank:8080 `
  -e RERANK_MODEL="Qwen3-Reranker-0.6B-q8_0.gguf" `
  e2e --out /work/e2e-results.json
# result lands at ./e2e-results.json on the host (bind mount) -> copy/move into baseline/03-turingdb/
```

`--output` is not a documented flag name in `real_document_benchmark.py`'s argparse (`:73-95` uses `--output`, confirmed present) — verified it is spelled `--output`, not `--out` (that spelling is only `e2e_score.py`'s flag). Do not conflate the two scripts' differently-named output-path flags in the plan.

## State of the Art

Not applicable — both scripts already represent this project's current, intended measurement approach; nothing here has changed recently that the planner needs to account for.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The five checks identified (vacuous `all()` over 3 checks; hardcoded `chunk_count` in 2 checks) are the specific checks D-07 means by "check() harness bug + document chunk-count mismatch," and together explain the ~18-vs-~14 gap | Common Pitfalls #5, Code Examples "D-07 candidate false-positive checks" | If wrong, `BASELINE.md`'s documented caveats point at the wrong checks, and Phase 6's per-check diff may treat a truly-regressed check as "already known-flaky" (masking a real regression) or vice versa. Executor should re-run the stub-mode e2e once (`docker compose run --rm e2e --out /work/e2e-results.json`, no `-e` overrides) and manually inspect which of the 19 `checks[].name` entries have `ok: false` or a suspicious `detail`, to corroborate before finalizing the caveat text. |
| A2 | `EMBED_MODEL`/`RERANK_MODEL`/`EMBED_DIMENSIONS` compose.yaml defaults (`mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M`, `Qwen3-Reranker-0.6B-q8_0.gguf`, `768`) are the values actually in effect, not overridden by a local, unreadable `.env` | Code Examples "Exact invocation", Pitfall 2 | If the operator's `.env` overrides these, the D-11 metadata would record the wrong model IDs. Mitigate by running `docker compose exec turing-agentmemory-mcp env \| grep -E "EMBED_\|RERANK_"` (or `docker compose config`) at execution time and recording the LIVE values, not the compose-file defaults quoted here. |
| A3 | `turingdb` genuinely has no Windows wheel (D-03's stated reason for Docker-only execution) | User Constraints (locked decision, not re-derived) | Low risk — this is an explicitly locked CONTEXT.md decision, not something this research re-verified; included here only for completeness since I could not independently confirm it (no local venv/wheel cache present to inspect, and the package is not on public PyPI under an obviously-checkable name in this session). |

## Open Questions

1. **Which sha256/manifest fields exactly does D-06 want beyond what `real_document_benchmark.py` already emits?**
   - What we know: the script's own `documents[]` array already has `filename`, `suffix`, `bytes`, `sha256`, and (for PDFs) `conversion.page_count` per file (`real_document_benchmark.py:474-492`). XLSX "sheet counts" are not currently captured anywhere in the existing output (MarkItDown's conversion metadata doesn't expose sheet count in `document_processing.py:82-89`).
   - What's unclear: whether the plan needs a small additional step to compute XLSX sheet counts (e.g., via `openpyxl` if already a transitive dep, or accept "not captured" as a documented gap).
   - Recommendation: confirm with the user whether "page/sheet counts" (D-06's literal wording) is a hard requirement or aspirational; if hard, a one-off manifest-only helper (outside the two frozen scripts, so it doesn't touch the LOC-constrained files) can compute it separately using `openpyxl.load_workbook(path, read_only=True).sheetnames`.

2. **Does the Italian corpus (D-05) need to be reachable a second time for Phase 6, and is that guaranteed?**
   - What we know: D-06 explicitly accepts this risk ("Phase 6 re-points `--root` at the same files; reproducibility depends on those files still existing").
   - What's unclear: nothing technical — this is a process/ownership question, not a research gap.
   - Recommendation: `BASELINE.md` should state the exact absolute `--root` path used, so Phase 6 has an unambiguous re-pointing target.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Compose | Entire baseline run (D-03) | Assumed ✓ (project's primary dev workflow per CLAUDE.md) | project's pinned `compose.yaml` | None — hard requirement, no fallback (D-03 is locked) |
| NVIDIA GPU visible to Docker | `agentmemory-embed`/`agentmemory-rerank` real providers (D-01/D-02) | Not verified this session (no way to probe GPU visibility from this research pass) | — | None — D-01/D-02 explicitly require real GPU providers, not stubs; if GPU is unavailable, the baseline as specified cannot be captured and the planner must escalate to the user rather than silently falling back to stub mode |
| Python host venv with project installed (`pip install -e ".[dev]"`) | Running `real_document_benchmark.py` on the Windows host (D-01) | Not verified this session (no `.venv` found in the working directory at research time) | — | None — required to import `fastmcp`, `markitdown`, `pypdfium2`, `turing_agentmemory_mcp.document_processing` locally |
| `PROVIDER_API_KEY` (OpenRouter) in `.env` | Question generation (D-08 baseline run) | Not verified — `.env` is git-ignored and denied to this research session's file-read tools | — | None — question generation cannot proceed without it; must be supplied by the operator before running |
| Italian corpus directory (D-05) | `--root` for `real_document_benchmark.py` | **Not supplied** — explicit OPEN INPUT | — | None — execution precondition; the plan must include an explicit "obtain `--root` path from user" step before the benchmark run task |

**Missing dependencies with no fallback:**
- GPU visibility, host Python venv readiness, `PROVIDER_API_KEY`, and the Italian corpus path are all execution preconditions that must be verified/obtained before the benchmark-running task starts, not assumed.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.2+ (existing; `pyproject.toml` `testpaths=tests`, `pythonpath=src`) |
| Config file | `pyproject.toml` (existing) |
| Quick run command | `python -m pytest tests/test_real_document_benchmark.py -q` |
| Full suite command | `python -m pytest -q` |

### Phase Requirements → Test Map

This phase's sole requirement (ARC-01) is an *artifact-capture* requirement, not new application behavior — the bulk of its verification is evidentiary (does the committed artifact exist, is it complete, does it reproduce) rather than unit-testable. The one piece of new *code* (the D-08 frozen-questions loader) does need a conventional unit test.

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ARC-01 (code) | `load_frozen_questions()` parses a valid frozen file and rejects a malformed one | unit | `pytest tests/test_real_document_benchmark.py::test_load_frozen_questions_round_trips -x` | ❌ Wave 0 — new test, new function |
| ARC-01 (code) | `--frozen-questions` bypasses `QuestionGenerator.generate()` for a given file (no network call attempted) | unit (monkeypatch `generator.generate` to raise if called) | `pytest tests/test_real_document_benchmark.py::test_frozen_questions_skip_generation -x` | ❌ Wave 0 — new test |
| ARC-01 (artifact) | `baseline/03-turingdb/` contains all 5 files (BASELINE.md, e2e-results.json, real-document-benchmark.json, frozen-questions.json, corpus-manifest.json) and each is valid JSON (except BASELINE.md) | smoke / manual-verify | `python -c "import json,pathlib; [json.loads(pathlib.Path(p).read_text()) for p in pathlib.Path('baseline/03-turingdb').glob('*.json')]"` | ❌ Wave 0 — no such check exists yet; a one-line CLI smoke check, not a pytest file |
| ARC-01 (artifact) | `e2e-results.json` has `check_count` present and, if it is not 19, the shortfall is explained in `BASELINE.md` (Pitfall 3) | manual-verify | inspect `checks` array length | — human judgment (documented reasoning, not automatable) |
| ARC-01 (artifact) | The baseline is committed via `git add -f baseline/03-turingdb/` before any ArcadeDB code lands (SC#3) | manual-verify / git-log check | `git log --oneline -- baseline/03-turingdb/` predates the first ArcadeDB-touching commit | — verified at Phase 4 kickoff, not at Phase 3 completion |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_real_document_benchmark.py -q` (fast, no live MCP/network needed for the two new unit tests)
- **Per wave merge:** `python -m pytest -q` plus the artifact-existence smoke check above
- **Phase gate:** Full suite green; `baseline/03-turingdb/` present and force-added; `BASELINE.md` cites every D-11 field

### Wave 0 Gaps
- [ ] `tests/test_real_document_benchmark.py::test_load_frozen_questions_round_trips` — new test for the new `load_frozen_questions()` helper
- [ ] `tests/test_real_document_benchmark.py::test_frozen_questions_skip_generation` — new test proving the D-08 bypass actually bypasses generation (not just a schema check)
- [ ] No framework install needed — pytest already configured and green (364 tests per `PROJECT.md`)

## Security Domain

`security_enforcement: true` in `.planning/config.json`, so this section is required, but this phase introduces no new attack surface: no new endpoint, no new auth path, no new persisted user data beyond what the existing MCP already handles. The only new code is a local, offline JSON-file loader.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No new auth path; the benchmark script uses the existing (possibly disabled) MCP auth exactly as configured today |
| V3 Session Management | No | N/A |
| V4 Access Control | No | No new tool/endpoint; `user_identifier` scoping in the benchmark run uses the existing `document_search`/`document_upload_*` tools unchanged |
| V5 Input Validation | Yes (narrow) | The new `load_frozen_questions()` must validate the loaded JSON's shape (`schema_version`, required keys per question row) and raise `ValueError` on malformation rather than silently producing empty/partial question sets — see the Code Example above |
| V6 Cryptography | No | No new crypto; sha256 usage for the corpus manifest is for content-addressing/dedup, not a security boundary |

### Known Threat Patterns for this phase's stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| A `PROVIDER_API_KEY` (real OpenRouter key) accidentally committed via a captured artifact or log | Information Disclosure | `real_document_benchmark.py`'s own artifact already carries a `privacy_note` warning it may contain source evidence and is gitignored (`real_document_benchmark.py:443-447`); the plan must NOT force-add `.benchmarks/*.json` or any file containing the raw question-generation payloads/API responses — only the curated `baseline/03-turingdb/` files (which do not include API keys) should be force-added |
| Corpus content (Italian source documents) leaking into the committed baseline | Information Disclosure | D-06 already mandates manifest+sha256 only, not bytes — enforced by construction if the plan builds `corpus-manifest.json` by extracting only `{filename,suffix,bytes,sha256,page_count}` fields and never copies source file contents into `baseline/` |
| Malformed/adversarial frozen-questions JSON (e.g., from a future compromised or corrupted freeze) silently producing an empty or wrong question set at Phase 6 replay time | Tampering | `load_frozen_questions()`'s schema validation (raise `ValueError` on any malformed row) — see Code Example |

## Sources

### Primary (HIGH confidence — verified directly against source in this repository)
- `scripts/real_document_benchmark.py` (full read) — CLI args, output schema, per-file loop, upload/poll/search flow
- `scripts/real_document_benchmark_scoring.py` (full read) — `summarize_results`, `file_digest`, `parse_generated_questions`, `select_evidence`
- `src/turing_agentmemory_mcp/e2e_score.py` (full read) — `run_e2e`, gate literal, E2E_USE_EXTERNAL_* handling
- `src/turing_agentmemory_mcp/e2e_score_scenarios.py` (full read) — all 19 checks, `check()` harness function
- `src/turing_agentmemory_mcp/e2e_score_stubs.py` (full read) — `TuringDaemon`, `LocalEmbedServer`/`LocalRerankServer` (HashingEmbedder-backed)
- `src/turing_agentmemory_mcp/entity_extraction.py:229` — `GLINER_ENABLED` default-off gate
- `src/turing_agentmemory_mcp/document_processing.py` (full read) — PDFium/MarkItDown conversion, no sheet-count field
- `compose.yaml` (full read) — every service's env block, healthchecks, `e2e` service entrypoint/volumes
- `Dockerfile` (full read) — `WORKDIR /app`, confirms `/work` bind mount is not the cwd
- `Makefile` — confirms `docker-e2e` = `docker compose run --rm e2e` verbatim
- `scripts/check-file-size.sh` (full read) — 600-LOC cap mechanics, `wc -l`-based, no allowlist
- `.gitignore` (full read) — lines 13-15 confirm `.turingdb/`, `.benchmarks/`, `e2e-results.json` gitignored
- `CONTRIBUTING.md`, `CLAUDE.md`, `.claude/CLAUDE.md` — project conventions, DoD, invariants
- `.planning/phases/03-turingdb-retrieval-baseline/03-CONTEXT.md`, `03-DISCUSSION-LOG.md` — locked decisions and rationale
- `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`, `.planning/PROJECT.md` — requirement/phase mapping and prior-phase measured numbers (9.474/18/19 stub baseline)
- `src/turing_agentmemory_mcp/benchmark.py:254-284` — existing git-SHA capture pattern to reuse
- `tests/test_real_document_benchmark.py` (full read) — confirms no existing test touches `run()`/CLI, so the D-08 additive change is safe to make
- `skills/turing-agentmemory/SKILL.md`, `references/operations.md` — D-12 hands-on validation reference material

### Secondary (MEDIUM confidence)
- None used — no web search was needed; this phase's research is entirely codebase-internal per the task's explicit framing ("this CONTEXT.md is exceptionally complete... your value is pinning down exact I/O contracts").

### Tertiary (LOW confidence / [ASSUMED])
- The specific identification of which checks constitute D-07's "check() harness bug" and the ~14/19 true-pass figure (Assumption A1) — code-pattern-verified but not independently confirmed against the original analysis behind D-07's wording.
- `.env` contents (API keys, any provider-config overrides) — file is gitignored and denied to this research session; assumed to match `compose.yaml` defaults unless the operator states otherwise (Assumption A2).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new stack; every tool/script already exists and was read in full
- Architecture / invocation mechanics: HIGH — every Docker/Compose/argparse claim was verified against the actual files, not inferred
- D-07 harness-bug diagnosis: MEDIUM/LOW — code-pattern-verified candidates, but the exact "true ~14/19" figure and which checks it refers to is an inference, flagged in the Assumptions Log for user confirmation
- Pitfalls: HIGH — all five are directly traceable to specific file/line evidence, not general best-practice guesses

**Research date:** 2026-07-13
**Valid until:** Effectively indefinite for the mechanics documented here (they describe the current, pre-port TuringDB stack, which by design will not change again before this phase runs — ARC-01's entire premise is capturing it before drift). Treat as stale only if `compose.yaml`, `e2e_score.py`, or `real_document_benchmark.py` are touched by any other work before this phase executes.
