# Coding Conventions

**Analysis Date:** 2026-07-16

## Naming Patterns

**Files:**
- Snake_case for all module names: `embeddings.py`, `document_processing.py`, `community_detection.py`, `arcadedb_client.py`
- Test files prefixed with `test_`: `test_community_detection.py`, `test_arcadedb_client.py`, `test_batch_memory.py`
- Shared test fixtures prefixed with underscore: `_batch_memory_shared.py`, `_arcadedb_lifecycle_isolation_support.py`, `_retrieval_arcadedb_shared.py`
- Concern-split modules follow pattern `<name>_<concern>.py`: `gliner_provider_extraction.py`, `gliner_provider_http.py`, `store_arcadedb_core_shared.py`

**Functions:**
- Snake_case for all function and method names
- Public functions: `convert_document_to_markdown()`, `stable_id()`, `embed_many()`, `detect()`
- Private functions prefixed with single underscore: `_markitdown_converter()`, `_pdfium_document()`, `_convert_pdfium()`, `_extract_html_main_content()`, `_embed_batch()`, `_install_shutdown_signal_handlers()`, `_read_settings()`, `_read_bounded_int()`
- Private static helpers: `_ensure_user()`, `_existing_entity_ids()`, `_write()`, `_write_many()`

**Variables and Attributes:**
- Snake_case for all variables and attributes: `base_url`, `user_identifier`, `source_memory_ids`, `max_cluster_size`, `batch_size`, `retry_base_s`, `embedding_dimensions`
- Constants in SCREAMING_SNAKE_CASE: `TOKEN_RE`, `RETRYABLE_PROVIDER_CODES`, `MAX_BODY_BYTES`, `DEFAULT_MODEL_NAME`, `_HTML_BOILERPLATE_SELECTOR`
- Loop variables lowercase: `text` in `for text in texts`, `edge` in `for edge in edges`

**Types and Classes:**
- PascalCase for all class names: `RetrievalCandidate`, `MemoryItem`, `DocumentHit`, `OpenAICompatibleEmbedder`, `HashingEmbedder`, `NativeLeidenDetector`, `ArcadeDBClient`, `TuringAgentMemory`
- Dataclasses with descriptive names: `FusedRetrievalCandidate`, `ConvertedDocument`, `WeightedEntityEdge`, `DetectedCommunity`, `CommunityDetection`, `CommunityProjection`
- Protocol classes for interfaces: `Embedder` (in `embeddings.py:27`), `EntityProcessor`, `MemoryExtractor`, `CommunityDetector`
- Exception classes inherit from standard exceptions: all raise `ValueError`, `RuntimeError`, `ImportError` with descriptive messages

## Code Style

**Formatting:**
- Tool: `ruff` (pinned at 0.15.21 in `pyproject.toml`)
- Line length: 100 characters (enforced; `E501` is ignored in linter)
- No semicolons for statement termination
- Imports use `from __future__ import annotations` in every file (first line after module docstring)
- Pipe union syntax for type hints: `str | None`, `list[str]`, `dict[str, object]`, `int | float`, `Any | None`
- Generic type hints for collections required throughout

**Linting:**
- Tool: `ruff` with configured rules in `pyproject.toml:tool.ruff.lint`
- Select rules: `E` (pycodestyle), `F` (pyflakes), `I` (isort), `B` (flake8-bugbear), `UP` (pyupgrade)
- Ignore: `E501` (line too long — manually controlled via 100-char limit)
- Target: Python 3.11+

**Dataclasses:**
- Heavily used throughout codebase for data containers
- Use `frozen=True` for immutable data (all exposed models): `@dataclass(frozen=True)` in `models.py:6`, `embeddings.py:33–54`, `community_detection.py:13–92`
- Use `slots=True` for performance in performance-critical classes: `@dataclass(frozen=True, slots=True)` in `community_detection.py:13`, `gliner_provider_extraction.py`
- Default factory for mutable defaults: `field(default_factory=dict)` in `models.py:14`, `field(default_factory=list)` in `models.py:73`
- Validation in `__post_init__()` for input checking: `embeddings.py:72–82` (batch size, dimensions, attempts), `community_detection.py:20–36` (edge weight validation), `gliner_provider_extraction.py`

