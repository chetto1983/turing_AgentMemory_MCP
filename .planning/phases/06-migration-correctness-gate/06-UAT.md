---
status: complete
phase: 06-migration-correctness-gate
source: [06-VERIFICATION.md]
started: 2026-07-16T11:03:38Z
updated: 2026-07-16T11:43:08Z
---

## Current Test

[testing complete]

## Tests

### 1. GPU-backed capture authenticity
expected: The captures are genuine real-hardware, real-provider ArcadeDB measurements (non-stub sidecar hostnames, sha256-verified corpus, check #13's real IndexError→pass flip, N=3 run-to-run variance), not hand-crafted artifacts.
result: pass
source: reproduced-live
evidence: |
  Independently reproduced against the live GPU stack during this UAT session (not
  a static read of the committed JSON):
  - GPU present: NVIDIA RTX A2000 Laptop, 4096 MiB — matches capture-provider-env.txt exactly.
  - Fresh 4th benchmark run (benchmark_id real-documents-direct-mcp-20260716T113526Z,
    11:35:26→11:39:49Z) produced full-corpus mrr_at_20=0.6953 / recall_at_1=0.60 /
    recall_at_20=0.8667 / latency_mean=3324ms / 60 questions / 0 search errors — lands
    inside the committed run1/2/3 band (0.6787/0.6787/0.6955) and matches run3 almost exactly.
  - GPU genuinely inferring during the fresh run: 20s dmon trace showed SM bursts of
    82/75/87/79/88% then idle between batches — the real granite-embed + BGE-rerank +
    GLiNER inference signature, matching the "88–100% during active inference" narrative.
  - Corpus sha256: all 12 files byte-identical to baseline/03-turingdb/corpus-manifest.json,
    zero drift, zero missing — independently reproduces the gate's D-11 pre-flight.
  - Provider config non-stub: sidecar hostnames agentmemory-embed:8080 / agentmemory-rerank:8080
    (not 127.0.0.1); all sidecars healthy.
  - Committed runs show genuine-measurement hallmarks: sequential back-to-back timestamps
    (~4 min each), real latency noise between runs, a real 8033ms outlier in run3, and a
    run3 metric flip on the DPR-156 decree (mrr 0.70→0.90) — not hand-copied values.
  Verified by the orchestrator directly this session; no dependence on the prior (cleared) session.

### 2. GATE.md honest-narration read-through
expected: GATE.md's verdict + rationale are honest — graded against the bug-corrected 7-doc bar (not the deflated full-corpus aggregate), complete per-document diff, disclosed deviations (GLiNER-on, latency volume-bloat confound, D-05 already-fixed, check-name rename), correct per-script repro flags (--out for e2e_score.py, --output for real_document_benchmark.py).
result: pass
source: read-through + code + user domain confirmation
evidence: |
  Read GATE.md end-to-end; every figure matches gate-result.json; deviations disclosed;
  repro flags correct (--out vs --output, explicitly warned not to conflate).
  One caveat examined and resolved: the aggregate table's port_mean (mrr 0.6843, +0.0863
  margin) is the full-12-doc N=3 mean, compared against the 7-doc baseline bar (0.5979).
  A same-subset (7-doc) comparison shows the port TIES the baseline (mrr +0.0004,
  recall_at_1 +0.0000, recall_at_20 +0.0000). This is NOT dishonesty:
  - It is the LOCKED D-01 design ("grade the port's full corpus against the baseline's
    working 7-doc quality... credits the port for fixing the bug"), disclosed in GATE.md's
    header ("full-corpus retrieval quality clears the 7-doc bar").
  - The 7-doc tie is EXPECTED because document_search is legacy dense+lexical+rerank RAG
    (blend_hybrid_score → _rerank_documents in store_documents.py) — it consumes no
    entity/graph/community channel, so GLiNER/entity extraction does not affect it (D-06).
    The bug-unaffected docs therefore retrieve identically to the TuringDB baseline.
  - The port's real lift is the 5 normattiva docs recovering 0.0→~0.8 (the document_id-length
    bug fix), credited per D-01 and shown separately as normattiva_evidence.
  Verdict GO is robust: it holds under both the D-01 full-corpus framing AND the honest
  same-subset framing (0.5983≥0.5800, 0.5143≥0.4989, 0.7714≥0.7483 all clear the 3% floor).

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none]
