# GLiNER2 Entity Extraction Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run `fastino/gliner2-base-v1` once in a cached CPU sidecar, route every MCP ingest through it, and prove the complete GPU embedding, GPU rerank, entity extraction, persistence, and LoCoMo paths.

**Architecture:** A non-root CPU-only HTTP provider loads GLiNER2 once and exposes `/health` and `/extract`. `entity_extraction.py` gains an HTTP processor and official GLiNER2 response normalization; `store.py` sends message batches through one extraction request before any graph or vector write. Compose makes the provider a healthy dependency and persists its Hugging Face cache.

**Tech Stack:** Python 3.12, stdlib `http.server` and `urllib`, `gliner2[local]==1.3.2`, Docker Compose, TuringDB, FastMCP, pytest, CUDA llama.cpp sidecars.

**Execution context:** Use the current workspace. It contains the uncommitted Granite/Qwen sidecar work required by this feature. Do not reset, checkout, or replace those changes, and do not add benchmark logs to commits.

---

## File Map

- Create `src/turing_agentmemory_mcp/gliner_provider.py`: one-process GLiNER2 HTTP provider and request validation.
- Create `docker/gliner-provider.Dockerfile`: pinned, cached, non-root CPU image.
- Create `tests/test_gliner_provider.py`: provider contract tests with an injected fake model.
- Create `tests/test_backboard_locomo_runner.py`: benchmark entity-proof aggregation tests.
- Modify `src/turing_agentmemory_mcp/entity_extraction.py`: nested response normalization, HTTP processor, and batching.
- Modify `src/turing_agentmemory_mcp/store.py`: batch entity processing before writes.
- Modify `tests/test_entity_extraction.py`: official GLiNER2 shape and HTTP client tests.
- Modify `tests/test_store_entity_processing.py`: one-call batch and fail-before-write tests.
- Modify `tests/test_docker_hardening.py`: provider image, cache, health, and Compose routing assertions.
- Modify `scripts/eval_backboard_locomo_mcp.py`: record and require the real entity model during benchmark ingestion.
- Modify `pyproject.toml`: pin the local GLiNER2 optional dependency.
- Modify `compose.yaml`: add and enable the CPU provider without changing frontend or GPU ports.
- Modify `README.md`: document the production GLiNER2 path and cache.

### Task 0: Preserve The Verified GPU Provider Baseline

**Files:**
- Existing: `README.md`
- Existing: `compose.yaml`
- Existing: `docker/llama-provider.Dockerfile`
- Existing: `src/turing_agentmemory_mcp/rerank.py`
- Existing: `tests/test_docker_hardening.py`
- Existing: `tests/test_rerank.py`

- [ ] **Step 1: Verify only the known baseline files are selected**

Run:

```powershell
git diff -- README.md compose.yaml src/turing_agentmemory_mcp/rerank.py tests/test_docker_hardening.py tests/test_rerank.py
git status --short docker/llama-provider.Dockerfile
```

Expected: Granite embedding, Qwen reranking, lexical fallback, TuringDB health cadence, and the llama provider Dockerfile are present. No GLiNER2 implementation is present yet.

- [ ] **Step 2: Run the baseline verification**

Run:

```powershell
python -m pytest tests/test_docker_hardening.py tests/test_rerank.py tests/test_admin_repair.py -q
docker compose config --quiet
```

Expected: `26 passed` and Compose exits 0.

- [ ] **Step 3: Commit only the baseline product files**

```powershell
git add README.md compose.yaml docker/llama-provider.Dockerfile src/turing_agentmemory_mcp/rerank.py tests/test_docker_hardening.py tests/test_rerank.py
git commit -m "feat: run retrieval models in GPU sidecars"
```

Expected: benchmark JSON/log files and `scripts/eval_backboard_locomo_mcp.py` remain untracked.

### Task 1: Normalize The Official GLiNER2 Response

**Files:**
- Modify: `tests/test_entity_extraction.py`
- Modify: `src/turing_agentmemory_mcp/entity_extraction.py:120-235`

- [ ] **Step 1: Replace the fake native GLiNER2 result with the official nested shape**

In `test_gliner2_processor_uses_extract_entities`, return:

```python
return {
    "entities": {
        "email": [
            {
                "text": "alice@example.com",
                "start": 6,
                "end": 23,
                "confidence": 0.94,
            }
        ]
    }
}
```

