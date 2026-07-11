# Testing Patterns

**Analysis Date:** 2026-07-11

## Test Framework

**Runner:**
- pytest 8.2+ (configured in `pyproject.toml`)
- Config: `pyproject.toml` with `[tool.pytest.ini_options]`
- Test paths: `testpaths = ["tests"]`
- Python path: `pythonpath = ["src"]` (allows direct imports of package)

**Assertion Library:**
- pytest built-in assertions
- Uses `assert` statements for all validations

**Run Commands:**
```bash
pytest                          # Run all tests
pytest tests/test_embeddings.py # Run specific test file
pytest -xvs                     # Run with verbose output and stop on first failure
pytest --tb=short               # Run with short traceback format
```

## Test File Organization

**Location:**
- Tests co-located in `/d/Repo/turing_AgentMemory_MCP/tests/` directory (separate from source)
- 30+ test files, one per major module

**Naming:**
- Files prefixed with `test_`: `test_embeddings.py`, `test_models.py`, `test_auth.py`
- Test functions prefixed with `test_`: `test_hashing_embedder_is_deterministic_and_normalized()`
- Descriptive names indicate what's being tested

**File List:**
- `test_embeddings.py` - Embedding system
- `test_models.py` - Data model serialization
- `test_document_processing.py` - Document conversion
- `test_governance.py` - Audit/redaction systems
- `test_auth.py` - Authentication
- `test_batch_memory.py` - Batch operations
- `test_community_detection.py` - Graph community detection
- (30+ total test files)

## Test Structure

**Suite Organization:**

```python
# Tests are function-based, not class-based
def test_hashing_embedder_is_deterministic_and_normalized() -> None:
    embedder = HashingEmbedder(dimensions=16)
    first = embedder.embed("espresso memory")
    second = embedder.embed("espresso memory")
    assert first == second
    assert round(sum(value * value for value in first), 6) == 1.0
    assert len(first) == 16
```

**Patterns:**
- **Setup:** Create objects directly in test function (no fixtures, no setup methods)
- **Teardown:** Pytest fixtures handle cleanup (e.g., `tmp_path` auto-cleanup)
- **Assertion:** Standard `assert` statements with inline conditions
- **Naming:** Descriptive test names explain behavior: `test_convert_document_to_markdown_uses_markitdown_convert_local()`

## Mocking

**Framework:** No external mocking library; uses custom fake/mock classes defined in test files

**Patterns:**

Create explicit mock classes inline:
```python
class FakeMarkItDown:
    def __init__(self, text: str) -> None:
        self.text = text
        self.paths: list[str] = []

    def convert_local(self, path: str) -> object:
        self.paths.append(path)
        return SimpleNamespace(text_content=self.text)

# Use in test
converter = FakeMarkItDown("# Release Notes")
result = convert_document_to_markdown(source, converter=converter)
assert converter.paths == [str(source)]
```

**Monkeypatch Usage (pytest fixture):**
```python
def test_openai_compatible_embedder_reads_provider_agnostic_env(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_BASE_URL", "http://embed.example.test")
    monkeypatch.setenv("EMBED_DIMENSIONS", "384")
    
    embedder = OpenAICompatibleEmbedder.from_env()
    
    assert embedder.dimensions == 384
```

**HTTP Server Mocking:**
```python
class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        inputs = json.loads(self.rfile.read(length).decode("utf-8"))["input"]
        # ... response logic
        self.send_response(200)

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    # ... test code
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
```

**What to Mock:**
- External HTTP services (embed servers, reranking services)
- File system operations (document converters)
- Database clients (TuringDB)
- Environment variables (via monkeypatch)

**What NOT to Mock:**
- Business logic functions (test the actual implementation)
- Internal helper functions (test through public API)
- Standard library functions (unless specifically testing error paths)

## Fixtures and Factories

**Test Data:**

