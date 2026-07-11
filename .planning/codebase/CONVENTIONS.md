# Coding Conventions

**Analysis Date:** 2026-07-11

## Naming Patterns

**Files:**
- Snake_case for all module names (e.g., `embeddings.py`, `document_processing.py`, `community_detection.py`)
- Test files prefixed with `test_` (e.g., `test_embeddings.py`, `test_models.py`)

**Functions:**
- Snake_case for all function names
- Private functions prefixed with underscore: `_internal_helper()`, `_ensure_graph_loaded()`
- Example: `convert_document_to_markdown()`, `aggregate_weighted_edges()`, `rank_hybrid()`

**Classes:**
- PascalCase for all class names
- Dataclasses heavily used with descriptive names: `RetrievalCandidate`, `MemoryItem`, `DocumentHit`
- Protocol classes for interfaces: `Embedder`, `ExtractProvider`, `CommunityRebuilder`
- Exception classes inherit from standard exceptions: `class RequestFailure(ValueError)`, `class ProviderFailure(ValueError)`

**Variables:**
- Snake_case for all variables and attributes
- Constants: SCREAMING_SNAKE_CASE
  - `DEFAULT_MODEL_NAME = "lion-ai/gliner2-base-v1-onnx"`
  - `MAX_BODY_BYTES = 1024 * 1024`
  - `LOGGER = logging.getLogger(__name__)`

**Type Hints:**
- Uses `from __future__ import annotations` in all files
- Pipe union syntax: `str | None`, `list[str]`, `dict[str, object]`
- Generic type hints for collections
- Protocol classes define interfaces: `class Embedder(Protocol):`

## Code Style

**Formatting:**
- Tool: ruff
- Line length: 100 characters
- No semicolons for statement termination
- Uses `from __future__ import annotations` for forward compatibility

**Linting:**
- Tool: ruff
- Configured rules: E (pycodestyle), F (pyflakes), I (isort), B (flake8-bugbear), UP (pyupgrade)
- Ignored: E501 (line too long - manually controlled via 100-char limit)
- Target: Python 3.11+

**Dataclass Usage:**
- Heavily used throughout codebase for data containers
- Use `frozen=True` for immutable data: `@dataclass(frozen=True)` in `models.py`, `embeddings.py`
- Use `slots=True` for performance in performance-critical classes: `@dataclass(frozen=True, slots=True)` in `community_detection.py`
- Default factory for mutable defaults: `field(default_factory=dict)`, `field(default_factory=list)`

**Docstring Style:**
- Module-level docstrings present for complex modules
- Minimal inline documentation (code is self-documenting)
- Class docstrings when behavior is non-obvious: `"""Adapt FastGLiNER2's one-text API to the provider batch contract."""` in `gliner_provider.py`
- No mandatory function-level docstrings

## Import Organization

**Order:**
1. `from __future__ import annotations`
2. Standard library imports (dataclasses, pathlib, datetime, typing, etc.)
3. Third-party imports (fastmcp, turingdb, markitdown, etc.)
4. Local package imports using relative imports (from .models import, from .embeddings import)

**Path Aliases:**
- Relative imports within package: `from .embeddings import Embedder`
- Absolute imports for CLI entry points: `from turing_agentmemory_mcp.utcp import build_utcp_manual`

**Example from `store.py`:**
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

from turing_agentmemory_mcp.community_detection import (
    CommunityEntity,
    ...
)
from .hybrid import blend_hybrid_score, lexical_score
```

## Error Handling

**Patterns:**
- Raise specific exception types with descriptive messages:
  - `raise ValueError("embedding dimensions must be positive")`
  - `raise FileNotFoundError(str(vector_dir))`
  - `raise NotADirectoryError(str(vector_dir))`
  - `raise RuntimeError("graspologic native leiden backend not available")`

- Validation in `__post_init__` for dataclasses:
  ```python
  def __post_init__(self) -> None:
      if self.batch_size <= 0:
          raise ValueError("embedding batch size must be positive")
  ```

- Try-except for external API calls and imports:
  ```python
  try:
      from graspologic.partition import hierarchical_leiden
  except ImportError as exc:
      raise RuntimeError("graspologic native leiden backend not available") from exc
  ```

- Use context managers for resource cleanup (file handles, server connections)

## Logging

**Framework:** Python's standard `logging` module

**Pattern:** Module-level logger initialization
```python
LOGGER = logging.getLogger(__name__)
```

**Usage:** Minimal - primarily in `gliner_provider.py` for HTTP server operations. Most code relies on exception raising rather than logging.

## Comments

**When to Comment:**
- Complex algorithmic logic (lexical scoring, community detection)
- Non-obvious performance optimizations
- Workarounds for known issues

**When NOT to Comment:**
- Self-documenting code (types and names convey intent)
- Simple business logic
- Standard patterns (for loops, conditionals)

**Example pattern:**
```python
# Normalize line endings from different PDF sources
normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()

# Leiden backend returned groups; assign to entity nodes
if node not in communities:
    raise ValueError("Leiden backend returned an unknown node")
```

## Function Design

**Size:** Functions range from 5-50 lines; helper functions extracted at 50+ lines

**Parameters:**
- Explicit keyword-only arguments for clarity: `def lexical_score(query: str, text: str) -> float:`
- Use keyword-only for optional/configuration parameters: `def convert_document_to_markdown(path: str | Path, *, converter: Any | None = None):`

**Return Values:**
- Type hints always present
- Return single objects or simple types; avoid tuple unpacking for clarity
- Use dataclasses for complex return values
- Example: `def store_message(...) -> MemoryItem:` returns a data object

## Module Design

**Exports:**
- Public APIs exported directly from modules
- Private helpers prefixed with underscore: `_ensure_graph_loaded()`, `_convert_pdfium()`, `_pdfium_document()`
- No `__all__` declarations; rely on naming convention

**Barrel Files:**
- `__init__.py` files present but minimal
- No re-exports in `__init__.py` files

**Example module structure (`document_processing.py`):**
- Public dataclass: `ConvertedDocument`
- Private converters: `_markitdown_converter()`, `_pdfium_document()`, `_convert_pdfium()`
- Public main function: `convert_document_to_markdown()`

---

*Convention analysis: 2026-07-11*
