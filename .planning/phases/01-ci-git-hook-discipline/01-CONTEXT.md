# Phase 1: CI + Git-Hook Discipline - Context

**Gathered:** 2026-07-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Install engineering discipline that guards **every downstream change** in this
stabilization milestone: fast local git hooks (`lefthook`) at commit/push time,
plus a GitHub Actions CI gate that enforces the full quality bar and — critically
— **never passes a skipped tier green**. Modeled on the Aura project
(`D:\Repo\Aura`: lefthook + GitHub Actions, no-skip-as-green, fast hooks / heavy
gates in CI). Aura is Go; this repo is Python, so the *discipline* is mirrored and
the *tooling* adapted (ruff, pytest, the E2E score gate, `docker compose config`).

This phase installs guardrails **and** performs the one refactor those guardrails
force on day one: because the 600-LOC cap has **no allowlist** (D-08), `store.py`
(3891 LOC) is **decomposed into ≤600-LOC modules within this phase** so the cap can
go green. Beyond that store.py split, this phase does **not** touch the backend,
retrieval logic, Docker stack composition, or any other CONCERNS.md item — those
are later phases the guardrails will protect. The store.py split must preserve
behavior (E2E score gate + full pytest stay green).

</domain>

<decisions>
## Implementation Decisions

### Locked upstream (carried forward — do NOT re-litigate)
These are fixed by ROADMAP.md success criteria + PROJECT.md Key Decisions:
- **L-01:** Local hooks = **lefthook**; CI = **GitHub Actions**. (There is no
  existing hook or CI config in this repo yet — only `.github/ISSUE_TEMPLATE/`
  and `PULL_REQUEST_TEMPLATE.md`. Clean slate.)
- **L-02:** `pre-commit` runs: `ruff format --check`, `ruff check`, and the
  **file-size cap enforcing no file >600 LOC, with NO allowlist** (see D-08 —
  reversed from the roadmap's original allowlist mandate). The cap is a
  **pre-commit** gate that scans ALL tracked `*.py` files and hard-fails now. Per
  user: *"no file >600 loc on precommit"* and *"no allowlist, refactor on touch."*
  ⚠ This supersedes ROADMAP Phase 1 SC#1 and CI-01, which still say "documented
  allowlist that includes store.py" — those MUST be rewritten (see Open Questions
  / closing note).
- **L-03:** `pre-push` runs: import/compile smoke, a **fast** pytest subset,
  `docker compose config --quiet`.
- **L-04:** CI job matrix: lint (ruff **pinned `0.15.x`** — bumped from the
  current stale `>=0.9` in `pyproject.toml`), unit tests (pytest, `pythonpath=src`),
  compose-validation, pip-audit (**`2.10.1`**), and a dockerized-integration job
  running the E2E score gate + real-document E2E.
- **L-05:** Heavy gates (full E2E, real-doc E2E, coverage) live in CI; hooks stay
  fast enough not to be habitually bypassed.
- **L-06 (REVISED by D-08):** `store.py` is **3891 LOC**. CLAUDE.md currently
  calls it "the large central exception … NO >600 loc" — but the user has removed
  the exception. There is **no allowlist**: `store.py` must be **decomposed to
  ≤600-LOC modules within this phase** (split by concern, `store_<concern>.py`, per
  the existing codebase pattern) so the cap can go green. The CLAUDE.md store.py-
  exception language MUST be rewritten as part of this phase.

### Hook distribution & install (Python/Windows reality)
- **D-01:** Install lefthook via the **`lefthook` pip package** added to the
  `dev` optional-dependency extra in `pyproject.toml`, so `pip install -e ".[dev]"`
  brings the binary into the venv. No Go or Node toolchain is introduced onto this
  pure-Python, Windows-primary repo. (Aura got the binary via `go install`; that
  path is unavailable here.)
- **D-02:** Fresh clones wire the git hooks via a documented `lefthook install`
  step, surfaced through a `make hooks` target (and README/CONTRIBUTING note).
  Do NOT auto-install silently.
