# Phase 3: TuringDB Retrieval Baseline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-12
**Phase:** 3-TuringDB Retrieval Baseline
**Areas discussed:** Baseline fidelity, Inflated score handling, Comparability locking, Artifact location/format, Industrial patterns (research)

---

## Industrial Patterns (user-requested web research)

Distilled 2025–2026 practice that grounded the decisions:
- Immutable baseline; run the candidate against **identical inputs** ("same rows both sides").
- Record **per-evaluator (per-check) deltas**, not just an aggregate, before pass/fail.
- Strictly version provider config + corpus so a later run is provably comparable.
- Freeze/document the golden query set.

Sources: qaskills.sh RAG Regression Testing 2026; Braintrust RAG evaluation;
Statsig Golden datasets; Microsoft BenchmarkQED; CircleCI RAGAS benchmarking.

---

## Baseline Fidelity

| Option | Description | Selected |
|--------|-------------|----------|
| Stubs for e2e + real GPU for real-doc | Deterministic stub e2e; real-doc on real stack | |
| Real GPU providers for BOTH | e2e also on real providers (E2E_USE_EXTERNAL_*) | ✓ (e2e mode) |
| Stub-only, defer real-doc | e2e only, skip real-doc benchmark | |

**User's choice:** Real corpus of Italian docs (PDF/XLSX/EPUB/webpage), driven via the
MCP installed in Claude Code + the existing `skills/turing-agentmemory` skill; then in
the follow-up, **real GPU providers for e2e too**, user-provided fixed corpus path, and
MCP+skill as a **supplemental** hands-on check.
**Notes:** User corrected an incorrect concern that EPUB was unsupported — verified
MarkItDown ships a built-in `_epub_converter.py` and `real_document_benchmark.py`
already lists `.epub` in `SUPPORTED_SUFFIXES`.

## Inflated Score Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Freeze + document + per-check | Record as-is, add per-check granularity + documented false-passes | ✓ |
| Fix harness first, honest baseline | Fix bug → ~14/19; flips CI gate red; heavy | |
| Surgical: fix only chunk-count | Fix only the non-cancelling check | |

**User's choice:** Freeze + document + per-check.
**Notes:** Inflation is harness-side (check() bug + chunk-count mismatch), not
embeddings, so real providers don't fix it. Kept CI gate stable; per-check diff makes
regressions visible in Phase 6. Chunk-count check flagged as not "cancelling out"
across the port.

## Comparability Locking

| Option | Description | Selected |
|--------|-------------|----------|
| Freeze generated questions into artifact | Run once, capture questions, Phase 6 replays | ✓ |
| Pin model + temp=0 + seed, regenerate | Rely on LLM determinism each run | |
| Accept variance, run N times | Compare distributions within tolerance | |

**User's choice:** Freeze generated questions into artifact; Phase 6 replays.
**Notes:** Likely needs a minimal additive `real_document_benchmark.py` change to
*load* a frozen-questions file.

## Artifact Location / Corpus Persistence

| Option | Description | Selected |
|--------|-------------|----------|
| Top-level baseline/ dir | Committed baseline/03-turingdb/ (force-add past gitignore) | ✓ |
| Inside the phase dir | .planning/phases/03-.../ | |
| Manifest + hashes only | Commit corpus manifest/sha256, not bytes | ✓ |
| Copy corpus bytes into baseline | Self-contained but size/licensing cost | |

**User's choice:** Top-level `baseline/03-turingdb/`; corpus persisted as manifest +
sha256 hashes only.
**Notes:** `.benchmarks/` and `e2e-results.json` are gitignored → force-add required.

## Claude's Discretion

- Number of runs / variance recording (single frozen run is the default).
- Exact manifest schema/field names within the mandatory-metadata constraints.

## Deferred Ideas

- Fix the e2e harness inflation (belongs to Phase 4+, where the CI threshold can be re-baselined).
- Adding new format-ingestion support (not needed — current stack covers the target formats).
- Committing a self-contained Italian fixture corpus (declined on size/licensing grounds).

## Open Input Required

- **Corpus `--root` path** was not supplied during discussion. The planner/executor
  MUST obtain the Italian document directory path from the user before running the
  baseline.