Custom mock classes in tests serve as factories:
```python
class CountingBatchEmbedder:
    dimensions = 3

    def __init__(self) -> None:
        self.embed_calls: list[str] = []
        self.embed_many_calls: list[list[str]] = []

    def embed(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        return [float(len(text)), 1.0, 0.0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        self.embed_many_calls.append(list(texts))
        return [self._vector(text) for text in texts]
```

**Built-in Pytest Fixtures:**
- `tmp_path` - Temporary directory for file operations
- `monkeypatch` - Environment variable and module patching

**Location:**
- No `conftest.py` file (fixtures defined inline or via monkeypatch)
- Mock classes defined directly in test file where used

## Coverage

**Requirements:** Not enforced in tooling

**Observed Coverage:**
- Core business logic well-covered (embeddings, document processing, models)
- Integration points have dedicated tests (auth, storage operations)
- Edge cases tested (empty inputs, invalid values, error conditions)

## Test Types

**Unit Tests:**
- Scope: Individual functions/classes
- Approach: Direct instantiation, mock dependencies, assert output
- Example: `test_hashing_embedder_is_deterministic_and_normalized()` tests `HashingEmbedder.embed()`

**Integration Tests:**
- Scope: Multiple components working together
- Approach: Create mock store/server, exercise multiple layers
- Example: `test_governance.py` creates full MCP app and tests auth flow
- Uses: `RecordingMemoryStore`, `RecordingDocumentStore` to capture interactions

**End-to-End Tests:**
- Scope: Full system with real dependencies
- Framework: Not used for automated E2E; manual benchmarking via `e2e_score.py`
- Benchmark suite: `benchmark.py` provides real-world performance tests

## Common Patterns

**Async Testing:**

Uses `asyncio.run()` for testing async functions:
```python
def test_auth_from_env_builds_static_token_verifier(monkeypatch) -> None:
    monkeypatch.setenv("AGENTMEMORY_AUTH_TOKEN", "dev-secret")
    
    verifier = auth_from_env()
    
    accepted = asyncio.run(verifier.verify_token("dev-secret"))
    assert accepted is not None
```

**Error Testing:**

```python
# Test exception is raised with pytest.raises
def test_convert_document_to_markdown_rejects_empty_output(tmp_path):
    source = tmp_path / "empty.pdf"
    source.write_bytes(b"%PDF")
    
    with pytest.raises(ValueError, match="empty markdown"):
        convert_document_to_markdown(source, converter=FakeMarkItDown("  \n"))

# Test ValueError on invalid input
def test_openai_compatible_embedder_bounds_provider_batches(monkeypatch) -> None:
    # Test that batch_size must be positive
    embedder = OpenAICompatibleEmbedder(batch_size=0)  # raises in __post_init__
```

**Module Mocking for Conditionals:**

For optional dependencies (e.g., turingdb not always available):
```python
import sys
import types

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.store import TuringAgentMemory  # Can now import safely
```

**Temporary Files:**

Use pytest's `tmp_path` fixture:
```python
def test_convert_document_to_markdown_uses_markitdown_convert_local(tmp_path):
    source = tmp_path / "release-notes.docx"
    source.write_bytes(b"fake docx")
    
    result = convert_document_to_markdown(source, converter=converter)
    
    assert result.metadata["source_path"] == str(source)
```

**State Capture for Verification:**

Tests often create recording/counting mocks to verify behavior:
```python
class RecordingMemoryStore(TuringAgentMemory):
    def __init__(self, tmp_path: Path, embedder: Embedder) -> None:
        super().__init__(...)
        self.write_queries: list[str] = []
        self.vector_loads: list[list[tuple[int, list[float]]]] = []
    
    def _write(self, query: str) -> None:
        self.write_queries.append(query)

# In test:
store = RecordingMemoryStore(tmp_path, embedder)
store.store_message(...)
assert len(store.write_queries) > 0
```

---

*Testing analysis: 2026-07-11*
