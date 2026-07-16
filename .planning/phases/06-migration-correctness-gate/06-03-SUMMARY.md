---
phase: 06-migration-correctness-gate
plan: 03
subsystem: testing
tags: [e2e-gate, retrieval-benchmark, arcadedb-migration, gpu-capture, real-providers]

# Dependency graph
requires:
  - phase: 03-turingdb-retrieval-baseline
    provides: "baseline/03-turingdb/{corpus-manifest.json, frozen-questions.json, real-document-benchmark.json, BASELINE.md} yardstick"
  - phase: 06-migration-correctness-gate
    provides: "06-01 scripts/gate_diff.py (verify_corpus/is_stub_provider/mean_of_runs/compute_verdict engine); 06-02 fail-closed Phase-7 gate guard"
provides:
  - "baseline/06-gate/e2e-results.json — real-provider ArcadeDB e2e capture (19 checks, non-stub sidecar hostnames, check #13 passing)"
  - "baseline/06-gate/real-document-benchmark-run{1,2,3}.json — N=3 frozen-question replay captures with per-query latency"
  - "baseline/06-gate/capture-provider-env.txt — provider config, repro commands, GLiNER-scope decision, deviation notes"
affects: [06-04, 07-turingdb-removal]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "e2e_score.py real-provider capture must run INSIDE the compose network (docker compose run --rm e2e) because agentmemory-embed/agentmemory-rerank are expose-only (not published to host) — running on host cannot reach real sidecar hostnames at all"
    - "MSYS_NO_PATHCONV=1 required for any docker compose command with a /container/path argument under Git Bash on Windows, or MSYS mangles it into a Windows path"
    - "real_document_benchmark.py's default --scope embeds a UTC timestamp, so repeated runs without an explicit --scope get fresh, non-colliding ArcadeDB tenants automatically"

key-files:
  created:
    - baseline/06-gate/e2e-results.json (gitignored by existing .gitignore `e2e-results.json` rule)
    - baseline/06-gate/real-document-benchmark-run1.json (untracked, not currently gitignored)
    - baseline/06-gate/real-document-benchmark-run2.json (untracked, not currently gitignored)
    - baseline/06-gate/real-document-benchmark-run3.json (untracked, not currently gitignored)
    - baseline/06-gate/capture-provider-env.txt (untracked, not currently gitignored)
  modified: []

key-decisions:
  - "D-06 GLiNER-scope: accepted the compose default (GLINER_ENABLED=1) rather than adding a compose override to disable it — document_search consumes no entity channel, so the locked comparison metrics and per-query search latency are unaffected; only ingestion wall-clock is heavier, which is out of scope for this capture's locked metrics"
  - "The plan's described `gate_diff.py --verify-corpus/--corpus-root/--manifest` CLI flag does not exist in scripts/gate_diff.py's main() (confirmed by reading 06-01's actual implementation) — the D-11 pre-flight was run by calling the already-tested verify_corpus() function directly via a Python one-liner instead, which is the exact function `main()`'s full-comparison mode also calls internally"
  - "Rebuilt turing-agentmemory-mcp:local / e2e images before capturing (Rule 3 blocking-issue fix) — the cached image predated the 04-09 ArcadeDB e2e rewire by ~15 commits and would have silently produced a stale-schema, TuringDB-named capture (confirmed by first attempt showing old check names and no backend/arcadedb_image fields)"
  - "Generated and persisted a fresh AGENTMEMORY_TENANT_NAMING_KEY in a local (gitignored, uncommitted) .env file (Rule 3 blocking-issue fix) — the rebuilt image enforces Phase 5's fail-closed tenant-router requirement that this repo's GPU host had never previously configured; verified no pre-existing tenant registry file existed on the persistent volume before generating a fresh key, so there was no fingerprint-mismatch risk"

requirements-completed: [ARC-09]

