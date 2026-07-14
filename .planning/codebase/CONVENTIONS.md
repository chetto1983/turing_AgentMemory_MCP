# Coding Conventions

**Analysis Date:** 2026-07-14

## Naming Patterns

**Files:**
- Use lowercase `snake_case.py` modules and `test_<subject>.py` tests, as in `src/turing_agentmemory_mcp/document_job_manager.py` and `tests/test_document_jobs.py`.
- Split large domains by concern with a shared stem: `src/turing_agentmemory_mcp/store_core.py`, `src/turing_agentmemory_mcp/store_search.py`, and `src/turing_agentmemory_mcp/store_memory_write.py`.
- Prefix non-collected shared test helpers with `_`, as in `tests/_batch_memory_shared.py`.

**Functions:**
- Use `snake_case`; reserve leading `_` for private helpers and seams such as `_env_bool()` in `src/turing_agentmemory_mcp/server.py`.
- Name tests `test_<observable_behavior>`, as in `tests/test_document_processing.py`.
- Name environment factories `<object>_from_env`, such as `store_from_env()` in `src/turing_agentmemory_mcp/server.py`.

**Variables:**
- Use descriptive `snake_case` and preserve domain terms (`user_identifier`, `document_id`, `session_id`) across `src/turing_agentmemory_mcp/models.py` and store modules.
- Use uppercase constants for fixed contracts, such as `MEMORY_EXTRACTION_SCHEMA_VERSION` in `src/turing_agentmemory_mcp/memory_extraction.py`.
- Prefix internal test doubles with `_`, such as `_FakeArcadeDBClient` in `tests/test_store_arcadedb_core.py`.

**Types:**
- Use `PascalCase` for classes, dataclasses, and protocols: `MemoryItem` in `src/turing_agentmemory_mcp/models.py` and `SpanRecorder` in `src/turing_agentmemory_mcp/observability.py`.
- Prefer built-in generics (`list[str]`, `dict[str, object]`) and `X | None`; Python 3.11 is the minimum in `pyproject.toml`.
- Model immutable values with `@dataclass(frozen=True)` and use `slots=True` where established, as in `src/turing_agentmemory_mcp/community_detection.py`.

## Code Style

**Formatting:**
- Use Ruff formatter with 100-character lines and Python 3.11 target from `pyproject.toml`.
- Run `python -m ruff format --check src tests scripts`; `.github/workflows/ci.yml` and `lefthook.yml` enforce it.
- Keep every tracked Python file at or below 600 lines. `scripts/check-file-size.sh` enforces this without exemptions.
- Start modern modules with `from __future__ import annotations`, as in `src/turing_agentmemory_mcp/server.py`.

**Linting:**
- Use Ruff 0.15.21 with `E`, `F`, `I`, `B`, and `UP` rules from `pyproject.toml`; `E501` is ignored because formatting owns wrapping.
- Run `python -m ruff check src tests scripts` or `make lint`; `lefthook.yml` checks staged Python files.
- Use targeted `# type: ignore[arg-type]` only at deliberate test-double boundaries, as in `tests/_batch_memory_shared.py`.

## Import Organization

**Order:**
1. Future imports.
2. Standard library imports.
3. Third-party imports.
4. Absolute `turing_agentmemory_mcp` package imports.

**Path Aliases:**
- No aliases are configured. Use absolute package imports; `pythonpath = ["src"]` in `pyproject.toml` supports tests.
- Avoid eager package re-exports. `src/turing_agentmemory_mcp/__init__.py` lazily exposes only `TuringAgentMemory`.

## Error Handling

**Patterns:**
- Validate boundary inputs and raise `ValueError` with actionable messages, as in `src/turing_agentmemory_mcp/document_jobs.py` and `src/turing_agentmemory_mcp/community_detection.py`.
- Translate dependency failures to contextual `RuntimeError` and preserve causes with `raise ... from exc`, as in `src/turing_agentmemory_mcp/embeddings.py`.
- Catch narrow exceptions; catch `Exception` only at lifecycle/observability boundaries that record, roll back, or convert failure, as in `src/turing_agentmemory_mcp/observability.py`.
- Fail closed for tenant, authentication, integrity, schema, and configuration validation; see `CONTRIBUTING.md` and `tests/test_arcadedb_tenant_isolation.py`.

## Logging

**Framework:** Structured span recorders in `src/turing_agentmemory_mcp/observability.py`.

**Patterns:**
- Wrap meaningful operations in observer spans with content-free attributes; use `NoopSpanRecorder` when disabled.
- Emit deterministic JSON through `JsonlSpanRecorder` or `StderrJsonSpanRecorder`.
- Record error type/message and re-raise so observability never changes behavior.
- Keep health signals free of memory/document content; `RuntimeSignals` stores identities, counts, and error types.

## Comments

**When to Comment:**
- Explain invariants, platform constraints, and why workarounds exist, as in `src/turing_agentmemory_mcp/server.py` and `lefthook.yml`.
- Document the contract proved by complex fakes or protocol simulations, as in `tests/test_store_arcadedb_core.py`.
- Do not narrate straightforward code; prefer domain names and focused helpers.

**JSDoc/TSDoc:**
- Not applicable. Python docstrings are selective for modules, contracts, and complex fakes, as in `tests/conftest.py` and `tests/test_arcadedb_client.py`.

## Function Design

**Size:** Keep functions focused and extract validation, serialization, and environment parsing helpers. The hard module cap is 600 lines via `scripts/check-file-size.sh`.

**Parameters:** Prefer keyword-only parameters for multi-field operations and configuration, as in `src/turing_agentmemory_mcp/server.py`. Annotate inputs/returns and accept narrow protocols.

**Return Values:** Return typed dataclasses and explicit `to_dict()` serialization, as in `src/turing_agentmemory_mcp/models.py`. Use `None` only when absence is contractual.

## Module Design

**Exports:** Keep helpers private with `_`; import APIs from defining modules. Use protocols for providers (`src/turing_agentmemory_mcp/embeddings.py`) and concern-specific store seams (`src/turing_agentmemory_mcp/store_*.py`).

**Barrel Files:** Barrels are minimal. `src/turing_agentmemory_mcp/__init__.py` exposes only `TuringAgentMemory`; add exports only for public package contracts.

---

*Convention analysis: 2026-07-14*
