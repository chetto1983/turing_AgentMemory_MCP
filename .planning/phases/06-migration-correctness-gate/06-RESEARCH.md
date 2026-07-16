# Phase 6: Migration-Correctness Gate - Research

**Researched:** 2026-07-16
**Domain:** Retrieval-quality measurement / GO-NO-GO gate authoring (no new library/framework surface — this is code-archaeology + comparison-logic research against an existing repo)
**Confidence:** HIGH (every claim below is either read directly from source at HEAD, computed from the committed baseline JSON with a one-off script, or confirmed via `git log`/`git show`/`git merge-base`; no external library research was needed for this phase's domain)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 — Bug-corrected bar (LOCKED):** The ArcadeDB port's full 12-document corpus retrieval numbers must meet-or-exceed the baseline's bug-corrected "meaningful" 7-doc figures (~0.60 MRR@20 / ~0.77 recall@20) — NOT the deflated full-corpus aggregate (0.349 MRR@20 / 0.450 recall@20).
- **D-02 — Metric set (LOCKED-by-implication):** MRR@20, recall@1, recall@20, reported both per-document AND aggregate. Latency is separate (D-06).
- **D-03 — Normattiva-fix is positive evidence (LOCKED-by-implication):** Gate must show the port retrieves the 5 normattiva docs (non-zero MRR/recall) and that e2e check #13 now passes.
- **D-04 — Band + N=3 runs (LOCKED):** port ≥ baseline − ~2–3% relative ε, evaluated on the mean of N=3 real-document-benchmark runs. e2e score-gate comparison is diffed per-check (deterministic), not via the ε-band.
- **D-05 — Fix + re-baseline (LOCKED):** Correct `check()` to compute `ok = bool(detail)`; then re-run the baseline side under the corrected harness; re-baseline CI's `score >= 9.8 and len(checks) == 19`. **RESEARCH FINDING: this fix is already present in HEAD source — see "CRITICAL FINDING" below, which changes what this decision requires in practice.**
- **D-06 — Record + no-regression (LOCKED):** Capture per-query latency on the ArcadeDB run; port must not regress vs. baseline. Quality parity (D-01/D-04) is the hard gate; latency is recorded/no-regression only. Compare against the *clean-DB* baseline latency (5.4s), not the confounded ~431s bloated path.
- **D-07 — Exact provider match (LOCKED):** embedder `mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M` (768d), reranker `bge-reranker-v2-m3-Q8_0.gguf`, `E2E_USE_EXTERNAL_EMBED=1 E2E_USE_EXTERNAL_RERANK=1`, GLiNER OFF.
- **D-08 — Frozen-question replay (LOCKED):** Replay the exact 60 frozen questions via `--frozen-questions baseline/03-turingdb/frozen-questions.json` — no regeneration.
- **D-09 — Committed artifact (LOCKED):** Commit `baseline/06-gate/` with `GATE.md` (human) + `gate-result.json` (machine: per-metric/per-check/per-document diff, latency, tolerance params, run count, provider config, corpus sha-verification, `verdict: GO|NO_GO`). Force-add (gitignored dirs). Also commit raw ArcadeDB-side captures + corrected baseline-side recapture.
- **D-10 — Phase-7 hard guard (LOCKED):** Phase 7 gated by a guard/test reading committed `gate-result.json`, refusing unless `verdict == GO`. Verdict produced by a real local/GPU run and committed — CI checks the committed verdict, does not re-run the GPU comparison.
- **D-11 — Hard-block until reproduced (LOCKED):** Gate REQUIRES the exact baseline corpus, sha256-verified against `corpus-manifest.json`, failing closed on drift, plus real granite+BGE sidecars. Both confirmed present at research time (see Area 4 below).

### Claude's Discretion

- Exact ε tolerance value (within ~2–3% relative intent), run count beyond N=3 floor, whether to record variance/stddev.
- Concrete `gate-result.json` schema/field names (within the D-09 contract) and exact form of the Phase-7 guard (pytest guard vs. small gate-check script), provided it fails closed on missing/NO_GO.
- Module/plan/wave decomposition. Natural ordering: (1) fix+re-baseline e2e harness (D-05), (2) capture GPU-backed ArcadeDB e2e + real-doc benchmark under matched providers/corpus/questions (D-07/D-08), (3) compute diff+verdict, write artifact (D-09), (4) wire Phase-7 guard (D-10).
- Whether the corrected baseline-side e2e recapture (D-05) is stored under `baseline/03-turingdb/` or `baseline/06-gate/` — keep the original inflated capture intact either way.

### Deferred Ideas (OUT OF SCOPE)

- Removing TuringDB + rewriting CLAUDE.md invariants (#2/#4/#6) — Phase 7, gated on this phase's GO verdict.
- All FUTURE-MILESTONE retrieval/memory-quality themes (T1–T5).
- PERF-03 adaptive-fetch tuning + A/B embedding-model swap/canary/rollback + TEST-07/08 — Phase 9 remainder.
- Fixing the `document_id`-length bug as a code change — expected already landed in Phase 4; Phase 6 only *verifies* it (D-03). If NOT fixed, that's a Phase-4 defect surfaced by the gate, not new Phase-6 scope.
- Windows CI lane / turingdb-on-Windows (CI-10, v2).

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ARC-09 | Migration-correctness gate — the ported ArcadeDB code meets-or-exceeds the ARC-01 baseline (HARD exit criterion; nothing downstream proceeds until it passes) | Areas 1–5 below ground every artifact/script/threshold the gate touches in its exact current-HEAD state; the "CRITICAL FINDING" section resolves a load-bearing discrepancy in the D-05 plan that would otherwise cause the planner to author a no-op code-edit task. |

</phase_requirements>

## Summary

This phase does not need new libraries, frameworks, or architecture — it needs the **planner to know exactly what state the repository is already in**, because CONTEXT.md's D-05 decision was written against an assumption (a live `check()` bug requiring a source fix) that this research shows is **already resolved in HEAD**, and one artifact-provenance mystery (the committed baseline JSON still shows the old buggy behavior despite the fix predating it) that needs to be called out explicitly rather than silently re-"fixed" a second time. Every other measurement input — the two benchmark scripts' CLI surface, the baseline JSON shapes, the corpus/frozen-questions, and the runtime stack — matches CONTEXT.md's citations closely, with a few small precision corrections (exact figures instead of "~", a CLI flag name difference, a check-name rename, and a GLiNER-scope nuance for the real-document-benchmark leg).

**Primary recommendation:** Do NOT plan a source-code edit for `e2e_score_check.py`'s `check()` function — it already computes `ok = bool(detail)` and has since before the Phase-3 baseline was even captured. Plan instead: (1) a small **verification task** that proves this with a grep/diff and a note in GATE.md; (2) a **derivation task** that recomputes "corrected" TuringDB-baseline pass/fail per-check from the `detail` field already present in the committed `baseline/03-turingdb/e2e-results.json` (no live TuringDB re-run needed — the fields required for D-05's "corrected re-baseline" are already on disk); (3) the real GPU-backed ArcadeDB-side e2e + real-doc-benchmark captures (which will be honest by construction, since current code is already fixed); (4) the diff/verdict/artifact logic (D-09); (5) the Phase-7 guard (D-10). CI's threshold assertion (`score>=9.8`, `check_count==19`, `verdict==VALIDATED_10_10`) is **already** the "re-baselined" state D-05 asked for — no CI edit is expected either, pending the planner's own confirmation.

## Architectural Responsibility Map

This phase produces no new application-tier code (no browser/API/DB changes). Its "components" are measurement tooling and committed artifacts:

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| e2e harness truthfulness (`check()`) | Store/script tier (`src/turing_agentmemory_mcp/e2e_score_check.py`) | — | Already-correct helper shared by every scenario check; verify, don't rewrite |
| Real-document retrieval capture | CLI/script tier (`scripts/real_document_benchmark.py` driving the live MCP server) | MCP/API tier (`document_search`, `document_ingest_*` tools) | The benchmark is an external client of the already-running dockerized MCP; it does not touch store internals |
| Diff/tolerance/verdict computation | New CLI/script tier (a small script under `scripts/` per Claude's Discretion) | — | Pure post-processing over two committed JSON artifacts; no runtime coupling to the MCP server |
| Gate artifact (`GATE.md` + `gate-result.json`) | Committed-artifact tier (`baseline/06-gate/`) | — | Force-added like `baseline/03-turingdb/`; durable, versioned, human+machine readable |
| Phase-7 guard | CI/test tier (pytest guard, following `tests/test_no_skip_as_green_guard.py`'s pattern) or a small gate-check script | — | Fails closed on missing/NO_GO `gate-result.json`; mirrors the repo's existing guard-test convention, not a new pattern |

## CRITICAL FINDING — D-05's "check() fix" is already landed; the D-05 CI re-baseline is already landed

This is the single most consequential finding for the plan and directly affects D-05's "one permitted code touch."

**1. The `check()` honesty fix already exists at HEAD and predates the Phase-3 baseline capture.**

`src/turing_agentmemory_mcp/e2e_score_check.py` (current location — see discrepancy #1 below), lines 33–55:

```python
def check(checks: list[dict[str, Any]], name: str, fn: Callable[[], Any]) -> None:
    started = time.perf_counter()
    try:
        detail = fn()
        checks.append(
            {
                "name": name,
                "ok": bool(detail),
                "points": 1.0,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "detail": detail,
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": name,
                "ok": False,
                "points": 1.0,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "error": {"type": type(exc).__name__, "message": str(exc)[:1000]},
            }
        )
```

`ok: bool(detail)` — exactly the semantics D-05 asks for. Verified via `git log`/`git show`:

- The fix landed in commit `8120efd` — `fix(e2e): honest check() scoring + multi-chunk test docs reach VALIDATED_10_10` (committed 2026-07-12 08:25, during Phase 1's CI bootstrapping work, well before Phase 3 even started).
- `git merge-base --is-ancestor 8120efd 07cab0b` (the commit that committed the Phase-3 baseline artifact) → **true**: the fix is an ancestor of the baseline commit, i.e. chronologically earlier.
- Confirmed directly: `git show ab7abd0:src/turing_agentmemory_mcp/e2e_score_scenarios.py` — `ab7abd0` is BASELINE.md's own recorded "Snapshot Git SHA" — already contains `"ok": bool(detail)` verbatim.
- `git merge-base --is-ancestor 8120efd HEAD` → **true**: still present, unchanged, today.

**2. Yet the COMMITTED baseline JSON exhibits the pre-fix (buggy) behavior.**

Directly read from `baseline/03-turingdb/e2e-results.json` (verified with a one-off script, not transcribed from BASELINE.md):

```json
{"name": "document_ingest_text_writes_chunks", "ok": true, "detail": false, ...}
{"name": "document_search_hybrid_exact_code_match_explains_lexical_score", "ok": true, "detail": false, ...}
{"name": "document_ingest_text_is_idempotent_for_same_payload", "ok": true, "detail": false, ...}
{"name": "document_reindex_text_replaces_old_chunks_and_metadata", "ok": true, "detail": false, ...}
```

This is genuinely inconsistent with the source at the recorded snapshot (`ab7abd0`), which computes `ok=bool(detail)` and would have produced `ok:false` for all four. **Most plausible explanation (not confirmed with a live Docker inspect — flag as a hypothesis, not fact):** BASELINE.md's D-02 reproduction command is `docker compose run --rm ... e2e --out ...`, which reuses whatever `turing-agentmemory-mcp:local` image was last built; if that image was built before `8120efd` landed and never rebuilt with `--build` before the capture run, the running container's `check()` would still be the old buggy version even though the git snapshot label (`ab7abd0`) postdates the source fix. The baseline capture's `detail` field is trustworthy either way (it's the raw assertion result, unaffected by the `ok` bug) — only `ok` is stale in the committed file.

**3. CI's threshold is already the D-05 "re-baselined" state, not the "~9.4 stub floor" CONTEXT.md describes.**

Read from `.github/workflows/ci.yml` (`dockerized-integration` job), lines 130–154 — the job asserts:
- `check_count == 19` (fail if any check skipped)
- `score >= 9.8`
- `verdict == VALIDATED_10_10`

Same commit `8120efd`'s message says verbatim: *"the CI dockerized-integration gate is tightened from the interim score>=9.4 floor to assert VALIDATED_10_10... the stale 'stub cannot reach 10/10' comments are corrected."* This CI job runs in **stub mode** (no `E2E_USE_EXTERNAL_EMBED`/`E2E_USE_EXTERNAL_RERANK` env vars set in the workflow step — `run_e2e()` defaults to the in-process `HashingEmbedder`/keyword-overlap stub servers when those are unset). CONTEXT.md's characterization ("CI currently asserts a measured stub floor ~9.4") is **stale relative to HEAD** — that was true at Phase 1's *initial* CI authoring, before `8120efd` tightened it later in the same phase.

**Consequence for the plan:** D-05's "re-baseline the CI score threshold to whatever the corrected-truth passing state is" is **already satisfied** for the stub-mode CI tier. What remains is entirely about the **real-provider, GPU-backed comparison** this phase is scoped to produce — not a CI-file edit. The planner should have a task that *verifies and documents* this (grep `ci.yml` + `e2e_score_check.py`, cite `8120efd`), not a task that edits `check()` or `ci.yml`.

**4. Because `detail` is preserved per-check in the committed JSON, the "corrected" TuringDB-side numbers are a derivation, not a live re-run.**

BASELINE.md already did this by hand: 18 raw `ok:true` − 4 confirmed false-passing (checks #12/14/15/16) = 14 true passes, +1 confirmed hard failure (#13) = 5 non-passing of 19. A tiny script applying `ok = bool(detail)` over the existing `checks` array reproduces this exactly and is trivially auditable — no TuringDB container needs to be started for this half of D-05's "re-run the baseline side" language. (`turingdb` compose service is still present and startable at HEAD if the planner nonetheless wants a fresh live TuringDB capture for belt-and-suspenders reproducibility — see Area 4.)

## Area 1 — The e2e harness: exact current-HEAD state

### File layout discrepancy vs. CONTEXT.md citations

CONTEXT.md/BASELINE.md cite `check()` at `src/turing_agentmemory_mcp/e2e_score_scenarios.py:39-51`. **This is stale.** As of commit `8a2cccd` (`feat(04-09): wire e2e_score.py to ArcadeDB...`), `check`/`payload` were split out into a new sibling module, `src/turing_agentmemory_mcp/e2e_score_check.py` (to keep `e2e_score_scenarios.py` under the 600-LOC cap), and are re-exported unchanged:

```python
# e2e_score_scenarios.py:15
from turing_agentmemory_mcp.e2e_score_check import check, payload  # noqa: F401 - re-exported
```

`check()`'s real current location is `e2e_score_check.py:33-55` (quoted in full above). Any plan task must `read_first` **`e2e_score_check.py`**, not the stale line range in `e2e_score_scenarios.py`.

### The 19 checks, enumerated (confirmed by reading `run_mcp_checks` + `run_e2e` in order)

| # | Check name | Hardcodes `chunk_count`? |
|---|---|---|
| 1 | `arcadedb_starts_schema_embed_and_rerank_contracts` (renamed from `turingdb_starts_...` at the 04-09 rewire — cosmetic only, same position) | no |
| 2 | `mcp_exposes_expected_tool_surface` | no |
| 3 | `memory_store_message_writes_scoped_memory` | no |
| 4 | `memory_store_messages_batches_idempotent_searchable_writes` | no |
| 5 | `memory_search_retrieves_alice_exact_top1` | no |
| 6 | `memory_search_does_not_leak_bob` | no |
| 7 | `memory_search_hybrid_exact_code_match_explains_lexical_score` | no |
| 8 | `memory_get_context_returns_prompt_ready_context` | no |
| 9 | `memory_store_message_is_idempotent_and_memory_list_filters_metadata` | no |
| 10 | `memory_get_and_update_return_structured_metadata` | no |
| 11 | `memory_delete_hides_memory_from_get_and_search` | no |
| 12 | `document_ingest_text_writes_chunks` | **yes** — `doc["chunk_count"] == 3` (`e2e_score_scenarios.py:327`) |
| 13 | `document_search_retrieves_exact_top1_with_citation_and_neighbor_context` | no |
| 14 | `document_search_hybrid_exact_code_match_explains_lexical_score` | no (asserts `hybrid_doc["chunk_count"] == 2` as part of a *different* check, `e2e_score_scenarios.py:388`, not #14 itself — see note below) |
| 15 | `document_ingest_text_is_idempotent_for_same_payload` | **yes** — `duplicate_doc["chunk_count"] == repeated_doc["chunk_count"] == 3` (`e2e_score_scenarios.py:428`) |
| 16 | `document_reindex_text_replaces_old_chunks_and_metadata` | **yes** — `reindexed_doc["chunk_count"] == 2` (`e2e_score_scenarios.py:484`) |
| 17 | `document_delete_hides_document_from_search` | no |
| 18 | `memoryarena_bucket_sample_retrieves_answer_context` | no |
| 19 | `restart_preserves_memory_and_document_retrieval` | no |

**Precision note vs. CONTEXT.md:** CONTEXT.md says "checks #12/#16 hardcode `chunk_count`." Reading the actual assertion bodies: #12, #15, AND #16 all assert an exact `chunk_count`; #14's assertion is on the *previous* ingest call's `hybrid_doc["chunk_count"] == 2` (a companion fixture set up right before it, `e2e_score_scenarios.py:388`), which is set-up state, not #14's own pass/fail predicate in the same sense as #12/15/16. When Phase 4's re-chunking changes chunk counts, **checks #12, #15, and #16 are all candidates for a legitimate (non-regression) flip** — the plan's per-check diff must treat all three, not just two, as chunk-count-sensitive.

### `e2e_score.py` — score/verdict/CLI (`src/turing_agentmemory_mcp/e2e_score.py`)

- `run_e2e()` (lines 54–180) **always** drives `ArcadeE2EBackend` (line 62: `backend = ArcadeE2EBackend()`) — there is **no code path left to run this harness against TuringDB**. This is the second major consequence of the 04-09 rewire (`8a2cccd`) the planner must know: if D-05's "re-run the baseline side under the corrected harness" is read literally as "run `e2e_score.py` against TuringDB again," **that is not possible with HEAD's tooling** — see the derivation approach in the CRITICAL FINDING above instead.
- Verdict/threshold, exact quote (`e2e_score.py:165`):
  ```python
  "verdict": "VALIDATED_10_10" if score >= 9.8 and len(checks) == 19 else "FAILED_SCORE_GATE",
  ```
- CLI exit-code assertion, exact quote (`e2e_score.py:189`):
  ```python
  return 0 if result["score"] >= 9.8 and result["check_count"] == 19 else 1
  ```
  Both match CONTEXT.md's citation `e2e_score.py:165,189` exactly — **no discrepancy here**.
- Provider env: `E2E_USE_EXTERNAL_EMBED`/`E2E_USE_EXTERNAL_RERANK` gate whether `LocalEmbedServer`/`LocalRerankServer` (in-process stubs) start at all (`run_e2e()` lines 78–88). When set to `"1"`, the script relies entirely on whatever `EMBED_BASE_URL`/`RERANK_BASE_URL`/etc. are already in the environment (i.e., pointed at the real compose sidecars) — it does not itself resolve GPU sidecar URLs; the caller must export them.
- Result JSON always includes `"backend": "arcadedb"` and `"arcadedb_image": ARCADEDB_E2E_IMAGE` (line 169–170) — this is why `baseline/04-arcadedb/e2e-results.json` has those two extra top-level keys and `baseline/03-turingdb/e2e-results.json` does not (confirmed: top-level keys of the 03-turingdb file are exactly `check_count, checks, cleanup, score, score_gate, turingdb_version, verdict` — no `backend`/`arcadedb_image`, because that file predates the 04-09 rewire).
- `scripts/e2e_score.py` (the CLI entrypoint, 12 lines) is a thin `sys.path` shim that imports `main` from the module above — `--out` is the correct flag (default `e2e-results.json`).

### `.github/workflows/ci.yml` — exact current assertion (lines 104–154)

- Starts only the `arcadedb` service (`docker compose up -d --wait arcadedb`) — not `turingdb`.
- Runs `python scripts/e2e_score.py --out e2e-result.json` **on the host** (not `docker compose run e2e`), specifically because the D-10 restart leg (`restart_backend_and_wait_ready`) shells out to `docker compose stop/start arcadedb` and needs host-level Docker control unavailable inside the `e2e` container — this is why the in-container run tops out at 18/19 and the host run reaches 19/19 (documented in both the workflow comments and `e2e_score.py`'s own module docstring).
- No `E2E_USE_EXTERNAL_EMBED`/`E2E_USE_EXTERNAL_RERANK` set → stub-mode, deterministic, GPU-free.
- Asserts exactly `check_count == 19`, `score >= 9.8`, `verdict == VALIDATED_10_10` (three separate `jq`/`awk` checks, lines 140–153) — **this already is the "re-baselined" bar**, matching finding #3 above.

## Area 2 — Measurement engines' CLI surface

### `scripts/real_document_benchmark.py` (591 LOC) — flags, defaults (from `parse_args()`, lines 77–100)

| Flag | Default | Notes |
|---|---|---|
| `--root` | `r"D:\turing_AgentMemory_MCP\test"` (Windows-hardcoded) | Must override to the baseline corpus path for any real run |
| `--mcp-url` | `http://127.0.0.1:8095/mcp/` | Matches the published `turing-agentmemory-mcp` port in `compose.yaml` |
| `--output` | `""` → falls back to `.benchmarks/<benchmark_id>.json` | **Not `--out`** — CONTEXT.md's canonical_refs list this flag correctly, but the phase description's prose elsewhere conflates it with `e2e_score.py`'s `--out`; the two scripts use different flag names |
| `--scope` | `""` → benchmark_id | Becomes the `user_identifier` used for every ingested doc/search in that run |
| `--top-k` | `20` | |
| `--search-concurrency` | `4` (baseline used `3`) | Must be `4` — the plan's original pin — or `3` to exactly match the captured baseline; D-04 says exact run-count/tolerance details are Claude's discretion, but this concurrency value affects nothing about scoring correctness, only wall-clock |
| `--poll-seconds` | `10.0` | |
| `--chunk-bytes` | `512 << 10` = `524288` | |
| `--question-count` | `10` (`QUESTION_COUNT`) — **irrelevant when `--frozen-questions` is set** | `resolve_questions()` bypasses `generate()` entirely when frozen questions are loaded (D-08) |
| `--passage-chars` | `1400` | Only used by the (bypassed) generator path |
| `--question-model` | `inclusionai/ling-2.6-flash` | Bypassed under `--frozen-questions` |
| `--question-url` | `https://openrouter.ai/api/v1/chat/completions` | Bypassed under `--frozen-questions` |
| `--question-api-key-env` | `PROVIDER_API_KEY` | Bypassed under `--frozen-questions` |
| `--env-file` | `.env` | Loaded via `load_env_file()` before `run()` |
| `--frozen-questions` | `""` → generation path | **Set to `baseline/03-turingdb/frozen-questions.json`** for the Phase-6 replay per D-08 |

`run()` (line 411) validates `1 <= top_k <= 200`, `1 <= search_concurrency <= 8`, `poll_seconds > 0`, `chunk_bytes > 0`; raises on any file not under `SUPPORTED_SUFFIXES` (`.docx .epub .html .htm .md .pdf .pptx .txt .url .xlsx`); raises `RuntimeError` if any document's ingest job doesn't reach `status == "succeeded"` (no partial-success path — matches CLAUDE.md invariant #5's "never expose a partially indexed document" framing).

`load_frozen_questions(path)` (`real_document_benchmark_scoring.py:152`) requires `questions_by_document` to be a non-empty dict, and every row to carry `source_id, question, answer, evidence_quote` — raises `ValueError` loudly on a malformed/incompatible freeze file, never silently degrades.

### Output JSON shape (confirmed directly from `baseline/03-turingdb/real-document-benchmark.json`)

Top-level: `benchmark_id, completed_at, created_at, documents, mcp_url, privacy_note, question_count_per_file, question_model, results, root, schema_version, search_concurrency, summary, top_k, user_identifier`.

- `documents`: list of 12, each `{bytes, conversion:{chars,converter,page_count,seconds}, document_id, enqueue_seconds, filename, job:{...ingest-status fields...}, question_usage, questions, suffix, path, title}`.
- `results`: list of 60 (one per question), each `{filename, document_id, question_index, source_id, question, answer, evidence_quote, evidence_rank, match_kind, latency_ms, error, retrieved:[{rank,chunk_id,locator,score,text_preview}×≤5]}`.
- `summary`: `{question_count, search_error_count, mrr_at_20, recall_at_k:{"1","3","5","10","20"}, latency_ms:{mean,max}, documents:{<document_id>: <same per-doc metrics shape>}}` — computed by `summarize_results()` (`real_document_benchmark_scoring.py:310`, via `_metrics()` at line 288). This is the exact per-document/aggregate structure D-02 requires the diff to read.
- **MRR@20 note:** `_metrics()` hardcodes the MRR cutoff at 20 regardless of `--top-k` (`(1.0/rank) if 0 < rank <= 20 else 0.0`) — if a plan ever changes `--top-k` away from 20, MRR@20 stays literally "at 20," decoupled from `--top-k`. Not a bug, just a naming trap to flag for whoever writes the diff script.

**Exact baseline figures** (recomputed directly from the committed `results` array with the same weighting `summarize_results()` uses, not transcribed from BASELINE.md's rounded "~" figures):

| Scope | MRR@20 | recall@1 | recall@20 |
|---|---|---|---|
| Full corpus (60 q, 12 docs) — matches `summary` verbatim | 0.3488 | 0.300 | 0.450 |
| 7-doc "meaningful" subset (35 q, excludes the 5 normattiva docs) — **this is D-01's pass bar** | **0.5979** | **0.5143** | **0.7714** |
| All 5 normattiva docs individually | 0.0 | 0.0 | 0.0 | (confirms D-03's "flat zero" claim exactly, per-document, no exceptions)

### `scripts/e2e_score.py` CLI

12-line shim; only flag is `--out` (default `e2e-results.json`); for a real-provider run: `E2E_USE_EXTERNAL_EMBED=1 E2E_USE_EXTERNAL_RERANK=1 EMBED_BASE_URL=... RERANK_BASE_URL=... python scripts/e2e_score.py --out <path>` (env-driven, no CLI flags for provider selection).

## Area 3 — Baseline artifact shapes (the yardstick)

### `baseline/03-turingdb/corpus-manifest.json`

Dict: `{documents: [{filename, bytes, sha256, suffix, page_count|null, sheet_count|null (xlsx only)}], generated_at, notes, root, schema_version, source_benchmark_id}`. 12 entries. **D-11 verification mechanism:** re-hash every file under `--root` with `hashlib.sha256` and compare against this list's `sha256` field per `filename` — `file_digest()` in `real_document_benchmark_scoring.py:142` already computes exactly this (bytes, sha256 tuple) as a side effect of every real-doc-benchmark run, so the sha-check can reuse that helper rather than hand-rolling a second hasher.

**Corpus presence confirmed live:** `D:/tmp/baseline-corpus` exists on this host with exactly the 12 expected filenames (verified via directory listing), matching D-11's "both are present now" claim.

### `baseline/03-turingdb/frozen-questions.json`

Dict: `{questions_by_document: {<filename>: [{answer, evidence_quote, question, source_id}×5]}, schema_version, source_benchmark_id}`. 12 files × 5 = 60 rows. Round-trips through `load_frozen_questions()` (confirmed by that function's own schema assertions matching this shape exactly).

### `baseline/03-turingdb/e2e-results.json`

Top-level keys: `check_count, checks, cleanup, score, score_gate, turingdb_version, verdict` (no `backend`/`arcadedb_image` — predates the 04-09 field additions). `verdict: "FAILED_SCORE_GATE"`, `score: 9.474`, `check_count: 19`, `turingdb_version: "1.35"`. Per-check array shape: `{name, ok, points, elapsed_ms, detail}` on success or `{name, ok:false, points, elapsed_ms, error:{type,message}}` on exception.

### `baseline/03-turingdb/real-document-benchmark.json`

Shape documented in Area 2 above.

### `baseline/04-arcadedb/NOTES.md` + `e2e-results.json`

- `NOTES.md` explicitly states this is the **correctness-parity** capture (stub embed/rerank), NOT the quality-parity capture Phase 6 must produce, and that `real-document-benchmark.json` was **not** captured (the corpus path didn't exist on that session's host) — matches CONTEXT.md's summary exactly.
- `e2e-results.json` top-level keys: `arcadedb_image, backend, check_count, checks, cleanup, score, score_gate, turingdb_version, verdict` — `verdict: "VALIDATED_10_10"`, `score: 10.0`, `check_count: 19`, `arcadedb_image: "arcadedata/arcadedb:26.7.1"`, `backend: "arcadedb"`. This is the reference shape the GPU-backed recapture (this phase's job) should reproduce field-for-field.

## Area 4 — Runtime stack to drive the gate run

From `compose.yaml` (confirmed by direct read, not assumed):

- **`turingdb` service is still present at HEAD** (Phase 7 hasn't run yet) — `docker/turingdb.Dockerfile`, published `127.0.0.1:6666`, healthcheck via `TuringDB(...).try_reach()`. Still startable if the planner wants a literal fresh TuringDB-side capture rather than the JSON-derivation approach from the CRITICAL FINDING.
- **`arcadedb`**: `arcadedata/arcadedb:26.7.1`, published `127.0.0.1:2480`, healthcheck `GET /api/v1/ready`.
- **`agentmemory-model-init`**: downloads and sha256-verifies three pinned GGUF files including `granite-embedding-311M-multilingual-r2-Q4_K_M.gguf` and `bge-reranker-v2-m3-Q8_0.gguf` (exact URLs/hashes present in compose.yaml, lines 328–339) — this is the provisioning step that must complete before `agentmemory-embed`/`agentmemory-rerank` can serve.
- **`agentmemory-embed`**: `llama-provider.Dockerfile`, `--model /models/pinned/granite-embedding-311M-multilingual-r2-Q4_K_M.gguf --embedding --pooling mean`, GPU-mandatory (`gpus: all`, nvidia-smi healthcheck), exposed internally on `:8080`.
- **`agentmemory-rerank`**: same image, `--model /models/pinned/bge-reranker-v2-m3-Q8_0.gguf --rerank --embedding --pooling rank`, GPU-mandatory, exposed internally on `:8080`.
- **`turing-agentmemory-mcp`**: published `127.0.0.1:8095:8080` — this is what `real_document_benchmark.py --mcp-url http://127.0.0.1:8095/mcp/` targets. Its `EMBED_MODEL`/`RERANK_MODEL` env defaults (lines 210, 217) already match D-07's pinned model IDs verbatim (`mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M`, `bge-reranker-v2-m3-Q8_0.gguf`) — no env override needed for provider parity on the real-doc-benchmark leg, only for the standalone `e2e_score.py` leg (which needs `E2E_USE_EXTERNAL_EMBED=1 E2E_USE_EXTERNAL_RERANK=1` plus the matching `EMBED_BASE_URL`/`RERANK_BASE_URL` env vars pointed at the sidecars' published/internal URLs, since `e2e_score.py` builds its own store directly and does not read `turing-agentmemory-mcp`'s compose env).

**GLiNER scope nuance (not explicitly resolved by CONTEXT.md D-07 — flagging for the planner):** D-07 says "GLiNER OFF," and this is accurate for the `e2e_score.py` leg (its `run_e2e()` instantiates `TuringAgentMemory` directly, bypassing `server_from_env()`/GLiNER entirely — confirmed, no `GLINER_*` env is ever read in `e2e_score.py`). It is **not accurate by default** for the `real_document_benchmark.py` leg, which talks to the live `turing-agentmemory-mcp` compose service — and `compose.yaml`'s `turing-agentmemory-mcp` service **hardcodes `GLINER_ENABLED=1`** (line 231, no `${VAR:-default}` templating, so it cannot be turned off via an unset env var — it needs an explicit override or a compose override file). Confirmed via `store_documents.py:450` (`search_documents` signature/body) that `document_search`'s ranking channels are vector (HNSW) + lexical (Lucene) merged by `chunk_id` only — no entity-dense channel — so GLiNER being on for document ingestion is very unlikely to change document-search *scores*, but it does add ingestion-time work (entity extraction runs per chunk) that could affect **latency** (D-06) if the baseline and port runs don't have it identically enabled/disabled. The planner should decide explicitly whether to override `GLINER_ENABLED=0` for the real-doc-benchmark leg (for a literal apples-to-apples D-06 latency comparison) or accept it as a documented, low-risk deviation (since it doesn't touch document retrieval scoring). This was not resolved in the D-07 discussion and is a real "planner discretion" item, not something this research can decide.

**Corpus:** confirmed present at `D:/tmp/baseline-corpus`, all 12 expected files.

## Area 5 — Phase-7 guard mechanism: existing repo conventions to follow

No `baseline/06-gate/` or gate-check script exists yet (confirmed — directory absent). The repo's one existing analogous pattern:

- **`tests/test_no_skip_as_green_guard.py`** (42 LOC) — uses pytest's `pytester` fixture to prove `tests/conftest.py`'s `pytest_runtest_makereport` hookwrapper converts a marked skip into a hard failure under `CI=true`, and stays a normal skip otherwise. This is the repo's template for "a small, self-contained pytest file that asserts a hard-fail condition and has its own negative self-test," which is exactly the shape D-10's guard needs: a pytest test (or small script) that reads `baseline/06-gate/gate-result.json`, asserts `verdict == "GO"`, and fails loudly (not skips) if the file is missing or `verdict == "NO_GO"`. **Fail-closed, not fail-open** — missing file must be a failure, matching this repo's "no-skip-as-green" discipline (CI-07) and the "ready registry row with missing database fails closed" invariant pattern used elsewhere (`tenant_registry.py`).
- **`scripts/check-file-size.sh`** (41 LOC) — the repo's other guard convention: a small standalone script (not Python) that scans tracked files and exits non-zero with a clear diagnostic on violation, wired into both lefthook `pre-commit` and CI's `lint` job. A plausible alternative shape for the Phase-7 guard if the planner prefers a shell/CI-only gate rather than a pytest test — either satisfies D-10's "provided it fails closed" contract.
- Both existing guards are **under the 600-LOC cap by construction** (42 and 41 lines) — the new gate-check guard should stay comparably small; there's no reason for it to approach the cap given it's a JSON-read + assertion.
- **No-skip-as-green discipline applies:** if the guard is a pytest test, it must not use `pytest.skip()` as an escape hatch when `gate-result.json` is absent — that would let a missing gate artifact pass green under non-`CI` runs while still being "skipped" (not failed) under `CI=true` only via the hookwrapper; simplest correct shape is an unconditional hard assertion/`pytest.fail()`, no skip marker at all.

## Discrepancies vs. CONTEXT.md citations (consolidated)

| # | CONTEXT.md claim | What HEAD actually shows | Impact on plan |
|---|---|---|---|
| 1 | `check()` lives at `e2e_score_scenarios.py:39-51` | Lives at `e2e_score_check.py:33-55` (moved during the 04-09 split, `e2e_score_scenarios.py` only re-exports it) | `read_first`/`action` fields for any D-05 task must target `e2e_score_check.py` |
| 2 | D-05 implies `check()` needs a source-code fix | `ok = bool(detail)` already present, has been since commit `8120efd` (predates even the Phase-3 baseline snapshot `ab7abd0`) | Replace "fix check()" task with "verify check() is already honest" + "derive corrected baseline numbers from existing `detail` fields" |
| 3 | "CI currently asserts a measured stub floor ~9.4" | CI (`ci.yml:140-153`) asserts `check_count==19`, `score>=9.8`, `verdict==VALIDATED_10_10` — the tightened bar, landed in the same commit `8120efd` | No CI-threshold edit expected; verify-only task |
| 4 | Implicit: "re-run the baseline side" means re-running `e2e_score.py` against TuringDB | `run_e2e()` (HEAD) is hardcoded to `ArcadeE2EBackend` — there is no TuringDB code path left in this script | Use the JSON-derivation approach (recompute `ok=bool(detail)` over the existing `detail` fields already in `baseline/03-turingdb/e2e-results.json`); `turingdb` compose service itself is still runnable separately if a live re-capture is wanted for extra rigor |
| 5 | "checks #12/#16 hardcode `chunk_count`" | #12, #15, AND #16 all assert exact `chunk_count` values | Per-check diff must treat 3 checks, not 2, as chunk-count-sensitive |
| 6 | D-07 "GLiNER OFF" | True for `e2e_score.py`'s own store (never wires GLiNER); **not** true by default for `real_document_benchmark.py` against the live MCP, where `compose.yaml` hardcodes `GLINER_ENABLED=1` with no env-var toggle | Planner must decide: override `GLINER_ENABLED=0` for exact D-06 latency parity, or accept+document as low-risk (no entity channel in document search) |
| 7 | `real_document_benchmark.py` flag naming (implicit) | The output flag is `--output`, not `--out` (that's `e2e_score.py`'s flag) | Reproduction commands in the eventual `GATE.md` must not conflate the two scripts' flag names |
| 8 | BASELINE.md's rounded "~0.60 MRR@20 / ~0.77 recall@20" | Exact recomputed values: MRR@20 = 0.5979, recall@1 = 0.5143, recall@20 = 0.7714 (7-doc, 35-question subset) | Plan can cite exact figures for the D-01 pass bar instead of approximations |

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Corpus identity verification | A new hashing utility | `file_digest()` (`real_document_benchmark_scoring.py:142`) — already returns `(bytes, sha256)` per file, same shape `corpus-manifest.json` was built from | Single source of truth for hash computation; avoids a second hasher that could disagree with the manifest's own generation logic |
| Per-document/aggregate metric computation | A new MRR/recall calculator | `summarize_results()`/`_metrics()` (`real_document_benchmark_scoring.py:288,310`) — already produces the exact per-document + aggregate shape the diff needs | Same weighting the baseline numbers were computed with; a re-derivation with different weighting would silently invalidate the comparison |
| e2e pass/fail scoring | A new scoring function | The existing `checks` array's `points`/`ok` fields, summed exactly as `run_e2e()` does (`earned/total*10`) | Any deviation here would make the gate's own e2e score not comparable to the two committed baseline JSONs |
| Frozen-question loading/validation | A second loader | `load_frozen_questions()` (`real_document_benchmark_scoring.py:152`) — already validates schema and fails loudly | Matches D-08's contract exactly; a hand-rolled loader risks silently accepting a malformed freeze file |

**Key insight:** every piece of comparison machinery this phase needs already exists in the repo and was purpose-built in Phase 3 for exactly this eventual comparison (per CONTEXT.md's own "Reusable Assets" note). The only genuinely new code this phase should write is the diff/tolerance/verdict script and the Phase-7 guard — both small, both following existing repo conventions (Area 5).

## Common Pitfalls

### Pitfall 1: Treating D-05 as "write the fix, watch tests go green"
**What goes wrong:** A task planned as "edit `check()` to compute `ok=bool(detail)`" will find nothing to change, and a naive executor might either silently no-op (leaving no evidence trail) or — worse — "fix" something else nearby to have *something* to show for the task.
**Why it happens:** CONTEXT.md's D-05 was authored against training/prior-phase knowledge that predates this research's git-forensics pass.
**How to avoid:** Frame the D-05 task explicitly as verification + derivation (see CRITICAL FINDING), with acceptance criteria that check `git blame`/`git show` evidence, not a diff.
**Warning signs:** A plan task whose only acceptance criterion is "the check() function computes ok=bool(detail)" with no verification-vs-fix framing.

### Pitfall 2: Re-running `e2e_score.py` expecting a TuringDB-side result
**What goes wrong:** Any attempt to point `e2e_score.py` at TuringDB for a "corrected baseline re-capture" will fail or silently run against ArcadeDB instead, because `run_e2e()` is hardcoded to `ArcadeE2EBackend`.
**Why it happens:** The 04-09 rewire (Phase 4) removed the TuringDB code path from this specific script; only the raw `TuringDaemon`/`LocalEmbedServer`/`LocalRerankServer` helpers remain importable (re-exported for `benchmark.py`/`agent_quality_eval.py`, which are separate, still-TuringDB-backed harnesses out of this phase's scope).
**How to avoid:** Use the JSON-derivation approach for the "corrected" TuringDB numbers; only stand up the live `turingdb` compose service if the plan explicitly wants an independent live re-capture via a *different* script than `e2e_score.py`.
**Warning signs:** A task action referencing `e2e_score.py --out ... ` with an expectation of TuringDB involvement.

### Pitfall 3: Chunk-count flips silently attributed to a "quality regression"
**What goes wrong:** Checks #12, #15, #16 all assert exact `chunk_count` values baked in at Phase-1 fixture-authoring time; Phase 4's re-chunking (ARC-04/ARC-05) may legitimately change these numbers, and a naive aggregate-only diff would report a "regression" that is actually benign.
**Why it happens:** The e2e harness's document fixtures are hand-tuned to `chunk_chars=360` boundaries; any chunking-strategy change shifts paragraph→chunk boundaries.
**How to avoid:** Per-check diff (already mandated by D-04/Phase-3-D-07); explicitly annotate any of #12/#15/#16 flips as "chunk-count-driven, expected" vs. a genuine functional regression by re-reading the `detail`/`error` payload, not just `ok`.
**Warning signs:** GATE.md reporting a check-count regression without inspecting whether it's one of the three chunk-count-sensitive checks.

### Pitfall 4: GLiNER-on-for-one-side-only latency confound
**What goes wrong:** If the ArcadeDB-side real-doc-benchmark run has `GLINER_ENABLED=1` (compose default) while the conceptual "baseline" comparison assumes GLiNER-off parity per D-07, a latency (D-06) or ingestion-time delta could be attributed to the ArcadeDB port when it's actually attributable to GLiNER-on ingestion overhead.
**Why it happens:** D-07's "GLiNER OFF" instruction was written with the `e2e_score.py` leg in mind (which never wires GLiNER regardless); the real-doc-benchmark leg goes through the live MCP where GLiNER is on by compose default.
**How to avoid:** Decide explicitly (planner discretion) whether to override `GLINER_ENABLED=0` for the compose `turing-agentmemory-mcp` service during the real-doc-benchmark capture, and document the choice in GATE.md either way.
**Warning signs:** A latency delta between baseline and port that doesn't decompose cleanly into "expected big win from removing the O(all-chunks) scan" (per D-06's rationale) — could be masked or amplified by GLiNER overhead present on one side only.

## Validation Architecture

`workflow.nyquist_validation` is `true` in `.planning/config.json` (not `false`, not absent-defaulting) — this section is required.

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest 8.2+ (`pyproject.toml`: `testpaths=tests`, `pythonpath=src`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_<new_gate_guard>.py -q` |
| Full suite command | `python -m pytest -q` |

This phase is unusual for Nyquist purposes: its "behavior" is a measurement pipeline and a committed artifact, not application code with unit-testable branches in the traditional sense. Validation here is a mix of (a) a conventional pytest guard for D-10 (the one piece of new, testable logic) and (b) **evidence-based verification against reference oracles** (the committed baseline JSONs) for the diff/verdict logic, which is closer to an integration/golden-file test than a pure unit test.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| ARC-09 (SC#1: run+compare within tolerance) | The diff/tolerance script correctly classifies a synthetic "meets bar" and a synthetic "misses bar" pair of metric sets | unit | `pytest tests/test_gate_diff.py -x` (new) | ❌ Wave 0 |
| ARC-09 (SC#1: per-check/per-document granularity) | Diff script surfaces per-check AND per-document deltas, not just an aggregate | unit | `pytest tests/test_gate_diff.py::test_per_document_granularity -x` (new) | ❌ Wave 0 |
| ARC-09 (SC#2: meet-or-exceed hard blocker) | A verdict of `NO_GO` is produced when any locked metric falls outside the ε-band on the mean-of-N run | unit + manual-run reference oracle | `pytest tests/test_gate_diff.py::test_verdict_no_go_below_band -x` (new); real verdict itself is produced by an actual GPU run, not simulated in CI | ❌ Wave 0 (unit); N/A (real run, GPU-gated, human/local-executed) |
| ARC-09 (SC#3: recorded gate artifact) | `baseline/06-gate/gate-result.json` is well-formed, contains all D-09-mandated fields, and `GATE.md` exists | unit (schema check) | `pytest tests/test_gate_artifact_schema.py -x` (new) | ❌ Wave 0 |
| D-10 (Phase-7 guard) | Guard fails closed when `gate-result.json` is absent or `verdict != "GO"`; passes only on committed `GO` | unit, following `tests/test_no_skip_as_green_guard.py`'s pytester-isolation pattern where feasible | `pytest tests/test_phase7_gate_guard.py -x` (new) | ❌ Wave 0 |

The GPU-backed real-provider e2e + real-document-benchmark captures themselves are **not** unit-testable — they are the reference-oracle data the above tests are written against once produced. This mirrors how `baseline/03-turingdb/BASELINE.md`'s own capture was validated (D-12 hands-on validation, Phase 3) rather than via pytest.

### Sampling Rate

- **Per task commit:** the diff/verdict script's own unit tests (`pytest tests/test_gate_*.py -q`)
- **Per wave merge:** full suite (`python -m pytest -q`) — the new gate-guard tests must not break existing suite green
- **Phase gate:** full suite green + the actual committed `gate-result.json`/`GATE.md` reviewed by a human before `/gsd-verify-work` (this is an irreversible-cutover gate; CLAUDE.md's "never claim a benchmark win from one corpus/one run/mismatched configs" applies directly)

### Wave 0 Gaps

- [ ] `tests/test_gate_diff.py` — covers the diff/tolerance/verdict logic (ARC-09 SC#1/SC#2) against synthetic fixture metric sets, not live data
- [ ] `tests/test_gate_artifact_schema.py` — covers D-09's `gate-result.json` field-completeness contract (ARC-09 SC#3)
- [ ] `tests/test_phase7_gate_guard.py` — covers D-10's fail-closed guard, following `tests/test_no_skip_as_green_guard.py`'s pytester-isolation convention for testing a guard-that-fails-closed without polluting the real collected suite
- [ ] No new pytest framework/config install needed — existing `pyproject.toml` pytest setup covers this phase's testable surface

## Security Domain

`security_enforcement` is `true`, `security_asvs_level: 1` in config — this section is required, kept proportionate to this phase's actual surface (a measurement/gate phase touching no auth, session, or new user-input-handling code).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | no | Phase touches no auth code path; the gate script and real-doc-benchmark client use whatever `AGENTMEMORY_AUTH_TOKEN(S)` is already configured on the target MCP, unchanged |
| V3 Session Management | no | No new session surface |
| V4 Access Control | no | Uses existing tenant-scoped tools (`document_search`, etc.) exactly as any other MCP client would; no new access-control logic introduced |
| V5 Input Validation | marginal | The new diff/verdict script parses two trusted, locally-committed JSON files (not external/untrusted input) — standard `json.loads` + schema-shape assertions (matching `load_frozen_questions()`'s existing "raise loudly on malformed schema" pattern) is sufficient; no new external-input surface |
| V6 Cryptography | marginal | Corpus sha256 verification (D-11) reuses `hashlib.sha256` via the existing `file_digest()` helper — standard library, not hand-rolled, matches CLAUDE.md invariant #4's "use stable/deterministic IDs, not ad hoc" spirit for this analogous case |

### Known Threat Patterns for this phase's stack

| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| A corrupted/tampered `gate-result.json` silently authorizing Phase-7 TuringDB removal | Tampering | D-10's guard must read the file fresh each time (no caching), assert schema shape AND `verdict=="GO"` explicitly (not just file-presence), and fail closed on any parse error — mirrors `tenant_registry.py`'s "any pre-existing file without the exact schema is corrupt, never auto-repaired" pattern already established in this codebase (Phase 5) |
| Corpus substitution (a different/tampered corpus silently passing as "the baseline corpus") | Spoofing/Tampering | D-11's sha256 verification against `corpus-manifest.json`, fail-closed on any drift — already the locked decision; this research confirms the exact hashing helper (`file_digest()`) to reuse |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | The stale-Docker-image hypothesis for why `baseline/03-turingdb/e2e-results.json` shows pre-fix `check()` behavior despite the fix predating its recorded git snapshot | CRITICAL FINDING, point 2 | If wrong, there may be a second, still-live code path that reintroduces the old `ok=True`-regardless-of-detail behavior somewhere not found in this pass — the planner's verification task should re-derive the "corrected" numbers from `detail` regardless of root cause, which is robust to this assumption being wrong either way |
| A2 | GLiNER's presence during document ingestion has no effect on `document_search` ranking scores (only on latency/side-effects) | Area 4, GLiNER scope nuance; Pitfall 4 | Based on reading `search_documents()`'s channel list (vector+lexical only, no entity-dense term) — if a future/undiscovered code path folds entity signal into document ranking, the "accept as low-risk deviation" option would be wrong; the safer default is to override `GLINER_ENABLED=0` for the real-doc-benchmark leg unless the planner explicitly confirms otherwise |

**If this table is empty:** N/A — two items above need planner/user confirmation before being treated as settled for the plan.

## Open Questions

1. **Should the Phase-6 real-doc-benchmark capture explicitly disable GLiNER for the live MCP, or accept it enabled (compose default) and document the deviation?**
   - What we know: `document_search` doesn't consume an entity channel, so retrieval *scores* are unaffected either way; GLiNER-on adds ingestion-time work that could inflate latency numbers on whichever side has it enabled.
   - What's unclear: whether the baseline's original D-01 capture (03-02) had GLiNER on or off — `capture-provider-env.txt`, cited by BASELINE.md as the source of truth for this, is not actually committed to the repo (confirmed absent), so this can't be checked retroactively.
   - Recommendation: default to matching whatever a fresh look at `compose.yaml` implies at plan-time (GLiNER on, since that's the hardcoded default with no override in the baseline's documented reproduction commands), and record the choice explicitly in `GATE.md`'s deviation log rather than silently assuming parity.

2. **Does the ArcadeDB port actually fix the `document_id`-length bug (D-03)?**
   - What we know: Phase 4's STATE.md decisions describe a full native-indexed-search rewrite of `document_search`/`store_documents.py` that should structurally eliminate the TuringDB-specific long-ID truncation bug, and check #13 (`document_search_retrieves_exact_top1_with_citation_and_neighbor_context`) is the harness's own regression sentinel for this.
   - What's unclear: this research did not execute a live ArcadeDB run to directly confirm check #13 passes today (out of scope for a research pass without live GPU/Docker execution) — the plan's own D-03 verification task is where this gets confirmed for real, not this document.
   - Recommendation: the plan must not assume D-03 is already satisfied; treat it as a real gate outcome to be measured, consistent with CONTEXT.md's own framing ("if the gate reveals it is NOT fixed, that is a Phase-4 defect surfaced by the gate, not new Phase-6 scope").

## Sources

### Primary (HIGH confidence — read directly from repo source at HEAD, or computed from committed data)
- `src/turing_agentmemory_mcp/e2e_score_check.py` — `check()`/`payload()`, full body read
- `src/turing_agentmemory_mcp/e2e_score_scenarios.py` — all 19 scenario assertions, read in full
- `src/turing_agentmemory_mcp/e2e_score.py` — `run_e2e()`, `main()`, verdict/threshold logic, full body read
- `.github/workflows/ci.yml` — `dockerized-integration` job, full body read
- `compose.yaml` — full body read (all 12 services)
- `scripts/real_document_benchmark.py` (591 LOC) and `scripts/real_document_benchmark_scoring.py` (325 LOC) — full bodies read
- `baseline/03-turingdb/BASELINE.md`, `e2e-results.json`, `real-document-benchmark.json`, `frozen-questions.json`, `corpus-manifest.json` — read/parsed directly, metrics recomputed independently with a one-off script (not transcribed)
- `baseline/04-arcadedb/NOTES.md`, `e2e-results.json` — read directly
- `tests/test_no_skip_as_green_guard.py`, `scripts/check-file-size.sh` — read directly (Phase-7 guard convention precedent)
- `src/turing_agentmemory_mcp/store_documents.py:450` (`search_documents` signature+body) — read to confirm no entity-dense channel
- Git forensics: `git log`, `git show <sha>:<path>`, `git merge-base --is-ancestor` against commits `8120efd`, `07cab0b`, `ab7abd0`, `8a2cccd`, `HEAD` — used to establish the chronological/ancestry facts in the CRITICAL FINDING section
- Live filesystem check of `D:/tmp/baseline-corpus` (12 files present, confirmed by directory listing)

### Secondary / Tertiary
- None used — this phase's domain required no external library/framework research; all claims are grounded in this repository's own source, git history, and committed artifacts (HIGH confidence throughout).

## Metadata

**Confidence breakdown:**
- e2e harness current state (Area 1, CRITICAL FINDING): HIGH — every claim verified by direct source read + git ancestry proof, not inference
- Measurement engine CLI surface (Area 2): HIGH — read directly from argparse definitions and confirmed against actual committed JSON output shapes
- Baseline artifact shapes (Area 3): HIGH — parsed directly with a one-off script, not transcribed
- Runtime stack (Area 4): HIGH for compose.yaml facts; MEDIUM for the GLiNER-scope-during-original-baseline-capture question (the one piece of evidence, `capture-provider-env.txt`, is not committed and couldn't be checked)
- Phase-7 guard patterns (Area 5): HIGH — read directly from the two existing analogous files in this repo

**Research date:** 2026-07-16
**Valid until:** This research is tied to a specific git commit state (`HEAD` at research time, `f813b03`). Any further commits touching `e2e_score.py`, `e2e_score_check.py`, `e2e_score_scenarios.py`, `ci.yml`, or `compose.yaml` before the plan executes should trigger a quick re-verification of the CRITICAL FINDING section specifically (re-run the `git show`/`grep` checks), since that finding is the one most likely to be invalidated by intervening work.