- **Rejected:** npm `lefthook` (forces a Node toolchain), standalone binary +
  Makefile fetch (more Windows moving parts), and swapping to the Python-native
  `pre-commit` framework (deviates from the locked lefthook decision).

### No-skip-as-green enforcement (the defining discipline)
- **D-03:** Enforce via a **central `conftest.py` CI-guard**: when `CI=true`, any
  `pytest.skip` on a marked integration/GPU tier is converted into a **failure**.
  This is the Python-idiomatic analogue of Aura's `CI: "true"`-armed `t.Fatal`
  guards — centralized so it's hard to bypass, rather than per-test boilerplate.
- **D-04:** Ship a **negative self-test** that proves the guard actually fires
  (a deliberately-skipped marked test MUST make the gate exit non-zero under
  `CI=true`). Mirrors Aura's "gate is not silently green" negative tests — without
  it, no-skip-as-green is unverified.
- **Rejected:** per-test fail-loud env guards (more boilerplate, easier to forget
  on new tests) and job-level YAML assertions on pytest output (weaker than
  test-level enforcement).

### GPU-less CI degrade floor (what concretely runs)
- **D-05:** On a GPU-less runner, the GPU-dependent embed/rerank/GLiNER tiers
  degrade to the **full deterministic E2E score gate + real-doc E2E run against
  the repo's existing in-process stub embed/rerank endpoints** (the same stubs
  `scripts/e2e_score.py` already spins up). Only the *real-provider* path is
  degraded; retrieval logic still executes end-to-end. This is the strongest
  floor and the closest thing to "the gate actually ran" without a GPU.
- **D-06:** This degraded run must be **visibly distinct** (named/labelled) from a
  real-GPU run so a reader never mistakes stub-mode for full-provider mode — but
  it is a real pass/fail signal, never a skip (ties to D-03/D-04).
- **Rejected:** stub-run + image-build smoke (build smoke deferred to the Phase 12
  Docker work; overkill for the guardrail phase) and import/compile-only smoke
  (exercises no retrieval — too weak for CI-08's "visible floor").

### Gate strictness policy
- **D-07:** **Coverage is a hard CI failure below the floor, and the floor only
  ever ratchets up** (never silently lowered). The floor number is **measured
  against the actual current suite** — a researcher/planner action, NOT a guessed
  value (see Open Questions). Tooling: add `pytest-cov`/`coverage` to the `dev`
  extra.
- **D-08 (reversed mid-discussion):** **No allowlist.** The file-size cap scans
  **all tracked `*.py` files** every commit and **hard-fails now** — there is no
  per-file exemption, not even for `store.py`. Adapt Aura's
  `scripts/check-file-size.sh` (600-LOC cap; keep its MSYS/Git-Bash process-
  substitution workaround) to scan `*.py`, dropping the allowlist mechanism
  entirely. **Consequence (in scope for Phase 1):** because the cap scans all files
  and blocks every commit until compliant, `store.py` (3891 LOC) **must be split
  into ≤600-LOC modules within this phase** before the hooks/CI can be green. This
  is "refactor on touch" applied to store.py up front. User chose this with the
  scope implication explicitly presented.
  - **Bootstrap ordering (planner MUST handle):** the split has to land before the
    hook is active (or via an initial `--no-verify` bootstrap), otherwise the very
    commit that installs lefthook is itself blocked. Sequence: decompose store.py →
    verify E2E score gate + full pytest still green (behavior preserved) → then
    install hooks + CI.
  - **Risk:** store.py is direct-ported to ArcadeDB in Phase 4; splitting it now
    means Phase 4 ports the split modules rather than one file. Acceptable per user;
    the deterministic E2E gate + existing tests are the safety net for the split.
  - **Rejected:** inline-comment allowlist, checked-in `.file-size-allowlist`,
    staged-files-only scanning (all would let store.py stay a 3891-LOC god module).
- **Rejected:** fixed (non-ratcheting) coverage floor, inline-comment allowlist,
  and advisory/non-blocking coverage (CI-09 explicitly wants a coverage *gate*).

### Claude's Discretion
- **Fast pytest subset boundary (L-03/pre-push):** how to carve the "fast subset"
  — mark slow/integration/GPU tests and run `-m "not slow and not integration"`,
  or a curated deselect list. Follow Aura's pattern (mark heavy tiers, exclude at
  hook time; run them fully in CI). Planner/researcher decides the exact marker
  taxonomy.
