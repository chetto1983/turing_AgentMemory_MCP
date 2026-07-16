---
status: testing
phase: 06-migration-correctness-gate
source: [06-VERIFICATION.md]
started: 2026-07-16T11:03:38Z
updated: 2026-07-16T11:03:38Z
---

## Current Test

number: 1
name: GPU-backed capture authenticity
expected: |
  The GPU-backed real-provider captures (baseline/06-gate/e2e-results.json and
  real-document-benchmark-run{1,2,3}.json) are genuine measurements from an actual
  NVIDIA-GPU Docker run against the real granite-embedding / BGE-reranker sidecars
  and the exact sha256-verified D:/tmp/baseline-corpus — not fabricated or hand-edited
  JSON. The capture-provider-env.txt narrative (stale-image rebuild, tenant-naming-key
  generation, MSYS path-conversion workaround) matches what actually happened; the raw
  JSON is the direct, unedited output of `docker compose run --rm e2e` and
  `real_document_benchmark.py`.
awaiting: user response

## Tests

### 1. GPU-backed capture authenticity
expected: The captures are genuine real-hardware, real-provider ArcadeDB measurements (non-stub sidecar hostnames, sha256-verified corpus, check #13's real IndexError→pass flip, N=3 run-to-run variance), not hand-crafted artifacts.
note: The orchestrator directly observed this capture live during this session — GPU stack containers running (embed/rerank/gliner/arcadedb/mcp healthy), GPU at 88–100% during active inference, 500+ MCP tool-calls per 3-min window, and it re-ran all three benchmark runs itself at the orchestrator level after the executor's backgrounded run was orphaned. Strong first-hand evidence of authenticity; formal human sign-off still requested before the irreversible Phase-7 removal.
result: [pending]

### 2. GATE.md honest-narration read-through
expected: Reading baseline/06-gate/GATE.md end-to-end confirms the verdict + rationale are honest — the port is graded against the D-01 bug-corrected 7-doc bar (0.5979 / 0.5143 / 0.7714), NOT the deflated full-corpus aggregate; the per-document diff is complete; deviations (GLiNER-on, latency volume-bloat confound, D-05 already-fixed-at-HEAD, check-name rename) are disclosed; and reproduction commands use the correct per-script flags (--out for e2e_score.py, --output for real_document_benchmark.py). Every figure matches gate-result.json exactly (already cross-checked mechanically in verification).
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