Assert the normalized metadata contains:

```python
assert result.metadata["entity_extraction"]["entities"] == [
    {
        "text": "alice@example.com",
        "label": "email",
        "start": 6,
        "end": 23,
        "score": 0.94,
    }
]
```

Add a separate test where the nested entry has `end` beyond the source length and assert the entity is omitted.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_entity_extraction.py::test_gliner2_processor_uses_extract_entities -q
```

Expected: FAIL because `_predict()` converts the dictionary to `['entities']` and normalization returns zero entities.

- [ ] **Step 3: Implement nested-result flattening**

Change native `_predict()` to return the provider payload unchanged:

```python
if self.backend == "gliner2":
    return self.model.extract_entities(
        text,
        self.labels,
        threshold=self.threshold,
        include_confidence=True,
        include_spans=True,
    )
```

Add this helper and call it at the start of `_normalize_entities`:

```python
def _flatten_entities(raw: Any) -> list[Any]:
    if isinstance(raw, dict) and isinstance(raw.get("entities"), dict):
        flattened: list[Any] = []
        for label, values in raw["entities"].items():
            for value in values or []:
                if isinstance(value, dict):
                    flattened.append({**value, "label": str(label)})
                elif isinstance(value, str):
                    flattened.append({"label": str(label), "text": value})
        return flattened
    if isinstance(raw, list):
        return raw
    return []
```

Update `_normalize_entities(raw_entities: Any, ...)` to iterate over `_flatten_entities(raw_entities)`. Keep `confidence` as an accepted alias for `score`.

- [ ] **Step 4: Run focused and entity-store tests**

Run:

```powershell
python -m pytest tests/test_entity_extraction.py tests/test_store_entity_processing.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the normalization fix**

```powershell
git add src/turing_agentmemory_mcp/entity_extraction.py tests/test_entity_extraction.py
git commit -m "fix: normalize native GLiNER2 entity results"
```

### Task 2: Add The Shared GLiNER2 Provider

**Files:**
- Create: `src/turing_agentmemory_mcp/gliner_provider.py`
- Create: `tests/test_gliner_provider.py`

- [ ] **Step 1: Write provider contract tests with no model download**

Create a fake model and assert validation, ordering, and model metadata:

```python
class FakeModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def batch_extract_entities(self, texts, labels, **kwargs):
        self.calls.append({"texts": texts, "labels": labels, **kwargs})
        return [
            {"entities": {"person": [{"text": text.split()[0], "start": 0, "end": len(text.split()[0])}]}}
            for text in texts
        ]


def test_provider_extracts_batch_in_input_order() -> None:
    model = FakeModel()
    provider = GLiNERProvider(
        model=model,
        model_name="fastino/gliner2-base-v1",
        device="cpu",
        batch_size=8,
    )
    result = provider.extract(
        {
            "texts": ["Alice builds", "Bob tests"],
            "labels": ["person"],
            "threshold": 0.5,
            "include_confidence": True,
            "include_spans": True,
        }
    )
    assert result["model"] == "fastino/gliner2-base-v1"
    assert result["device"] == "cpu"
    assert [row["entities"]["person"][0]["text"] for row in result["results"]] == ["Alice", "Bob"]
    assert model.calls[0]["batch_size"] == 8
```

Add tests asserting empty `texts`, empty `labels`, non-string entries, and a wrong result count raise `ValueError` before a response is emitted.

- [ ] **Step 2: Run provider tests and verify RED**

Run:

```powershell
python -m pytest tests/test_gliner_provider.py -q
```

Expected: collection fails because `turing_agentmemory_mcp.gliner_provider` does not exist.

- [ ] **Step 3: Implement the provider core**

Create `GLiNERProvider` with injected `model`, `model_name`, `device`, `batch_size`, and a `threading.Lock`. Validate the payload, call `batch_extract_entities` under the lock, and return:

```python
{
    "model": self.model_name,
    "device": self.device,
    "results": results,
}
```

Implement a stdlib `BaseHTTPRequestHandler` that:

```python
GET  /health  -> {"status": "ok", "model": ..., "device": "cpu"}
POST /extract -> provider.extract(decoded_json)
```

Return JSON 400 for `ValueError`, JSON 500 for unexpected extraction errors, and 404 for unknown paths. Log only path, status, text count, and elapsed milliseconds.

