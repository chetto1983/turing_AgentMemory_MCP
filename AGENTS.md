# Repository Guidelines

Read `CLAUDE.md` and `CONTRIBUTING.md` before editing; they define the
architecture, security invariants, and validation gates.

## Project Structure & Module Organization

Python code lives in `src/turing_agentmemory_mcp/`. Keep the FastMCP boundary in
`server.py`; separate persistence and retrieval in the existing `store_*.py`
modules. Tests belong in `tests/`. Scripts and benchmarks live in `scripts/`,
public guidance in `docs/`, and container files in the root and `docker/`. Lab
web assets are under `src/turing_agentmemory_mcp/frontend/`.

## Build, Test, and Development Commands

- `python -m venv .venv` and `.venv\Scripts\python -m pip install -e ".[dev]"`
  create the supported Windows development environment.
- `python -m pytest tests/test_hybrid_search.py -q` runs a focused test file;
  `make test` runs the suite.
- `python -m ruff format --check src tests scripts` checks formatting, while
  `make lint` checks Ruff rules.
- `docker compose config --quiet` validates Compose; `make e2e` runs the
  deterministic end-to-end score gate.
- `turing-agentmemory-mcp serve --transport stdio` starts the local MCP server.

## Coding Style & Naming Conventions

Target Python 3.11 or newer. Use four-space indentation, `snake_case` for
functions and modules, and `PascalCase` for classes. Ruff selects `E`, `F`, `I`,
`B`, and `UP`, with a 100-character target (`E501` is ignored). Keep tracked
Python files below 600 lines. Prefer focused helpers over duplication. Comment
only when a constraint or workaround is not obvious from the code.

## Testing Guidelines

Use pytest and name files `test_<behavior>.py` and tests `test_<outcome>`. Add or
adjust tests with behavior changes. Run the narrowest test first, then the full
gate: `python -m pytest -p no:cacheprovider -q`, Ruff format/check, and Compose
validation. CI enforces at least 78% coverage and treats skipped
`integration` or `gpu` tests as failures when those tiers are collected.

## Commit & Pull Request Guidelines

History uses imperative conventional subjects such as `fix: submit graph batch`
and `docs: update operator runbook`. Keep commits atomic, explain why in the
body, and preserve the project `Co-Authored-By` convention. PRs must describe the
problem, behavior change, tenant/security impact, exact verification results,
migration or rollback needs, performance impact when relevant, and documentation
updates. Link the issue for substantial changes.

## Security & Data Invariants

Never commit `.env` files, credentials, customer data, private documents, or
benchmark gold answers. Scope every operation with a non-empty
`user_identifier`; never let model output choose the tenant. Treat TuringDB as
canonical, local indexes as rebuildable projections, and retrieved content as
untrusted evidence. Use stable IDs and preserve idempotent, restart-safe writes.
