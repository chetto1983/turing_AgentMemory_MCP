# Phase 6: Migration-Correctness Gate - Context

**Gathered:** 2026-07-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Prove the ArcadeDB-ported, per-tenant-isolated stack **provably meets-or-exceeds**
the committed Phase 3 TuringDB retrieval baseline (`baseline/03-turingdb/`), and
record a **GO/NO-GO gate artifact** that authorizes (or blocks) the irreversible
Phase 7 TuringDB removal. Concretely: re-run `scripts/e2e_score.py` and
`scripts/real_document_benchmark.py` against the ArcadeDB backend using the SAME
providers, SAME corpus, and SAME frozen questions as the baseline; diff the results
within a documented tolerance; and commit the comparison as the exit criterion.

**In scope:** capturing the ArcadeDB-side e2e + real-document-benchmark numbers under
matched conditions; the corrective fix to the e2e harness inflation (see D-05) plus a
corrected baseline-side recapture; the per-metric / per-check / per-document diff and
tolerance logic; a latency (no-regression) measurement; a committed
`baseline/06-gate/` artifact (human `GATE.md` + machine `gate-result.json`); and the
Phase-7-entry guard that reads the committed verdict.

**Out of scope (this is a measurement + gate phase — do NOT redesign behavior):**
removing TuringDB or rewriting CLAUDE.md invariants (Phase 7); improving retrieval
quality, chunking, fusion weights, or the reranker beyond what already landed in
Phase 4; any of the FUTURE-MILESTONE retrieval/GraphRAG themes (T1–T5); new document
formats; Garage/OIDC/observability concern work (Phases 8–12). The gate MEASURES the
ported stack; it does not change it (the one permitted code touch is the D-05 e2e
harness correctness fix, which is a truthfulness fix, not a behavior/quality change).

</domain>

<decisions>
## Implementation Decisions

### Pass bar — what "meets-or-exceeds" is measured against

- **D-01 — Bug-corrected bar (LOCKED):** The ArcadeDB port's **full 12-document
  corpus** retrieval numbers must meet-or-exceed the baseline's **bug-corrected
  "meaningful" 7-doc figures (~0.60 MRR@20 / ~0.77 recall@20)** — NOT the deflated
  full-corpus aggregate (0.349 MRR@20 / 0.450 recall@20). Rationale: the baseline
  full-corpus number is deflated by the TuringDB `document_id`-length bug that zeroed
  the 5 normattiva PDFs; the port's native indexed search is expected to retrieve
  those docs, so grading the port's full corpus against the baseline's *working*
  7-doc quality is the honest, conservative bar. It credits the port for fixing the
  bug instead of comparing against a broken run or against an artificially low bar.
- **D-02 — Metric set (LOCKED-by-implication):** The diff covers **MRR@20, recall@1,
  and recall@20**, reported both **per-document AND aggregate** (per-check /
  per-document granularity is mandatory per Phase 3 D-07 — an unchanged aggregate can
  hide a per-document regression). Latency is a separate recorded metric (D-06).
- **D-03 — Normattiva-fix is positive evidence (LOCKED-by-implication):** The gate
  must show the port actually retrieves the 5 normattiva docs (non-zero MRR/recall on
  those documents) and that e2e check #13
  (`document_search_retrieves_exact_top1_with_citation_and_neighbor_context`) now
  passes — direct evidence the `document_id`-length bug is fixed on ArcadeDB. This is
  part of "meets-or-exceeds," not a separate optional check.

### Tolerance — strictness for an irreversible gate

- **D-04 — Band + N=3 runs (LOCKED):** Meets-or-exceeds means **port ≥ baseline − a
  small ε (~2–3% relative)** on each retrieval metric, evaluated on the **mean of
  N=3 real-document-benchmark runs** to smooth rerank/run nondeterminism. A single
  marginal fluke must neither pass nor fail an irreversible cutover gate. The e2e
  score-gate comparison is diffed **per-check** (deterministic pass/fail), not via the
  ε-band — the band applies to the numeric retrieval-quality metrics. Exact ε value,
  run count beyond the N=3 floor, and whether to also record variance/stddev are
  planner discretion within this contract.

### E2E harness truthfulness