In `main()`, load exactly once:

```python
model_name = os.environ.get("GLINER_MODEL", "fastino/gliner2-base-v1")
batch_size = int(os.environ.get("GLINER_BATCH_SIZE", "8"))
model = GLiNER2.from_pretrained(model_name, map_location="cpu")
serve(GLiNERProvider(model=model, model_name=model_name, device="cpu", batch_size=batch_size))
```

Use one Python process. `ThreadingHTTPServer` may accept concurrent requests, but the provider lock must serialize model access.

- [ ] **Step 4: Run provider tests and lint**

Run:

```powershell
python -m pytest tests/test_gliner_provider.py -q
python -m ruff check src/turing_agentmemory_mcp/gliner_provider.py tests/test_gliner_provider.py
```

Expected: all provider tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit the provider contract**

```powershell
git add src/turing_agentmemory_mcp/gliner_provider.py tests/test_gliner_provider.py
git commit -m "feat: add shared GLiNER2 HTTP provider"
```

### Task 3: Add The MCP HTTP Entity Processor

**Files:**
- Modify: `tests/test_entity_extraction.py`
- Modify: `src/turing_agentmemory_mcp/entity_extraction.py`

- [ ] **Step 1: Write failing HTTP processor tests**

Monkeypatch `urlopen` with a response containing two nested GLiNER2 results. Construct the processor from environment:

```python
monkeypatch.setenv("GLINER_ENABLED", "1")
monkeypatch.setenv("GLINER_BACKEND", "gliner2_http")
monkeypatch.setenv("GLINER_BASE_URL", "http://agentmemory-gliner:8080")
monkeypatch.setenv("GLINER_MODEL", "fastino/gliner2-base-v1")
monkeypatch.setenv("GLINER_LABELS", "person,project")
processor = entity_processor_from_env()
results = processor.process_many(["Alice builds TuringDB", "Bob tests FastMCP"])
```

Assert one POST to `/extract`, both texts in one payload, input-order results, model metadata, spans, and scores. Add tests for HTTP 500 and a one-result response for two texts; both must raise `RuntimeError`.

- [ ] **Step 2: Run the HTTP tests and verify RED**

Run:

```powershell
python -m pytest tests/test_entity_extraction.py -k "http" -q
```

Expected: FAIL because `gliner2_http` is not a supported backend and no `process_many` method exists.

- [ ] **Step 3: Implement `HTTPGLiNEREntityProcessor`**

Add fields for `base_url`, `model_name`, `labels`, `threshold`, `redact`, `metadata_key`, and `timeout_s`. `from_env()` reads `GLINER_BASE_URL` and `GLINER_TIMEOUT_SECONDS`.

`process_many()` must POST this exact payload:

```python
payload = {
    "texts": texts,
    "labels": self.labels,
    "threshold": self.threshold,
    "include_confidence": True,
    "include_spans": True,
}
```

Use the existing `urllib` provider pattern. Convert `HTTPError`, `URLError`, JSON errors, OS errors, and timeout errors into a `RuntimeError` that names the provider URL but never includes source text. Validate that `len(results) == len(texts)`.

Refactor result-to-`ProcessedText` logic into a shared helper so native and HTTP processors use identical normalization and redaction. Implement `process(text)` as `process_many([text])[0]`. Select the HTTP class in `entity_processor_from_env()` before `_load_model()` is called.

- [ ] **Step 4: Run all entity tests**

Run:

```powershell
python -m pytest tests/test_entity_extraction.py tests/test_store_entity_processing.py -q
```

Expected: all tests pass, including legacy native and ONNX backends.

- [ ] **Step 5: Commit the MCP client**

```powershell
git add src/turing_agentmemory_mcp/entity_extraction.py tests/test_entity_extraction.py
git commit -m "feat: call GLiNER2 through shared HTTP provider"
```

### Task 4: Batch Entity Extraction Before Store Writes

**Files:**
- Modify: `tests/test_store_entity_processing.py`
- Modify: `src/turing_agentmemory_mcp/store.py:135-255`
- Modify: `src/turing_agentmemory_mcp/store.py:1230-1242`

- [ ] **Step 1: Write failing one-call batch and atomic-failure tests**

Add a processor that records `process_many` calls and raises on demand:

```python
class BatchEntityProcessor:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def process(self, text: str) -> ProcessedText:
        raise AssertionError("batch store must use process_many")

    def process_many(self, texts: list[str]) -> list[ProcessedText]:
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return [ProcessedText(text=text, metadata={}) for text in texts]
```

Store two messages and assert one call containing both texts. In a second test, set `fail=True` and assert `write_queries`, `vector_loads`, and embedder calls remain empty.

- [ ] **Step 2: Run the two tests and verify RED**

Run:

```powershell
python -m pytest tests/test_store_entity_processing.py -k "batch_entity or extraction_failure" -q
```

Expected: FAIL because `store_messages()` currently invokes `process()` once per message.

- [ ] **Step 3: Implement `_process_texts_for_storage`**

Move redaction and metadata preparation into a batch helper:

```python
def _process_texts_for_storage(
    self,
    rows: list[tuple[str, dict[str, object]]],
) -> list[tuple[str, dict[str, object]]]:
    redacted_rows = [self._redact_for_storage(text, metadata) for text, metadata in rows]
    texts = [text for text, _ in redacted_rows]
    process_many = getattr(self.entity_processor, "process_many", None)
    processed = process_many(texts) if callable(process_many) else [self.entity_processor.process(text) for text in texts]
    if len(processed) != len(rows):
        raise RuntimeError(f"entity processor returned {len(processed)} results for {len(rows)} inputs")
    return [self._merge_entity_metadata(item, metadata) for item, (_, metadata) in zip(processed, redacted_rows, strict=True)]
```

Keep `_process_text_for_storage()` as a one-row wrapper. Restructure `store_messages()` to validate and collect all raw rows, call `_process_texts_for_storage()` once, then compute IDs, embeddings, graph writes, and vector loads. No persistence method may run before the batch helper returns successfully.

- [ ] **Step 4: Run batch, governance, and store tests**

Run:

```powershell
python -m pytest tests/test_store_entity_processing.py tests/test_batch_memory.py tests/test_governance.py -q
```

Expected: all tests pass and duplicate-safe behavior remains unchanged.

- [ ] **Step 5: Commit atomic batch extraction**

```powershell
git add src/turing_agentmemory_mcp/store.py tests/test_store_entity_processing.py
git commit -m "feat: batch entity extraction before memory writes"
```

### Task 5: Containerize And Enable The Cached CPU Sidecar

**Files:**
- Create: `docker/gliner-provider.Dockerfile`
- Modify: `pyproject.toml:24-28`
- Modify: `compose.yaml`
- Modify: `tests/test_docker_hardening.py`

- [ ] **Step 1: Add failing Docker and Compose assertions**

Extend `test_runtime_dockerfiles_pin_base_image_and_run_as_non_root` to read the new Dockerfile and match:

```python
PINNED_GLINER_PYTHON_RE = re.compile(
    r"^FROM python:3\.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf$",
    re.MULTILINE,
)
```

Add `test_compose_routes_mcp_to_cached_cpu_gliner_sidecar` asserting:

```python
gliner = services["agentmemory-gliner"]
assert "gpus" not in gliner
assert gliner["read_only"] is True
assert gliner["user"] == "10001:10001"
assert "agentmemory-gliner-cache:/models" in gliner["volumes"]
assert gliner["healthcheck"]["retries"] >= 80
assert services["turing-agentmemory-mcp"]["depends_on"]["agentmemory-gliner"]["condition"] == "service_healthy"
app_env = set(services["turing-agentmemory-mcp"]["environment"])
assert "GLINER_ENABLED=1" in app_env
assert "GLINER_BACKEND=gliner2_http" in app_env
assert "GLINER_MODEL=fastino/gliner2-base-v1" in app_env
assert "GLINER_BASE_URL=http://agentmemory-gliner:8080" in app_env
```

- [ ] **Step 2: Run hardening tests and verify RED**

Run:

```powershell
python -m pytest tests/test_docker_hardening.py -q
```

Expected: FAIL because the Dockerfile, service, cache volume, and enabled env do not exist.

- [ ] **Step 3: Create the provider Dockerfile**

Use this structure:

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

ENV HOME=/models \
    HF_HOME=/models/huggingface \
    XDG_CACHE_HOME=/models/.cache \
    PYTHONPATH=/app/src \
    PYTHONPYCACHEPREFIX=/tmp/pycache

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /models --shell /usr/sbin/nologin app \
    && mkdir -p /app/src /models /tmp /run \
    && chown -R app:app /app /models /tmp /run

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --root-user-action=ignore "gliner2[local]==1.3.2"