- **CI trigger/branch config, concurrency-cancel, permissions block:** follow
  Aura's `ci.yml` conventions (push/PR on `master`/`main`, `cancel-in-progress`,
  `permissions: contents: read`). Adapt branch list to this repo's `master`.
- **Whether lint's ruff runs at pre-commit vs pre-push:** Aura moved lint to
  pre-commit so regressions surface at the authoring commit — reasonable default,
  planner's call within L-02/L-03.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase spec & requirements
- `.planning/ROADMAP.md` §"Phase 1: CI + Git-Hook Discipline" — the 4 success
  criteria (hooks wired, CI job matrix, no-skip-as-green + GPU degrade, coverage
  gate) that define done.
- `.planning/REQUIREMENTS.md` §"CI & Git Hooks (CI)" — CI-01..CI-09, the exact
  requirement text and pins (ruff `0.15.x`, pip-audit `2.10.1`).

### Reference implementation to mirror (Aura — Go repo, discipline not tooling)
- `D:\Repo\Aura\lefthook.yml` — the pre-commit/pre-push structure to adapt
  (parallel commands, glob-gating, fast-hooks/heavy-in-CI philosophy, `--no-verify`
  bypass note).
- `D:\Repo\Aura\.github\workflows\ci.yml` — the CI job matrix, the `CI: "true"`
  no-skip-as-green env-arming pattern, negative-gate self-tests, concurrency-cancel,
  file-size-cap step.
- `D:\Repo\Aura\scripts\check-file-size.sh` — the file-size cap script to adapt to
  Python (`*.py`, `.file-size-allowlist`-driven exemption). Note its documented
  Windows Git Bash here-string workaround (process substitution, not `<<<`).

### Repo state the plan builds on
- `pyproject.toml` — current tool config: ruff (`select E,F,I,B,UP`; `ignore E501`;
  `line-length 100`; `target-version py311`), pytest (`testpaths=tests`,
  `pythonpath=src`), `dev` extra to extend (add `lefthook`, `pytest-cov`, bump ruff
  pin). **⚠ Also fix the stale `description = "TuringDB-backed..."` only if a plan
  touches it — not this phase's job unless incidental.**
- `Makefile` — existing `test`/`e2e`/`docker-e2e`/`lint` targets; add `hooks` (and
  possibly `tools`) target here.
- `scripts/e2e_score.py` — the deterministic E2E score gate; already spins up a
  temporary local TuringDB + **stub embed/rerank endpoints** in-process (this is
  the GPU-less floor mechanism in D-05). `E2E_USE_EXTERNAL_EMBED/RERANK=1` selects
  real providers.
- `CLAUDE.md` §"Commands" + §"Post-edit validation" + §"Behavioral rules"
  (NO >600 loc; store.py is the sanctioned exception) — the gate this CI encodes.
- `.planning/codebase/TESTING.md` — current test suite shape (30+ function-based
  pytest files, no `conftest.py` yet, `CI`-style env via `monkeypatch`), informs
  the conftest CI-guard (D-03) and the fast-subset carve.
- `.planning/codebase/CONCERNS.md` — the downstream work these guardrails protect.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`scripts/e2e_score.py` stub endpoints** — the in-process stub embed/rerank
  servers are the exact mechanism for the GPU-less degrade floor (D-05); no new
  stub code needed, just wire the E2E gate to run in stub mode on GPU-less CI.
- **Aura's `check-file-size.sh`** — port near-verbatim but **drop the allowlist
  concept** (swap globs to `*.py`; scan all tracked `*.py`; hard-fail >600). Keep
  its documented MSYS/Git-Bash process-substitution workaround; this repo is
  Windows-primary so the same trap applies.
