---
phase: 4
slug: arcadedb-direct-port
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-13
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Detailed validation requirements are in `04-RESEARCH.md` § "Validation Architecture".
> This draft is filled in by the planner (per-task map) and the nyquist-auditor during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2+ (`testpaths=tests`, `pythonpath=src`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `python -m pytest tests/test_<affected>.py -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~60–120 seconds (full suite) |

Note (from MEMORY): `turingdb` has no Windows wheel — the E2E score gate runs via `.venv` python + Docker on Windows. The ArcadeDB smoke-test spike (D-02) and any ArcadeDB-touching tests must run against a live `arcadedb` container, not in-process.

---

## Sampling Rate

- **After every task commit:** Run `python -m ruff check src tests scripts` + the narrowest affected `python -m pytest tests/test_<affected>.py -q`
- **After every plan wave:** Run `python -m pytest -q`
- **Before `/gsd-verify-work`:** Full suite green + `docker compose config --quiet`
- **Max feedback latency:** ~120 seconds

---

## Per-Task Verification Map

> Filled by the planner once tasks are decomposed; each task's `<acceptance_criteria>` maps here.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 4-01-01 | 01 | 1 | ARC-02/03 | — | tenant scope enforced on every ported query | integration | `python -m pytest tests/test_arcadedb_client.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_arcadedb_client.py` — smoke-test spike (D-02) resolving the §3 unknowns; the hard gate before query builders
- [ ] `tests/conftest.py` — shared fixtures (live ArcadeDB container / ephemeral DB, embed/rerank stubs)
- [ ] Parity harness reuse — Phase-3 `--frozen-questions` loader + `baseline/03-turingdb/` for the D-06 bake-off yardstick

*Existing pytest infrastructure covers the rest; the spike + parity harness are the new dependencies.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Chaos-restart reconnect (D-10) | ARC-02 (readiness) | Requires killing/restarting the live ArcadeDB container mid-op | Bring stack up, run ingest, `docker restart arcadedb`, assert store reconnects + `/health` real-probe recovers |

*Most behaviors have automated verification; chaos-restart is scripted but container-dependent.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