coverage:
  - id: D1
    description: "D-11 corpus sha256 pre-flight passes with zero drift against baseline/03-turingdb/corpus-manifest.json before any capture is taken"
    requirement: ARC-09
    verification:
      - kind: manual_procedural
        ref: "python -c invocation of scripts.gate_diff.verify_corpus() against D:/tmp/baseline-corpus — result {'ok': true, 'mismatches': []}"
        status: pass
    human_judgment: false
  - id: D2
    description: "Real-provider ArcadeDB e2e capture (baseline/06-gate/e2e-results.json): 19 checks, check #1 detail shows sidecar hostnames (agentmemory-embed:8080/agentmemory-rerank:8080, non-stub), check #13 (document_search_retrieves_exact_top1_with_citation_and_neighbor_context) passes — direct evidence the TuringDB-baseline document_id-length bug is fixed on the ArcadeDB port"
    requirement: ARC-09
    verification:
      - kind: manual_procedural
        ref: "docker compose run --rm e2e (real granite+BGE sidecars) -> baseline/06-gate/e2e-results.json"
        status: pass
    human_judgment: false
  - id: D3
    description: "N=3 real_document_benchmark.py frozen-question replay captures (60 questions/run, 12 docs/run, non-zero latency and per-document metrics on all 5 normattiva_* PDFs, zero search errors)"
    requirement: ARC-09
    verification:
      - kind: manual_procedural
        ref: "real-document-benchmark-run{1,2,3}.json: mrr_at_20/recall_at_k/latency_ms/documents present, question_count=60, len(documents)=12 in every run"
        status: pass
    human_judgment: false
  - id: D4
    description: "Quality-parity judgment (does the N=3 mean clear the epsilon=0.03 band vs the D-01 bug-corrected 7-doc bar) is a Manual-Only human-verify item per VALIDATION.md, deferred to 06-04's gate_diff run + end-of-phase human-verify"
    verification: []
    human_judgment: true
    rationale: "This plan's scope is capturing raw measurements only; computing the formal GO/NO_GO verdict is 06-04's scope (feeds baseline/03-turingdb/real-document-benchmark.json + these captures through scripts/gate_diff.py). A preview computation during this capture shows all three locked metrics clearing the floor (mrr_at_20 0.6843 vs floor 0.5800; recall@1 0.5889 vs floor 0.4989; recall@20 0.8556 vs floor 0.7483) with no regression in latency (3345ms mean vs 5400ms baseline), but the authoritative verdict computation and GATE.md artifact are 06-04's deliverable, not this plan's."

# Metrics
duration: 95min
completed: 2026-07-16
status: complete
---

# Phase 6 Plan 3: GPU-Backed Real-Provider ArcadeDB Capture Summary

