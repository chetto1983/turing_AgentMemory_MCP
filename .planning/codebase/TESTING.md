# Testing Patterns

**Analysis Date:** 2026-07-16

## Test Framework

**Runner:**
- `pytest` 8.2+ (specified in `pyproject.toml:project.optional-dependencies.dev`)
- Config: `pyproject.toml:tool.pytest.ini_options` (lines 57–64)
  - `testpaths = ["tests"]` — tests only collected from `tests/` directory
  - `pythonpath = ["src"]` — source code added to path so imports work
  - Custom markers: `slow`, `integration`, `gpu` with special CI handling

**Assertion Library:**
- pytest's built-in assertions (no separate assertion library)
- Used throughout: `assert condition`, `assert x == y`, `assert x is not None`

**Run Commands:**
```bash
python -m pytest                                  # Run all tests
python -m pytest tests/test_community_detection.py   # Single test file
python -m pytest tests/test_community_detection.py::test_native_leiden_is_deterministic_and_separates_weighted_components  # Single test
python -m pytest -q                               # Quiet mode
python -m pytest -p no:cacheprovider -q          # Skip cache provider (from CONTRIBUTING.md)
python -m ruff format --check src tests scripts  # Format check
python -m ruff check src tests scripts            # Linting
bash scripts/check-file-size.sh                  # File size check (600-LOC cap)
```

## Test File Organization

**Location:**
- Co-located with source in `tests/` directory (separate, not inside `src/`)
- Test file path mirrors source structure: `tests/test_embeddings.py` for `src/turing_agentmemory_mcp/embeddings.py`
- Fixtures shared across multiple test files use underscore prefix: `tests/_batch_memory_shared.py`, `tests/_arcadedb_lifecycle_isolation_support.py`, `tests/_store_arcadedb_core_shared.py`

**Naming:**
- Test functions prefixed with `test_`: `test_native_leiden_is_deterministic_and_separates_weighted_components()`, `test_vector_neighbors_resolves_and_returns_record_plus_score()`
- Test file naming: `test_<module>.py` where module is the code being tested
- Shared fixture files named with leading underscore: `_batch_memory_shared.py`, `_arcadedb_physical_isolation_support.py`
- Fixture classes/functions: `CountingBatchEmbedder`, `RecordingMemoryStore`, `_client()`, `_insert_chunk()`

**Structure:**
```
tests/
├── conftest.py                                 # Central pytest hooks + no-skip-as-green guard
├── test_*.py                                   # One test file per module or concern
├── _*_shared.py                                # Shared fixtures (not collected as tests)
└── [subdirs if needed per major area]
```

## Test Structure

**Suite Organization:**

```python
# Example from test_community_detection.py:33–48
def test_native_leiden_is_deterministic_and_separates_weighted_components() -> None:
    # ARRANGE: set up detector with known parameters
    detector = NativeLeidenDetector(seed=42, iterations=2, max_cluster_size=10)

    # ACT: run detection twice with different orderings
    first = detector.detect("alice", ["a", "b", "c", "d", "e", "f"], two_cluster_edges())
    second = detector.detect(
        "alice",
        ["f", "e", "d", "c", "b", "a"],
        list(reversed(two_cluster_edges())),
    )

    # ASSERT: verify determinism and correctness
    assert first == second
    assert {community.member_ids for community in first.communities} == {
        ("a", "b", "c"),
        ("d", "e", "f"),
    }
    assert first.isolates == ()
```

**Patterns:**
- No explicit setup/teardown functions; use fixtures and context managers
- Arrange-Act-Assert (AAA) pattern implicit in test code
- Setup via fixtures (module-scoped, function-scoped, parametrized)
- Teardown via pytest `autouse=True` fixtures: `tests/test_arcadedb_client.py:58–81` `_fresh_database` fixture auto-runs, cleans up before and after

**Fixtures with Module Scope:**
```python
# tests/test_arcadedb_client.py:46–55
@pytest.fixture(scope="module")
def client() -> ArcadeDBClient:
    candidate = _client()
    if not candidate.is_ready():
        pytest.skip(
            f"ArcadeDB not reachable at {candidate.base_url} -- start it with "
            "`docker compose up -d arcadedb` before running this hard-gate smoke test.",
            allow_module_level=True,
        )
    return candidate
```