COPY src/ /app/src/
RUN chown -R app:app /app/src

USER app
EXPOSE 8080
ENTRYPOINT ["python", "-m", "turing_agentmemory_mcp.gliner_provider"]
```

Pin `gliner2[local]==1.3.2` in the `gliner` optional extra in `pyproject.toml` as well.

- [ ] **Step 4: Add the Compose service and MCP dependency**

Add `agentmemory-gliner` with model/batch/host/port environment, `expose: ["8080"]`, the named cache, non-root/read-only hardening, `/tmp` and `/run` tmpfs mounts, `restart: unless-stopped`, and CPU/RAM limits from the spec. Its healthcheck calls `http://127.0.0.1:8080/health` with Python `urllib.request.urlopen`.

Set the MCP environment to the exact four asserted values and add `GLINER_TIMEOUT_SECONDS=120`. Add `agentmemory-gliner-cache:` under top-level volumes. Do not add a host port and do not change `agentmemory-lab` port `8096`.

- [ ] **Step 5: Verify Compose and hardening tests GREEN**

Run:

```powershell
python -m pytest tests/test_docker_hardening.py -q
docker compose config --quiet
docker compose config --services
```

Expected: hardening tests pass, config exits 0, and services include `agentmemory-gliner` and `agentmemory-lab`.

- [ ] **Step 6: Commit the container wiring**

```powershell
git add docker/gliner-provider.Dockerfile pyproject.toml compose.yaml tests/test_docker_hardening.py
git commit -m "feat: enable cached CPU GLiNER2 sidecar"
```

### Task 6: Prove GLiNER2 Use In Benchmark Artifacts

**Files:**
- Create: `tests/test_backboard_locomo_runner.py`
- Modify: `scripts/eval_backboard_locomo_mcp.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing benchmark aggregation tests**

Extract a pure helper and test these stored MCP results:

```python
rows = [
    {"metadata": {"entity_extraction": {"model": "fastino/gliner2-base-v1", "entity_count": 2}}},
    {"metadata": {}},
]
assert summarize_entity_extraction(rows) == {
    "annotated_memories": 1,
    "entities": 2,
    "models": ["fastino/gliner2-base-v1"],
}
```

Add a test asserting `require_entity_model(summary, "fastino/gliner2-base-v1")` raises when the model list is empty or different.

- [ ] **Step 2: Run the benchmark helper tests and verify RED**

Run:

```powershell
python -m pytest tests/test_backboard_locomo_runner.py -q
```

Expected: FAIL because the helper functions do not exist.

- [ ] **Step 3: Add model proof to ingestion and output**

Accumulate `annotated_memories`, `entities`, and unique models from every `memory_store_messages` result. Add `--require-entity-model` with default `fastino/gliner2-base-v1`. Fail immediately after the first completed conversation if no stored result reports that model.

Add the aggregate under:

```json
"entity_extraction": {
  "required_model": "fastino/gliner2-base-v1",
  "annotated_memories": 1,
  "entities": 2,
  "models": ["fastino/gliner2-base-v1"]
}
```

Keep all ingest and search operations as MCP tool calls; do not read TuringDB directly in the evaluator.

- [ ] **Step 4: Update the README**

Replace the Docker in-process GLiNER instructions with the production sidecar contract, cache volume, CPU placement, exact model, and `GLINER_BASE_URL`. State that native and ONNX backends remain available for non-Docker use.

- [ ] **Step 5: Run tests and compile the evaluator**

Run:

```powershell
python -m pytest tests/test_backboard_locomo_runner.py tests/test_entity_extraction.py -q
python -m py_compile scripts/eval_backboard_locomo_mcp.py
```

Expected: all tests pass and compilation exits 0.

- [ ] **Step 6: Commit benchmark proof and docs**

```powershell
git add scripts/eval_backboard_locomo_mcp.py tests/test_backboard_locomo_runner.py README.md
git commit -m "test: require GLiNER2 in direct MCP benchmark"
```

### Task 7: Build And Validate The Real Product Stack

**Files:**
- Runtime validation only

- [ ] **Step 1: Run the full local test gate**

Run:

```powershell
python -m pytest -q
python -m ruff check src tests scripts
docker compose config --quiet
```

Expected: zero failures and zero lint errors.

- [ ] **Step 2: Build with cache and health cadence**

Run `docker compose build agentmemory-gliner turing-agentmemory-mcp`. Do not use `--no-cache`. Capture build output under `.benchmarks`, poll the build process and Docker health regularly, and do not impose a run-level timeout.

Expected: BuildKit reuses pip layers when repeated and produces `turing-agentmemory-gliner:local` plus the MCP image.

- [ ] **Step 3: Start the complete repository**

Run:

```powershell
docker compose up -d
docker compose ps --format "{{.Service}}|{{.State}}|{{.Health}}|{{.Ports}}"
```

Poll until TuringDB, MCP, GLiNER2, Granite, Qwen, and Lab are healthy. Expected host ports remain `6666`, `8095`, and `8096`; GLiNER2 has no host port.

- [ ] **Step 4: Probe the real model and cache**

From the MCP container, POST two texts to `http://agentmemory-gliner:8080/extract`. Require model `fastino/gliner2-base-v1`, device `cpu`, two results, and at least one valid span. Inspect sidecar process/GPU state and require no GLiNER process on CUDA.

