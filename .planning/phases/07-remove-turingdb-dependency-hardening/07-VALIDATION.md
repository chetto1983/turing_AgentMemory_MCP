---
phase: 7
slug: remove-turingdb-dependency-hardening
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-16
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded by plan-phase from RESEARCH.md `## Validation Architecture`; the per-task
> map, Wave 0 list, and sign-off are filled by `/gsd-validate-phase` after plans exist.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2+ (`pythonpath=src`, `testpaths=tests`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `python -m pytest tests/test_<affected>.py -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~60–180 s (full suite) |

Removal-specific oracles (from RESEARCH.md `## Validation Architecture`):

| Oracle | Command | Proves |
|--------|---------|--------|
| No-import grep-gate | `python -m pytest tests/test_no_turingdb_imports.py -q` (new) | no `import turingdb` / `from turingdb` remains in `src/` |
| DEP-01 compat-smoke | `python -m pytest -q -k graspologic_compat` (new) | `graspologic-native==1.3.1` + live Leiden API smoke |
| DEP-02 compat-smoke | `python -m pytest -q -k fastmcp_compat` (extend `tests/test_warning_filters.py`) | `fastmcp>=3.4,<4` + FastMCP app-construction/registration smoke |
| Compose oracle | `docker compose config --quiet` | `turingdb` + `turingdb-volume-init` services gone, stack valid |
| Correctness oracle | full `python -m pytest -q` + E2E score gate (`scripts/e2e_score.py`) | ArcadeDB-alone stack still green |

---

## Sampling Rate

- **After every task commit:** Run the narrowest affected `python -m pytest tests/test_<affected>.py -q`
- **After every plan wave:** Run the full suite `python -m pytest -q`
- **Before `/gsd-verify-work`:** Full suite green + `docker compose config --quiet` clean + E2E score gate green
- **Max feedback latency:** ~180 s (full suite)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| {filled by /gsd-validate-phase once plans exist} | | | | | | | | | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_no_turingdb_imports.py` — grep-gate guard (ARC-10)
- [ ] `tests/test_graspologic_compat.py` — version pin + Leiden smoke (DEP-01)
- [ ] extend `tests/test_warning_filters.py` — fastmcp range + app-construction smoke (DEP-02)

*Wave 0 list refined by /gsd-validate-phase against the finalized plans.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| {filled by /gsd-validate-phase} | | | |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 180s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