**Autouse Fixtures for Setup/Teardown:**
```python
# tests/test_arcadedb_client.py:58–81
@pytest.fixture(scope="module", autouse=True)
def _fresh_database(client: ArcadeDBClient):
    # TEARDOWN: cleanup before test
    try:
        client._server_command(f"drop database {TEST_DATABASE}")
    except RuntimeError:
        pass
    # SETUP: initialize schema
    client.ensure_database()
    client.command("CREATE VERTEX TYPE Chunk")
    # ... more DDL ...
    yield  # tests run here
    # TEARDOWN: cleanup after tests
    try:
        client._server_command(f"drop database {TEST_DATABASE}")
    except RuntimeError:
        pass
```

## Mocking

**Framework:** pytest's built-in `monkeypatch` fixture for environment variables; no external mocking library used

**Patterns:**

**Environment Variable Mocking:**
```python
# tests/test_auth.py:13–17
def test_auth_from_env_is_disabled_without_static_token(monkeypatch) -> None:
    monkeypatch.delenv("AGENTMEMORY_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("AGENTMEMORY_AUTH_TOKENS", raising=False)
    assert auth_from_env() is None
```

```python
# tests/test_auth.py:20–35
def test_auth_from_env_builds_static_token_verifier(monkeypatch) -> None:
    monkeypatch.setenv("AGENTMEMORY_AUTH_TOKEN", "dev-secret")
    monkeypatch.setenv("AGENTMEMORY_AUTH_CLIENT_ID", "local-client")
    monkeypatch.setenv("AGENTMEMORY_AUTH_SCOPES", "memory:read,memory:write")
    monkeypatch.setenv("AGENTMEMORY_AUTH_REQUIRED_SCOPES", "memory:read")

    verifier = auth_from_env()
    assert verifier is not None
    # ... assertions ...
```

**Recording Mock Objects:**
Created custom mock classes to record calls and verify behavior without external dependencies:

```python
# tests/_batch_memory_shared.py:19–35
class CountingBatchEmbedder:
    dimensions = 3

    def __init__(self) -> None:
        self.embed_calls: list[str] = []
        self.embed_many_calls: list[list[str]] = []

    def embed(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        return self._vector(text)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        self.embed_many_calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        return [float(len(text)), 1.0, 0.0]
```

```python
# tests/_batch_memory_shared.py:38–78
class RecordingMemoryStore(TuringAgentMemory):
    """Subclass TuringAgentMemory to record calls without hitting a real database."""
    def __init__(
        self,
        tmp_path: Path,
        embedder: CountingBatchEmbedder,
        memory_extractor: object | None = None,
        sparse_index: SparseIndex | None = None,
    ) -> None:
        super().__init__(
            client=object(),  # type: ignore[arg-type]  # Use object() as placeholder
            turing_home=tmp_path,
            embedder=embedder,
            reranker=None,
            memory_extractor=memory_extractor,  # type: ignore[arg-type]
            sparse_index=sparse_index,
        )
        self.memories: dict[tuple[str, str], MemoryItem] = {}
        self.vector_loads: list[list[tuple[int, list[float]]]] = []
        self.write_queries: list[str] = []
        self.write_params: list[dict[str, object] | None] = []
```

**What to Mock:**
- Environment variables (use `monkeypatch`)
- External service responses (use placeholder objects or stubs)
- Database clients (inject test doubles like `RecordingMemoryStore`)

**What NOT to Mock:**
- Core business logic (test real, not stubs)
- Live integration tests require real services (marked with `@pytest.mark.integration`)
- Actual file I/O for document processing tests
- Real embedding vectors for retrieval tests

## Fixtures and Factories

**Test Data:**

**Shared Edge Factory:**
```python
# tests/test_community_detection.py:21–30
def two_cluster_edges() -> list[WeightedEntityEdge]:
    return [
        WeightedEntityEdge("a", "b", 3.0, ("m1",)),
        WeightedEntityEdge("b", "c", 3.0, ("m1",)),
        WeightedEntityEdge("a", "c", 3.0, ("m2",)),
        WeightedEntityEdge("d", "e", 3.0, ("m3",)),
        WeightedEntityEdge("e", "f", 3.0, ("m3",)),
        WeightedEntityEdge("d", "f", 3.0, ("m4",)),
        WeightedEntityEdge("c", "d", 0.01, ("bridge",)),
    ]
```

**Parametrized Tests:**
```python
# tests/test_community_detection.py:99–100
@pytest.mark.parametrize("weight", [0.0, -1.0, math.nan, math.inf, True])
def test_weighted_edges_reject_invalid_weights(weight: object) -> None:
    # Test multiple invalid weight values in one test
    ...
```

