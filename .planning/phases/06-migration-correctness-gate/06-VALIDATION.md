---
phase: 6
slug: migration-correctness-gate
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-16
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2+ (`pyproject.toml` `tool.pytest.ini_options`, `pythonpath=src`) |
| **Config file** | `pyproject.toml` (`testpaths=tests`) |
| **Quick run command** | `.venv\Scripts\python -m pytest tests/test_<affected>.py -q` |
| **Full suite command** | `.venv\Scripts\python -m pytest -q` |
| **Estimated runtime** | ~120 seconds (full unit suite; the GPU gate run is separate and manual — see Manual-Only Verifications) |

---

## Sampling Rate

- **After every task commit:** Run the narrowest affected `python -m pytest tests/test_<affected>.py -q` plus `python -m ruff format --check src tests scripts` and `python -m ruff check src tests scripts`
- **After every plan wave:** Run `python -m pytest -q` and `bash scripts/check-file-size.sh`
- **Before `/gsd-verify-work`:** Full suite must be green; `docker compose config --quiet` must pass
- **Max feedback latency:** 120 seconds (unit tier). The retrieval-quality gate verdict (SC#2) is validated by a manual GPU/Docker run, not the unit tier — see below.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| (seeded — planner populates per-task rows) | — | — | ARC-09 | — | N/A | unit | `python -m pytest -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Note: SC#1 (run + compare within tolerance) and SC#3 (recorded gate artifact) are validated by deterministic diff/verdict logic that IS unit-testable against the committed baseline JSON. SC#2 (retrieval meet-or-exceed) requires a real GPU/Docker run against `D:/tmp/baseline-corpus` and is captured as a committed artifact — see Manual-Only Verifications. The Phase-7 guard (D-10) reads the committed verdict and IS unit-testable (fail-closed on missing/NO_GO).*

---

## Wave 0 Requirements

- [ ] `tests/test_gate_diff.py` (or equivalent) — stubs for the per-metric / per-check / per-document diff + tolerance (ε-band) logic against committed baseline JSON fixtures
- [ ] `tests/test_phase7_gate_guard.py` — stub asserting the guard fails closed on missing / NO_GO `gate-result.json`
- [ ] Reuse existing `tests/conftest.py` (`sys.modules["turingdb"]` stub convention) — no new framework install needed

*Existing pytest infrastructure covers the deterministic diff/verdict/guard behaviors. The GPU meet-or-exceed capture is manual by nature.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Retrieval quality meets-or-exceeds baseline (SC#2 / D-01 / D-04) | ARC-09 | Needs real GPU providers (granite + BGE) + external 12-doc corpus; CI GPU-less runners degrade to a stub floor that is NOT a valid quality verdict (D-10) | Stand up `arcadedb` + `agentmemory-embed` + `agentmemory-rerank` + `agentmemory-model-init` via `compose.yaml`; run `scripts/real_document_benchmark.py --frozen-questions baseline/03-turingdb/frozen-questions.json --root D:/tmp/baseline-corpus` N=3 with `E2E_USE_EXTERNAL_EMBED=1 E2E_USE_EXTERNAL_RERANK=1`; run `scripts/e2e_score.py`; compute diff; confirm `verdict` in committed `baseline/06-gate/gate-result.json` |
| Normattiva-fix positive evidence (SC#2 / D-03 / e2e check #13) | ARC-09 | Same GPU/Docker dependency; the gate's actual job is to MEASURE whether the port retrieves the 5 normattiva PDFs | Assert non-zero MRR/recall on the 5 normattiva docs and e2e check #13 passing in the committed captures |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s (unit tier)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