**Documentation:**
- No mandatory function-level docstrings; names explain *what*
- Module-level docstrings for complex modules: `community_detection.py:1`, `gliner_provider.py:1–2`, `document_processing.py:8–16`
- Class docstrings when behavior is non-obvious: `OpenAICompatibleEmbedder` in `embeddings.py:56`
- Comments only for non-obvious *why* (hidden constraints, workarounds, surprising behavior): `ids.py:16`, `community_detection.py:104–106`, `document_processing.py:8–16`

## Import Organization

**Order (observed across codebase):**
1. `from __future__ import annotations` (always first, even before docstring if module has one)
2. Standard library imports: `os`, `json`, `re`, `hashlib`, `tempfile`, `pathlib.Path`, `dataclasses`, `typing`, `urllib`
3. Third-party imports: `pytest`, `yaml`, `markitdown`, `pypdfium2`
4. Local imports: `from turing_agentmemory_mcp.module import Class`
5. Relative imports (within package): `from .embeddings import Embedder` (seen in test files and cross-module references)

**Examples:**
- `embeddings.py:1–22`: Future, then stdlib (hashlib, json, math, re, time, dataclasses, typing, urllib), then local imports
- `models.py:1–4`: Future, then stdlib (dataclasses)
- `community_detection.py:1–11`: Future, docstring, stdlib (math, collections.abc, dataclasses, typing), then relative import
- `document_processing.py:1–6`: Future, then stdlib (tempfile, dataclasses, pathlib, typing)

**Path Aliases:**
- No path aliases configured; all imports use absolute paths `from turing_agentmemory_mcp.module`
- Relative imports within tests: `from _batch_memory_shared import CountingBatchEmbedder` (test fixtures)

## Error Handling

**Patterns:**
- Raise specific exception types with descriptive messages, never silent failures
- `ValueError` for validation errors (invalid input, configuration): `embeddings.py:38–40`, `community_detection.py:20–36`, `gliner_provider.py:47–55`
- `RuntimeError` for runtime failures (external service unavailable, provider errors): `embeddings.py:146`, `gliner_provider.py:78`
- `ImportError` for missing optional dependencies with context: `document_processing.py:77–80`, `gliner_provider.py:77–78`
- Validation in `__post_init__` for dataclasses: `embeddings.py:72–82` validates batch size is positive integer, dimensions match, attempts > 0

**Try-Except Patterns:**
- Retry logic with exponential backoff: `embeddings.py:138–162` catches `HTTPError`, `URLError`, `TimeoutError`, `OSError` with `time.sleep(retry_base_s * (2**attempt))`
- Context managers for resource cleanup: `document_processing.py:97–103` uses named `tempfile.NamedTemporaryFile` with try/finally for cleanup; `pypdfium2` document/page `.close()` in nested try/finally blocks
- Graceful degradation on optional integrations: If entity extraction fails, memory stored without tags; if community rebuild fails, log warning and skip

## Logging

**Framework:** No explicit logging library imported; uses `print()` directly for CLI output (`cli.py:55`, `e2e_score.py`)

**Patterns:**
- CLI tools print JSON to stdout for machine parsing: `cli.py:55` `json.dumps(result, indent=2, sort_keys=True)`
- Comments indicate where to add logging: `server.py`, `store.py` (observability hooks present but no console logger configured by default)
- Observability signals recorded via `SpanRecorder` protocol (optional): `observability.py` handles timing spans

## Comments

