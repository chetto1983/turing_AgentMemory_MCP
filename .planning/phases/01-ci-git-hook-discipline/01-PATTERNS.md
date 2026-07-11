# Phase 1: CI + Git-Hook Discipline - Pattern Map

**Mapped:** 2026-07-11
**Files analyzed:** ~24 (5 new infra files + 10 over-cap decomposition targets + 3 modified config/docs + N split-output siblings)
**Analogs found:** 24 / 24 (every file has at least a role-match analog; the 5 new infra files have exact analogs in the sibling Aura repo)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `lefthook.yml` | config | event-driven (git hook trigger) | `D:\Repo\Aura\lefthook.yml` | exact (cross-repo, discipline not tooling) |
| `.github/workflows/ci.yml` | config | event-driven (CI trigger) | `D:\Repo\Aura\.github\workflows\ci.yml` | exact (cross-repo, discipline not tooling) |
| `scripts/check-file-size.sh` | utility | batch (scan + fail) | `D:\Repo\Aura\scripts\check-file-size.sh` | exact (adapt glob, drop allowlist) |
| `tests/conftest.py` | test (fixture/hook) | event-driven (pytest hookwrapper) | none in-repo (net-new); RESEARCH.md has the finished hookwrapper | no analog — use RESEARCH.md code verbatim |
| `tests/test_no_skip_as_green_guard.py` | test | event-driven (pytester subprocess) | none in-repo (net-new); RESEARCH.md has the finished pytester probe | no analog — use RESEARCH.md code verbatim |
| `src/turing_agentmemory_mcp/store.py` (facade, post-split) | service (facade) | CRUD | `src/turing_agentmemory_mcp/entity_extraction.py` (Protocol + factory shape) for module conventions; the split itself has no prior in-repo analog (first mixin decomposition in this codebase) | role-match (module-header convention only) |
| `store_core.py` | service (mixin) | CRUD (init/query/write infra) | `src/turing_agentmemory_mcp/document_jobs.py` (dataclass + `@contextmanager` sqlite session pattern) for low-level infra shape | role-match |
| `store_memory_write.py` | service (mixin) | CRUD (writes) | `src/turing_agentmemory_mcp/governance.py` (`audit_event`, redaction call shape used inside writes) | role-match |
| `store_memory_read.py` | service (mixin) | CRUD (reads) | `src/turing_agentmemory_mcp/temporal_graph.py` (filter/normalize dataclass helpers) | role-match |
| `store_search.py` | service (mixin) | request-response (rerank pipeline) | `src/turing_agentmemory_mcp/rerank.py` (`apply_rerank_guard`, `assemble_rerank_document`) | role-match |
| `store_evidence.py` | service (mixin) | transform (multi-signal evidence collection) | `src/turing_agentmemory_mcp/retrieval_fusion.py` (weighted RRF fusion over channels) | role-match |
| `store_documents.py` | service (mixin) | CRUD + file-I/O adjacent (document/chunk lifecycle) | `src/turing_agentmemory_mcp/document_processing.py` (`ConvertedDocument` dataclass + conversion pipeline shape) | role-match |
| `store_chunking.py` | utility | transform | `src/turing_agentmemory_mcp/hybrid.py` (small pure-function + regex-constant module shape) | role-match |
| `store_rebuild.py` | service (mixin) | batch (projection rebuild) | `src/turing_agentmemory_mcp/community_detection.py` (`NativeLeidenDetector`, incremental rebuild entrypoints) | role-match |
| `store_utils.py` | utility | transform | `src/turing_agentmemory_mcp/ids.py` (pure ID/value helper functions, no class state) | role-match |
| `src/turing_agentmemory_mcp/benchmark.py` (split) | utility/CLI | batch | sibling split pattern: `hybrid.py`/`ids.py` (pure-function module) + `document_processing.py` (pipeline-stage module) as concern boundaries | role-match |
| `src/turing_agentmemory_mcp/e2e_score.py` (split) | test/CLI (deterministic gate) | request-response + batch | same sibling-module convention; scenario data vs. runner vs. stub-server concerns split the way `gliner_provider.py` separates HTTP-server plumbing from extraction logic | role-match |
| `src/turing_agentmemory_mcp/server.py` (split) | controller (MCP tool boundary) | request-response | itself (762 LOC) — split by tool-group concern (`server_memory_tools.py`, `server_document_tools.py`, `server_admin_tools.py` etc.), same `*_from_env()` factory convention seen in its own imports (lines 1-32 shown below) | exact (self-analog for factory/import convention) |
| `src/turing_agentmemory_mcp/document_jobs.py` (split) | model/service (SQLite job store) | CRUD + file-I/O | itself (666 LOC) — split dataclass/schema from `@contextmanager` session helpers from lease/heartbeat query methods, same convention as `sparse_index.py`'s SQLite FTS5 module shape | role-match |
| `src/turing_agentmemory_mcp/gliner_provider.py` (split) | service (HTTP provider) | request-response (HTTP server) | itself (658 LOC) — split `BaseHTTPRequestHandler` plumbing from extraction/label-schema logic, matching `entity_extraction.py`'s Protocol-vs-HTTP-impl separation | role-match |
| `tests/test_gliner_provider.py` (split) | test | request-response | existing per-module test files in `tests/` (e.g. `tests/test_hybrid_search.py`, one file per concern) — split by test class/fixture group into `test_gliner_provider_extraction.py` / `test_gliner_provider_server.py` | role-match |
| `tests/test_batch_memory.py` (split) | test | CRUD (batch write) | existing `tests/test_*` naming convention — split by scenario group (e.g. `test_batch_memory_write.py` / `test_batch_memory_dedup.py`) | role-match |
| `scripts/eval_backboard_locomo_mcp.py` (split) | utility/CLI (benchmark) | batch | sibling `scripts/eval_locomo_answers.py` (existing smaller eval script in same directory) | role-match |
| `scripts/real_document_benchmark.py` (split) | utility/CLI (benchmark) | batch + request-response (live MCP calls) | sibling `scripts/benchmark.py`-style CLI argument/runner shape already in `scripts/` | role-match |
| `pyproject.toml` (modified) | config | — | itself — existing `[project.optional-dependencies].dev` / `[tool.pytest.ini_options]` blocks (see excerpt below) | exact (edit in place) |
| `Makefile` (modified) | config | — | itself — existing `test`/`e2e`/`docker-e2e`/`lint` targets (13 lines total, shown below) | exact (edit in place) |
| `CLAUDE.md` (modified) | config/docs | — | itself — §"DEEP REFACTOR ON TOUCH" paragraph | exact (edit in place) |

