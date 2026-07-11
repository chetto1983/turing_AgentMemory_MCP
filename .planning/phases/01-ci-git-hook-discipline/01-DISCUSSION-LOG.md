# Phase 1: CI + Git-Hook Discipline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-11
**Phase:** 1-CI + Git-Hook Discipline
**Areas discussed:** Hook install/distribution, No-skip-as-green enforcement, GPU-less degrade floor, Gate strictness policy

---

## Hook install & distribution (Python/Windows reality)

| Option | Description | Selected |
|--------|-------------|----------|
| pip `lefthook` wrapper | Add `lefthook` to the `dev` extra; `pip install -e .[dev]` brings the binary in-venv; `make hooks` / `lefthook install` wires hooks. Zero non-Python toolchain. | ✓ |
| npm `lefthook` | lefthook's primary distribution, but forces a Node toolchain onto a pure-Python repo. | |
| Standalone binary + Makefile | `make tools` fetches per-OS release binary; more Windows moving parts. | |
| Python-native `pre-commit` instead | Drop lefthook for the pre-commit framework; deviates from the locked lefthook decision. | |

**User's choice:** pip `lefthook` wrapper
**Notes:** Chosen because the repo has no Go toolchain (Aura got lefthook via `go install`) and is Windows-primary. Research flagged to confirm the pip wrapper ships a working Windows binary; standalone-binary fallback documented if not.

---

## No-skip-as-green enforcement

| Option | Description | Selected |
|--------|-------------|----------|
| conftest CI-guard converts skips→failures | Central `conftest.py`: under `CI=true`, a skip on a marked integration/GPU tier becomes a failure; plus a negative self-test proving the guard fires. | ✓ |
| Fail-loud env guards in each test | Each test `pytest.fail()`s on missing env under CI (mirrors Aura `t.Fatal`); more per-test boilerplate. | |
| Job-level assertions in the workflow | CI YAML asserts each tier actually ran (0 skips); weaker than test-level enforcement. | |

**User's choice:** conftest CI-guard converts skips→failures
**Notes:** Central and hard to bypass; the negative self-test is mandatory — an unproven gate isn't trusted (Aura discipline).

---

## GPU-less degrade floor (what concretely runs)

| Option | Description | Selected |
|--------|-------------|----------|
| Full E2E against in-process stubs | Run the deterministic E2E score gate + real-doc E2E on the repo's existing stub embed/rerank endpoints; only the real-provider path degrades. Strongest floor. | ✓ |
| Stub-run + image build smoke | Also build GPU sidecar images without running them; catches Dockerfile rot. | |
| Import/compile smoke only | Import + `compileall` + `docker compose config`; exercises no retrieval. Weakest. | |

**User's choice:** Full E2E against in-process stubs
**Notes:** Uses `scripts/e2e_score.py`'s existing in-process stubs; degraded run must be visibly labelled as stub-mode but is a real pass/fail, never a skip. Image-build smoke deferred to Phase 12 Docker work.

---

## Gate strictness policy (coverage floor)

| Option | Description | Selected |
|--------|-------------|----------|
| Hard floor, ratchet up; allowlist file | Coverage hard-fails below the measured floor and only ratchets up; (allowlist portion later reversed — see below). | ✓ (coverage part) |
| Hard floor fixed; inline allowlist | Fixed hard coverage gate. | |
| Advisory coverage; hard file-size | Coverage reported but non-blocking. Loosens CI-09. | |

**User's choice:** Hard coverage floor, ratchet up.
**Notes:** Coverage floor number must be *measured* against the actual current suite, never guessed (CI-09).

## File-size cap — allowlist REVERSAL (mid-discussion follow-ups)

The user then messaged *"no file >600 loc on precommit"* and *"no allowlist,
refactor on touch,"* reversing the allowlist half of the choice above. A clarifying
question was asked (three options), and the user selected:

| Option | Description | Selected |
|--------|-------------|----------|
| Cap staged files only; no allowlist | Hook checks only this commit's files; touching store.py forces its split. | |
| **No allowlist, scan all files, fail now** | Hook scans ALL tracked files; every commit blocked until store.py is ≤600 LOC — store.py refactored **inside Phase 1**, expanding scope. | ✓ |
| Keep allowlist (as roadmap says) | store.py stays on `.file-size-allowlist`; matches locked ROADMAP/CI-01. | |

**User's choice:** No allowlist, scan all files, fail now.
**Notes:** Chosen with the scope implication explicitly presented. Consequences: (1) `store.py` (3891 LOC) must be decomposed into ≤600-LOC concern modules within this phase, behavior preserved via the E2E gate + full pytest; (2) ROADMAP Phase 1 SC#1 and CI-01 (which mandate an allowlist) must be rewritten; (3) CLAUDE.md's store.py-exception language must be removed. Bootstrap ordering: split store.py before hooks go active (or `--no-verify` the installing commit).

---

## Claude's Discretion

- Fast pytest-subset marker taxonomy for pre-push (mark heavy tiers, exclude at hook time; run fully in CI — Aura pattern).
- CI trigger/branch config, concurrency-cancel, `permissions` block (follow Aura `ci.yml`; adapt to `master`).
- Whether ruff lint runs at pre-commit vs pre-push (Aura moved it to pre-commit).

## Deferred Ideas

- Windows CI lane (CI-10) — already v2/deferred; do not add a `windows-latest` job unless promoted.
- GPU sidecar Docker image build smoke — belongs with Phase 12 Docker stack work.
- Stale `pyproject.toml` description / MIT-vs-Apache licensing churn — Phase 7 concern, not this phase.