- **Existing `store_<concern>.py` split pattern** — the codebase already favors
  small modules split by concern (per CLAUDE.md §"DEEP REFACTOR ON TOUCH"); the
  store.py decomposition follows that same naming/structure, extracting cohesive
  concerns (graph writes, vector ops, hybrid retrieval, lifecycle, retention,
  audit hooks) into siblings while keeping the public `TuringAgentMemory` API.
- **`Makefile`** — existing target style to extend with `hooks`.

### Established Patterns
- Tests are **function-based pytest, no `conftest.py` today** — introducing one is
  net-new; it becomes the home for the no-skip-as-green CI-guard (D-03) and the
  marker registration for the fast-subset carve.
- Env-driven config via `monkeypatch` in tests; `CI=true` env-arming (Aura's
  pattern) fits cleanly.
- ruff config already present and matches CLAUDE.md (line-length 100, E501 ignored)
  — CI lint just pins the version and runs it; no rule changes.

### Integration Points
- `pyproject.toml` `[project.optional-dependencies].dev` — add `lefthook`,
  `pytest-cov`; bump `ruff` pin to `0.15.x`. New: pip-audit is a CI-only tool
  (pin `2.10.1` in the workflow, not necessarily a repo dep).
- New files this phase introduces: `lefthook.yml`, `.github/workflows/ci.yml`,
  `scripts/check-file-size.sh` (no allowlist), `tests/conftest.py` (CI-guard), a
  negative self-test for the guard, and a `make hooks` target.
- **Modified: `store.py` → split into multiple `store_<concern>.py` modules**
  (each ≤600 LOC) plus a slimmed `store.py`/package that preserves the
  `TuringAgentMemory` import path used by `server.py`, the document worker, and
  ~30 test files. This is the largest single piece of work in the phase.

</code_context>

<specifics>
## Specific Ideas

- Mirror Aura's discipline faithfully, including its **negative self-tests** — a
  gate that isn't continuously proven to fail on the bad case is not trusted here.
- No file — including `store.py` — is exempt from the 600-LOC cap. store.py is
  split into ≤600-LOC concern modules as part of this phase (no allowlist).