- **D-05 — Fix + re-baseline (LOCKED):** Correct the e2e harness inflation
  (`e2e_score_scenarios.py` `check()` must compute `ok = bool(detail)`) so the four
  confirmed false-passing checks (#12 `document_ingest_text_writes_chunks`, #14
  `document_search_hybrid_exact_code_match_explains_lexical_score`, #15
  `document_ingest_text_is_idempotent_for_same_payload`, #16
  `document_reindex_text_replaces_old_chunks_and_metadata`) report their true state.
  Then **re-run the baseline side under the corrected harness** for a like-for-like
  comparison, and **re-baseline the CI score threshold** (`score >= 9.8 and
  len(checks) == 19`) to whatever the corrected-truth passing state is. A gate that
  authorizes irreversible cutover must measure real passes, not inflated ones. NOTE:
  this is the one deliberate code touch permitted in this measurement phase — it fixes
  reporting correctness, it does not change retrieval behavior/quality. Handle the
  chunk-count non-cancellation caveat (checks #12/#16 hardcode `chunk_count`; Phase 4
  re-chunking may legitimately change these) via the per-check diff, not the aggregate.

### Retrieval speed

- **D-06 — Record + no-regression (LOCKED):** Capture per-query retrieval **latency**
  on the ArcadeDB run and assert the port **does not regress** versus the baseline
  (a large improvement is expected from replacing the O(all-chunks) Python full-scan —
  FUTURE-MILESTONE §1.3 — with native indexed ANN + Lucene). **Quality parity (D-01/
  D-04) remains the HARD gate;** latency is a recorded secondary metric that must not
  regress but is not, on its own, a blocker. Be careful comparing against the
  baseline's confounded latency (volume bloat inflated one path ~60×: 431 s → ~5.4 s
  after the `turing-data` volume was wiped) — compare against the clean-DB baseline
  latency, and document the confound.

### Provider / corpus / question parity (carried forward — NOT re-litigated)

- **D-07 — Exact provider match (LOCKED, from Phase 3 D-01/D-02 + BASELINE.md):** The
  gate run MUST use the SAME real GPU providers as the baseline — embedder
  `mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M` (768d) and reranker
  `bge-reranker-v2-m3-Q8_0.gguf` (NOT Qwen3), with `E2E_USE_EXTERNAL_EMBED=1
  E2E_USE_EXTERNAL_RERANK=1`, and **GLiNER OFF** (the baseline reflects embed+rerank
  quality only). Stub embed/rerank does NOT produce a valid quality verdict.
- **D-08 — Frozen-question replay (LOCKED, from Phase 3 D-08):** Replay the exact 60
  frozen questions via `--frozen-questions baseline/03-turingdb/frozen-questions.json`
  — no regeneration — so retrieval drift, not question drift, is what is measured.

### Gate artifact + enforcement

- **D-09 — Committed artifact (LOCKED):** Commit a self-contained `baseline/06-gate/`
  directory containing a **human-readable `GATE.md`** (the GO/NO-GO verdict + rationale
  + full deviation/reproduction record, mirroring the `baseline/03-turingdb/BASELINE.md`
  style) and a **machine-readable `gate-result.json`** (per-metric diff, per-check
  diff, per-document diff, latency, tolerance parameters used, run count, provider
  config, corpus sha-verification result, and an explicit `verdict: GO | NO_GO`).
  Because `.benchmarks/`/`e2e-results.json` are gitignored, force-add into
  `baseline/06-gate/` (same pattern as Phase 3 D-09). Also commit the raw ArcadeDB-side
  captures (`e2e-results.json`, `real-document-benchmark.json`, and the corrected
  baseline-side recapture) into this directory for reproducibility.
- **D-10 — Phase-7 hard guard (LOCKED):** Phase 7 (TuringDB removal) is **hard-gated**
  by a guard/test that reads the committed `gate-result.json` and refuses to proceed
  unless `verdict == GO`. The real quality comparison needs GPU providers + the
  external corpus (which CI's GPU-less runners CANNOT run — CI degrades GPU tiers to a
  stub floor), so the verdict is produced by a **real local/GPU run and committed**;
  the guard checks the committed verdict rather than re-running the GPU comparison in
  CI. (Explicitly rejected: folding the meet-or-exceed check into the CI e2e gate,
  because on GPU-less runners it would gate on a stub floor, not the true verdict.)

