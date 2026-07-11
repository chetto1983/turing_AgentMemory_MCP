---
phase: 1
slug: ci-git-hook-discipline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-11
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `01-RESEARCH.md` §"Validation Architecture" (all numbers measured this
> session, not guessed).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (installed 9.1.1; `pyproject.toml` requires `>=8.2`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["src"]`); **no `conftest.py` yet — this phase creates the first one** |
| **Quick run command** | `python -m pytest -q` |
| **Full suite command** | `python -m pytest --cov=src/turing_agentmemory_mcp --cov-fail-under=<FLOOR> -q` |
| **Estimated runtime** | ~25–32 s (362 tests today; fully self-contained — fakes/mocks only, no live TuringDB/Docker/GPU) |
| **E2E gate** | `python scripts/e2e_score.py --out e2e-results.json` — must stay `VALIDATED_10_10`, score ≥ 9.8 |
| **Coverage baseline (measured 2026-07-11)** | **74%** incl. `e2e_score.py` in denominator / **78%** excl. it. Floor is set from the post-decomposition suite and **only ever ratchets up** (D-07). Never lower silently. |

---

## Sampling Rate

- **After every task commit:** `python -m pytest -q` (the fast subset
  `-m "not slow and not integration and not gpu"` is currently equivalent to the
  full suite — no test carries those markers yet; the taxonomy is forward-looking).
- **After every plan wave:** full suite with coverage
  (`--cov=src/turing_agentmemory_mcp --cov-fail-under=<FLOOR>`), **plus**
  `python scripts/e2e_score.py` after **any wave that touched a file-decomposition
  split** (store.py or any of the other 9 over-cap files — D-09).
- **Before `/gsd-verify-work`:** full suite green **AND** E2E score gate
  `VALIDATED_10_10` (≥9.8) **AND** `ruff check src tests scripts` clean **AND**
  `ruff format --check src tests scripts` clean (D-09a) **AND**
  `docker compose config --quiet` exits 0.
- **Max feedback latency:** ~32 s (quick), ~60–90 s (full + coverage).

---

## Per-Requirement Verification Map

Task-ID rows (`1-NN-NN`) are filled in during planning/execution; this maps each
phase requirement to its verification mechanism (from RESEARCH §"Phase Requirements
→ Test Map").

| Requirement | Behavior | Test Type | Automated Command | File Exists? |
|-------------|----------|-----------|-------------------|--------------|
| CI-01 | Pre-commit blocks on format / lint / file-size violations | manual (git-hook behavior) | `lefthook run pre-commit` against a deliberately-violating staged file | ❌ Wave 0 (`lefthook.yml`, `scripts/check-file-size.sh` new) |
| CI-02 | Pre-push runs compile smoke + fast subset + `docker compose config --quiet` | manual (git-hook behavior) | `lefthook run pre-push` | ❌ Wave 0 |
| CI-03 | CI lint job passes on a clean checkout (ruff `0.15.x`) | integration (CI-only) | GitHub Actions run on a test PR/push | ❌ Wave 0 (`.github/workflows/ci.yml` new) |
| CI-04 | CI unit-test job passes (pytest, `pythonpath=src`, **Python 3.12** — D-11) | integration (CI-only) | GitHub Actions unit-tests job | ❌ Wave 0 |
| CI-05 | Dockerized-integration job runs E2E score gate + **deterministic** real-doc E2E (D-10) | integration (CI-only) | `docker compose run --rm e2e` (+ deterministic doc test) | ❌ Wave 0 |
| CI-06 | Compose-validation + `pip-audit` (`2.10.1`) | integration (CI-only) | `docker compose config --quiet`; `pip-audit` | ❌ Wave 0 (underlying cmds already verified working) |
| CI-07 | No-skip-as-green guard fires under `CI=true` | unit (self-test) | `python -m pytest tests/test_no_skip_as_green_guard.py -q` (with `CI=true`) | ❌ Wave 0 (new `conftest.py` + negative self-test) |
| CI-08 | GPU-less degrade floor is a real stub-mode pass, never a skip | integration (CI-only) | `docker compose run --rm e2e` with default (stub) embed/rerank env, **visibly labelled** | ✅ mechanism exists in `scripts/e2e_score.py`; needs CI wiring + label |
| CI-09 | Coverage floor hard-fails below the measured floor | unit (aggregate) | `python -m pytest --cov=src/turing_agentmemory_mcp --cov-fail-under=<FLOOR> -q` | ✅ baseline measured (74%/78%); only `--cov-fail-under` wiring is new |

*Status per task: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` — no-skip-as-green CI-guard, `pytest_runtest_makereport` hookwrapper (D-03/CI-07)
- [ ] `tests/test_no_skip_as_green_guard.py` — negative self-test proving the guard fires, via the `pytester` fixture (D-04)
- [ ] `lefthook.yml` — pre-commit / pre-push hook definitions
- [ ] `.github/workflows/ci.yml` — CI job matrix (lint, unit-tests, compose-validate, supply-chain, dockerized-integration)
- [ ] `scripts/check-file-size.sh` — 600-LOC cap, **no allowlist**, MSYS/Git-Bash process-substitution-safe (D-08)
- [ ] Framework install: add `pytest-cov==7.1.0`, `lefthook==2.1.10` to the `dev` extra; bump `ruff` pin to `0.15.21` (from `>=0.9`)
- [ ] Marker registration: `[tool.pytest.ini_options] markers = [...]` for `slow`, `integration`, `gpu`

**Prerequisite gate (bootstrap, before hooks can be enabled):** all 10 over-cap
files decomposed to ≤600 LOC (D-09) **and** a one-time `ruff format src tests scripts`
pass (D-09a), each verified with `pytest -q` + `scripts/e2e_score.py` staying green.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Pre-commit hook actually blocks a real commit | CI-01 | Git-hook wiring is only exercised by a real `git commit`; not unit-testable in-process | Stage a file with a lint/format/size violation; `git commit` must be rejected; `git commit --no-verify` must bypass |
| Pre-push hook actually blocks a real push | CI-02 | Same — git-hook behavior | Trigger `lefthook run pre-push`; a failing subset/compile/compose must return non-zero |
| CI matrix runs green on GitHub | CI-03..CI-06 | Requires an actual GitHub Actions run on a push/PR | Open a test PR; confirm all jobs pass on a clean checkout |
| GPU-less degrade floor is visibly labelled (not a silent skip) | CI-08 | Requires reading the CI job log/label | Confirm the stub-mode E2E step is named/labelled distinct from a real-GPU run |

---

## Validation Sign-Off

- [ ] All tasks have an `<automated>` verify or a Wave 0 dependency
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references above
- [ ] No watch-mode flags in any command
- [ ] Feedback latency < 90 s (full + coverage)
- [ ] `nyquist_compliant: true` set in frontmatter once the above hold

**Approval:** pending