- Windows/Git-Bash portability is a real constraint (primary dev platform): any
  shell script must work under MSYS/busybox (see the here-string workaround in
  Aura's script).

</specifics>

<deferred>
## Deferred Ideas

- **Windows CI lane (CI-10)** — already tracked as v2/deferred in STATE.md and
  REQUIREMENTS.md. "Windows/PowerShell is primary" would justify it, but it's not
  in this milestone's roadmap. Do not add a `windows-latest` job unless explicitly
  promoted.
- **GPU sidecar Docker image build smoke** — belongs with the Phase 12 Docker
  one-command-stack work; not part of the guardrail phase (see D-05 rejection).
- **Fixing the stale `pyproject.toml` description / MIT-vs-Apache licensing churn
  from the ArcadeDB migration** — a Phase 7 (invariants rewrite) concern, not this
  phase.

</deferred>

## Open Questions for Research/Planning (not user decisions)

- **⚠ ROADMAP + REQUIREMENTS rewrite (REQUIRED follow-up):** ROADMAP Phase 1 SC#1
  and CI-01 still mandate "a documented allowlist that includes store.py at
  ~3900 LOC." The user reversed this (no allowlist; split store.py). Those criteria
  MUST be updated (via `/gsd-phase edit 1` + a REQUIREMENTS.md edit) so the phase's
  own success criteria match the decision — otherwise verification will check
  against a contradicted criterion. Do this before planning executes.
- **⚠ CLAUDE.md rewrite (in-scope for this phase):** CLAUDE.md §"DEEP REFACTOR ON
  TOUCH" calls store.py "the large central exception … NO >600 loc." Remove the
  exception language and reflect the new no-allowlist cap.
- **store.py decomposition plan:** how to cut 3891 LOC into cohesive ≤600-LOC
  concern modules without breaking the `TuringAgentMemory` public API or the ~30
  importing test files. Researcher/planner designs the split; the E2E score gate +
  full pytest are the behavior-preservation gate.
- **Coverage floor number:** run the actual current suite under coverage once to
  measure the real baseline, then set the hard floor at (or just below) it. Never
  guess (CI-09). This is a measured input, not a discussion decision.
- **Exact fast-pytest-subset marker taxonomy** (see Claude's Discretion) — derive
  from which existing tests are slow/require external services.
- **pip `lefthook` package coverage on Windows** — confirm the pip `lefthook`
  wrapper ships a working Windows binary; if it doesn't, fall back to the
  standalone-binary path (D-01's rejected alternative) and note the deviation.

## Resolved Decisions (planning session — 2026-07-11)

Post-research user decisions that resolve the Open Questions above. These are now
**LOCKED for this phase** (do NOT re-litigate). Numbering continues the D-XX series.

- **D-09 (file-size cap scope — resolves OQ "store.py decomposition" scope):**
  Research found `store.py` is **not** the only over-cap file — **10 tracked `*.py`
  files exceed 600 LOC today**. User chose the **literal reading of D-08 (no
  allowlist, no category exemption)**: **all 10 are decomposed into cohesive
  ≤600-LOC modules within this phase**, and the cap scans **all** tracked `*.py`.
  The 10 files (current LOC):
  1. `src/turing_agentmemory_mcp/store.py` (3891) — the headline split (mixin
     modules behind a thin facade; preserve the `TuringAgentMemory` import path).
  2. `tests/test_gliner_provider.py` (1076)
  3. `src/turing_agentmemory_mcp/benchmark.py` (1044)
  4. `scripts/eval_backboard_locomo_mcp.py` (936)
  5. `src/turing_agentmemory_mcp/e2e_score.py` (873)
  6. `scripts/real_document_benchmark.py` (827)
  7. `src/turing_agentmemory_mcp/server.py` (762)
  8. `tests/test_batch_memory.py` (749)
  9. `src/turing_agentmemory_mcp/document_jobs.py` (666)
  10. `src/turing_agentmemory_mcp/gliner_provider.py` (658)
  Behavior is preserved across every split (E2E score gate + full pytest stay
  green — run them after each extraction, not only at the end).
  - **D-09a (second bootstrap gate, from research):** `ruff format --check` fails
    on **49/78** tracked files today. A one-time repo-wide
    `python -m ruff format src tests scripts` pass must land (verified green after)
    as part of the bootstrap, **before** the pre-commit hook is enabled — otherwise
    the hook-installing commit blocks itself on pre-existing formatting drift.

- **D-10 (CI-05 "real-document E2E" — resolves OQ2):** Satisfied by the
  **deterministic, in-process real-file path already in the repo** (the
  `scripts/e2e_score.py` document flow + the existing deterministic doc test) — no
  live LLM, no `PROVIDER_API_KEY` secret, CI-shaped and already green.
  `scripts/real_document_benchmark.py` **stays an operator-run tool and is NOT
  wired into CI** (it is still decomposed for the cap per D-09, just not made a CI
  gate). A live-corpus CI run is an explicit non-goal for this phase.

- **D-11 (CI Python version — resolves OQ3):** The CI unit-test job runs a
  **single Python 3.12** (matches the dev venv + all research verification). A
  3.11–3.14 matrix is an explicit, non-mandated future follow-up.

### Follow-up status (from the Open Questions above)
- ✅ **ROADMAP + REQUIREMENTS rewrite — DONE.** ROADMAP SC#1/#5 and REQUIREMENTS
  CI-01 already say "≤600 LOC across all tracked `*.py`, NO allowlist, store.py
  decomposed" (commit `33b43ac`). No contradicted criterion remains.
- ⏳ **CLAUDE.md rewrite — IN SCOPE for this phase.** Remove the `store.py` "large
  central exception … NO >600 loc" language in CLAUDE.md §"DEEP REFACTOR ON TOUCH"
  and reflect the no-allowlist cap. The planner MUST include this edit.

---

*Phase: 1-CI + Git-Hook Discipline*
*Context gathered: 2026-07-11 · Decisions resolved: 2026-07-11 (post-research)*
