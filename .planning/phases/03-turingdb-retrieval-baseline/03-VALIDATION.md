---
phase: 3
slug: turingdb-retrieval-baseline
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-13
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

This is a snapshot/measurement phase. The only new CODE is the D-08 frozen-questions
loader (unit-tested, TDD). The rest is artifact capture + assembly, verified by
fast `python -c` JSON smoke checks plus two human-verify checkpoints (GPU-provider
run preconditions and D-12 hands-on validation).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2+ (existing; `pyproject.toml` `testpaths=tests`, `pythonpath=src`) |
| **Config file** | `pyproject.toml` (existing) |
| **Quick run command** | `python -m pytest tests/test_real_document_benchmark.py -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~2s (new loader tests); artifact smoke checks are sub-second `python -c` one-liners |

---

## Sampling Rate

- **After every task commit:** `python -m pytest tests/test_real_document_benchmark.py -q` (03-01); the task's `python -c` artifact smoke check (03-02/03-03)
- **After every plan wave:** `python -m pytest -q` + `bash scripts/check-file-size.sh`
- **Before `/gsd-verify-work`:** Full suite green; `baseline/03-turingdb/` force-added with all five files
- **Max feedback latency:** ~5s for code; the two live-run tasks (03-02) are ~10-30 min wall-clock (GPU/LLM), not context-bound

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 1 | ARC-01 | T-03-01 | Loader raises ValueError on malformed freeze (fail-loud) | unit (RED) | `python -m pytest tests/test_real_document_benchmark.py -q` | ❌ W0 | ⬜ pending |
| 3-01-02 | 01 | 1 | ARC-01 | T-03-01 | Valid freeze round-trips; skip-generation bypasses generator | unit (GREEN) | `python -m pytest tests/test_real_document_benchmark.py -q && bash scripts/check-file-size.sh` | ❌ W0 | ⬜ pending |
| 3-02-01 | 02 | 2 | ARC-01 | — | Real GPU providers confirmed healthy; corpus `--root` obtained (no stub fallback) | checkpoint:human-action | N/A (precondition gate) | — | ⬜ pending |
| 3-02-02 | 02 | 2 | ARC-01 | T-03-02 / T-03-03 | No credential/whole-file leak in captured JSON; all jobs succeeded | smoke | `python -c "import json,pathlib; d=json.loads(pathlib.Path('baseline/03-turingdb/real-document-benchmark.json').read_text(encoding='utf-8')); assert all(x['job'].get('status')=='succeeded' for x in d['documents'])"` | ❌ W0 | ⬜ pending |
| 3-02-03 | 02 | 2 | ARC-01 | T-03-02 | Real-provider e2e; check_count present and NOT 1 (no fail-fast collapse) | smoke | `python -c "import json,pathlib; d=json.loads(pathlib.Path('baseline/03-turingdb/e2e-results.json').read_text(encoding='utf-8')); assert d.get('check_count') not in (None,1)"` | ❌ W0 | ⬜ pending |
| 3-03-01 | 03 | 3 | ARC-01 | T-03-05 | Manifest carries no bytes; frozen questions replay-valid | smoke | `python -c "import sys,pathlib; sys.path.insert(0,'scripts'); from real_document_benchmark_scoring import load_frozen_questions; assert load_frozen_questions(pathlib.Path('baseline/03-turingdb/frozen-questions.json'))"` | ❌ W0 | ⬜ pending |
| 3-03-02 | 03 | 3 | ARC-01 | T-03-05 | BASELINE.md cites all D-11 fields + as-observed D-07 caveats | smoke | `python -c "import pathlib; t=pathlib.Path('baseline/03-turingdb/BASELINE.md').read_text(encoding='utf-8').lower(); assert all(w in t for w in ['provider','run param','git','per-check','chunk','reproduction'])"` | ❌ W0 | ⬜ pending |
| 3-03-03 | 03 | 3 | ARC-01 | T-03-04 | Only five curated files force-added; no credential leak; all JSON valid | smoke | `python -c "import json,glob; [json.loads(open(p,encoding='utf-8').read()) for p in glob.glob('baseline/03-turingdb/*.json')]"` + `git ls-files baseline/03-turingdb/` | ❌ W0 | ⬜ pending |
| 3-04-01 | 04 | 3 | ARC-01 | — | MCP tools discoverable; scoped call succeeds | human-check | manual (Claude Code lists turing-agentmemory tools) | — | ⬜ pending |
| 3-04-02 | 04 | 3 | ARC-01 | T-03-07 | Tenant-scoped cited retrieval works; no cross-tenant leakage | checkpoint:human-verify | manual (invariant #1 sanity check) | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_real_document_benchmark.py::test_load_frozen_questions_round_trips` — new test for the new `load_frozen_questions()` helper (created in 03-01 Task 1 RED)
- [ ] `tests/test_real_document_benchmark.py::test_load_frozen_questions_rejects_malformed` — malformed-input ValueError coverage (V5 input validation / T-03-01)
- [ ] `tests/test_real_document_benchmark.py::test_resolve_questions_skips_generation_when_frozen` — proves the D-08 bypass actually skips generation
- [ ] No framework install needed — pytest already configured and green (364 tests baseline)

*The `baseline/03-turingdb/*` artifact smoke checks are inline `python -c` one-liners, not pytest files — no scaffold to pre-create beyond the directory itself (created at run time in 03-02).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real GPU embed/rerank providers reachable + corpus `--root` supplied | ARC-01 (D-01/D-02/D-05) | GPU availability + an open-input private corpus path cannot be asserted from CI/code | 03-02 Task 1 checkpoint: `docker compose ps` shows agentmemory-embed/rerank `healthy`; operator provides absolute `--root` |
| As-observed D-07 known-false-passing e2e checks | ARC-01 (D-07) | Requires human judgment reading the real `checks[]` output against the [ASSUMED] candidate list; not automatable | 03-03 Task 2: transcribe `checks[].ok` as observed; confirm/refute the 5 RESEARCH candidates; keep the two inflation phenomena separate |
| Ingest + tenant-scoped cited retrieval on the Italian corpus | ARC-01 (D-12) | Supplemental hands-on confidence via installed MCP; interactive, not a committed number | 03-04 Task 2 checkpoint: search Italian, confirm citations + no cross-tenant leakage |
| Baseline committed BEFORE any ArcadeDB code (SC#3) | ARC-01 (D-09) | Cross-phase ordering; verified at Phase 4 kickoff | `git log --oneline -- baseline/03-turingdb/` predates the first ArcadeDB-touching commit |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or a documented Wave 0 / manual-checkpoint dependency
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (each auto task carries a smoke/unit check; checkpoints are the only manual gates and are non-adjacent within a plan)
- [x] Wave 0 covers all MISSING references (the 3 new loader tests)
- [x] No watch-mode flags
- [x] Feedback latency < 5s for code; live-run tasks are wall-clock-bound by design (GPU/LLM), acknowledged
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-13
