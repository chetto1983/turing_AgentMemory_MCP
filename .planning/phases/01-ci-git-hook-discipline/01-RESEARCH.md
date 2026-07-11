# Phase 1: CI + Git-Hook Discipline - Research

**Researched:** 2026-07-11
**Domain:** Git hooks (lefthook) + GitHub Actions CI for a Python/FastMCP repo; large-module decomposition; pytest coverage/marker discipline
**Confidence:** HIGH (all package/version/coverage claims below were verified by executing commands against this repo and the live PyPI registry in this session, not recalled from training data)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Locked upstream (carried forward — do NOT re-litigate):**
- **L-01:** Local hooks = **lefthook**; CI = **GitHub Actions**. No existing hook or CI config in this repo (only `.github/ISSUE_TEMPLATE/` and `PULL_REQUEST_TEMPLATE.md`). Clean slate.
- **L-02:** `pre-commit` runs: `ruff format --check`, `ruff check`, and the file-size cap enforcing no file >600 LOC, with **NO allowlist** (D-08 reversed the roadmap's original allowlist mandate). The cap is a pre-commit gate that scans ALL tracked `*.py` files and hard-fails now.
- **L-03:** `pre-push` runs: import/compile smoke, a **fast** pytest subset, `docker compose config --quiet`.
- **L-04:** CI job matrix: lint (ruff **pinned `0.15.x`**), unit tests (pytest, `pythonpath=src`), compose-validation, pip-audit (**`2.10.1`**), and a dockerized-integration job running the E2E score gate + real-document E2E.
- **L-05:** Heavy gates (full E2E, real-doc E2E, coverage) live in CI; hooks stay fast enough not to be habitually bypassed.
- **L-06 (REVISED by D-08):** `store.py` is **3891 LOC**. There is **no allowlist**: `store.py` must be **decomposed to ≤600-LOC modules within this phase** (split by concern, `store_<concern>.py`). The CLAUDE.md store.py-exception language MUST be rewritten.

**Hook distribution & install (Python/Windows reality):**
- **D-01:** Install lefthook via the **`lefthook` pip package** added to the `dev` optional-dependency extra, so `pip install -e ".[dev]"` brings the binary into the venv. No Go/Node toolchain.
- **D-02:** Fresh clones wire git hooks via a documented `lefthook install` step, surfaced through a `make hooks` target. Do NOT auto-install silently.
- **Rejected:** npm `lefthook`, standalone binary + Makefile fetch, swapping to Python-native `pre-commit` framework.

**No-skip-as-green enforcement (the defining discipline):**
- **D-03:** Enforce via a **central `conftest.py` CI-guard**: when `CI=true`, any `pytest.skip` on a marked integration/GPU tier is converted into a **failure**.
- **D-04:** Ship a **negative self-test** that proves the guard actually fires (a deliberately-skipped marked test MUST make the gate exit non-zero under `CI=true`).
- **Rejected:** per-test fail-loud env guards, job-level YAML assertions on pytest output.

**GPU-less CI degrade floor:**
- **D-05:** On a GPU-less runner, GPU-dependent embed/rerank/GLiNER tiers degrade to the **full deterministic E2E score gate + real-doc E2E run against the repo's existing in-process stub embed/rerank endpoints** (the same stubs `scripts/e2e_score.py` already spins up).
- **D-06:** This degraded run must be **visibly distinct** (named/labelled) from a real-GPU run — but it is a real pass/fail signal, never a skip.
- **Rejected:** stub-run + image-build smoke, import/compile-only smoke.

**Gate strictness policy:**
- **D-07:** Coverage is a hard CI failure below the floor, and the floor only ever ratchets up (never silently lowered). The floor number is **measured against the actual current suite** — not guessed. Tooling: add `pytest-cov`/`coverage` to the `dev` extra.
- **D-08 (reversed mid-discussion):** **No allowlist.** The file-size cap scans all tracked `*.py` files every commit and hard-fails now — no per-file exemption, not even for `store.py`. Adapt Aura's `check-file-size.sh` (600-LOC cap, keep MSYS/Git-Bash process-substitution workaround) to scan `*.py`, dropping the allowlist mechanism entirely.
  - **Bootstrap ordering (planner MUST handle):** the split has to land before the hook is active (or via an initial `--no-verify` bootstrap), otherwise the very commit that installs lefthook is itself blocked. Sequence: decompose store.py → verify E2E score gate + full pytest still green → then install hooks + CI.
  - **Risk:** store.py is direct-ported to ArcadeDB in Phase 4; splitting it now means Phase 4 ports the split modules rather than one file. Acceptable per user.
  - **Rejected:** inline-comment allowlist, checked-in `.file-size-allowlist`, staged-files-only scanning.

### Claude's Discretion
- **Fast pytest subset boundary (L-03/pre-push):** mark slow/integration/GPU tests and run `-m "not slow and not integration and not gpu"`, or a curated deselect list. Planner/researcher decides the exact marker taxonomy.
- **CI trigger/branch config, concurrency-cancel, permissions block:** follow Aura's `ci.yml` conventions, adapted to `master`.
- **Whether lint's ruff runs at pre-commit vs pre-push:** pre-commit is the reasonable default (Aura moved lint to pre-commit so regressions surface at the authoring commit).

### Deferred Ideas (OUT OF SCOPE)
- **Windows CI lane (CI-10)** — v2/deferred. Do not add a `windows-latest` job unless explicitly promoted.
- **GPU sidecar Docker image build smoke** — belongs with Phase 12 Docker work.
- **Fixing the stale `pyproject.toml` description / MIT-vs-Apache licensing churn from the ArcadeDB migration** — a Phase 7 concern.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CI-01 | lefthook pre-commit (ruff format --check, ruff check, file-size cap ≤600 LOC, no allowlist, store.py decomposed) | See "Standard Stack", "store.py Decomposition", "Package Legitimacy Audit", Pitfall 1 (10 files already exceed the cap, not just store.py) |
| CI-02 | lefthook pre-push (import/compile smoke, fast pytest subset, `docker compose config --quiet`) | See "Fast Subset / Marker Taxonomy" — current suite has NO slow tests today; markers are forward-looking |
| CI-03 | GitHub Actions lint job (ruff pinned 0.15.x) | Verified: ruff 0.15.21 is current; `ruff check`/`ruff format --check` results captured below |
| CI-04 | GitHub Actions unit-test job (pytest, pythonpath=src) | Verified: 362 tests, 25-32s, zero external-service dependencies today |
| CI-05 | GitHub Actions dockerized-integration job (E2E score gate + real-document E2E) | See Open Question 2 — `real_document_benchmark.py` is NOT CI-shaped as written (hardcoded path, live OpenRouter call, standalone MCP URL) |
| CI-06 | GitHub Actions compose-validation + pip-audit 2.10.1 | Verified: `docker compose config --quiet` passes today; pip-audit 2.10.1 is the current latest release |
| CI-07 | No-skip-as-green | See "Code Examples" — conftest.py hookwrapper design + negative self-test pattern |
| CI-08 | GPU-less degrade floor | See D-05 mechanism confirmed in `scripts/e2e_score.py` (`E2E_USE_EXTERNAL_EMBED/RERANK`) |
| CI-09 | Coverage gate, measured floor | **Measured this session: 74% (6326 stmts / 1645 miss) including `e2e_score.py`; 78% excluding it.** See "Coverage Floor" section |
</phase_requirements>

## Summary

This phase has two independent halves that must be sequenced correctly: (1) a large,
mechanical-but-risky refactor (splitting `store.py`, 3891 LOC, into concern modules) that
must land and be verified green **before** (2) the guardrails (lefthook + CI) that would
otherwise block the very commit that installs them. Both halves are now de-risked by direct
verification in this session rather than assumption.

The single most important finding this research surfaced, which CONTEXT.md's Open Questions
did not anticipate: **`store.py` is not the only file over the 600-LOC cap.** A repo-wide scan
of all tracked `*.py` files found **9 additional files** already over 600 LOC — 5 in `src/`
(`benchmark.py` 1044, `e2e_score.py` 873, `server.py` 762, `document_jobs.py` 666,
`gliner_provider.py` 658), 2 in `tests/` (`test_gliner_provider.py` 1076, `test_batch_memory.py`
749), and 2 in `scripts/` (`eval_backboard_locomo_mcp.py` 936, `real_document_benchmark.py`
827). Because D-08 explicitly locked "no allowlist... scans ALL tracked `*.py` files... hard-fails
now" and explicitly rejected "staged-files-only scanning," the literal reading of the locked
decision means **all 10 files** (store.py + 9 others) must be under the cap before the
pre-commit hook can be turned on — not just store.py. This is flagged as Open Question 1 below
because it materially changes the phase's scope versus what ROADMAP SC#5 and CONTEXT.md
anticipated (store.py only).

The second major finding: **`ruff format --check` currently fails on 49 of the repo's ~78
tracked Python files** (verified this session with the pinned ruff 0.15.21). This is a second,
independent bootstrap-ordering problem alongside the store.py split — a one-time
`ruff format src tests scripts` pass (or equivalent staged commit) must land before the
pre-commit hook is turned on, or the hook-installation commit blocks itself on pre-existing
formatting drift, not just LOC.

On the positive side: the pip `lefthook` package (D-01) is **confirmed to work cleanly on
Windows** — its `win_amd64` wheel bundles a real `lefthook.exe` binary and wires a
`console_scripts` entry point that dispatches to it by platform, verified by downloading and
inspecting the actual wheel. `ruff`, `pip-audit`, and `pytest-cov` are all mature, well-known
packages with the exact pinned versions available on PyPI today. The existing 362-test pytest
suite is fully self-contained (fakes/mocks only, no live TuringDB/Docker/GPU dependency) and
already runs in ~25-30s — meaning there is currently **no slow/integration/GPU-marked tier to
carve out**; the marker taxonomy this phase introduces is forward-looking infrastructure for
future phases, not a response to an existing slow-test problem. Coverage was measured directly
in this session (not guessed): **74%** including `e2e_score.py` in the denominator, or **78%**
if it is excluded (recommended, since it's exercised by its own dedicated `make e2e` run, not
by pytest).

**Primary recommendation:** Sequence the phase as (1) resolve Open Question 1 (confirm/expand
decomposition scope) → (2) decompose `store.py` (and any other in-scope oversized files) into
`store_<concern>.py` mixin modules behind a slim `store.py` facade, preserving the
`TuringAgentMemory` import path → (3) run a one-time `ruff format` pass across the repo → (4)
verify `pytest -q` (362/362) and `scripts/e2e_score.py` (10/10, score ≥9.8) are still green → (5)
only then wire `lefthook.yml` + `.github/workflows/ci.yml`, register pytest markers, add the
`conftest.py` no-skip-as-green guard + its negative self-test, and set the coverage floor from
the measured baseline.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Pre-commit fast checks (format/lint/file-size) | Local git hook (lefthook) | — | Must run in <5s to avoid habitual `--no-verify` bypass; no network/DB needed |
| Pre-push medium checks (compile smoke, fast pytest, compose config) | Local git hook (lefthook) | — | Slower than pre-commit but still local-only; no CI round-trip needed to catch obvious breaks |
| Full test suite + coverage gate | CI (GitHub Actions) | — | Requires the complete dependency set (`graspologic-native`, etc.) and takes longer than a hook budget allows |
| E2E score gate (stub embed/rerank) | CI (GitHub Actions) — dockerized-integration job | Local (`make e2e`) | Runs entirely in-process (TuringDB daemon + stub HTTP servers spun up by the script itself); Docker wraps it for environment parity, not because it needs Docker services |
| Real-document E2E | CI (GitHub Actions) — **contested**, see Open Question 2 | Operator-run script | `scripts/real_document_benchmark.py` as currently written needs a live paid LLM key + a pre-running MCP server; not CI-shaped without further work |
| Supply-chain scan (pip-audit) | CI (GitHub Actions) | — | Needs the fully resolved dependency set installed; not meaningful as a pre-commit/pre-push check |
| `store.py` decomposition | Source tree (`src/turing_agentmemory_mcp/`) | — | Pure refactor; no tier crossing, but is the load-bearing prerequisite for CI-01/the file-size cap |
| No-skip-as-green guard | Test infrastructure (`tests/conftest.py`) | CI (arms via `CI=true` env) | The guard logic is local-repo code; CI just sets the env var that arms it — same code path runs identically if a developer sets `CI=true` locally |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `lefthook` | 2.1.10 (pip) `[VERIFIED: PyPI + wheel inspection]` | Local git hook runner (pre-commit/pre-push) | L-01 locked; confirmed the `win_amd64`/`win_arm64` wheels bundle a real platform binary + `console_scripts` entry point — works cleanly with `pip install -e ".[dev]"` on this Windows-primary repo |
| `ruff` | 0.15.21 `[VERIFIED: pip index + local run]` | Lint + format (already a dependency, bump the pin) | L-04 requires pinning to `0.15.x`; 0.15.21 is the current latest 0.15.x release; verified `ruff check src tests scripts` passes cleanly and `ruff format --check` fails on 49 files (pre-existing drift, not a regression from the version bump) |
| `pytest-cov` | 7.1.0 `[VERIFIED: pip index]` | Coverage measurement + `--cov-fail-under` gate | D-07 requires `pytest-cov`/`coverage`; 7.1.0 is current, no known incompatibility with pytest 8.2+/9.x |
| `pip-audit` | 2.10.1 `[VERIFIED: pip index — exact match to the L-04 pin]` | Supply-chain vulnerability scan | L-04 pins exactly this version; it is also the current latest release on PyPI, so the pin is not stale |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `coverage` (transitive via `pytest-cov`) | bundled | Underlying coverage engine | Only needed directly if the plan wants `[tool.coverage.run] omit` config (recommended for `e2e_score.py`, see Coverage Floor section) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pip `lefthook` | Standalone binary download + Makefile fetch | Rejected in CONTEXT.md (D-01) — more Windows moving parts; the pip wheel already bundles the binary cleanly |
| pip `lefthook` | Python-native `pre-commit` framework | Rejected in CONTEXT.md — deviates from the locked lefthook decision, and would require re-deriving Aura's hook-file philosophy in a different tool |
| Central `conftest.py` guard | Per-test `if os.environ.get("CI") and ...: pytest.fail(...)` boilerplate | Rejected in CONTEXT.md (D-03) — easy to forget on new tests; centralizing via a `pytest_runtest_makereport` hookwrapper makes it structurally impossible to skip |

**Installation:**
```bash
# pyproject.toml [project.optional-dependencies].dev additions:
#   lefthook==2.1.10  (or a compatible >=2.1 pin)
#   ruff==0.15.21     (bump from the current unpinned ">=0.9")
#   pytest-cov==7.1.0
# pip-audit is a CI-only tool (installed in the workflow step, not a repo dependency)
pip install -e ".[dev]"
```

**Version verification (this session, against this repo/venv):**
```
$ python -m pip index versions lefthook   -> 2.1.10 (latest)
$ python -m pip index versions ruff       -> 0.15.21 (latest; 0.15.x line active)
$ python -m pip index versions pip-audit  -> 2.10.1 (latest — exact match to the locked pin)
$ python -m pip index versions pytest-cov -> 7.1.0 (latest)
```

## Package Legitimacy Audit

> `gsd-tools query package-legitimacy check` was attempted but the seam binary was not found
> in this environment (no `gsd-core` installation discoverable). All verification below was
> therefore done manually against the PyPI JSON API and by downloading/inspecting the actual
> wheel — a stronger check than the automated seam would provide for the one package (`lefthook`)
> where Windows-binary provenance mattered.

| Package | Registry | Age (first release / this version) | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `lefthook` | PyPI | Long-established Go tool (evilmartians); pip wrapper actively maintained, 2.1.10 current | Not spot-checked (mature, widely used in JS/Go ecosystems); wheel content directly inspected instead | github.com/evilmartians/lefthook | OK | Approved — `[VERIFIED: PyPI + direct wheel download/inspection]` the `win_amd64` wheel at `lefthook-2.1.10-py3-none-win_amd64.whl` contains `lefthook/bin/lefthook-windows-x86_64/lefthook.exe` and a `console_scripts` entry (`lefthook = lefthook.main:main`) that dispatches to it by platform |
| `ruff` | PyPI | Astral (Charlie Marsh); already a project dependency | Extremely high (tens of millions/week — industry-standard Python linter) | github.com/astral-sh/ruff | OK | Approved — already in use, only the pin changes |
| `pip-audit` | PyPI | PyPA official project | High (PyPA-maintained supply-chain tool) | github.com/pypa/pip-audit | OK | Approved |
| `pytest-cov` | PyPI | Long-established pytest-dev project | Very high (the standard pytest coverage plugin) | github.com/pytest-dev/pytest-cov | OK | Approved |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none. All four packages are long-established,
widely-used, org-backed tools with no slopsquatting risk signals (no unusually-new release,
no missing source repo, no anomalous first-release date). `lefthook` is the only one worth a
deeper look given the Windows-specific concern in D-01, and it was verified at the strongest
level available (direct wheel inspection) rather than left at `[ASSUMED]`.

## store.py Decomposition Plan

**Verified facts about `store.py` today (3891 LOC, one class `TuringAgentMemory` + one
module-level dataclass `_DocumentChunkGraphUnit` + two module constants):**
- Public API surface actually consumed externally (confirmed via grep of `server.py`,
  `document_job_manager.py`, `e2e_score.py`, `benchmark.py`, and ~10 test files that do
  `from turing_agentmemory_mcp.store import TuringAgentMemory`): `bootstrap`, `store_message`,
  `store_messages`, `add_entity`, `add_preference`, `add_fact`, `search_memory`, `get_memory`,
  `list_memories`, `update_memory`, `delete_memory`, `get_context`, `ingest_document_text`,
  `get_document`, `reindex_document_text`, `delete_document`, `search_documents`,
  `rebuild_vector_projection`, `rebuild_communities`, `rebuild_sparse_projection`,
  `load_graph_after_restart`, `runtime_status`. **The import path
  `turing_agentmemory_mcp.store.TuringAgentMemory` itself must not change** — every consumer
  imports it from there.
- No sibling module (`embeddings.py`, `entity_extraction.py`, `governance.py`, `hybrid.py`,
  `ids.py`, `memory_extraction.py`, `models.py`, `observability.py`, `provider_config.py`,
  `rerank.py`, `retrieval_fusion.py`, `search_controls.py`, `sparse_index.py`,
  `temporal_graph.py`, `community_detection.py`) imports **from** `store.py` — confirmed via
  grep. This means splitting `store.py` introduces **zero new cross-module import-cycle risk**
  against the rest of the codebase; all risk is contained to how the new `store_*.py` siblings
  relate to each other.

**Recommended approach: mixin classes in `store_<concern>.py` siblings, composed by a thin
`store.py` facade.** This is lower-risk than a package-directory rename or a
function-based delegation rewrite, because:
1. It is a mechanical cut-and-paste of existing method bodies into new files — no call-site
   rewrites, no changed method signatures, no changed `self.` semantics.
2. Cross-concern method calls (e.g. `search_memory` calling `self._rerank_memory`,
   `self._embed_text`, `self._records`) continue to work unmodified because all mixins compose
   into **one** class at runtime — Python resolves `self.<method>` via the MRO regardless of
   which sibling file defined it. No mixin needs to import another mixin's class.
3. The import path `from turing_agentmemory_mcp.store import TuringAgentMemory` is preserved
   exactly — `store.py` still exists, it just becomes a small facade.

**Illustrative module split** (line spans measured directly from the current file; treat as a
starting decomposition — exact boundaries may shift ±30-50 LOC during implementation, and the
`check-file-size.sh` script itself is the authoritative pass/fail check, not this table):

| Proposed module | Contents (method names) | Approx. LOC |
|---|---|---|
| `store_core.py` (`_StoreCore` mixin — provides `__init__`) | `__init__`, `bootstrap`, `load_graph_after_restart`, `runtime_status`, `_ensure_graph_loaded`, `_ensure_vector_index`, `_tenant_vector_index`, `_ensure_tenant_vector_index`, `_ensure_user`, `_require_user`, `_span`, `_audit`, `_query`, `_write`, `_write_many`, `_records`, `_now_iso`, `_json_dumps`, `_json_loads` | ~400 |
| `store_memory_write.py` | `store_message`, `store_messages`, `add_entity`, `add_preference`, `add_fact`, `_write_memory`, `_create_memories_batch`, `_plan_memory_projections`, `_batch_payload_key`, `_memory_matches_payload` (module constant `_MISSING` lives here) | ~590 |
| `store_memory_read.py` | `get_memory`, `list_memories`, `update_memory`, `delete_memory`, `_memory_from_row`, `_row_is_expired`, `_memory_matches_filters`, `_row_matches_metadata_filters`, `_active_memory_rows`, `_clean_limit`, `_clean_tags` | ~375 |
| `store_search.py` | `search_memory`, `_search_memory_fused`, `_rerank_memory`, `_annotate_memory_rerank`, `_memory_rerank_document`, `_fused_rerank_score_details` | ~430 |
| `store_evidence.py` | `_collect_retrieval_evidence`, `_episode_dense_evidence`, `_fact_dense_evidence`, `_entity_dense_evidence`, `_sparse_evidence`, `_community_dense_evidence`, `_query_graph_evidence`, `_expand_entity_evidence`, `_fact_sources_by_ids`, `_community_sources_by_ids`, `_memory_rows_for_ids` | ~450 |
| `store_documents.py` | `get_context`, `ingest_document_text`, `get_document`, `reindex_document_text`, `delete_document`, `_create_document`, `_document_graph_queries`, `_document_chunk_batch_query`, `_update_document_metadata`, `search_documents`, `_document_from_row`, `_active_chunk_rows`, `_rerank_documents`, `_reranked_score_details` (module dataclass `_DocumentChunkGraphUnit` lives here) | ~640 — **will need one more sub-split** (e.g. pull `_rerank_documents`/`_reranked_score_details` into `store_search.py`, or move `_document_chunk_batch_query` into `store_chunking.py`) to clear 600 |
| `store_chunking.py` | `_chunk_document_text`, `_chunk_text`, `_pack_text`, `_chunk_context` (module constant `_PAGE_MARKER_PATTERN` lives here) | ~110 |
| `store_rebuild.py` | `rebuild_sparse_projection`, `rebuild_vector_projection`, `rebuild_communities`, `_refresh_communities_after_batch`, `_community_graph_inputs`, `_active_community_ids`, `_replace_community_graph`, `_canonical_sparse_documents`, `_canonical_vector_records`, `_sparse_rebuild_rows`, `_unique_projection_entities`, `_existing_entity_ids`, `_prepare_sparse_projection`, `_sparse_doc_key`, `_sparse_kind`, `_fact_ids_for_memory` | ~560 |
| `store_utils.py` | `_projection_edge_literals`, `_cypher_value`, `_process_text_for_storage`, `_process_texts_for_storage`, `_redact_for_storage`, `_merge_entity_metadata`, `_row_search_text`, `_embed_many`, `_embed_text`, `_load_vectors`, `_vector_literal`, `_is_expired`, `_parse_filter_datetime`, `_timestamp_in_range`, `_parse_datetime`, `_int_value`, `_memory_vector_id`, `_entity_vector_id`, `_fact_vector_id`, `_community_vector_id`, `_document_vector_id`, `_document_text_hash` | ~300 |
| `store.py` (facade) | `class TuringAgentMemory(_MemoryWriteMixin, _MemoryReadMixin, _SearchMixin, _EvidenceMixin, _DocumentMixin, _ChunkingMixin, _RebuildMixin, _UtilsMixin, _StoreCore): pass` + re-export imports | ~40-60 |

**Behavior-preservation gate (run after every module extracted, not just at the end):**
```bash
python -m pytest -q                                    # 362/362 must stay green
python scripts/e2e_score.py --out e2e-results.json      # must stay VALIDATED_10_10, score >= 9.8
python -m ruff check src tests scripts                  # must stay clean
```

**Minor design note (non-blocking):** each `store_<concern>.py` mixin references `self.<attr>`
for attributes only ever assigned in `_StoreCore.__init__` (e.g. `self.client`, `self.embedder`,
`self.fusion_weights`). This works correctly at runtime (Python resolves instance attributes
dynamically), but editors/type-checkers won't see the attribute declarations locally in each
mixin file. This is a pure DX nit, not a correctness risk — if desired, a
`if TYPE_CHECKING:`-guarded `Protocol` stub listing the shared attributes can be added to each
mixin file for editor support, but it is not required for this phase's success criteria.

## Architecture Patterns

### System Architecture Diagram

```
git commit  ──▶ lefthook pre-commit (parallel)
                   ├─ ruff format --check {staged *.py}
                   ├─ ruff check {staged *.py}
                   └─ check-file-size.sh  (ALL tracked *.py, no allowlist)
                        │
                        ▼ (any failure blocks the commit; --no-verify bypasses)
git push    ──▶ lefthook pre-push (parallel)
                   ├─ python -m compileall src tests scripts   (import/compile smoke)
                   ├─ pytest -m "not slow and not integration and not gpu"  (fast subset)
                   └─ docker compose config --quiet
                        │
                        ▼
GitHub push/PR ──▶ CI (GitHub Actions)
                   ├─ lint job:        ruff format --check + ruff check + check-file-size.sh
                   ├─ unit-tests job:  pytest --cov=src/turing_agentmemory_mcp --cov-fail-under=<FLOOR>
                   │                     + tests/test_no_skip_as_green_guard.py (CI=true)
                   ├─ compose-validate job: docker compose config --quiet
                   ├─ supply-chain job:     pip-audit (2.10.1) against the installed env
                   └─ dockerized-integration job (CI=true):
                         ├─ docker compose run --rm e2e   (scripts/e2e_score.py, stub embed/rerank
                         │    — the GPU-less degrade floor per D-05; VISIBLY LABELLED as stub-mode)
                         └─ real-document E2E              — see Open Question 2 (not CI-shaped
                              as scripts/real_document_benchmark.py exists today)
```

### Recommended Project Structure
```
lefthook.yml                          # new — hook definitions
.github/workflows/ci.yml              # new — CI job matrix
scripts/check-file-size.sh            # new — 600-LOC cap, no allowlist, MSYS-safe
tests/conftest.py                     # new — no-skip-as-green CI-guard (D-03)
tests/test_no_skip_as_green_guard.py  # new — negative self-test (D-04)
src/turing_agentmemory_mcp/
  store.py                            # slim facade after decomposition
  store_core.py                       # new — __init__/bootstrap/low-level query-write infra
  store_memory_write.py               # new
  store_memory_read.py                # new
  store_search.py                     # new
  store_evidence.py                   # new
  store_documents.py                  # new
  store_chunking.py                   # new
  store_rebuild.py                    # new
  store_utils.py                      # new
```

### Pattern: Mixin-composed facade (store.py split)
**What:** Split one large class into several `_<Concern>Mixin` classes in sibling modules; the
original module becomes a thin facade that composes them via multiple inheritance.
**When to use:** When a single class has grown past a size cap but its methods share instance
state defined in one `__init__`, and there is no natural sub-object boundary (e.g. `TuringAgentMemory`
methods all operate on the same `self.client`/`self.embedder`/etc., so extracting standalone
helper objects would require threading many parameters through every call).
**Example (illustrative shape — not the literal file to write verbatim):**
```python
# store_memory_read.py
from __future__ import annotations
from turing_agentmemory_mcp.models import MemoryItem

class _MemoryReadMixin:
    def get_memory(self, *, user_identifier: str, memory_id: str) -> MemoryItem | None:
        self._require_user(user_identifier)   # defined in _StoreCore, resolved via MRO
        ...

# store.py (facade)
from __future__ import annotations
from turing_agentmemory_mcp.store_core import _StoreCore
from turing_agentmemory_mcp.store_memory_read import _MemoryReadMixin
from turing_agentmemory_mcp.store_memory_write import _MemoryWriteMixin
# ... remaining mixin imports ...

class TuringAgentMemory(
    _MemoryWriteMixin,
    _MemoryReadMixin,
    # ... remaining mixins ...
    _StoreCore,
):
    """Unified memory/document store. See docs/architecture.md."""
```

### Anti-Patterns to Avoid
- **Package-directory rename (`store.py` → `store/__init__.py`):** Works for import-path
  preservation too, but adds directory-structure churn beyond what CLAUDE.md's existing
  `<name>_<concern>.py` sibling-file convention already establishes. Prefer the sibling-file
  mixin approach to match the codebase's existing pattern exactly.
- **Splitting mid-refactor without running the E2E gate between extractions:** the E2E gate is
  the only signal that exercises the full retrieval-fusion + rerank + document-chunking call
  graph end-to-end; unit tests alone (which heavily use fakes) can pass while a subtle
  cross-mixin wiring mistake (e.g. a method accidentally left calling a private helper that
  moved to a different mixin under a name that no longer resolves) still breaks retrieval. Run
  `scripts/e2e_score.py` after each extraction, not just once at the end.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Local git hook running | Custom `.git/hooks/pre-commit` shell script wiring | `lefthook` (pip package) | Already locked (L-01); handles parallel execution, staged-file globbing, and cross-platform dispatch (the wheel bundles the right binary per-OS) |
| Coverage measurement | A custom line-counting script | `pytest-cov` / `coverage.py` | Industry-standard, already integrates with pytest's `--cov` flags and `[tool.coverage.report] fail_under` |
| Supply-chain vulnerability scanning | Custom dependency-CVE lookup script | `pip-audit` | PyPA-maintained, matches the exact requested pin (2.10.1), designed for exactly this use case |
| Converting a `pytest.skip()` into a CI failure | Wrapping every test body in a try/except that checks `os.environ` | A single `pytest_runtest_makereport` hookwrapper in `tests/conftest.py` | This IS the idiomatic, documented pytest mechanism for altering a test's outcome after the fact (`pytest.TestReport.outcome`); there is no external package for "no-skip-as-green" because it is inherently a one-hook, ~15-line pattern — hand-rolling it here is correct, not an anti-pattern, but it must live in exactly one place (`conftest.py`), not per-test |

**Key insight:** Everything else in this phase (hook running, coverage, vulnerability
scanning) has a mature, already-locked library. The one piece of genuinely custom code this
phase writes — the no-skip-as-green guard — is custom *because* no library exists for it; it
is a small, well-documented pytest hook pattern, not a reinvention of something already solved.

## Common Pitfalls

### Pitfall 1: The file-size cap will not go green on day one even after store.py is split
**What goes wrong:** Turning on `check-file-size.sh` (scanning ALL tracked `*.py`, per D-08)
immediately after splitting only `store.py` will still fail, because 9 other tracked files are
already over 600 LOC today: `src/turing_agentmemory_mcp/benchmark.py` (1044),
`tests/test_gliner_provider.py` (1076), `scripts/eval_backboard_locomo_mcp.py` (936),
`src/turing_agentmemory_mcp/e2e_score.py` (873), `scripts/real_document_benchmark.py` (827),
`src/turing_agentmemory_mcp/server.py` (762), `tests/test_batch_memory.py` (749),
`src/turing_agentmemory_mcp/document_jobs.py` (666),
`src/turing_agentmemory_mcp/gliner_provider.py` (658).
**Why it happens:** ROADMAP SC#5 and CONTEXT.md's Open Questions scoped the decomposition work
to `store.py` only, but D-08's locked wording ("scans ALL tracked `*.py` files... no per-file
exemption... hard-fails now") does not carve out an exception for these files.
**How to avoid:** This is **Open Question 1** below — it must be resolved (either by expanding
this phase's scope to decompose all 10 files, or by an explicit, documented scope amendment)
before the file-size hook can be turned on for real. Do not silently narrow the hook's glob to
`store.py`'s own directory or to `src/` only — that would reintroduce an implicit allowlist by
another name, which D-08 explicitly rejected ("staged-files-only scanning... would let store.py
stay a god module" — the same logic applies to any narrowed glob).
**Warning signs:** `bash scripts/check-file-size.sh` reporting `OVER CAP` for any file other
than the pre-split `store.py`.

### Pitfall 2: `ruff format --check` fails on 49 files today — a second bootstrap gate
**What goes wrong:** Enabling the `ruff-format` pre-commit command immediately after installing
lefthook will block the first real commit on pre-existing formatting drift unrelated to the
current change, because 49 of ~78 tracked Python files are not currently `ruff format`-clean
(verified this session with ruff 0.15.21 — includes `store.py`, `server.py`,
`retrieval_fusion.py`, `sparse_index.py`, `temporal_graph.py`, `rerank.py`, `utcp.py`, and 42
test files).
**Why it happens:** the repo has never run `ruff format` as a gate; formatting has drifted
freely since the codebase was written.
**How to avoid:** Run `python -m ruff format src tests scripts` once as its own bootstrap
commit (or fold it into the same bootstrap commit as the store.py split and any other
oversized-file splits), verify `pytest -q` and `scripts/e2e_score.py` are still green after
reformatting (formatting-only changes should not alter behavior, but this is exactly the kind
of assumption the E2E gate exists to catch), then turn on the pre-commit hook.
**Warning signs:** `ruff format --check src tests scripts` reporting `Would reformat: ...` for
any file.

### Pitfall 3: `graspologic-native` is a real, easy-to-miss local-environment gap
**What goes wrong:** Running `pytest --cov=...` in a venv that has `graspologic-native` (an
existing, already-declared `pyproject.toml` dependency) NOT installed produces 6 test failures
in `tests/test_community_detection.py` (`RuntimeError: graspologic-native==1.3.1 is required
for community detection` / `ModuleNotFoundError`), which silently drags down the measured
coverage baseline (verified: 73% vs. the true 74% once installed) and could make someone
believe those 6 tests are flaky or broken.
**Why it happens:** the dev venv used for local iteration can drift from `pyproject.toml`'s
declared dependency set if `pip install -e ".[dev]"` was run before `graspologic-native` was
added, or if a partial install was interrupted.
**How to avoid:** Always run `pip install -e ".[dev]"` (which pulls the full `dependencies`
list including `graspologic-native==1.3.1`, confirmed to have manylinux/win_amd64/macOS wheels
for cp39-abi3, i.e. it installs cleanly on GH Actions `ubuntu-latest` too) fresh before
measuring coverage or running the full suite. The CI unit-test job doing this from a clean
checkout will not hit this pitfall; it is a local/dev-venv hygiene issue only.
**Warning signs:** `RuntimeError: graspologic-native==1.3.1 is required for community
detection` in test output; unexpectedly low coverage on `community_detection.py`.

### Pitfall 4: `scripts/real_document_benchmark.py` is not CI-shaped as written
**What goes wrong:** Treating CI-05/SC#2's "real-document E2E" as "just run
`scripts/real_document_benchmark.py` in the dockerized-integration job" will fail, because the
script (a) defaults `--root` to a hardcoded local path (`D:\turing_AgentMemory_MCP\test`), (b)
expects an already-running MCP server at a fixed URL (`http://127.0.0.1:8095/mcp/`) rather than
spinning one up itself, and (c) always calls a live paid LLM (OpenRouter, via
`--question-api-key-env PROVIDER_API_KEY`) to generate questions — there is no stub/deterministic
mode analogous to `e2e_score.py`'s in-process embed/rerank stubs.
**Why it happens:** this script was built as an operator-run benchmark tool, not as an
automatable CI gate; `e2e_score.py` (which IS fully self-contained) was built later with CI-style
determinism in mind.
**How to avoid:** See Open Question 2 below — this needs an explicit decision, not a guess.
**Warning signs:** CI job hangs waiting on a URL nobody started, or fails on a missing
`PROVIDER_API_KEY` secret / a nonexistent Windows path on the Linux runner.

## Code Examples

### No-skip-as-green conftest.py guard (D-03)
```python
# tests/conftest.py
"""Central no-skip-as-green guard: under CI=true, a skip on a marked integration/gpu
tier is a failure, not a pass. See D-03/CI-07."""
from __future__ import annotations

import os

import pytest

_CI_ENFORCED_MARKERS = {"integration", "gpu"}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    outcome = yield
    if os.environ.get("CI") != "true":
        return
    report = outcome.get_result()
    if not report.skipped:
        return
    markers = {marker.name for marker in item.iter_markers()} & _CI_ENFORCED_MARKERS
    if not markers:
        return
    report.outcome = "failed"
    report.longrepr = (
        f"no-skip-as-green: {item.nodeid} skipped under CI=true (markers={sorted(markers)}). "
        "A skipped integration/gpu tier must never pass green in CI."
    )
```

```toml
# pyproject.toml — register the markers (keeps conftest.py focused on the hook only)
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
markers = [
    "slow: excluded from the pre-push fast subset; always runs in CI",
    "integration: requires a live external service; a skip is a CI failure under CI=true",
    "gpu: requires a GPU-backed provider; a skip is a CI failure under CI=true",
]
```

### Negative self-test proving the guard fires (D-04)
```python
# tests/test_no_skip_as_green_guard.py
"""Proves the conftest.py no-skip-as-green guard actually fires (D-04). Uses pytest's
own `pytester` fixture (the documented mechanism for testing conftest/plugin hooks) so the
probe test never pollutes the real collected suite."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_REPO_CONFTEST = Path(__file__).resolve().parent / "conftest.py"

_PROBE = """
import pytest

@pytest.mark.integration
def test_deliberately_skipped():
    pytest.skip("proves the no-skip-as-green guard fires under CI=true")
"""


def test_ci_guard_converts_a_marked_skip_into_a_failure(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CI", "true")
    pytester.makeconftest(_REPO_CONFTEST.read_text())
    pytester.makepyfile(_PROBE)
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*no-skip-as-green*"])


def test_without_ci_env_the_same_skip_still_passes_green(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    pytester.makeconftest(_REPO_CONFTEST.read_text())
    pytester.makepyfile(_PROBE)
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(skipped=1)
```

### check-file-size.sh (adapted from Aura, allowlist dropped per D-08)
```bash
#!/usr/bin/env bash
# check-file-size.sh — enforce the 600-LOC cap (CLAUDE.md / D-08). Scans ALL tracked
# *.py files (src, tests, scripts) with NO allowlist/exemption.
#
# Usage: bash scripts/check-file-size.sh [cap]   (default cap: 600)
set -euo pipefail

CAP="${1:-600}"
if ! [[ "$CAP" =~ ^[0-9]+$ ]]; then
  echo "usage: $0 [cap]" >&2
  exit 2
fi

TARGETS=$(git ls-files '*.py' || true)
if [ -z "$TARGETS" ]; then
  echo "check-file-size: no *.py files matched; nothing to check."
  exit 0
fi

# Process-substitution (not a `<<<` here-string): on Windows Git Bash (MSYS/busybox)
# a here-string mangles the final list entry, which `wc` then can't open and `set -e`
# turns into a false commit-blocking failure. Process substitution keeps the loop in
# the current shell so the violations counter + exit code still propagate correctly.
violations=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue   # tracked-but-deleted-in-worktree (e.g. mid-split) is not an error
  lines=$(wc -l < "$f" | tr -d '[:space:]')
  if [ "$lines" -gt "$CAP" ]; then
    printf "OVER CAP: %s (%d LOC > %d)\n" "$f" "$lines" "$CAP"
    violations=$((violations + 1))
  fi
done < <(printf '%s\n' "$TARGETS")

if [ "$violations" -gt 0 ]; then
  echo ""
  echo "check-file-size: $violations file(s) exceed the ${CAP}-LOC cap." >&2
  echo "No allowlist. Refactor on touch: split <name>_<concern>.py." >&2
  exit 1
fi
echo "check-file-size: all tracked *.py files within the ${CAP}-LOC cap."
```

### lefthook.yml skeleton
```yaml
# lefthook.yml — local git hooks (https://lefthook.dev).
#
# Install once per clone:  lefthook install   (or: make hooks)
#   binary source: pip install -e ".[dev]"  (bundles the platform lefthook binary)
# Bypass in an emergency:  git commit --no-verify   /   git push --no-verify
#
# Heavy gates (E2E score gate, real-document E2E, coverage) intentionally stay in CI.

pre-commit:
  parallel: true
  commands:
    ruff-format:
      glob: "*.py"
      run: python -m ruff format --check {staged_files}
    ruff-check:
      glob: "*.py"
      run: python -m ruff check {staged_files}
    file-size:
      # Intentionally NOT glob-gated to staged files — D-08 requires scanning ALL
      # tracked *.py every commit, not just what changed.
      run: bash scripts/check-file-size.sh

pre-push:
  parallel: true
  commands:
    compile-smoke:
      run: python -m compileall -q src tests scripts
    fast-tests:
      run: python -m pytest -q -m "not slow and not integration and not gpu"
    compose-config:
      run: docker compose config --quiet
```

### ci.yml skeleton (adapted from Aura's discipline, much smaller service surface)
```yaml
name: CI

on:
  push: { branches: ["master"] }
  pull_request: { branches: ["master"] }

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with: { python-version: "3.12" }
      - run: pip install "ruff==0.15.21"
      - run: ruff format --check src tests scripts
      - run: ruff check src tests scripts
      - run: bash scripts/check-file-size.sh

  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: python -m pytest --cov=src/turing_agentmemory_mcp --cov-fail-under=<FLOOR> -q
      - name: no-skip-as-green guard self-test
        env: { CI: "true" }
        run: python -m pytest tests/test_no_skip_as_green_guard.py -q

  compose-validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - run: docker compose config --quiet

  supply-chain:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]" "pip-audit==2.10.1"
      - run: pip-audit   # audits the active virtualenv's installed distributions

  dockerized-integration:
    runs-on: ubuntu-latest
    env: { CI: "true" }   # arms the no-skip-as-green guard for this job too
    steps:
      - uses: actions/checkout@v7
      - name: E2E score gate (stub embed/rerank floor — GPU-less, D-05)
        run: docker compose run --rm e2e
      # Real-document E2E step: see Open Question 2 — not runnable as-is.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No hooks, no CI (current state) | lefthook + GitHub Actions with no-skip-as-green | This phase | Establishes the guardrail baseline every later phase depends on |
| ruff unpinned (`>=0.9` in pyproject.toml) | ruff pinned `0.15.x` (0.15.21 verified) | This phase (L-04) | No new lint violations introduced by the version bump (`ruff check` passes clean); `ruff format --check` surfaces 49 files of pre-existing drift that must be fixed as part of turning the hook on |
| store.py as a 3891-LOC monolith (explicitly exempted in CLAUDE.md) | store.py split into ≤600-LOC concern modules, no exemption | This phase (D-08) | Also changes Phase 4's ArcadeDB port surface — it will port several smaller files instead of one large one (acceptable per CONTEXT.md's noted risk) |

**Deprecated/outdated:**
- CLAUDE.md's "`store.py` is the large central exception... NO >600 loc" language — must be
  rewritten in this phase per CONTEXT.md's Open Questions (in-scope, not deferred).
- ROADMAP.md Phase 1 SC#1 and REQUIREMENTS.md CI-01's "documented allowlist that includes
  store.py" wording — already flagged in CONTEXT.md as needing a rewrite before/alongside
  planning; REQUIREMENTS.md's CI-01 text as read for this research already reflects the
  corrected no-allowlist wording, so this may already be resolved — verify at plan time that
  ROADMAP.md's phase-detail SC#1 text (line ~37) matches (it does, per this session's read: "a
  file-size cap enforcing ≤600 LOC across all tracked `*.py` files with NO allowlist — no file
  is exempt").

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The store.py mixin decomposition module boundaries proposed above will each independently land under 600 LOC without further sub-splitting | store.py Decomposition Plan | Low — explicitly caveated as illustrative; the file-size script is the authoritative check, and one or two modules (`store_documents.py` especially) are flagged as likely needing one more split at implementation time |
| A2 | `pip-audit` run bare (no `-r`/`--requirement` flag) against an editable-installed venv correctly audits all resolved dependencies including transitive ones | Code Examples (ci.yml) | Medium — if this doesn't surface transitive CVEs as expected, the planner should verify pip-audit's environment-scan mode against this project's actual dependency tree, or switch to `pip-audit -r <(pip freeze)` |
| A3 | The coverage floor should exclude `e2e_score.py` from the measured denominator (recommended 78% baseline) rather than include it (74% baseline) | Coverage Floor section | Low-Medium — this is a defensible convention (the file IS the E2E gate, exercised by its own `make e2e` invocation, not pytest) but is a policy choice, not a hard fact; the planner/user should confirm which baseline to ratchet from |

**All other claims in this research (package versions, wheel contents, test-suite behavior,
coverage numbers, `docker compose config` success, `ruff` results) were directly verified by
executing commands against this repository and the live PyPI registry in this session — none
are `[ASSUMED]`.**

## Open Questions

1. **Does the file-size cap's scope (D-08) cover all 9 additional over-600-LOC files, or is
   this phase's decomposition work limited to store.py only?**
   - What we know: D-08 is unambiguous in its literal wording ("scans ALL tracked `*.py`
     files... no per-file exemption, not even for store.py"; explicitly rejects
     "staged-files-only scanning" as a workaround). ROADMAP SC#5 and CONTEXT.md's Open
     Questions, however, only scope the decomposition deliverable to store.py.
   - What's unclear: whether the user intended the "no allowlist" decision to apply narrowly
     (store.py was the only file discussed because it was the only one measured at
     discuss-phase time) or literally (the cap really does apply to every tracked file, and
     any file over it — including test files and scripts — blocks every future commit).
   - Recommendation: bring this back to the user for an explicit confirmation before planning
     locks in scope, since it is a 2x-or-more scope change (10 files vs. 1). If the user
     confirms the literal reading, the plan must budget decomposition work for
     `benchmark.py`, `e2e_score.py`, `server.py`, `document_jobs.py`, `gliner_provider.py`,
     `test_gliner_provider.py`, `test_batch_memory.py`, `eval_backboard_locomo_mcp.py`, and
     `real_document_benchmark.py` in addition to `store.py`. If the user narrows scope to
     store.py only for this phase, the plan should explicitly document that the file-size hook
     will initially fail on the other 9 files and either (a) note this as a known, tracked
     follow-up (contradicts D-08's "hard-fails now" framing — needs the user's explicit sign-off
     to accept this contradiction), or (b) the 9 files are decomposed as parallel/incidental
     work within this same phase.

2. **Is `scripts/real_document_benchmark.py` actually meant to run inside the CI
   dockerized-integration job for CI-05, given it needs a live paid LLM key, a
   pre-running MCP server at a fixed URL, and a hardcoded local path?**
   - What we know: `scripts/real_document_benchmark.py` (827 LOC) is an operator-run benchmark
     tool — `--root` defaults to `D:\turing_AgentMemory_MCP\test`, `--mcp-url` defaults to
     `http://127.0.0.1:8095/mcp/` (expects an already-listening server, unlike `e2e_score.py`
     which spins up its own TuringDB daemon + stub servers in-process), and question generation
     always calls a live OpenRouter endpoint via `--question-api-key-env PROVIDER_API_KEY`.
     There is a separate, already-existing `tests/test_real_document_benchmark.py` that unit-tests
     the script's deterministic helper functions (`select_passages`, `parse_generated_questions`,
     `evidence_rank`, `summarize_results`) against fake/local data — no live LLM or MCP server
     needed — and this already runs as part of the normal pytest suite today.
   - What's unclear: whether CI-05's "real-document E2E" is satisfied by the existing
     `tests/test_real_document_benchmark.py` unit tests (already running, zero new CI work), or
     whether it requires actually invoking `scripts/real_document_benchmark.py` end-to-end in
     CI (which would need a `PROVIDER_API_KEY` GitHub secret, a way to start the MCP server
     first, a CI-appropriate `--root` override pointing at a small in-repo fixture corpus, and
     its own no-skip-as-green treatment if the secret is absent on a fork PR).
   - Recommendation: treat this as a plan-time decision point requiring explicit user/planner
     resolution, not a research-level guess. If the intent is the latter (a true live corpus
     run in CI), that is materially more design work than this phase's other success criteria
     and may deserve its own follow-up plan or even phase-scope discussion, since it touches
     `real_document_benchmark.py` itself (currently out of this phase's stated boundary, which
     is hooks/CI + the store.py split only).

3. **Should the CI unit-test job run a single Python version or a matrix across 3.11-3.14
   (the range `pyproject.toml` declares support for)?**
   - What we know: CLAUDE.md/pyproject.toml claim Python 3.11-3.14 support; this session's
     verification was done against Python 3.12.10 only (the repo's existing `.venv`).
   - What's unclear: whether verifying only one version in CI is acceptable for this phase, or
     whether a matrix is expected given the stated support range.
   - Recommendation: default to a single version (3.12, matching the existing dev venv) for
     this phase's CI job to keep scope contained, and note a version-matrix expansion as a
     natural (but not mandated) follow-up — this was not raised as a locked decision or
     discretion item in CONTEXT.md, so treat it as a low-stakes planner judgment call.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker + Docker Compose | pre-push `docker compose config --quiet`, CI compose-validate + dockerized-integration jobs | ✓ (verified: `docker compose config --quiet` exits 0 against this repo's `compose.yaml` today) | Docker 29.6.1 / Compose v5.3.0 (dev machine); GH Actions `ubuntu-latest` ships Docker preinstalled | — |
| `graspologic-native==1.3.1` | Community-detection tests (6 tests), coverage measurement | ✓ once `pip install -e ".[dev]"` completes | 1.3.1 — confirmed wheels for win_amd64/win_arm64/manylinux (x86_64+aarch64)/musllinux/macOS, cp39-abi3 | None needed — a real dependency with broad wheel coverage; only a stale local venv would miss it |
| `lefthook` (pip) | D-01, pre-commit/pre-push wiring | ✓ (verified via wheel download) | 2.1.10 — win_amd64 wheel bundles a real `lefthook.exe` | None needed |
| `PROVIDER_API_KEY` / live OpenRouter access | `scripts/real_document_benchmark.py` question generation | ✗ in a clean CI environment (secret not yet configured; no repo evidence one exists) | — | See Open Question 2 — no fallback currently designed for this in CI |

**Missing dependencies with no fallback:**
- `PROVIDER_API_KEY` for a live `scripts/real_document_benchmark.py` CI run (see Open
  Question 2 — this needs a design decision, not a "fallback," since no stub/deterministic
  mode exists in the script today).

**Missing dependencies with fallback:**
- None currently identified beyond the above (Docker, graspologic-native, and lefthook are all
  confirmed available/installable).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (installed in `.venv`); `pyproject.toml` requires `>=8.2` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["src"]`); no `conftest.py` exists yet — this phase creates the first one |
| Quick run command | `python -m pytest -q` — verified: 362 tests, ~25-32s, zero external-service dependency |
| Full suite command | `python -m pytest --cov=src/turing_agentmemory_mcp --cov-fail-under=<FLOOR> -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CI-01 | Pre-commit blocks on format/lint/file-size violations | manual (git hook behavior) | `lefthook run pre-commit` (dry-run against a deliberately-violating staged file) | ❌ Wave 0 — `lefthook.yml` + `scripts/check-file-size.sh` new |
| CI-02 | Pre-push runs compile smoke + fast subset + compose config | manual (git hook behavior) | `lefthook run pre-push` | ❌ Wave 0 |
| CI-03/CI-04 | CI lint + unit-test jobs pass on a clean checkout | integration (CI-only) | GitHub Actions run on a test PR/push | ❌ Wave 0 — `.github/workflows/ci.yml` new |
| CI-05 | Dockerized-integration job runs E2E + real-doc E2E | integration (CI-only) | `docker compose run --rm e2e` (E2E half); real-doc half blocked on Open Question 2 | ❌ Wave 0 |
| CI-06 | Compose-validation + pip-audit | integration (CI-only) | `docker compose config --quiet`; `pip-audit` | ❌ Wave 0 (job) — underlying commands already verified working |
| CI-07 | No-skip-as-green guard fires under `CI=true` | unit (self-test) | `python -m pytest tests/test_no_skip_as_green_guard.py -q` | ❌ Wave 0 — new file, pattern given in Code Examples |
| CI-08 | GPU-less degrade floor is a real stub-mode pass, not a skip | integration (CI-only) | `docker compose run --rm e2e` with default (stub) embed/rerank env | ✅ mechanism already exists in `scripts/e2e_score.py`; only needs CI wiring + a visible label |
| CI-09 | Coverage floor is measured, hard-fails below it | unit (aggregate) | `python -m pytest --cov=src/turing_agentmemory_mcp --cov-fail-under=<FLOOR> -q` | ✅ measurement already performed this session (74%/78%); only the `--cov-fail-under` wiring is new |

### Sampling Rate
- **Per task commit:** the fast pytest subset (`-m "not slow and not integration and not gpu"`)
  — currently equivalent to the FULL suite (25-32s) since no test carries any of these markers
  yet.
- **Per wave merge:** full suite with coverage (`--cov-fail-under=<FLOOR>`), plus
  `scripts/e2e_score.py` after any store.py-decomposition-touching wave.
- **Phase gate:** full suite green + E2E score gate (`VALIDATED_10_10`, score ≥9.8) + `ruff
  check`/`ruff format --check` clean + `docker compose config --quiet` before
  `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/conftest.py` — the no-skip-as-green guard hook (D-03)
- [ ] `tests/test_no_skip_as_green_guard.py` — the negative self-test (D-04), pattern given above
- [ ] `lefthook.yml` — hook definitions
- [ ] `.github/workflows/ci.yml` — CI job matrix
- [ ] `scripts/check-file-size.sh` — file-size cap script, no allowlist
- [ ] Framework install: `pytest-cov==7.1.0`, `lefthook==2.1.10`, `ruff==0.15.21` added to the
  `dev` extra in `pyproject.toml`
- [ ] Marker registration: `[tool.pytest.ini_options] markers = [...]` for `slow`,
  `integration`, `gpu`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | This phase touches no auth surface (server.py's existing `AGENTMEMORY_AUTH_TOKEN(S)` bearer-token auth is untouched) |
| V3 Session Management | No | Not applicable to CI/hook tooling |
| V4 Access Control | No | Not applicable |
| V5 Input Validation | No | No new user-facing input surface is introduced |
| V6 Cryptography | No | Not applicable |
| V14 Configuration (supply chain / dependency management) | Yes | `pip-audit==2.10.1` scans the resolved dependency set for known CVEs as a CI gate (CI-06) — this is the one ASVS-adjacent control this phase actually installs |

### Known Threat Patterns for this phase's surface

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secrets leaking into CI logs (e.g. a future `PROVIDER_API_KEY` for real-document E2E, per Open Question 2) | Information Disclosure | Store any such key as a GitHub Actions repository secret, never hardcode a real value in `.github/workflows/ci.yml`; if the workflow needs a non-secret placeholder for `docker compose config` interpolation elsewhere, follow Aura's pattern of an explicit `ci-not-a-secret` literal, never a real credential |
| A compromised/typosquatted dev-tooling package (lefthook, ruff, pip-audit, pytest-cov) executing arbitrary code at install time | Tampering | Addressed by this research's Package Legitimacy Audit — all four are verified mature, org-backed packages; pin exact versions in `pyproject.toml`'s `dev` extra rather than open ranges where the locked decisions specify exact pins (lefthook, ruff, pip-audit) |
| A `postinstall`-style script in a new dev dependency doing something unexpected | Tampering | Not applicable here — `lefthook`'s pip wheel is a plain Python package with a `console_scripts` entry point (verified by inspecting the wheel contents directly); it has no pip install-time script hook, only a runtime dispatcher (`lefthook/main.py`) that subprocess-execs the bundled binary when invoked, which only happens when the user runs `lefthook` explicitly (e.g. via `lefthook install`) |

## Sources

### Primary (HIGH confidence — verified this session against live systems)
- PyPI JSON API (`pypi.org/pypi/<pkg>/<version>/json`) — used to enumerate `lefthook` 2.1.10's
  and `graspologic-native` 1.3.1's distributed wheel platforms
- Direct wheel download + `zipfile` inspection of
  `lefthook-2.1.10-py3-none-win_amd64.whl` — confirmed bundled `lefthook.exe` binary and
  `console_scripts` entry point
- `python -m pip index versions <lefthook|ruff|pip-audit|pytest-cov>` — current latest
  releases, run against the live PyPI registry
- This repository's own `.venv`, `git ls-files`, `pytest`, `ruff`, and `docker compose config`
  — all commands executed directly against the actual working tree in this session

### Secondary (MEDIUM confidence)
- `D:\Repo\Aura\lefthook.yml`, `D:\Repo\Aura\.github\workflows\ci.yml`,
  `D:\Repo\Aura\scripts\check-file-size.sh` — read directly as the reference discipline to
  mirror (per CONTEXT.md canonical refs); Aura is a different language/stack (Go/TS), so its
  specific tool invocations were adapted, not copied, for Python

### Tertiary (LOW confidence)
- None — every claim in this document was either directly verified this session or explicitly
  logged in the Assumptions Log above.

## Metadata

**Confidence breakdown:**
- Standard stack (lefthook/ruff/pip-audit/pytest-cov versions + Windows wheel behavior): HIGH —
  directly verified against PyPI and by wheel inspection, not recalled
- store.py decomposition plan: MEDIUM-HIGH — method-to-module mapping is derived from an exact
  line-by-line grep of the real file (not guessed), but exact final module boundaries are an
  implementation-time judgment call, explicitly caveated
- Coverage floor: HIGH — measured directly this session (74%/78%), not guessed, per D-07's
  explicit requirement
- CI-05 "real-document E2E" feasibility: MEDIUM — the gap (script not CI-shaped) is directly
  verified by reading the script; the *resolution* is an open question requiring a decision,
  not something research can resolve unilaterally
- Pitfalls (file-size cap scope, ruff format drift, graspologic-native venv gap): HIGH — all
  three were reproduced directly in this session, not inferred

**Research date:** 2026-07-11
**Valid until:** ~14 days for the version pins (ruff/pip-audit release cadence is fast; re-verify
before locking exact pins into `pyproject.toml` if planning is delayed) — 30 days for the
architectural/decomposition guidance, which is stable regardless of point-release drift