**Location:**
- Shared fixtures live in `tests/conftest.py` (global) or `tests/_*_shared.py` (module-specific)
- Example: `tests/_batch_memory_shared.py` exports `CountingBatchEmbedder`, `RecordingMemoryStore`
- Imported as: `from _batch_memory_shared import CountingBatchEmbedder, RecordingMemoryStore`

## Coverage

**Requirements:** No explicit coverage target enforced in CI; however, coverage configuration exists in `pyproject.toml:tool.coverage.run` (omit `*/e2e_score*.py`)

**View Coverage:**
```bash
python -m pytest --cov=src --cov-report=html
# Opens htmlcov/index.html with line-by-line coverage
```

**Instrumentation:**
- Add `pytest-cov` for coverage reporting (listed in `pyproject.toml:project.optional-dependencies.dev`)
- No branches excluded except E2E scoring code

## Test Types

**Unit Tests:**
- Scope: Single function or class in isolation
- Approach: Fast, no external dependencies (or mocked)
- Examples: `test_community_detection.py::test_native_leiden_is_deterministic_and_separates_weighted_components()` (tests pure Leiden algorithm), `test_embeddings.py` (mock embedder)
- Run: `python -m pytest tests/ -k "not integration"` (excludes integration tier)

**Integration Tests:**
- Scope: Multiple components together; requires a live external service
- Approach: Marked with `@pytest.mark.integration`
- Examples: `test_arcadedb_client.py` (requires live ArcadeDB container), `test_docker_hardening.py` (Docker service verification)
- Run: `python -m pytest -m integration`
- CI enforcement: Under `CI=true`, skipping an `@pytest.mark.integration` test fails the build (see `tests/conftest.py:14–28`)

**GPU Tests:**
- Scope: Tests requiring GPU-backed inference providers
- Approach: Marked with `@pytest.mark.gpu`
- Examples: Real embedding/reranking provider tests, GLiNER provider tests
- Run: `python -m pytest -m gpu`
- CI enforcement: Under `CI=true`, skipping a `@pytest.mark.gpu` test fails the build

**Slow Tests:**
- Scope: Tests that take >5 seconds (benchmarking, E2E, full suite)
- Approach: Marked with `@pytest.mark.slow`
- Run: `python -m pytest -m slow` (or omitted by default for faster iteration)
- CI enforcement: Always runs in CI; skips are allowed locally

**Marker Enforcement (conftest.py):**
```python
# tests/conftest.py:13–28
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    outcome = yield
    if os.environ.get("CI") != "true":
        return  # Locally, skips are OK
    report = outcome.get_result()
    if not report.skipped:
        return  # Only check skips
    markers = {marker.name for marker in item.iter_markers()} & _CI_ENFORCED_MARKERS
    if not markers:
        return  # Not an enforced marker
    report.outcome = "failed"  # Convert skip to failure under CI=true
    report.longrepr = f"no-skip-as-green: {item.nodeid} skipped under CI=true (markers={sorted(markers)})"
```

## Common Patterns

**Async Testing:**

No explicit async testing patterns observed. FastMCP uses async internally, but tests are synchronous:
```python
# tests/test_auth.py:29
accepted = asyncio.run(verifier.verify_token("dev-secret"))
```

Pattern: Call async functions via `asyncio.run()` in test body.

**Error Testing:**

```python
# tests/test_community_detection.py:99–103 (via parametrize)
@pytest.mark.parametrize("weight", [0.0, -1.0, math.nan, math.inf, True])
def test_weighted_edges_reject_invalid_weights(weight: object) -> None:
    with pytest.raises(ValueError):
        WeightedEntityEdge("a", "b", weight)
```

Pattern: Use `pytest.raises(ExceptionType)` context manager to verify errors are raised.

**Live Service Skipping:**

```python
# tests/test_arcadedb_client.py:46–55
@pytest.fixture(scope="module")
def client() -> ArcadeDBClient:
    candidate = _client()
    if not candidate.is_ready():
        pytest.skip(
            f"ArcadeDB not reachable at {candidate.base_url} -- start it with "
            "`docker compose up -d arcadedb` before running this hard-gate smoke test.",
            allow_module_level=True,
        )
    return candidate
```

Pattern: Check service reachability in fixture; `pytest.skip()` at module level if not available.

**Document Processing E2E:**

Full scenario tests verify: async job → truthful terminal state → canonical chunks → scoped cited search → staged bytes removed on success (from CONTRIBUTING.md:53–59). No single code snippet; pattern is a multi-step workflow assertion.

---

*Testing analysis: 2026-07-16*