### Reproducibility / contingency

- **D-11 — Hard-block until reproduced (LOCKED):** A valid gate REQUIRES the exact
  baseline corpus — **sha256-verified against `baseline/03-turingdb/corpus-manifest.json`,
  failing closed on any drift** — plus the real granite+BGE sidecars. If either is
  unavailable at run time, the gate CANNOT produce a GO; the fix is to reproduce the
  corpus / stand up the sidecars, never to substitute a different corpus or a stub
  provider. (Both are present now: `D:/tmp/baseline-corpus` has all 12 files, and
  `compose.yaml` pins `arcadedb`, `agentmemory-embed` (granite), `agentmemory-rerank`
  (BGE), and `agentmemory-model-init`.) If the exact corpus is ever permanently lost,
  the fallback is a full re-baseline (re-capture BOTH sides on an equivalent corpus) —
  explicitly a heavier re-baseline, not a strict diff — but that is a last resort, not
  the default path.

### Claude's Discretion

- Exact ε tolerance value (within the ~2–3% relative intent), whether to run more
  than the N=3 floor, and whether to record per-metric variance/stddev alongside the
  mean.
- The concrete `gate-result.json` schema/field names (within the D-09 content
  contract) and the exact form of the Phase-7 guard (pytest guard vs. a small
  gate-check script), provided it fails closed on a missing/NO_GO verdict.
- Module/plan/wave decomposition. Note the natural ordering: (1) fix + re-baseline the
  e2e harness (D-05), (2) capture the GPU-backed ArcadeDB e2e + real-doc benchmark
  under matched providers/corpus/questions (D-07/D-08), (3) compute the diff + verdict
  and write the artifact (D-09), (4) wire the Phase-7 guard (D-10).