Restart only `agentmemory-gliner`, wait for healthy, and inspect logs. Expected: the model loads from `agentmemory-gliner-cache`; no model file is downloaded again.

- [ ] **Step 5: Validate real metadata through direct MCP**

Use a FastMCP stdio client through `docker exec -i turing-agentmemory-mcp ... serve --transport stdio`. Call `memory_store_messages` for a fresh user with two entity-rich messages, then `memory_search`. Require returned metadata to name `fastino/gliner2-base-v1` and include valid entities.

- [ ] **Step 6: Run the product E2E score**

Run the existing Compose E2E command with external Granite and Qwen variables. Require `check_count: 19`, `score: 10.0`, and `VALIDATED_10_10`.

### Task 8: Run Full LoCoMo And Restart-Persistence Validation

**Files:**
- Runtime output: a UTC-stamped `.benchmarks/backboard-locomo-direct-mcp-*.json`

- [ ] **Step 1: Start a fresh full benchmark scope**

Run:

```powershell
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$scope = "bench-backboard-locomo-gliner2-$stamp"
$output = ".benchmarks/backboard-locomo-direct-mcp-$stamp.json"
python -u scripts/eval_backboard_locomo_mcp.py --top-k 20 --batch-size 50 --scope-prefix $scope --require-entity-model fastino/gliner2-base-v1 --output $output
```

Launch it hidden with separate stdout/stderr logs. Do not reuse `20260710T090210Z` or any repaired vector scope.

- [ ] **Step 2: Monitor by conditions, not a wall-clock timeout**

At a regular cadence, verify evaluator progress, all Compose health states, GPU utilization, empty benchmark error signals, and no TuringDB `corrupt`, `invalid`, `fatal`, `panic`, or `failed` messages. Stop only on process completion or a concrete unhealthy/error condition.

- [ ] **Step 3: Validate the completed artifact**

Require:

```text
conversations = 10
turns = 5882
evaluated_questions = 1540
search_errors = 0
entity_extraction.models = ["fastino/gliner2-base-v1"]
entity_extraction.annotated_memories > 0
entity_extraction.entities > 0
```

Report evidence retrieval at 1, 3, 5, 10, and 20 separately from Mem0's answer-judge score.

- [ ] **Step 4: Verify persistence after a controlled restart**

Stop MCP, restart TuringDB, wait for healthy, start MCP, and wait for all dependencies healthy. Rerun one completed conversation with `--skip-ingest`, the same scope, and top-k 20. Compare its metrics to the matching conversation in the full artifact and require equality.

- [ ] **Step 5: Verify vector integrity and final repository state**

Scan TuringDB logs after restart, inspect vector index metadata, run `python -m pytest -q`, and run `docker compose ps`. Require no corruption and all product services healthy.

- [ ] **Step 6: Commit any verification-only test adjustment, never benchmark logs**

If no source adjustment was needed, create no commit. If a test-only adjustment was required, stage that exact test path, run its full verification, and commit it separately. Leave `.benchmarks/*.log` and generated benchmark JSON outside product commits unless the user explicitly requests benchmark fixtures.
