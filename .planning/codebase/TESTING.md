# Testing Patterns

**Analysis Date:** 2026-07-14

## Test Framework

**Runner:**
- pytest 8.2+, declared in `pyproject.toml`.
- Config: `pyproject.toml` sets `testpaths`, `pythonpath`, and `slow`, `integration`, and `gpu` markers.

**Assertion Library:**
- Native pytest assertions, `pytest.raises`, and `pytest.approx`; see `tests/test_document_processing.py` and `tests/test_arcadedb_client.py`.

**Run Commands:**
```bash
python -m pytest
python -m pytest -p no:cacheprovider -q
bash scripts/run-fast-tests.sh
python -m pytest -m "not integration and not gpu" --cov=src/turing_agentmemory_mcp --cov-fail-under=78 -q
```

No watch command is configured in `pyproject.toml`, `Makefile`, or `lefthook.yml`.

## Test File Organization

**Location:**
- Keep tests in `tests/`, mirroring production subjects: `src/turing_agentmemory_mcp/models.py` maps to `tests/test_models.py`.
- Put reusable fakes in non-collected modules such as `tests/_batch_memory_shared.py`; keep global policy hooks in `tests/conftest.py`.

**Naming:**
- Use `test_<subject>.py` files and `test_<behavior>()` functions.
- Give doubles behavior-revealing names such as `FakeMarkItDown` in `tests/test_document_processing.py` and `RecordingMemoryStore` in `tests/_batch_memory_shared.py`.

**Structure:**
```text
tests/
├── conftest.py
├── test_<production_subject>.py
├── test_<integration_subject>.py
└── _<domain>_shared.py
```

## Test Structure

**Suite Organization:**
```python
def test_convert_document_to_markdown_rejects_empty_output(tmp_path):
    source = tmp_path / "empty.pdf"
    source.write_bytes(b"%PDF")
    with pytest.raises(ValueError, match="empty markdown"):
        convert_document_to_markdown(source, converter=FakeMarkItDown("  \n"))
```
This arrange/act/assert pattern appears in `tests/test_document_processing.py`.

**Patterns:**
- Arrange explicit inputs/fakes, call one behavior, then assert outputs and important side effects.
- Use `tmp_path` for filesystem, SQLite, uploads, and projections, as in `tests/test_document_jobs.py`.
- Use `monkeypatch` for environment and dependency seams, as in `tests/test_auth.py`.
- Use `@pytest.mark.parametrize` for validation matrices, as in `tests/test_community_detection.py`.
- Use module-scoped fixtures only for expensive live resources and tear them down explicitly, as in `tests/test_arcadedb_client.py`.

## Mocking

**Framework:** pytest `monkeypatch` plus hand-written fakes, stubs, and recording implementations.

**Patterns:**
```python
monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
with pytest.raises(RuntimeError, match="ArcadeDB HTTP 500"):
    client.command("SELECT FROM V")
```
This transport seam is used in `tests/test_arcadedb_client_transport.py`.

**What to Mock:**
- Mock network transports, providers, environment configuration, and narrow protocols when testing local behavior.
- Use recording fakes for batching, transaction sessions, bound parameters, and call order, as in `tests/test_store_arcadedb_core.py`.

**What NOT to Mock:**
- Do not mock the live ArcadeDB capability contract in `@pytest.mark.integration` tests such as `tests/test_arcadedb_client.py`.
- Use real temporary bytes, hashes, cleanup, and SQLite state where `tmp_path` suffices, as in `tests/test_document_file_pipe.py`.
- Never count skipped integration/GPU tests as CI success; `tests/conftest.py` converts marked skips to failures under `CI=true`.

## Fixtures and Factories

**Test Data:**
```python
class RecordingMemoryStore(TuringAgentMemory):
    def __init__(self, tmp_path: Path, embedder: CountingBatchEmbedder) -> None:
        super().__init__(client=object(), turing_home=tmp_path, embedder=embedder, reranker=None)
        self.write_queries: list[str] = []
```
The full recording-fake pattern is in `tests/_batch_memory_shared.py`.

**Location:**
- Shared domain fixtures live in `tests/_*_shared.py`.
- Local fakes/factories stay beside their consumer, such as `_make_store()` in `tests/test_store_arcadedb_core.py`.
- Repository-wide hooks live in `tests/conftest.py`.

## Coverage

**Requirements:** `.github/workflows/ci.yml` enforces 78% coverage of `src/turing_agentmemory_mcp` for the non-integration/non-GPU suite. `pyproject.toml` omits `*/e2e_score*.py`.

**View Coverage:**
```bash
python -m pytest -m "not integration and not gpu" --cov=src/turing_agentmemory_mcp --cov-report=term-missing --cov-fail-under=78 -q
```

## Test Types

**Unit Tests:**
- Default tests emphasize deterministic in-memory fakes, local SQLite/filesystem state, and monkeypatched transports.
- Run the narrowest affected file first, then the full gate in `CONTRIBUTING.md`.

**Integration Tests:**
- Mark live-service tests `@pytest.mark.integration`; `tests/test_arcadedb_client.py` is canonical.
- Mark GPU-provider tests `@pytest.mark.gpu`; apply the same no-skip-as-green rule from `tests/conftest.py`.
- Mark expensive deterministic tests `slow`; `scripts/run-fast-tests.sh` excludes them only from the fast pre-push subset.

**E2E Tests:**
- `scripts/e2e_score.py` is the deterministic E2E score gate, called by `make e2e` and `.github/workflows/ci.yml`.
- CI requires valid JSON, exactly 19 checks, score >= 9.8, and verdict `VALIDATED_10_10` against live ArcadeDB.
- Operator-run real-document benchmarks live in `scripts/real_document_benchmark.py`, with tests in `tests/test_real_document_benchmark.py`.

## Common Patterns

**Async Testing:**
```python
accepted = asyncio.run(verifier.verify_token("dev-secret"))
assert accepted is not None
```
Tests drive async boundaries with `asyncio.run()`, as in `tests/test_auth.py`; no async pytest plugin is configured.

**Error Testing:**
```python
with pytest.raises(ValueError, match="empty markdown"):
    convert_document_to_markdown(source, converter=FakeMarkItDown("  \n"))
```
Assert exception type and stable diagnostic text, as in `tests/test_document_processing.py` and `tests/test_document_jobs.py`.

**Policy tests:**
- Encode workflow invariants in `tests/test_ci_hook_wiring.py`, `tests/test_compose_config.py`, `tests/test_docker_hardening.py`, and `tests/test_no_skip_as_green_guard.py`.
- Test security/durability directly in `tests/test_arcadedb_tenant_isolation.py`, `tests/test_document_file_pipe.py`, and `tests/test_store_arcadedb_core.py`.

---

*Testing analysis: 2026-07-14*