## Pattern Assignments

### `lefthook.yml`

**Analog:** `D:\Repo\Aura\lefthook.yml` (69 lines, full file read)

**Structure to mirror** (parallel commands, glob-gating, comment style explaining bypass/heavy-gates-stay-in-CI):
```yaml
pre-commit:
  parallel: true
  commands:
    gofmt:
      glob: "*.go"
      run: bash scripts/gofmt-staged.sh {staged_files}
      stage_fixed: true
    file-size:
      run: bash scripts/check-file-size.sh
pre-push:
  parallel: true
  commands:
    build:
      run: bash -c 'go build $(bash scripts/go_packages.sh)'
```

Adapt directly to the Python-equivalent skeleton already drafted in RESEARCH.md's "lefthook.yml skeleton" section (ruff-format/ruff-check/file-size at pre-commit; compile-smoke/fast-tests/compose-config at pre-push) — that skeleton already follows this exact Aura structure and comment conventions (install-once note, `--no-verify` bypass note, "heavy gates stay in CI" note at the top). Use it near-verbatim.

**Key convention to preserve:** top-of-file comment block documents (1) install command, (2) bypass command, (3) why heavy gates are NOT here. Aura's `file-size` command is NOT staged-file-gated (`glob`) — it runs against all tracked files unconditionally, matching D-08's "scans ALL tracked files" requirement exactly (Python skeleton in RESEARCH.md already does this correctly).

