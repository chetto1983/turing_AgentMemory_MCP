# Phase 3: TuringDB Retrieval Baseline - Context

**Gathered:** 2026-07-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Capture a **recorded, versioned retrieval-quality baseline of the current TuringDB
stack** as the yardstick for the Phase 6 migration-correctness gate. Run
`scripts/e2e_score.py` and `scripts/real_document_benchmark.py` against the current
TuringDB-backed stack, capture their numeric results to a committed, reproducible
artifact, and commit it **before any ArcadeDB code touches the stack** (ARC-01).

**In scope:** running the two baseline scripts against the current stack; freezing
their inputs and outputs into a committed, comparable artifact; documenting the
provider config / corpus / run params that make it reproducible; supplemental
hands-on validation via the MCP installed in Claude Code.

**Out of scope (snapshot phase — do NOT change behavior):** any ArcadeDB work;
fixing retrieval quality; changing chunking, embeddings, or scoring semantics.
The one *permitted* code touch is a minimal, additive `real_document_benchmark.py`
enhancement to **load** frozen questions (see D-08) — it must not alter how the
current run generates/scores.

</domain>

<decisions>
## Implementation Decisions

### Baseline Fidelity
- **D-01:** The baseline is a **real** run against the real Dockerized stack with
  **real GPU embed/rerank providers** — not stub-only. `real_document_benchmark.py`
  runs against a live MCP + real providers on a real corpus.
- **D-02:** `e2e_score.py` also runs against **real providers**
  (`E2E_USE_EXTERNAL_EMBED=1` / `E2E_USE_EXTERNAL_RERANK=1`), not the in-process
  stubs. Consequence: the e2e number becomes provider-dependent, so the exact
  provider config MUST be pinned in the artifact (see D-11) for Phase 6 to reproduce.
- **D-03:** Windows note — `turingdb` has no Windows wheel; the current TuringDB
  stack runs under **Docker** to execute both scripts (see `[[e2e-requires-docker-on-windows]]`).

### Corpus
- **D-04:** The corpus is a **real Italian, multi-format document set** — PDF, XLSX,
  EPUB, and webpage/HTML. All four formats are confirmed ingestable by the current
  stack (`real_document_benchmark.py:59-70` `SUPPORTED_SUFFIXES`; EPUB via MarkItDown's
  built-in `_epub_converter.py`, unaffected by `enable_plugins=False`).
- **D-05:** The user provides a **fixed `--root` path** to their existing Italian
  files. **⚠ OPEN INPUT — the path was not yet supplied; the planner/executor MUST
  obtain it from the user before running.**
- **D-06:** **Persist corpus as manifest + sha256 hashes only** (filenames, sizes,
  sha256, format, page/sheet counts) — NOT the file bytes. Avoids repo-size and
  licensing/redistribution concerns for the Italian docs. Phase 6 re-points `--root`
  at the same files; reproducibility depends on those files still existing.

### Inflated Score Handling
- **D-07:** The committed e2e score is **known-inflated** (reports ~18/19; true
  ~14/19) via a `check()` harness bug + a document chunk-count mismatch — **not**
  embeddings, so switching to real providers does NOT fix it
  (see `[[e2e-stub-score-baseline]]`). Decision: **freeze the number as-is**, but
  additionally record **per-check pass/fail granularity** and **explicitly document
  which checks are known-false-passing**. Do NOT fix the harness in this phase
  (fixing would flip the CI gate `score >= 9.8` red and belongs to Phase 4+).
  Phase 6 must diff **per-check**, not just the aggregate, so a real regression on
  any currently-passing check stays visible even though the headline number is inflated.
  Special caveat for the chunk-count check: Phase 4 re-chunking may change it, so it
  will not "cancel out" across the port — call it out in the manifest.

### Comparability Locking
- **D-08:** `real_document_benchmark.py` generates its 10 questions/file via an LLM
  (nondeterministic). **Freeze the generated questions into the artifact**; Phase 6
  **replays those exact questions** (no regeneration) so retrieval drift — not
  question drift — is what gets measured. This requires a **minimal additive change
  to `real_document_benchmark.py` to load a frozen-questions file** (it currently
  only generates); justified as a means to SC#2 reproducibility. The change must not
  alter generation/scoring for the baseline run itself.

### Artifact Location & Format
- **D-09:** Committed baseline lives in a **top-level `baseline/03-turingdb/`**
  directory (self-contained, decoupled from `.planning/`, obvious for Phase 6 to
  consume). Because `.benchmarks/` and `e2e-results.json` are **gitignored**
  (`.gitignore:14-15`), the artifact must be **force-added** into `baseline/`.
- **D-10:** Format = **raw machine-readable JSON** (the scripts' own outputs +
  frozen questions + corpus manifest) **plus a human-readable manifest** (e.g.
  `baseline/03-turingdb/BASELINE.md`) summarizing config, per-check results, and the
  documented inflation caveats.