**When to Comment:**
- Complex algorithmic logic: Leiden clustering (graspologic-native), weighted edge aggregation, RRF fusion math
- Non-obvious performance optimizations: vector dimension caching, batch size tuning, post-filter k-underfill strategy
- Workarounds for known issues: `document_processing.py:8–16` HTML boilerplate stripping rationale, `test_arcadedb_client.py:1–24` vector literal binding vs. bind-param difference
- Historical context and deprecation: extensive comments in deleted-test sections (e.g., `test_batch_memory.py:19–42` explains why tests were deleted and what replaced them)

**Self-Documenting Code Preferred:**
- Type hints convey intent: `def embed(self, text: str) -> list[float]:`
- Names explain behavior: `_extract_html_main_content()`, `aggregate_weighted_edges()`, `stable_id()`
- Simple business logic needs no comments

## Function Design

**Explicit Keyword-Only Arguments:**
- Used for clarity and configuration: `def convert_document_to_markdown(path: str | Path, *, converter: Any | None = None)` (`document_processing.py:120`)
- `def provider_env(name: str, *, default: str = "")` (`provider_config.py:8`)
- `def from_env(cls, *, dimensions: int | None = None)` (`embeddings.py:85`)
- Pattern enforces caller to name the parameter, avoiding positional confusion

**Type Hints:**
- Always present on function signatures
- Return types always specified: `def stable_id(prefix: str, *parts: str) -> str:` (`ids.py:9`)
- Union types: `str | None`, `int | float`, `dict[str, object] | None`
- Protocols for interface definitions: `Embedder` protocol defines `dimensions: int` and `def embed(self, text: str) -> list[float]` contract

**Return Values:**
- Return single objects or dataclasses (not tuple unpacking): `def get_memory(...) -> MemoryItem | None:` returns data object or None
- Complex returns use frozen dataclasses: `RetrievalCandidate`, `MemoryItem`, `ConvertedDocument`
- Side effects documented via exception raising, not return codes

**Parameter Validation:**
- Validate in `__post_init__` for dataclasses rather than in `__init__` constructors
- Raise `ValueError` with descriptive messages: `if not isinstance(text, str): raise ValueError(...)`
- Check for empty strings: `if not user_identifier.strip(): raise ValueError("... must be non-empty")`

## Module Design

**Public APIs:**
- Exported directly from modules; rely on naming convention (`_` prefix for private)
- No `__all__` declarations; private helpers use underscore prefix
- Factories as class methods: `@classmethod def from_env(cls) -> OpenAICompatibleEmbedder:` (`embeddings.py:84–101`)
- Protocol classes define interfaces without implementation

**Private Helpers:**
- Prefixed with single underscore: `_ensure_graph_loaded()`, `_convert_pdfium()`, `_pdfium_document()`
- Not exported; name signals internal-only use
- Used for implementation details to break up large functions

**Barrel Files:**
- Minimal `__init__.py` files; rely on relative imports and public names
- Example: `src/turing_agentmemory_mcp/__init__.py:1–2` empty or minimal re-exports

**Example Module Structure:**
- `document_processing.py`: Public `ConvertedDocument` dataclass, public `convert_document_to_markdown()` function; private converters `_markitdown_converter()`, `_pdfium_document()`, `_convert_pdfium()`, `_convert_html_cleaned()`, `_extract_html_main_content()`
- `embeddings.py`: Public `Embedder` protocol, public `HashingEmbedder` and `OpenAICompatibleEmbedder` classes with `from_env()` factories; private `_embed_batch()`
- `provider_config.py`: All public utility functions (`provider_env`, `provider_secret`, `provider_api_key_header`, etc.); no private helpers

**File Size Constraint:**
- 600-LOC cap per `*.py` file (enforced by `scripts/check-file-size.sh`, NO allowlist)
- Large modules split by concern: `store.py` facade delegates to mixin modules, `gliner_provider.py` splits extraction/HTTP/CLI logic
- Refactoring required on touch: if editing a file, reduce it to <600 LOC in the same commit

---

*Convention analysis: 2026-07-16*
