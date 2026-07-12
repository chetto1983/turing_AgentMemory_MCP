---
phase: 1
slug: ci-git-hook-discipline
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-11
validated: 2026-07-12
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
| CI-01 | Pre-commit blocks on format / lint / file-size violations | manual (git-hook) **+ unit (headline 600-LOC invariant)** | `lefthook run pre-commit` (manual) **AND** `python -m pytest -q tests/test_file_size_cap.py` (portable, no bash) | ✅ `lefthook.yml`, `scripts/check-file-size.sh`, **`tests/test_file_size_cap.py` (new — Nyquist)** |
| CI-02 | Pre-push runs compile smoke + fast subset + `docker compose config --quiet` | manual (git-hook behavior) | `lefthook run pre-push` | ❌ Wave 0 |
| CI-03 | CI lint job passes on a clean checkout (ruff `0.15.x`) | integration (CI-only) **+ unit (wiring contract)** | GitHub Actions run (manual) **AND** `python -m pytest -q tests/test_ci_hook_wiring.py` | ✅ `.github/workflows/ci.yml` + **`tests/test_ci_hook_wiring.py` (new — Nyquist)** |
| CI-04 | CI unit-test job passes (pytest, `pythonpath=src`, **Python 3.12** — D-11) | integration (CI-only) **+ unit (wiring contract)** | GitHub Actions unit-tests job (manual) **AND** `tests/test_ci_hook_wiring.py` (asserts `--cov-fail-under=78` + `CI=true` armed) | ✅ ci.yml + `tests/test_ci_hook_wiring.py` |
| CI-05 | Dockerized-integration job runs E2E score gate + **deterministic** real-doc E2E (D-10) | integration (CI-only) | `docker compose run --rm e2e` (+ deterministic doc test); wiring guarded by `tests/test_ci_hook_wiring.py` | ✅ ci.yml `dockerized-integration` job |
| CI-06 | Compose-validation + `pip-audit` (`2.10.1`) | integration (CI-only) **+ unit (wiring/pin contract)** | `docker compose config --quiet`; `pip-audit` (manual) **AND** `tests/test_ci_hook_wiring.py` (asserts `pip-audit==2.10.1` pin) | ✅ ci.yml `compose-validate` + `supply-chain` jobs + wiring test |
| CI-07 | No-skip-as-green guard fires under `CI=true` | unit (self-test) | `python -m pytest tests/test_no_skip_as_green_guard.py -q` (with `CI=true`) | ✅ `tests/conftest.py` + `tests/test_no_skip_as_green_guard.py` |
| CI-08 | GPU-less degrade floor is a real stub-mode pass, never a skip | integration (CI-only) | `docker compose run --rm e2e` with default (stub) embed/rerank env, **visibly labelled**; wiring guarded by `tests/test_ci_hook_wiring.py` | ✅ `scripts/e2e_score.py` + ci.yml `check_count==19`/`score>=9.4` assert |
| CI-09 | Coverage floor hard-fails below the measured floor | unit (aggregate) | `python -m pytest --cov=src/turing_agentmemory_mcp --cov-fail-under=<FLOOR> -q` | ✅ baseline measured (74%/78%); only `--cov-fail-under` wiring is new |

*Status per task: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/conftest.py` — no-skip-as-green CI-guard, `pytest_runtest_makereport` hookwrapper (D-03/CI-07)
- [x] `tests/test_no_skip_as_green_guard.py` — negative self-test proving the guard fires, via the `pytester` fixture (D-04)
- [x] `lefthook.yml` — pre-commit / pre-push hook definitions
- [x] `.github/workflows/ci.yml` — CI job matrix (lint, unit-tests, compose-validate, supply-chain, dockerized-integration)
- [x] `scripts/check-file-size.sh` — 600-LOC cap, **no allowlist**, MSYS/Git-Bash process-substitution-safe (D-08)
- [x] Framework install: add `pytest-cov==7.1.0`, `lefthook==2.1.10` to the `dev` extra; bump `ruff` pin to `0.15.21` (from `>=0.9`)
- [x] Marker registration: `[tool.pytest.ini_options] markers = [...]` for `slow`, `integration`, `gpu`

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

- [x] All tasks have an `<automated>` verify or a documented Manual-Only justification
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references above
- [x] No watch-mode flags in any command
- [x] Feedback latency < 90 s (full + coverage)
- [x] `nyquist_compliant: true` set in frontmatter once the above hold

**Approval:** validated 2026-07-12

---

## Validation Audit 2026-07-12

State A audit of the executed phase. The draft contract classified CI-01 (headline
600-LOC cap) and the hook/CI wiring (CI-03..CI-06, CI-08) as MISSING automated
coverage — enforced only by bash (`check-file-size.sh`) and the CI YAML, neither of
which runs under `pytest -q`. Two portable, cross-platform pytest guards were added
(pure Python; no bash/Docker/git-hook execution; run in the default fast subset):

- `tests/test_file_size_cap.py` (2 tests) — walks `git ls-files '*.py'`, asserts every
  tracked file ≤600 LOC using `wc -l` (== `b"\n"` count) semantics; a negative
  self-test proves the cap actually fires against an artificially low cap.
- `tests/test_ci_hook_wiring.py` (6 tests) — parses `lefthook.yml` + `.github/workflows/ci.yml`,
  asserts the pre-commit/pre-push commands, the 5 CI jobs, and the
  `pip-audit==2.10.1` / `ruff==0.15.21` / `--cov-fail-under=78` / `CI=true` pins/wiring
  are present (guards against silent deletion).

CI-07 was already covered by `tests/test_no_skip_as_green_guard.py`. CI-02 (real push),
CI-05/CI-08 runtime behavior, and CI-09 (coverage floor, enforced by the CI
`--cov-fail-under` command itself) remain legitimately Manual-Only / CI-only.

| Metric | Count |
|--------|-------|
| Gaps found | 2 |
| Resolved (automated tests added) | 2 |
| Escalated | 0 |
| New tests | 8 (2 files) |
| Suite after | 372 collected, all green; ruff clean |