**Captured the reference-oracle ARC-09 gate inputs on the real GPU stack: a real-provider (granite+BGE, non-stub) ArcadeDB e2e run confirming the TuringDB-baseline document_id-length bug is fixed (check #13 now passes), plus N=3 frozen-question real-document-benchmark replays showing all 5 normattiva_* PDFs retrieve with non-zero MRR/recall for the first time.**

## Performance

- **Duration:** ~95 min (includes diagnosing and fixing two blocking infrastructure issues: a stale Docker image and a missing required tenant-naming-key env var)
- **Started:** 2026-07-16T11:48:00+02:00 (approx, from first Read)
- **Completed:** 2026-07-16T13:23:00+02:00 (approx)
- **Tasks:** 2 (both `type="execute"`, manual GPU/Docker measurement, `autonomous: false`)
- **Files created:** 5 (all under `baseline/06-gate/`; none are code)

## Accomplishments

- **D-11 corpus pre-flight**: `verify_corpus()` against `D:/tmp/baseline-corpus` and `baseline/03-turingdb/corpus-manifest.json` reports `{"ok": true, "mismatches": []}` — zero drift, all 12 files sha256-verified before any capture began.
- **Real-provider e2e capture** (`baseline/06-gate/e2e-results.json`): 19/19 checks executed, check #1 (`arcadedb_starts_schema_embed_and_rerank_contracts`) detail confirms non-stub sidecar hostnames (`http://agentmemory-embed:8080`, `http://agentmemory-rerank:8080`), score 9.474 (`FAILED_SCORE_GATE`, expected per D-07 — real providers never clear the 10/10 stub-tuned threshold). **Check #13 (`document_search_retrieves_exact_top1_with_citation_and_neighbor_context`) now passes** (`ok: true, detail: true`) — direct, real-provider, real-ArcadeDB evidence that the Phase-3-baseline `IndexError` (document-scoped search failing for long `document_id` values) is fixed on the port (D-03).
- **N=3 frozen-question benchmark captures** (`baseline/06-gate/real-document-benchmark-run{1,2,3}.json`): each run replays the exact committed 60 questions (`--frozen-questions baseline/03-turingdb/frozen-questions.json`, no regeneration) across all 12 documents, with zero search errors in every run.
  - run1: mrr@20=0.6787, recall@1=0.5833, recall@20=0.85, latency mean=3380ms
  - run2: mrr@20=0.6787, recall@1=0.5833, recall@20=0.85, latency mean=3293ms
  - run3: mrr@20=0.6955, recall@1=0.60, recall@20=0.8667, latency mean=3362ms
  - **N=3 mean**: mrr@20=0.6843, recall@1=0.5889, recall@20=0.8556, latency mean=3345ms
- **All 5 normattiva_* PDFs retrieve with non-zero per-document MRR@20 across every run** (regio-decreto-1941=1.0, decreto-legislativo-2003=0.867, decreto-legislativo-2005-30=0.75, decreto-legislativo-2005-82=0.64, decreto-presidente-repubblica-1973=0.70–0.90) — this is the direct positive counter-evidence to the Phase-3 baseline's flat-zero deflation on these same 5 documents (D-03/D-08).
- **`capture-provider-env.txt`** records the exact provider model IDs, endpoints, env flags, reproduction commands (including the two Windows/Docker gotchas found live: `MSYS_NO_PATHCONV=1` and the stale-image rebuild), and the D-06 GLiNER-scope decision.
- A **preview gate computation** (not the authoritative 06-04 run) shows all three locked metrics clearing the epsilon=0.03 floor against the D-01 bug-corrected 7-doc bar (mrr_at_20 0.6843 ≥ 0.5800; recall@1 0.5889 ≥ 0.4989; recall@20 0.8556 ≥ 0.7483), with search latency 3345ms well under the baseline's 5.4s mean (no regression, D-06).

## Task Commits

This is a manual-only measurement plan (`autonomous: false`) with no source-code tasks — no per-task commits were made. Per the plan's explicit instruction ("Force-add is handled in 06-04"), the 5 capture artifacts under `baseline/06-gate/` are intentionally left uncommitted on disk for 06-04 to consume:

- `baseline/06-gate/e2e-results.json` — already matches the existing `.gitignore` bare-filename rule `e2e-results.json` (gitignored).
- `baseline/06-gate/real-document-benchmark-run{1,2,3}.json` and `baseline/06-gate/capture-provider-env.txt` — checked with `git check-ignore -v`; **none of these 4 currently match any `.gitignore` rule**, so they are plain untracked files, not force-add candidates. This differs slightly from the plan's framing ("force-add is handled in 06-04" for all 5) — only `e2e-results.json` actually needs `-f`; the other 4 can be added normally by 06-04 (or 06-04 may choose to extend `.gitignore` for consistency). Documented here for 06-04's awareness; not fixed in this plan (out of this plan's declared file scope).

**Plan metadata:** this SUMMARY.md commit (docs), plus the standard STATE.md/ROADMAP.md update commit.

## Files Created/Modified

- `baseline/06-gate/e2e-results.json` (245 lines) - real-provider (granite+BGE, non-stub) ArcadeDB e2e capture, 19 checks
- `baseline/06-gate/real-document-benchmark-run1.json` - N=1 frozen-question replay, 60 questions/12 docs
- `baseline/06-gate/real-document-benchmark-run2.json` - N=2 frozen-question replay, 60 questions/12 docs
- `baseline/06-gate/real-document-benchmark-run3.json` - N=3 frozen-question replay, 60 questions/12 docs
- `baseline/06-gate/capture-provider-env.txt` - provider config, repro commands, GLiNER-scope decision, deviation notes
- `.env` (local, gitignored, NOT a plan artifact) - a fresh `AGENTMEMORY_TENANT_NAMING_KEY` generated per `docs/configuration.md`'s documented method, required to unblock the rebuilt mcp container's Phase-5 tenant router (see Deviations)

## Decisions Made

- **D-06 GLiNER-scope**: accepted `GLINER_ENABLED=1` (compose default) rather than adding a compose override. `document_search` consumes no entity channel, so the locked comparison metrics and per-query search latency are unaffected — only document-ingestion wall-clock is heavier, which this plan does not gate on. Recorded in `capture-provider-env.txt`.
- **Corpus pre-flight invocation**: called `scripts.gate_diff.verify_corpus()` directly (via `python -c`) instead of a nonexistent `--verify-corpus` CLI flag — `scripts/gate_diff.py`'s `main()` has no such standalone flag (confirmed by reading the actual 06-01 implementation); this is the exact tested function `main()`'s own full-comparison mode calls internally, so the pre-flight guarantee is identical.
- **Real-provider e2e must run inside the compose network**: `agentmemory-embed`/`agentmemory-rerank` only `expose: 8080` internally (not published to the host), so the only way to get real, non-stub sidecar hostnames into check #1's detail is `docker compose run --rm e2e` from inside the compose network — running `e2e_score.py` on the host directly is not possible for the real-provider leg. This is why check #19 (`restart_preserves_memory_and_document_retrieval`) reports `ok: false` (`docker is not on PATH -- cannot restart the arcadedb service` inside the e2e container) — a known, documented (compose.yaml's own comment), accepted trade-off, not a defect, and not required by this plan's success criteria (which requires check #13, not check #19, to pass).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Rebuilt stale `turing-agentmemory-mcp:local`/`e2e` Docker images before capturing**
- **Found during:** Task 1 (real-provider e2e capture)
- **Issue:** The cached image (`turing-agentmemory-mcp:local`, built 2026-07-11) predated the 04-09 ArcadeDB e2e rewire (committed 2026-07-14) by ~15 further commits through the current HEAD (2026-07-16). A first e2e run against the stale image produced a capture with the old TuringDB-era check name (`turingdb_starts_schema_embed_and_rerank_contracts`), no `backend`/`arcadedb_image` fields, and check #13 failing exactly like the Phase-3 baseline — i.e. it would have silently produced a wrong, stale-code capture that appeared to reproduce the known bug rather than testing whether it was fixed.
- **Fix:** Ran `docker compose build turing-agentmemory-mcp e2e` to rebuild both images from current HEAD, recreated the `turing-agentmemory-mcp` service, and re-ran the e2e capture. The corrected capture shows `backend: "arcadedb"`, `arcadedb_image: "arcadedata/arcadedb:26.7.1"`, and check #13 passing.
- **Files modified:** none (Docker image rebuild only, no source changes)
- **Verification:** `baseline/06-gate/e2e-results.json` shows the correct current-HEAD field shape and check #13 `ok: true`.
- **Committed in:** N/A (infrastructure operation, no git commit — this SUMMARY documents it)

**2. [Rule 3 - Blocking] Generated and set `AGENTMEMORY_TENANT_NAMING_KEY` for the GPU capture host**
- **Found during:** Task 2 (N=3 real-document-benchmark capture), first attempt
- **Issue:** After the image rebuild above, the `turing-agentmemory-mcp` container crash-looped (`ValueError: AGENTMEMORY_TENANT_NAMING_KEY is required`) — Phase 5's fail-closed tenant router (added after the stale image was originally built) requires this env var with no fallback, and this GPU capture host had no `.env` file configuring it at all. The first N=3 benchmark attempt failed with "Client failed to connect: All connection attempts failed" as a direct symptom of this crash loop.
- **Fix:** Verified no pre-existing `agent-memory-tenant-registry.sqlite3` file existed on the persistent `turing-data` volume (so generating a fresh key carried zero fingerprint-mismatch risk per `docs/configuration.md`'s stated immutability warning), then generated a fresh strict-base64, 32-random-byte key via the exact documented method (`python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"`) and appended it to a new local `.env` file. Restarted `turing-agentmemory-mcp`; `/health` now reports `status: ok`.
- **Files modified:** `.env` (local, gitignored, never committed — not a tracked repository file)
- **Verification:** `curl http://127.0.0.1:8095/health` returns `{"status": "ok", ...}`; subsequent benchmark runs completed successfully.
- **Committed in:** N/A (local environment configuration, not committed)

### Harness/execution-mechanics deviation (not a data or method change)

**3. Orphaned first benchmark run re-executed by the orchestrator**
- **Found during:** Task 2, after the naming-key fix above
- **Issue:** This executor agent launched the first frozen-question benchmark run (`real-document-benchmark-run1.json`) via `run_in_background`. That background process does not survive the executor's own turn boundary — when the turn ended (waiting on the async completion notification), the background process was orphaned/killed mid-run, leaving `run1.json` as an incomplete partial artifact.
- **Resolution:** The orchestrator re-ran **all three** benchmark runs in the foreground (a process context that survives across turns) using the exact documented reproduction command from `capture-provider-env.txt` (`PROVIDER_API_KEY=unused-frozen-questions-bypass PYTHONPATH=src .venv python scripts/real_document_benchmark.py --frozen-questions baseline/03-turingdb/frozen-questions.json --root D:/tmp/baseline-corpus --mcp-url http://127.0.0.1:8095/mcp/ --top-k 20 --search-concurrency 3 --chunk-bytes 524288 --poll-seconds 10 --output baseline/06-gate/real-document-benchmark-run{1,2,3}.json`). This is a change in *how* the runs were executed (foreground vs. this executor's background attempt), not a change in *what* was measured or *which* corpus/providers/questions were used — all three runs are real GPU/real-provider ArcadeDB captures against the same already-verified corpus and frozen question set. Verified independently in this session by loading and cross-checking each run's `summary` block directly from disk (see Accomplishments numbers above, confirmed byte-for-byte against the orchestrator's report).
- **Files modified:** `baseline/06-gate/real-document-benchmark-run{1,2,3}.json` (produced by the orchestrator's foreground re-run, not this executor's orphaned background attempt)
- **Committed in:** N/A (capture artifacts are intentionally left uncommitted per plan instruction; see Task Commits above)

---

**Total deviations:** 3 (2 Rule-3 blocking-issue auto-fixes; 1 harness/execution-mechanics re-run, not a method or data change)
**Impact on plan:** All three were necessary to produce a valid capture at all (stale image would have silently invalidated the check #13 evidence; missing naming key crashed the server entirely; the orphaned background run simply needed re-execution in a surviving process). No scope creep — no plan file outside `baseline/06-gate/*` was modified, and no compose.yaml/source changes were made.

## Issues Encountered

- Git Bash on Windows (MSYS) mangles `/work/...`-style container paths passed to `docker compose run` into Windows paths (e.g. `/work/x` → `C:/Program Files/Git/work/x`) unless `MSYS_NO_PATHCONV=1` is set for that invocation. Documented in `capture-provider-env.txt` for reproducibility.
- A pre-existing, unrelated `compose.yaml` healthcheck bug was observed (the `turing-agentmemory-mcp` healthcheck script asserts `payload['runtime']['ready']`/`arcadedb`/`registry`/`router` keys that no longer exist in the current `/health` response schema — it now nests readiness under `runtime.stages.*.ready` with no top-level `runtime.ready`), causing Docker to report the container "unhealthy" even while it serves fully correct `200 ok` responses with every stage `ready: true`. This is **out of scope** for this plan (not in `files_modified`, not caused by this plan's changes, and does not block the capture — the container runs and serves correctly regardless of Docker's own health-check verdict). Logged here for future triage; not fixed.

## User Setup Required

None beyond what the plan's own `user_setup` block specified (bringing up the GPU stack, confirming the corpus) — both were completed as part of this plan's execution. The two additional environment fixes above (image rebuild, tenant naming key) were auto-resolved per Rule 3 and did not require user action.

## Next Phase Readiness

- All 5 capture artifacts (`e2e-results.json`, `real-document-benchmark-run{1,2,3}.json`, `capture-provider-env.txt`) exist on disk under `baseline/06-gate/`, staged (uncommitted, mostly-but-not-entirely gitignored per the Task Commits note above) for 06-04 to consume via `scripts/gate_diff.py`'s `main()` (`--e2e-port`, `--port-runs` x3, `--corpus-root`/`--manifest`, `--frozen-questions`).
- A preview gate computation in this session shows the port clearing every locked metric's epsilon=0.03 floor with no latency regression — 06-04 should confirm this with the authoritative `gate_diff.py` run and produce the `GATE.md`/`gate-result.json` verdict artifact.
- No blockers for 06-04. The two infrastructure fixes (image rebuild, tenant naming key) are durable for the remainder of this GPU host's session — 06-04 does not need to repeat them unless the containers are recreated again from a stale image.
- The unrelated `compose.yaml` healthcheck schema-mismatch bug (see Issues Encountered) should be triaged in a future plan/phase — it does not block Phase 6 but produces a misleading "unhealthy" Docker status for a fully working service.

---
*Phase: 06-migration-correctness-gate*
*Completed: 2026-07-16*

## Self-Check: PASSED

- FOUND: baseline/06-gate/e2e-results.json
- FOUND: baseline/06-gate/real-document-benchmark-run1.json
- FOUND: baseline/06-gate/real-document-benchmark-run2.json
- FOUND: baseline/06-gate/real-document-benchmark-run3.json
- FOUND: baseline/06-gate/capture-provider-env.txt
- FOUND: 5020ac5 (docs, this summary)
