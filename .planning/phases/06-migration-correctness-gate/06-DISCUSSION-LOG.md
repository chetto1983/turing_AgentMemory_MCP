# Phase 6: Migration-Correctness Gate - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-16
**Phase:** 6-Migration-Correctness Gate
**Areas discussed:** Pass bar & tolerance, Crediting bugs the port fixes, Gate artifact & block enforcement, Corpus/GPU contingency, Retrieval speed

---

## Pass basis (which baseline number is the bar)

| Option | Description | Selected |
|--------|-------------|----------|
| Bug-corrected bar | Port's full 12-doc corpus must meet-or-exceed the baseline's meaningful 7-doc numbers (~0.60/~0.77); credits the port for fixing the document_id bug | ✓ |
| Like-for-like 7-doc | Compare port vs baseline on the same 7 working docs only, excluding normattiva from both | |
| Raw full-corpus | Port full-corpus vs baseline deflated full-corpus (0.349/0.450); artificially low bar | |

**User's choice:** Bug-corrected bar
**Notes:** The TuringDB baseline full-corpus number is deflated by the document_id-length bug (5 normattiva PDFs → 0.000). Grading the port's full corpus against the baseline's working 7-doc quality (~0.60 MRR@20 / ~0.77 recall@20) is the honest, conservative bar.

---

## Tolerance (strictness for an irreversible gate)

| Option | Description | Selected |
|--------|-------------|----------|
| Band + N runs | Port ≥ baseline − ~2-3% relative per metric, averaged over N=3 runs to smooth variance | ✓ |
| Strict ≥, single run | One run; port ≥ baseline on every metric, zero slack | |
| Per-check only | No numeric band; zero per-check/per-document regressions + aggregate not-worse | |

**User's choice:** Band + N runs
**Notes:** Prevents a marginal fluke from passing or failing an irreversible cutover gate. The ε-band applies to the numeric retrieval metrics; the e2e comparison is diffed per-check (deterministic).

---

## E2E truth (harness inflation)

| Option | Description | Selected |
|--------|-------------|----------|
| Fix + re-baseline | Correct check()=bool(detail), re-run baseline side corrected, re-baseline the CI score threshold | ✓ |
| Leave, diff per-check | Keep the CI harness as-is; diff detail-corrected per-check by hand | |

**User's choice:** Fix + re-baseline
**Notes:** A gate authorizing irreversible cutover must measure real passes, not the 4 confirmed false-passing checks (#12/#14/#15/#16). This is the one permitted code touch in the measurement phase — a truthfulness fix, not a behavior/quality change.

---

## Speed (is latency a gate criterion)

| Option | Description | Selected |
|--------|-------------|----------|
| Record + no-regress | Capture per-query latency, assert no regression; quality parity stays the hard gate | ✓ |
| Hard speed gate | Require a demonstrated latency improvement as a co-equal pass criterion | |
| Quality-only | Latency out of the gate's scope | |

**User's choice:** Record + no-regress
**Notes:** User referenced ARCADEDB-capabilities §2 and FUTURE-MILESTONE §1.3 — the O(all-chunks) Python full-scan is the real doc-retrieval bottleneck the port replaces with native indexed ANN + Lucene. A large latency win is expected, but baseline latency was confounded by volume bloat (431 s → ~5.4 s after wipe), so latency is recorded as no-regression, not the hard gate.

---

## Enforcement (how "blocks cutover" is enforced against Phase 7)

| Option | Description | Selected |
|--------|-------------|----------|
| Artifact + Phase-7 guard | Commit baseline/06-gate/ (GATE.md + gate-result.json); Phase 7 hard-gated by a guard/test requiring verdict==GO | ✓ |
| Artifact + manual stop | Same artifact, enforced by discipline/checklist at Phase 7 entry, no automated guard | |
| Fold into CI e2e gate | Extend CI e2e gate — but GPU-less runners can only gate on a stub floor, not the true verdict | |

**User's choice:** Artifact + Phase-7 guard
**Notes:** The real quality comparison needs GPU providers + external corpus, which CI's GPU-less runners can't run. The verdict is produced by a real local/GPU run and committed; the guard checks the committed verdict. Folding into CI was explicitly rejected as weaker than it sounds.

---

## Contingency (reproducibility policy)

| Option | Description | Selected |
|--------|-------------|----------|
| Hard-block until reproduced | Same corpus (sha256-verified vs corpus-manifest.json) + real granite+BGE required; no substitute yields a valid verdict | ✓ |
| Allow equivalent (re-baseline) | Permit an equivalent corpus if the exact one is lost — but forces a full re-baseline of both sides | |

**User's choice:** Hard-block until reproduced
**Notes:** Corpus (D:/tmp/baseline-corpus, all 12 files) and granite+BGE sidecars are present now, so the gate can run for real this phase. The hard-block is the fail-closed rule for any future run where either is unavailable. Equivalent-corpus re-baseline is a last resort, not the default.

---

## Claude's Discretion

- Exact ε tolerance value (within ~2-3% relative), run count beyond the N=3 floor, whether to record per-metric variance.
- The `gate-result.json` schema/field names and the exact form of the Phase-7 guard (pytest vs. gate-check script), provided it fails closed on a missing/NO_GO verdict.
- Plan/wave decomposition (natural order: fix+re-baseline e2e → GPU-backed ArcadeDB capture → diff+verdict+artifact → Phase-7 guard).
- Whether the corrected baseline-side e2e recapture lives under baseline/03-turingdb/ or baseline/06-gate/ (keep the original inflated capture intact either way).

## Deferred Ideas

- Removing TuringDB + rewriting CLAUDE.md invariants — Phase 7 (gated on this phase's GO).
- All FUTURE-MILESTONE retrieval/memory-quality themes (T1–T5) — future milestone, not this gate.
- PERF-03 adaptive-fetch tuning + A/B embedding swap + TEST-07/08 — Phase 9 remainder.
- Fixing the document_id bug as code — expected already fixed in the Phase 4 port; Phase 6 only verifies it.
- Windows CI lane / turingdb-on-Windows — deferred (CI-10, v2); sys.modules stub remains the workaround.