- **D-11 (mandatory metadata):** The artifact MUST pin everything needed to
  reproduce and directly compare later (SC#2): embed + rerank **model IDs, dims, and
  endpoints**; corpus manifest + sha256 hashes; the **frozen questions**; run params
  (`--top-k`, `--chunk-bytes`, `--poll-seconds`, `--scope`, `--question-model`,
  `--question-url`, `--search-concurrency`); the **git SHA** of the snapshot; and the
  **per-check e2e results** with the inflation caveats from D-07.

### MCP + Skill Validation
- **D-12:** Install this MCP into Claude Code and use the existing
  `skills/turing-agentmemory` skill to **hands-on validate** ingest + cited retrieval
  on the Italian corpus. This is **supplemental** (confidence-building) — the
  committed, comparable baseline is the two scripts' numeric output, not the
  interactive session.

### Claude's Discretion
- Number of benchmark runs / variance recording (single frozen run vs N runs) is not
  locked — planner may choose, but a single frozen run with pinned inputs (D-08) is
  the default given comparability comes from identical inputs, not averaging.
- Exact manifest schema/field names within the D-11 constraints.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Baseline scripts (the deliverable's engines)
- `scripts/e2e_score.py` — thin CLI shim; imports `main` from
  `src/turing_agentmemory_mcp/e2e_score.py`.
- `src/turing_agentmemory_mcp/e2e_score.py` — score/verdict/CLI orchestration;
  `--out` default `e2e-results.json`; gate `score >= 9.8 and check_count == 19`;
  reads `E2E_USE_EXTERNAL_EMBED` / `E2E_USE_EXTERNAL_RERANK` (lines ~57/63).
- `src/turing_agentmemory_mcp/e2e_score_scenarios.py` — the 19 deterministic
  MCP checks (this is where the `check()` harness bug + chunk-count mismatch live).
- `scripts/real_document_benchmark.py` — live-MCP ingest + 10-question/file scoring;
  `SUPPORTED_SUFFIXES` (`:59-70`), CLI args (`:75-94`), question generation. **This is
  the file the D-08 frozen-questions load path is added to.**
- `scripts/real_document_benchmark_scoring.py` — deterministic scoring/grounding helpers.

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — **ARC-01** (this phase's sole requirement).
- `.planning/ROADMAP.md` §"Phase 3" — Goal + SC#1–3; Phase 6 (`ARC-09`) is the
  consumer of this baseline.

### Invariants & discipline
- `CLAUDE.md` — invariant #6 (`load_graph` after TuringDB restart), benchmark-JSON→
  `.benchmarks/` convention (overridden here by D-09 for a *committed* artifact),
  and the Definition of Done for document changes.
- `CONTRIBUTING.md` — real-document E2E verification steps referenced by the DoD.

### Format support
- `src/turing_agentmemory_mcp/document_processing.py` — PDF→PDFium, everything else→
  MarkItDown (`enable_plugins=False`; EPUB still works via built-in converter).

### Supplemental validation
- `skills/turing-agentmemory/SKILL.md` (+ `references/mcp-tools.md`, `operations.md`)
  — the installed-skill path used for D-12 hands-on validation.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/e2e_score.py` + `scripts/real_document_benchmark.py` already exist and run
  the exact measurements SC#1 requires — the phase is about **capturing/freezing**
  their outputs, not writing new benchmarks.
- `skills/turing-agentmemory/` is already a complete, git-tracked Claude Code skill
  (SKILL.md, references, evals) — ready to install for D-12 validation.

### Established Patterns
- Benchmark scripts write machine-readable JSON (CLAUDE.md). `real_document_benchmark`
  emits a JSON artifact + prints `BENCHMARK_COMPLETE {summary}`; `e2e_score` writes
  `e2e-results.json` (`verdict`/`score`/`check_count`).
- `E2E_USE_EXTERNAL_EMBED` / `E2E_USE_EXTERNAL_RERANK` env flags already switch the
  e2e gate from stubs to real providers — no code change needed for D-02.

### Integration Points
- The committed `baseline/03-turingdb/` artifact is the exact input Phase 6 (ARC-09)
  reads to run the meet-or-exceed comparison. Its schema (D-11) is a cross-phase contract.
- Frozen questions (D-08) become a new input contract between this phase and Phase 6.

</code_context>

<specifics>
## Specific Ideas

- Corpus must be **Italian** and span **PDF, XLSX, EPUB, and webpage** — the user
  wants multilingual, multi-format retrieval represented in the yardstick, not the
  synthetic English stub scenarios.
- The user wants to **drive the stack by hand** through Claude Code (installed MCP +
  skill), not only trust a script number (D-12).

</specifics>

<deferred>
## Deferred Ideas

- **Fix the e2e harness inflation** (`check()` bug + chunk-count mismatch) so the gate
  reflects true quality — deferred out of this snapshot phase; belongs with the
  ArcadeDB port / gate work (Phase 4+), where the CI threshold can be re-baselined.
- **Add EPUB/other-format ingestion improvements** — not needed; current stack already
  handles the target formats.
- **Assembling a committed, self-contained Italian fixture corpus** (vs. manifest-only)
  — considered and declined (D-06) on size/licensing grounds; could be revisited if
  full clean-checkout reproducibility becomes required.

</deferred>

---

*Phase: 3-TuringDB Retrieval Baseline*
*Context gathered: 2026-07-12*