---

### `.github/workflows/ci.yml`

**Analog:** `D:\Repo\Aura\.github\workflows\ci.yml` (1352 lines — read via Grep for job/step headers only, not the full file)

**Job-list structure** (grep output, lines 3-1220):
```
on: / push: / permissions: / concurrency:
jobs:
  build-and-lint:      (line 36)
  unit-test:            (line 88)
  windows-unit:         (line 110)   -- NOT applicable (CI-10 deferred)
  cache-invariant:      (line 144, CI: "true")
  vulncheck:            (line 179)
  integration-test:     (line 197, CI: "true")
  sqlc-golden: / web-*: (Go/web-specific — NOT applicable)
```

**No-skip-as-green arming convention** (repeated at every integration-tier job, e.g. line 153, 215, 502, 664, 741, 787, 898, 965):
```yaml
    env:
      CI: "true"  # arms the in-script no-skip-as-green guards
```
This is the exact convention to replicate on the Python side: any CI job that must exercise a tier capable of skipping (the dockerized-integration job, and the unit-tests job's `test_no_skip_as_green_guard.py` step) sets `env: { CI: "true" }` with an inline comment naming what it arms. RESEARCH.md's `ci.yml` skeleton (see "Code Examples") already applies this convention correctly at `unit-tests` (guard self-test step) and `dockerized-integration` (whole job). Use that skeleton as the file to write, cross-checked against this Aura structure for the top-of-file `on:`/`permissions:`/`concurrency:` block shape.

**Top block to port verbatim in spirit** (branches/cancel-in-progress/permissions — RESEARCH.md's skeleton already adapts this to `master`):
```yaml
on:
  push: { branches: ["master"] }
  pull_request: { branches: ["master"] }
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

---

### `scripts/check-file-size.sh`

**Analog:** `D:\Repo\Aura\scripts\check-file-size.sh` (66 lines, full file read above)

**Core pattern to port near-verbatim, dropping only the allowlist/exemption globs:**
```bash
set -euo pipefail
CAP="${1:-600}"
TARGETS=$(git ls-files '*.go' '*.ts' '*.tsx' \
  | grep -v -E '^internal/db/sqlc/' \
  | grep -v -E '^third_party/' \
  ... \
  || true)
```
becomes (per D-08, no exemption grep pipeline at all):
```bash
TARGETS=$(git ls-files '*.py' || true)
```

**Process-substitution loop (keep verbatim — this is the load-bearing Windows/Git-Bash fix, documented at lines 40-46 of the Aura original):**
```bash
violations=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue
  lines=$(wc -l < "$f" | tr -d '[:space:]')
  if [ "$lines" -gt "$CAP" ]; then
    printf "OVER CAP: %s (%d LOC > %d)\n" "$f" "$lines" "$CAP"
    violations=$((violations + 1))
  fi
done < <(printf '%s\n' "$TARGETS")
```

**Exit/error-message pattern (adapt wording, keep structure):**
```bash
if [ "$violations" -gt 0 ]; then
  echo ""
  echo "check-file-size: $violations file(s) exceed the ${CAP}-LOC cap." >&2
  echo "Refactor on touch per CLAUDE.md §Behavioral rules: split <name>_<concern>.{go,ts,tsx}." >&2
  exit 1
fi
```
Python-adapted message ("split `<name>_<concern>.py`") is already fully drafted in RESEARCH.md's "check-file-size.sh (adapted from Aura, allowlist dropped per D-08)" code block — write that file verbatim.

---

### `tests/conftest.py` and `tests/test_no_skip_as_green_guard.py`

**No in-repo analog** — this repo has zero `conftest.py` files today (`.planning/codebase/TESTING.md` confirms: "30+ function-based pytest files, no conftest.py yet"). Aura's equivalent is Go `t.Fatal`-based env-armed guards scattered per-integration-test file (not a single central hook — Python's `pytest_runtest_makereport` hookwrapper is a stronger, more centralized mechanism with no direct Go-side structural analog).

**Use RESEARCH.md's fully-drafted code verbatim** (see RESEARCH.md "Code Examples" section):
- `tests/conftest.py`: `pytest_runtest_makereport` hookwrapper, `_CI_ENFORCED_MARKERS = {"integration", "gpu"}`, converts `report.outcome = "failed"` when `CI=true` and a skip carries an enforced marker.
- `tests/test_no_skip_as_green_guard.py`: uses the `pytester` fixture (`pytest_plugins = ["pytester"]`), a `_PROBE` string fixture module, `pytester.makeconftest(_REPO_CONFTEST.read_text())`, `runpytest_subprocess()`, asserts `failed=1` under `CI=true` and `skipped=1` without it.

**Closest structural sibling for test-file conventions** (imports, `from __future__ import annotations`, function-based tests, `monkeypatch` fixture usage): any existing `tests/test_*.py` — e.g. `tests/test_admin_repair.py` — for general style consistency (module docstring optional, no class-based test grouping).

---

### `store.py` decomposition (store_core.py, store_memory_write.py, store_memory_read.py, store_search.py, store_evidence.py, store_documents.py, store_chunking.py, store_rebuild.py, store_utils.py)

**Analog for import-block convention:** `src/turing_agentmemory_mcp/store.py` itself, current header (lines 1-60, already read in full):
```python
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from turingdb import TuringDB

from turing_agentmemory_mcp.community_detection import (...)
from turing_agentmemory_mcp.embeddings import Embedder, OpenAICompatibleEmbedder
from turing_agentmemory_mcp.entity_extraction import (...)
...
```
Each `store_<concern>.py` mixin should import only the sibling-module symbols it actually uses (subset of this block) — do not import `TuringDB`/provider classes into mixins that don't construct them (those stay in `store_core.py`).

**Class shape today** (confirmed via Grep): `class _DocumentChunkGraphUnit` (dataclass, line 89) then `class TuringAgentMemory:` (line 99) — a single flat class, no existing mixin precedent in this codebase. RESEARCH.md's "Pattern: Mixin-composed facade" is the pattern to use; treat it as the authoritative shape (own code example, not a copy of an existing file):
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
# ... remaining mixin imports ...

class TuringAgentMemory(
    _MemoryWriteMixin,
    _MemoryReadMixin,
    # ... remaining mixins ...
    _StoreCore,
):
    """Unified memory/document store. See docs/architecture.md."""
```

**Nearest existing sibling-module conventions to match for each mixin's internal shape (not for copying code, only for header/docstring/constant style):**
- `store_core.py` (init/query/write infra, `@contextmanager`-style session helpers): `src/turing_agentmemory_mcp/document_jobs.py` — module docstring at line 1 (`"""Durable tenant-scoped state for asynchronous document ingestion."""`), constants block (lines 15-18: `DOCUMENT_JOB_SCHEMA_VERSION`, `BUSY_TIMEOUT_MS`, compiled regex, status sets) before the dataclass — mirror this "docstring, then module constants, then class" ordering in `store_core.py`.
- `store_chunking.py` and `store_utils.py` (pure-function modules with a couple of small constants): `src/turing_agentmemory_mcp/hybrid.py` — module-level regex constants (lines 6-8), two float weight constants (lines 10-11), one frozen dataclass (lines 14-20), then top-level functions. This is the smallest/cleanest analog for a "few functions + a couple of constants" module shape.
- `store_evidence.py` / `store_rebuild.py` (multi-signal aggregation over several data sources): `src/turing_agentmemory_mcp/retrieval_fusion.py` and `src/turing_agentmemory_mcp/community_detection.py` — both already implement the "collect from N sources, fuse/aggregate deterministically" shape these mixins need to preserve.
- `store_search.py` (rerank pipeline glue): `src/turing_agentmemory_mcp/rerank.py` — `apply_rerank_guard`/`assemble_rerank_document` are the exact functions `store_search.py`'s `_rerank_memory` already calls; keep the import, don't reimplement.

**Behavior-preservation gate (run after every extraction — copy this exactly from RESEARCH.md):**
```bash
python -m pytest -q                                    # 362/362 must stay green
python scripts/e2e_score.py --out e2e-results.json      # must stay VALIDATED_10_10, score >= 9.8
python -m ruff check src tests scripts                  # must stay clean
```

---

### `server.py`, `document_jobs.py`, `gliner_provider.py` splits

**Analog:** each file is its own best analog for import/header convention (all three already read above, lines 1-45 each). Split boundaries follow the same "docstring/constants first, then cohesive concern classes/functions" ordering already visible in `document_jobs.py` (module docstring → constants → dataclass) and `gliner_provider.py` (docstring → imports → `DEFAULT_MODEL_NAME`/timeout/size constants → `LOGGER` → HTTP server class). When splitting:
- `server.py` → split by MCP tool group (memory tools / document tools / admin tools) behind the existing `create_mcp_app`/`*_from_env()` factory functions (lines 1-32 shown above: `auth_from_env`, `document_upload_store_from_env`, `document_ingest_manager_from_env` are already separate factory functions in separate modules — follow that existing "factory lives near what it constructs" convention).
- `document_jobs.py` → split dataclass/schema (`DocumentIngestJob`, schema constants) from the SQLite `@contextmanager` session/query methods, matching `sparse_index.py`'s SQLite-FTS5 module boundary (schema constants at top, connection helpers, then query methods).
- `gliner_provider.py` → split `BaseHTTPRequestHandler`/`ThreadingHTTPServer` plumbing (constants at lines 26-38: `MAX_BODY_BYTES`, `MAX_TEXTS`, etc.) from extraction/label-schema logic that calls into `memory_extraction.py`'s `MEMORY_ENTITY_LABELS`/`MEMORY_KIND_LABELS` — matches `entity_extraction.py`'s existing Protocol-vs-HTTP-impl separation.

---

### `benchmark.py`, `e2e_score.py`, `scripts/eval_backboard_locomo_mcp.py`, `scripts/real_document_benchmark.py` splits

**Analog:** sibling files already in the same directory — `scripts/eval_locomo_answers.py` (smaller existing eval script, same `scripts/` directory) is the nearest structural analog for splitting the two oversized `scripts/` files into a CLI-arg-parsing module + a scoring/runner module. No code excerpt needed beyond directory-convention: keep `scripts/*.py` as flat CLI scripts (no package split), just multiple files per concern, same as the existing `scripts/agent_quality_eval.py` / `scripts/benchmark.py` / `scripts/e2e_score.py` / `scripts/real_document_benchmark.py` sibling layout.

---

### `tests/test_gliner_provider.py`, `tests/test_batch_memory.py` splits

**Analog:** existing one-file-per-concern test naming convention already used across `tests/` (e.g. `tests/test_admin_repair.py`, `tests/test_agent_quality_eval.py`, `tests/test_agentmemory_skill.py`, `tests/test_auth.py` — each a narrow concern, function-based, no shared base class). Split each oversized test file along its own internal fixture/scenario grouping into 2+ files following this same flat, function-based, `test_<concern>.py` naming pattern (e.g. `test_gliner_provider_http.py` / `test_gliner_provider_extraction.py`).

---

### `pyproject.toml` (modified)

**Analog:** itself — current `[project.optional-dependencies].dev` and `[tool.pytest.ini_options]` blocks (full file read, lines 1-60+):
```toml
[project.optional-dependencies]
dev = [
  "pytest>=8.2",
  "ruff>=0.9",
]
...
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```
Edit in place: bump `"ruff>=0.9"` → `"ruff==0.15.21"`, add `"lefthook==2.1.10"`, `"pytest-cov==7.1.0"` to the `dev` list; add a `markers = [...]` key to `[tool.pytest.ini_options]` per RESEARCH.md's drafted block (slow/integration/gpu marker descriptions).

---

### `Makefile` (modified)

**Analog:** itself — full file (13 lines, read above):
```makefile
.PHONY: test e2e docker-e2e lint

test:
	python -m pytest

e2e:
	python scripts/e2e_score.py --out e2e-results.json

docker-e2e:
	docker compose run --rm e2e

lint:
	python -m ruff check src tests scripts
```
Add a `hooks` target following this exact tab-indented, blank-line-separated, `.PHONY`-registered style:
```makefile
.PHONY: test e2e docker-e2e lint hooks

hooks:
	lefthook install
```

---

### `CLAUDE.md` (modified)

**Analog:** itself — §"DEEP REFACTOR ON TOUCH" bullet currently reads (from the project CLAUDE.md already in context):
> "...Prefer small modules split by concern (`<name>_<concern>.py`); the codebase already does this. `store.py` is the large central exception — extend it deliberately, don't grow it casually. NO >600 loc."

Remove the "`store.py` is the large central exception ... NO >600 loc" clause entirely (D-08/D-09 supersede it — no exception exists post-split); keep the rest of the bullet (small modules by concern) unchanged since that convention is exactly what the store.py split reinforces.

## Shared Patterns

### No-skip-as-green (CI=true arming convention)
**Source:** `D:\Repo\Aura\.github\workflows\ci.yml` lines 153, 215, 502, 664, 741, 787, 898, 965 (repeated `env: { CI: "true" }` with an inline "arms the ... guard" comment)
**Apply to:** `.github/workflows/ci.yml`'s `unit-tests` job (self-test step) and `dockerized-integration` job; `tests/conftest.py`'s hookwrapper.
```yaml
    env:
      CI: "true"  # arms the in-script no-skip-as-green guards
```

### Sibling-module concern split (`<name>_<concern>.py`)
**Source:** existing repo-wide convention, exemplified by `hybrid.py` / `retrieval_fusion.py` / `temporal_graph.py` / `sparse_index.py` all sitting alongside `store.py` as already-separated concerns.
**Apply to:** every one of the 10 over-cap files (store.py's 8 new siblings, plus the split output of `benchmark.py`, `e2e_score.py`, `server.py`, `document_jobs.py`, `gliner_provider.py`, and the two `tests/`/two `scripts/` files).

### Windows/MSYS-safe shell loop (process substitution, not here-string)
**Source:** `D:\Repo\Aura\scripts\check-file-size.sh` lines 40-57 (documented workaround for a real Git-Bash `<<<` bug)
**Apply to:** `scripts/check-file-size.sh` (must be ported, not re-derived) — this is a load-bearing Windows-portability fix, not a style preference.

### Behavior-preservation gate after each mechanical extraction
**Source:** RESEARCH.md "Behavior-preservation gate" — `python -m pytest -q`, `python scripts/e2e_score.py --out e2e-results.json`, `python -m ruff check src tests scripts`
**Apply to:** every store.py mixin extraction and every other file split in this phase — run after each extraction, not only at the end.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `tests/conftest.py` | test (fixture/hook) | event-driven | No `conftest.py` exists anywhere in this repo today; use RESEARCH.md's fully-drafted hookwrapper code directly |
| `tests/test_no_skip_as_green_guard.py` | test (self-test) | event-driven | No `pytester`-based plugin/hook test exists in this repo today; use RESEARCH.md's fully-drafted `pytester` probe code directly |

## Metadata

**Analog search scope:** `D:\Repo\turing_AgentMemory_MCP\src\turing_agentmemory_mcp\*.py`, `D:\Repo\turing_AgentMemory_MCP\tests\*.py`, `D:\Repo\turing_AgentMemory_MCP\scripts\*.py`, `D:\Repo\turing_AgentMemory_MCP\Makefile`, `D:\Repo\turing_AgentMemory_MCP\pyproject.toml`; cross-repo `D:\Repo\Aura\lefthook.yml`, `D:\Repo\Aura\.github\workflows\ci.yml`, `D:\Repo\Aura\scripts\check-file-size.sh`
**Files scanned:** 33 in-repo `src/` modules (Glob), 5 `tests/` samples, 6 `scripts/` samples, Makefile, pyproject.toml, plus 3 full/targeted reads of Aura reference files
**Pattern extraction date:** 2026-07-11
