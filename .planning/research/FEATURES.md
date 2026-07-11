# Feature Research: CI/CD + Git-Hook Discipline (Thrust 3)

**Domain:** CI/CD and local git-hook tooling for a Python 3.11–3.14 / FastMCP / TuringDB repo, discipline mirrored from the Go monorepo `D:\Repo\Aura` (lefthook + GitHub Actions, no-skip-as-green, fast-hooks/heavy-CI split, GPU-tier compile-floor degradation)
**Researched:** 2026-07-11
**Confidence:** HIGH (versions verified via web search 2026-07-11; repo facts verified by reading `pyproject.toml`, `compose.yaml`, `CLAUDE.md`, `cli.py`, `e2e_score.py`, `Makefile`, and Aura's `lefthook.yml` / `.github/workflows/ci.yml` directly)

## Key repo facts that shape every recommendation below

- **No `.github/workflows/` and no `lefthook.yml`/`.pre-commit-config.yaml` exist yet** — this is greenfield install, not a migration.
- **`scripts/e2e_score.py` / `turing-agentmemory-mcp e2e-score` is GPU-independent by default.** It spins up in-process stub embed/rerank HTTP servers unless `E2E_USE_EXTERNAL_EMBED=1` / `E2E_USE_EXTERNAL_RERANK=1` is set (`e2e_score.py:777,783`), and `cli.py` already returns exit code `1` when `score != 10.0` — this is itself a no-skip-as-green primitive already in the codebase; CI just needs to invoke it and trust its exit code.
- **`compose.yaml`'s `e2e` service (`profiles: ["e2e"]`)** runs `python scripts/e2e_score.py` in the built image — it does **not** start the GPU sidecars, so `docker compose run --rm e2e` is also GPU-free by default. This is the dockerized-integration tier and it is cheap to run on hosted runners.
- **Three services are GPU-mandatory** (`gpus: all`, `NVIDIA_VISIBLE_DEVICES`, `deploy.resources.reservations.driver: nvidia`): `agentmemory-embed`, `agentmemory-embed-gemma`, `agentmemory-rerank` (and `agentmemory-gliner` for entity extraction). These are the tiers that need Aura-style compile-floor degradation on GitHub-hosted runners.
- **File sizes already exceed a Go-style 600-LOC cap broadly**: `store.py` 3891, `benchmark.py` 1044, `e2e_score.py` 873, `server.py` 762, `document_jobs.py` 666, `gliner_provider.py` 658. CLAUDE.md already names `store.py` as "the large central exception." A blind Aura-style cap would fail on day one — the cap needs a documented allowlist, not a single global threshold.
- **No pytest markers, no `conftest.py`, no coverage tooling configured today** (`pyproject.toml` dev extras = `pytest>=8.2`, `ruff>=0.9` only). No-skip-as-green and coverage gates are both new infrastructure, not adaptations of existing config.
- **Versions to pin (verified 2026-07-11, not training-data guesses):** lefthook `v2.1.10`, ruff `0.15.17` (current `pyproject.toml` pin of `>=0.9` is 6+ minor series stale and should be tightened), pip-audit `2.10.1`, pytest-cov `7.1.0`, `actions/checkout@v7`, `actions/setup-python@v6`, `actions/cache@v6` (all confirmed current as of research date; Aura's `ci.yml` already uses `checkout@v7`/`cache@v6`, corroborating these are current majors, not stale pins).

## Feature Landscape

### Table Stakes (Non-Negotiable — Directly Requested, Directly Modeled on Aura)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| `lefthook.yml` pre-commit: `ruff format --check` + `ruff check` | PROJECT.md Thrust 3 names this explicitly; matches Aura's pattern of putting the fast static-analysis gate at commit time so a regression is one small diff, not a bisect | LOW | `glob: "*.py"` scoped so a docs-only commit skips it, same as Aura's `gofmt`/`lint` glob gating. Ruff format and ruff check are two separate lefthook commands (mirrors Aura's separate `gofmt` / `lint` commands) so a formatting-only fix and a lint fix surface as distinct fast signals. |
| `lefthook.yml` pre-commit: file-size cap | PROJECT.md Thrust 3 names this explicitly, mirrors `scripts/check-file-size.sh` in Aura | MEDIUM | **Must ship with an explicit allowlist**, not a flat threshold — `store.py` (3891 LOC), `benchmark.py`, `e2e_score.py`, `server.py`, `document_jobs.py`, `gliner_provider.py` already exceed any Go-parity cap (600). Recommended shape: cap = 900 LOC for any file NOT in a `# grandfathered` allowlist in the check script itself (mirrors CLAUDE.md's own explicit `store.py` exception); new files always enforced at 900. Without the allowlist this hook is DOA on first `lefthook install`. |
| `lefthook.yml` pre-push: import/compile smoke | Matches Aura's pre-push `build`/`deadcode` — "still works" floor before the network round-trip | LOW | Python has no compile step; the equivalent is `python -c "import turing_agentmemory_mcp.server"` (or `python -m py_compile` over `src/`) plus `python -m ruff check --select F401,F821` (Pyflakes catches undefined-name/unused-import, the closest Python analog to a Go build break). |
| `lefthook.yml` pre-push: fast pytest subset | PROJECT.md Thrust 3 names this explicitly | MEDIUM | "Fast subset" needs a concrete definition — see No-Skip-As-Green section: mark GPU-live / dockerized-integration tests with markers and have the pre-push hook run `pytest -m "not docker_integration and not gpu_live"`. Full unmarked suite still runs in CI. |
| `lefthook.yml` pre-push: `docker compose config --quiet` | CLAUDE.md already lists this as part of "the gate"; PROJECT.md Thrust 3 names it explicitly | LOW | Already a documented manual step (`CLAUDE.md` "Before closing a task"); this feature just automates what a developer is already supposed to run. Zero new script needed — direct passthrough. |
| `.github/workflows/ci.yml` — lint job (ruff) | PROJECT.md Thrust 3 names this explicitly | LOW | `python -m ruff check src tests scripts` (matches `Makefile`'s existing `lint` target exactly — reuse it, do not reinvent). |
| `.github/workflows/ci.yml` — unit test job (pytest, `pythonpath=src`) | PROJECT.md Thrust 3 names this explicitly | LOW | `python -m pytest` already honors `pythonpath = ["src"]` from `pyproject.toml`; no extra CI-side path wiring needed (unlike Aura's `go_packages.sh` package discovery, Python's `pytest` config already does this). |
| `.github/workflows/ci.yml` — dockerized integration + E2E score gate job | PROJECT.md Thrust 3 names this explicitly | MEDIUM | Two sub-choices exist and both should run: (1) `python -m turing_agentmemory_mcp e2e-score` in-process on the runner (fast, GPU-free, exercises the real MCP tools per CLAUDE.md's own E2E description) and (2) `docker compose run --rm e2e` (exercises the actual built image + compose network wiring, catches Dockerfile/dependency drift the in-process run cannot). Depends on Thrust 1 (reliable one-command compose stack) for (2) to be non-flaky — see Dependencies. |
| `.github/workflows/ci.yml` — compose validation job | PROJECT.md Thrust 3 names this explicitly; CLAUDE.md already documents `docker compose config --quiet` as part of "the gate" | LOW | Cheapest job in the matrix (no Docker daemon work, pure YAML interpolation check); should run first / fail fast, mirroring Aura's cheap gates running before expensive ones. |
| `.github/workflows/ci.yml` — supply-chain scan (pip-audit) | PROJECT.md Thrust 3 names this explicitly; parallels Aura's `govulncheck` job | LOW | `pip-audit` pinned `2.10.1`, run against the installed `.[dev]` (and optionally `,gliner`) environment. Should be a separate job (like Aura's `vulncheck`) so a new CVE doesn't block merges silently bundled into lint. |
| No-skip-as-green discipline for pytest | PROJECT.md Thrust 3 names this explicitly as a discipline requirement, not optional | MEDIUM-HIGH | See dedicated section below — this is the one item needing new Python-side infrastructure (markers + a `conftest.py` guard), not a 1:1 port of a Go idiom. |
| GPU-less CI degradation for the CUDA sidecar tiers | PROJECT.md/Context explicitly calls this out, matches Aura's `document_ingest_live`/`rerank_integration`/`graphrag_live` compile-floor pattern | MEDIUM | See dedicated section below. Lower complexity than Aura's equivalent because `e2e_score.py` already defaults to GPU-free stubs — only the *real* GPU sidecar tier needs degrading, not the whole E2E gate. |

### Differentiators (This Repo's Specific Fit — Beyond a Literal Aura Port)

| Feature | Value Proposition | Complexity | Notes |
|---------|--------------------|------------|-------|
| Coverage gate via `pytest-cov` + `coverage.py`, floor set deliberately low at rollout (e.g. 60–70%) with a documented ratchet plan | Aura's CI enforces an 85% floor (`scripts/coverage_gate.sh`) on a codebase that has had that discipline from early phases; this repo has **zero** coverage tooling today (per TESTING.md, "Not enforced in tooling"). Bolting on an 85% floor day one would either fail immediately or force a padding exercise that adds no real signal | LOW to add, MEDIUM to calibrate | Add `pytest-cov 7.1.0` as a dev dependency, run `pytest --cov=src/turing_agentmemory_mcp --cov-report=term-missing --cov-fail-under=<floor>` as its own CI job (separate from the plain unit-test job, mirroring Aura's separate `coverage_gate.sh` step so a coverage regression is legible independently from a test failure). Measure actual current coverage first, set the floor at or slightly below it, then ratchet up in a later phase — do not guess a number. |
| `docker compose build` "GPU image compile floor" job (build the 3 CUDA sidecar images without running them) | This is the direct Python/Docker analog of Aura's `go vet -tags rerank_integration ...` always-green floor — it proves the Dockerfiles + pinned dependency versions for `agentmemory-embed`, `agentmemory-rerank`, `agentmemory-gliner` still resolve, without needing an actual GPU | LOW | `docker compose build agentmemory-embed agentmemory-rerank agentmemory-gliner` on a GitHub-hosted (GPU-less) runner. Catches base-image/dependency rot even though the containers never execute a request in CI. |
| Ruff version pin tightened from `>=0.9` to an exact/narrow range in `pyproject.toml` | `ruff>=0.9` floats across 6+ minor series (0.9 → 0.15 as of this research) with behavior/rule-set changes between them; an unpinned floor means "lint passes locally, fails in CI" or vice versa the moment `pip install` picks up a newer resolver-selected ruff | LOW | Pin `ruff==0.15.17` (or `~=0.15.0`) in both `pyproject.toml` dev extras and the `lefthook.yml` invocation (or route lefthook through the same venv's `ruff` binary so there is only one pin to maintain, not two). |
| Windows-lane sanity job in CI (`windows-latest`, no Docker) | CLAUDE.md states "Windows/PowerShell is primary" for local dev, yet the whole CI plan above is Linux/Docker-first (matching Aura's `windows-unit` job that exists because Aura found OS-specific code paths the Linux lane never touched) | LOW | Cheap job: `pip install -e ".[dev]"` + `pytest -m "not docker_integration and not gpu_live"` on `windows-latest`. Catches path-separator / `pathlib` / file-locking bugs the Linux lane can't, at low marginal CI cost. Not requested explicitly in PROJECT.md but directly justified by CLAUDE.md's own stated primary platform — flag for roadmap decision rather than assume. |
| `Makefile` targets as the single source of truth both lefthook and CI call | Avoids the classic drift where the hook runs one command and CI runs a slightly different one (Aura's own hooks literally re-run `scripts/*.sh` that CI also calls, for this reason) | LOW | Extend the existing `Makefile` (`test`, `e2e`, `docker-e2e`, `lint`) with `lint-fix`, `test-fast` (marker-excluded subset), `coverage`, `audit` targets; have both `lefthook.yml` and `ci.yml` invoke `make <target>` rather than duplicating raw commands in three places. |

### Anti-Features (Tempting Because Aura Does Them, Wrong Fit Here)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Literal port of Aura's `dupl`/`jscpd` (100-token clone detector) and `deadcode`/`knip` gates | "Install ALL the CI/hook discipline" reads as "copy every gate Aura has" | Aura's `dupl`/`deadcode` gates exist because Go has no equivalent to `ruff check --select F401` and no ecosystem-standard dead-code linter baked into its primary formatter; Python's `ruff` (rules `F`, `B`) already covers unused imports/names/most dead-code smells, and a dedicated Python clone-detector (e.g. a `pylint` similarity plugin) is a heavier, noisier tool for a benefit `ruff`'s `B` rule set already partially covers | Do not add a separate duplicate-code scanner in Thrust 3. If duplication becomes a real problem later, address it as a CONCERNS.md item with a scoped tool choice, not a blanket CI gate mirrored from a different language's toolchain. |
| 600-LOC file-size cap applied uniformly, no allowlist | Directly copying Aura's `scripts/check-file-size.sh` threshold | Would immediately fail on `store.py` (3891 LOC) which CLAUDE.md *itself* calls out as "the large central exception... extend it deliberately, don't grow it casually" — a uniform gate contradicts the project's own documented architecture decision and would either block all future work on `store.py` or force a bypass habit (`--no-verify`) that undermines the whole hook discipline | Ship the cap with a named-file allowlist from day one (see Table Stakes row above); revisit the allowlist explicitly if/when `store.py` is split as part of the Thrust 2 backend-driver-abstraction work. |
| Requiring the real GPU-live E2E tier (real CUDA embed/rerank/gliner containers serving real requests) to pass on every PR via GitHub-hosted runners | "No-skip-as-green" read maximally strict — "nothing may ever be green without actually running" | GitHub-hosted runners have no GPU; a job that hard-requires the CUDA sidecars to be reachable will **always** fail on every PR, not just skip — this is not "no-skip-as-green" being followed, it's the gate being permanently red, which trains reviewers to ignore/override it (the opposite of the intended discipline) | Split the tiers explicitly: the compile/build floor (image builds correctly) is unconditional and always runs; the *live* GPU tier is either (a) reserved for a self-hosted GPU runner label (`runs-on: [self-hosted, gpu]`) as an optional/manual job, matching how Aura gates its own GPU-dependent `rerank_integration`/`graphrag_live` tiers to compile-only on hosted runners, or (b) run via `E2E_USE_EXTERNAL_EMBED=1`/`E2E_USE_EXTERNAL_RERANK=1` against a pre-provisioned external endpoint on a scheduled/manual `workflow_dispatch`, never blocking the default PR gate. |
| `pre-commit` (the Python framework, pre-commit.com) as the hook runner | It is the "obvious" Python-ecosystem choice and has first-class ruff hooks (`ruff-pre-commit`) | The user explicitly said "look at Aura" for the CI/hook model, and Aura's whole hook discipline (parallel commands, fast pre-commit / heavier pre-push split, single `lefthook.yml` mirroring `make quality`) is built around lefthook's specific feature set (per-stage parallel command groups, language-agnostic single binary, YAML mirrors Makefile targets 1:1). Introducing `pre-commit` instead means re-deriving that structure in a different tool's idiom, and it doesn't naturally support Aura's fast-commit/heavy-push staging split as cleanly (its native model is stage-agnostic hook repos) | Use **lefthook** (pinned `v2.1.10`), installed via `pipx install lefthook` or the `lefthook` PyPI/npm wrapper, so the local hook tool is the same one Aura uses and the `lefthook.yml` structure/vocabulary transfers directly for anyone who has worked in both repos. |
| `husky` | Node-ecosystem hook manager | This is a pure-Python backend repo with no `package.json`/npm dependency today (the `frontend/` Lab console is static assets served by `lab.py`, not a Node build) — pulling in Node/npm purely to run git hooks adds a whole second toolchain for zero benefit over lefthook, which needs no Node runtime | lefthook (single static binary, no runtime dependency). |
| Mutation testing (Stryker-equivalent, e.g. `mutmut`/`cosmic-ray`) in the default CI matrix | Aura's frontend CI runs Stryker mutation testing (`web-mutation` job) as part of its "industrial set" | Not requested in PROJECT.md Thrust 3 (which scopes lint/unit/dockerized-integration+E2E/compose-validation/supply-chain-scan/no-skip-as-green/GPU-degradation only); mutation testing is expensive per-run and this repo has no coverage baseline yet — adding it before a coverage floor even exists is sequencing out of order | Out of scope for this milestone; revisit only after the coverage gate is calibrated and stable. |

## Feature Dependencies

```
[Thrust 1: reliable one-command `docker compose up`]
    └──required-by──> [CI: dockerized integration + E2E score gate job (docker compose run --rm e2e)]
    └──required-by──> [CI: compose validation job (docker compose config --quiet)]
                           (config validation itself has NO dependency on Thrust 1 being fixed —
                            it only parses YAML — but the actual `run --rm e2e` step needs a
                            stack that reliably comes up, or that CI job will be flaky by
                            construction, undermining no-skip-as-green from a different angle)

[pytest custom markers: docker_integration, gpu_live]
    └──required-by──> [lefthook pre-push: fast pytest subset ("not docker_integration and not gpu_live")]
    └──required-by──> [No-skip-as-green conftest.py backstop]
    └──required-by──> [CI: unit test job vs dockerized-integration job split]

[e2e_score.py's existing E2E_USE_EXTERNAL_EMBED / E2E_USE_EXTERNAL_RERANK stub switches]
    └──enables──> [CI E2E gate running GPU-free by default on hosted runners]
    └──enables──> [GPU-live E2E variant (E2E_USE_EXTERNAL_EMBED=1) on self-hosted/GPU runner
                    without any code change — same script, different env]

[file-size cap allowlist naming store.py/benchmark.py/e2e_score.py/server.py/...]
    └──required-by──> [lefthook pre-commit: file-size cap]
                           (without the allowlist this hook is DOA on the very first commit)

[GPU image compile-floor job (`docker compose build` for the 3 CUDA sidecars)]
    └──independent-of──> [Thrust 1 stack reliability]
                           (a build-only step does not need the stack to run, so it can ship
                            immediately, ahead of Thrust 1 completing)

[Coverage measurement baseline run]
    └──required-by──> [Coverage gate floor number in CI]
                           (do not guess a floor — measure current coverage first, then set it)

[ruff pin tightened in pyproject.toml]
    └──required-by──> [lefthook pre-commit ruff commands and CI lint job agreeing]
                           (an unpinned floor means local/CI ruff versions can silently diverge)
```

### Dependency Notes

- **Dockerized-integration CI depends on Thrust 1 (docker-stack reliability) for its live-`docker compose run` step, but not for its config-validation step.** Sequence the CI job so `docker compose config --quiet` ships and gates immediately (zero dependency), while the `docker compose run --rm e2e` step can be added to the same job or a follow-on job once Thrust 1 lands — do not block the whole CI rollout on Thrust 1 finishing.
- **The GPU-live tier cannot be made to pass on GitHub-hosted runners no matter how the code is written** — there is no GPU. This is a hard external constraint, not a design choice; the only two honest options are self-hosted GPU runner or `workflow_dispatch`-gated manual run against an external endpoint. Both keep the compile-floor unconditional and green.
- **No-skip-as-green markers must exist before the pre-push fast-subset hook can exclude the right tests** — define `docker_integration` and `gpu_live` (or similar) pytest markers as the first concrete implementation step of Thrust 3, everything else in the "fast subset" and "CI job split" rows reads off that vocabulary.
- **File-size-cap and its allowlist are coupled** — do not ship the check script without the allowlist in the same commit; a bare cap script will fail-closed on `store.py` immediately and either block all commits or force habitual `--no-verify`, defeating the hook's purpose (mirrors the CLAUDE.md warning about hooks staying "fast enough not to be habitually bypassed" — a hook that's *wrong*, not just slow, gets bypassed just as fast).

## MVP Definition

### Launch With (v1 — first Thrust-3 phase)

- [ ] `lefthook.yml` with pre-commit (`ruff format --check`, `ruff check`, file-size cap w/ allowlist) — the fast, always-on local gate
- [ ] `lefthook.yml` with pre-push (import/compile smoke, fast pytest subset, `docker compose config --quiet`)
- [ ] pytest custom markers (`docker_integration`, `gpu_live`) registered in `pyproject.toml` `[tool.pytest.ini_options] markers = [...]`, applied to the (currently zero) tests that need them as those tests are written/identified
- [ ] `conftest.py` no-skip-as-green backstop (session-finish hook failing the run under `CI=true` if a no-skip-marked test was skipped) — essential because it is the one mechanism this repo has zero prior art for
- [ ] `.github/workflows/ci.yml`: lint job, unit-test job, compose-validation job, supply-chain-scan (pip-audit) job — all GPU-free, all can ship immediately with no Thrust-1 dependency
- [ ] Ruff pin tightened from `>=0.9` to `==0.15.17` (or `~=0.15.0`) in `pyproject.toml`

### Add After Validation (v1.x — once Thrust 1's compose stack is reliable)

- [ ] `.github/workflows/ci.yml`: dockerized-integration + E2E score gate job (`docker compose run --rm e2e`), sequenced after Thrust 1
- [ ] GPU image compile-floor job (`docker compose build` for the 3 CUDA sidecars) — can actually ship earlier (no Thrust-1 dependency) but is naturally grouped with the dockerized-integration work
- [ ] Coverage gate: measure baseline, set an explicit floor, add as its own CI job

### Future Consideration (v2+ — explicitly out of this milestone's scope per Anti-Features)

- [ ] Real GPU-live E2E tier on a self-hosted/GPU-labeled runner or scheduled `workflow_dispatch`
- [ ] Coverage floor ratchet upward once a stable baseline has run for a few weeks
- [ ] Windows-lane CI job (flagged as a differentiator, not requested — needs an explicit roadmap decision, not an assumption)

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|----------------------|----------|
| lefthook pre-commit (ruff format/check + file-size cap) | HIGH | LOW | P1 |
| lefthook pre-push (compile smoke, fast pytest, compose config) | HIGH | LOW | P1 |
| No-skip-as-green pytest markers + conftest backstop | HIGH | MEDIUM | P1 |
| CI: lint / unit-test / compose-validation / pip-audit jobs | HIGH | LOW | P1 |
| Ruff version pin tightening | MEDIUM | LOW | P1 |
| File-size-cap allowlist | HIGH (blocking for the cap to be usable at all) | LOW | P1 |
| CI: dockerized-integration + E2E gate job | HIGH | MEDIUM | P2 (after Thrust 1) |
| GPU image compile-floor job | MEDIUM | LOW | P2 |
| Coverage gate (measured floor) | MEDIUM | MEDIUM | P2 |
| `Makefile` target consolidation (single source of truth) | MEDIUM | LOW | P2 |
| Windows-lane CI job | LOW-MEDIUM | LOW | P3 |
| Real GPU-live E2E tier (self-hosted/manual) | MEDIUM | HIGH (needs runner infra decision) | P3 |
| Mutation testing | LOW (unrequested) | HIGH | Out of scope |
| Duplicate-code scanner (Aura `dupl`/`jscpd` parity) | LOW (ruff already covers most of this in Python) | MEDIUM | Out of scope |

**Priority key:**
- P1: Ships in the first Thrust-3 phase, no external dependency
- P2: Ships once Thrust 1 (docker-stack reliability) lands, or is naturally sequenced with it
- P3: Explicit roadmap decision needed before building; not blocking Thrust 3's core discipline

## Reference Implementation Sketches

These are illustrative, not final code — they exist to make the "concrete no-skip-as-green mechanism" and "GPU-less degradation approach" quality-gate items unambiguous for the phase that implements them.

**No-skip-as-green — per-test explicit guard (mirrors Aura's `envOrSkip` t.Fatal-under-CI):**
```python
# tests/_ci_guards.py
import os
import pytest

def require_env_or_skip(name: str) -> str:
    """Aura-style no-skip-as-green: under CI, a missing precondition FAILS, never skips."""
    value = os.environ.get(name)
    if value:
        return value
    if os.environ.get("CI") == "true":
        pytest.fail(f"{name} must be set under CI (no-skip-as-green) — a missing var fails, not skips")
    pytest.skip(f"{name} not set (local dev skip)")
```

**No-skip-as-green — session-level backstop (catches accidental skips the per-test guard didn't cover):**
```python
# tests/conftest.py
import os

NO_SKIP_MARKERS = {"docker_integration", "gpu_live"}

def pytest_sessionfinish(session, exitstatus):
    if os.environ.get("CI") != "true":
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = reporter.stats.get("skipped", []) if reporter else []
    offending = [r for r in skipped if NO_SKIP_MARKERS & set(getattr(r, "keywords", {}))]
    if offending:
        names = ", ".join(r.nodeid for r in offending)
        print(f"NO-SKIP-AS-GREEN: {len(offending)} marked test(s) skipped under CI: {names}")
        session.exitstatus = 1
```

**GPU-less degradation — CI job shape:**
```yaml
gpu-compile-floor:
  name: GPU sidecar image build floor (no GPU needed — proves images still build)
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v7
    - name: Build CUDA sidecar images (build-only, never run)
      run: docker compose build agentmemory-embed agentmemory-rerank agentmemory-gliner

e2e-gate:
  name: E2E score gate (GPU-free by default — e2e_score.py stubs embed/rerank)
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v7
    - uses: actions/setup-python@v6
      with: { python-version: "3.11" }
    - run: pip install -e ".[dev]"
    - run: python -m turing_agentmemory_mcp e2e-score --out e2e-results.json
    - run: docker compose config --quiet
    - run: docker compose run --rm e2e   # also GPU-free; profiles: ["e2e"]
```

## Sources

- `D:\Repo\Aura\lefthook.yml` — direct read, pre-commit/pre-push structure and rationale comments (accessed 2026-07-11)
- `D:\Repo\Aura\.github\workflows\ci.yml` — direct read (first ~1100 of 1353 lines), job matrix, no-skip-as-green `envOrSkip`/`CI=true` pattern, GPU-tier compile-floor pattern (accessed 2026-07-11)
- This repo: `CLAUDE.md`, `pyproject.toml`, `compose.yaml`, `Makefile`, `src/turing_agentmemory_mcp/cli.py`, `src/turing_agentmemory_mcp/e2e_score.py`, `.planning/PROJECT.md`, `.planning/codebase/{TESTING,STACK,CONVENTIONS}.md` — direct reads (2026-07-11)
- [lefthook releases](https://github.com/evilmartians/lefthook/releases) — v2.1.10 current as of 2026-07-08 (confidence: HIGH, official GitHub releases page)
- [ruff CHANGELOG](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md) / [ruff v0.15.0 blog](https://astral.sh/blog/ruff-v0.15.0) — 0.15.17 current as of 2026-06-25 release (confidence: HIGH)
- [pip-audit PyPI](https://pypi.org/project/pip-audit/) / [pip-audit releases](https://github.com/pypa/pip-audit/releases) — 2.10.1 current (confidence: HIGH)
- [actions/setup-python releases](https://github.com/actions/setup-python) — v6.0.0 current major (confidence: HIGH)
- [pytest-cov PyPI](https://pypi.org/project/pytest-cov/) — 7.1.0 current (confidence: HIGH)
- `actions/checkout@v7`, `actions/cache@v6` version currency cross-checked against Aura's own `ci.yml` (a repo actively maintained through 2026) using those exact tags (confidence: MEDIUM-HIGH — corroborating source, not an independent version-registry lookup for these two specific actions)

---
*Feature research for: CI/CD + git-hook tooling, Turing AgentMemory MCP stabilization milestone (Thrust 3)*
*Researched: 2026-07-11*