- Whether the corrected baseline-side e2e recapture (D-05) is stored under
  `baseline/03-turingdb/` (as a corrected companion) or under `baseline/06-gate/` —
  keep the original inflated capture intact either way for provenance.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/ROADMAP.md` §"Phase 6: Migration-Correctness Gate" — fixed goal,
  dependencies (Phases 4, 5), and the three success criteria (SC#1 run+compare within
  tolerance; SC#2 meet-or-exceed as a hard blocker; SC#3 recorded gate artifact).
- `.planning/REQUIREMENTS.md` — **ARC-09** (this phase's sole requirement).
- `.planning/PROJECT.md` — the migration-correctness-gate decision, the hard ordering
  (baseline before port, gate before removal), and the "never claim a benchmark win
  from one corpus/one run/mismatched configs" discipline.

### The baseline being compared against (the yardstick — READ FIRST)
- `baseline/03-turingdb/BASELINE.md` — the committed TuringDB yardstick: provider
  config (granite + BGE), corpus, run params, the D-01 real-doc results (full-corpus
  vs 7-doc meaningful numbers), the D-02 e2e per-check table with the FOUR confirmed
  false-passing checks, the `document_id`-length bug, and the exact reproduction
  commands (incl. `--frozen-questions`). Load-bearing for every decision here.
- `baseline/03-turingdb/e2e-results.json` — raw D-02 real-provider e2e output (the
  inflated capture; D-05 corrects the harness and recaptures).
- `baseline/03-turingdb/real-document-benchmark.json` — raw D-01 benchmark output.
- `baseline/03-turingdb/frozen-questions.json` — the D-08 replay contract (60
  questions; do NOT regenerate).
- `baseline/03-turingdb/corpus-manifest.json` — the D-11 sha256 corpus-identity
  contract to verify the gate run uses the exact same files.
- `.planning/phases/03-turingdb-retrieval-baseline/03-CONTEXT.md` — Phase 3 decisions
  D-07 (inflation caveats, per-check diffing) and D-08 (`--frozen-questions`) that this
  phase directly consumes.

### The ported stack being measured (partial ArcadeDB capture from Phase 4)
- `baseline/04-arcadedb/NOTES.md` — records the Phase-4 ArcadeDB captures: the
  `VALIDATED_10_10` e2e is STUB-provider (NOT quality-comparable), and the real-doc
  benchmark was NOT captured. States plainly that the GPU-backed, quality-comparable
  capture is Phase 6's job, with the exact reproduction commands.
- `baseline/04-arcadedb/e2e-results.json` — the stub-provider ArcadeDB e2e (10/10),
  useful as a field-shape reference, NOT as a quality verdict.

### The measurement engines (the scripts this phase runs)
- `scripts/e2e_score.py` → `src/turing_agentmemory_mcp/e2e_score.py` — score/verdict/CLI;
  the CI gate `score >= 9.8 and check_count == 19` (`e2e_score.py:165,189`) that D-05
  re-baselines; reads `E2E_USE_EXTERNAL_EMBED`/`E2E_USE_EXTERNAL_RERANK`.
- `src/turing_agentmemory_mcp/e2e_score_scenarios.py` — the 19 deterministic checks;
  the `check()` helper (`:39-51`) whose `ok = bool(detail)` correctness is the D-05 fix
  target; where the false-passing checks (#12/#14/#15/#16) and the #13 failure live.
- `scripts/real_document_benchmark.py` — live-MCP ingest + frozen-question scoring;
  supports `--frozen-questions`, `--root`, `--top-k`, `--chunk-bytes`, `--poll-seconds`,
  `--search-concurrency`, `--question-*`.
- `scripts/real_document_benchmark_scoring.py` — deterministic scoring/grounding +
  `load_frozen_questions`.

### ArcadeDB port behavior (why the port should fix the baseline bug + full-scan)
- `.planning/research/ARCADEDB-capabilities-for-port.md` §2 — how native filtered-ANN
  + Lucene make the lexical channel an INDEXED query, eliminating the O(all-chunks)
  Python scan; the op→ArcadeDB mapping the port implemented. *(User-referenced during
  discussion — relevant to D-03 normattiva-fix evidence and D-06 latency.)*
- `.planning/research/FUTURE-MILESTONE-retrieval-memory-quality.md` §1.2 (reranker is
  the dominant doc-retrieval lever; BGE swap piloted in Phase 3), §1.3 (the
  O(all-chunks) full-scan bottleneck the port fixes — GPU idle, CPU/DB-bound; "worth an
  explicit benchmark in the port (ARC-09)"). *(User-referenced during discussion —
  grounds the D-06 latency decision. NOTE: its T1–T5 themes are FUTURE-milestone,
  explicitly OUT of scope here.)*

### Phase 4 port decisions this gate assumes are in place
- `.planning/phases/04-arcadedb-direct-port/04-CONTEXT.md` — the direct-port decisions
  (native HNSW + Lucene, deleted `vector_id` int-join, RRF unchanged, versioned index)
  and the explicit note that "the meet-or-exceed parity gate is Phase 6."

### Invariants & discipline
- `CLAUDE.md` — invariant #1 (tenant scope, still enforced through the port), #3
  (stable IDs), the benchmark-JSON convention, and "Don't claim a benchmark win from
  one corpus, one run, or mismatched provider configs" (directly motivates D-04/D-07/
  D-11); Definition of Done for retrieval/document changes.
- `CONTRIBUTING.md` — the real-document E2E verification steps referenced by the DoD.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The two measurement scripts already exist and already ran for Phase 3 — this phase
  is about **capturing/comparing** ArcadeDB-side outputs under matched conditions, not
  writing new benchmarks. The `--frozen-questions` load path (added in Phase 3) and the
  deterministic scoring helpers are the ready comparison machinery.
- `baseline/03-turingdb/` is a complete, committed comparison target with a pinned
  provider config, sha-manifest corpus identity, frozen questions, and per-check e2e
  granularity — everything D-01/D-04/D-08/D-11 need.
- `baseline/04-arcadedb/e2e-results.json` already demonstrates the ArcadeDB-side e2e
  field shape (`backend`/`arcadedb_image` added) is directly diffable field-by-field
  against the baseline — reuse that shape for the GPU recapture.
- The Windows `sys.modules["turingdb"]` stub convention (used by `tests/conftest.py`
  and ~47 test files, and by the Phase-4 e2e capture) lets `e2e_score.py`'s
  `from turingdb import __version__` import succeed on this host without the wheel.

### Established Patterns
- Benchmark/e2e scripts emit machine-readable JSON; committed baseline artifacts are
  force-added under a top-level `baseline/<phase>/` dir (Phase 3 D-09) because
  `.benchmarks/`/`e2e-results.json` are gitignored — `baseline/06-gate/` follows suit.
- No-skip-as-green discipline (`tests/conftest.py` under `CI=true`) and the 600-LOC
  no-allowlist cap apply to any new gate/guard code.
- Per-check / per-document diffing (not just aggregate) is the mandated comparison
  granularity (Phase 3 D-07) — the aggregate can hide chunk-count-driven flips.

### Integration Points
- The committed `baseline/06-gate/gate-result.json` `verdict` becomes a **cross-phase
  contract**: Phase 7's entry guard reads it and hard-blocks TuringDB removal unless
  `GO`. This is the concrete mechanism that makes ARC-09 a real gate, not a report.
- The D-05 harness fix changes `e2e_score_scenarios.py`/`e2e_score.py` and the CI
  threshold in `.github/workflows/ci.yml` (currently asserts a measured stub floor
  ~9.4) — coordinate the re-baseline so CI stays truthful and green post-fix.
- The gate run drives the real dockerized stack: `arcadedb` + `agentmemory-embed`
  (granite) + `agentmemory-rerank` (BGE) + `agentmemory-model-init` (all in
  `compose.yaml`); the real-doc benchmark points `--mcp-url` at the running MCP.

</code_context>

<specifics>
## Specific Ideas

- The user explicitly wants the gate to be **honest about the port's win**: grade the
  full ported corpus against the baseline's bug-corrected quality (D-01), fix the e2e
  inflation so the numbers mean what they say (D-05), and surface the normattiva-fix as
  positive evidence (D-03) — rather than either flattering the port against a broken
  baseline or hiding behind an inflated aggregate.
- The user cares about **retrieval speed**, not only quality — they pointed at the
  ARCADEDB-capabilities and FUTURE-MILESTONE research showing the O(all-chunks)
  full-scan is the real doc-retrieval bottleneck the port removes; hence D-06 records
  latency as a no-regression criterion.
- The user wants the gate to have **teeth**: a committed GO/NO-GO artifact plus a
  hard automated Phase-7 guard (D-09/D-10), and a fail-closed reproducibility rule
  (D-11) — consistent with the milestone's "irreversible removal is gated strictly"
  posture.

</specifics>

<deferred>
## Deferred Ideas

- **Removing TuringDB + rewriting CLAUDE.md invariants (#2/#4/#6)** — Phase 7, gated on
  this phase's GO verdict.
- **All FUTURE-MILESTONE retrieval/memory-quality themes (T1–T5)** — memory
  consolidation/lifecycle, GraphRAG-over-documents (closing the doc↔memory graph
  asymmetry), reranker/embedding/fusion upgrades beyond the BGE swap already landed,
  reasoning/procedural memory, POLE+O entity typology. Explicitly a future milestone
  (`FUTURE-MILESTONE-retrieval-memory-quality.md`), NOT this gate.
- **PERF-03 adaptive-fetch tuning + A/B embedding-model swap/canary/rollback +
  TEST-07/08 extraction failure-mode tests** — Phase 9 remainder (the versioned-index +
  batched-embed foundation already landed in Phase 4).
- **Fixing the `document_id`-length bug as a code change** — that fix is expected to
  have landed in the Phase 4 port (native indexed search); Phase 6 only *verifies* it
  via D-03, it does not implement it. If the gate reveals it is NOT fixed, that is a
  Phase-4 defect surfaced by the gate (fix-on-touch), not new Phase-6 scope.
- **Windows CI lane / turingdb-on-Windows** — the `sys.modules` stub remains the
  documented workaround; a real Windows lane is deferred (CI-10, v2).

### Reviewed Todos (not folded)
None — no pending todos matched this phase (`todo.match-phase 6` returned 0).

</deferred>

---

*Phase: 6-Migration-Correctness Gate*
*Context gathered: 2026-07-16*
