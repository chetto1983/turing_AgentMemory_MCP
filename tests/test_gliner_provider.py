from __future__ import annotations

import signal
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from _gliner_provider_shared import extract_payload, memory_payload, memory_result

import turing_agentmemory_mcp.gliner_provider as gliner_provider
import turing_agentmemory_mcp.gliner_provider_extraction as gliner_provider_extraction
from turing_agentmemory_mcp.gliner_provider import FastGLiNER2Adapter, GLiNERProvider
from turing_agentmemory_mcp.memory_extraction import MEMORY_EXTRACTION_SCHEMA_VERSION


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def batch_extract_entities(
        self,
        texts: list[str],
        labels: list[str],
        *,
        batch_size: int,
        threshold: float,
        include_confidence: bool,
        include_spans: bool,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "texts": texts,
                "labels": labels,
                "batch_size": batch_size,
                "threshold": threshold,
                "include_confidence": include_confidence,
                "include_spans": include_spans,
            }
        )
        return [
            {
                "entities": {
                    label: [
                        {
                            "text": text,
                            "start": 0,
                            "end": len(text),
                            "confidence": 0.9,
                        }
                    ]
                    for label in labels
                }
            }
            for text in texts
        ]


class ConcurrentEntityModel:
    def __init__(
        self,
        *,
        delays: dict[str, float] | None = None,
        responses: dict[str, object] | None = None,
        failure_text: str | None = None,
    ) -> None:
        self.delays = delays or {}
        self.responses = responses or {}
        self.failure_text = failure_text
        self.calls: list[str] = []
        self.completions: list[str] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def predict_entities(self, text: str, labels: list[str]) -> object:
        if isinstance(text, list):
            raise AssertionError("FastGLiNER2 accepts one string per inference")
        with self.lock:
            self.calls.append(text)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delays.get(text, 0.01))
            if text == self.failure_text:
                raise RuntimeError("single-text inference failed")
            return self.responses.get(
                text,
                [{"text": text, "label": labels[0], "score": 0.9, "start": 0, "end": len(text)}],
            )
        finally:
            with self.lock:
                self.active -= 1
                self.completions.append(text)


def run_concurrent_batch(
    model: ConcurrentEntityModel,
    texts: list[str],
    *,
    batch_size: int,
    include_confidence: bool = True,
    include_spans: bool = True,
) -> list[list[dict[str, object]]]:
    return FastGLiNER2Adapter(model).batch_extract_entities(
        texts,
        ["project"],
        batch_size=batch_size,
        threshold=0.5,
        include_confidence=include_confidence,
        include_spans=include_spans,
    )


def test_concurrent_batch_preserves_input_order_count_and_single_string_calls() -> None:
    texts = ["slowest", "slower", "faster", "fastest"]
    model = ConcurrentEntityModel(delays=dict(zip(texts, [0.16, 0.12, 0.08, 0.04], strict=True)))

    results = run_concurrent_batch(model, texts, batch_size=4)

    assert [entities[0]["text"] for entities in results] == texts
    assert len(results) == len(texts)
    assert sorted(model.calls) == sorted(texts)
    assert model.max_active == 4
    assert model.completions == list(reversed(texts))


def test_concurrent_batch_bounds_calls_in_flight() -> None:
    texts = [f"text-{index}" for index in range(8)]
    model = ConcurrentEntityModel(delays=dict.fromkeys(texts, 0.04))

    results = run_concurrent_batch(model, texts, batch_size=2)

    assert len(results) == len(texts)
    assert len(model.calls) == len(texts)
    assert model.max_active == 2


def test_batch_size_semantics_are_concurrency_width_not_model_batch_size() -> None:
    texts = [f"text-{index}" for index in range(12)]
    model = ConcurrentEntityModel(delays=dict.fromkeys(texts, 0.04))

    results = run_concurrent_batch(model, texts, batch_size=4)

    assert len(results) == 12
    assert len(model.calls) == 12
    assert model.max_active == 4


def test_concurrent_batch_size_one_stays_sequential_and_ordered() -> None:
    texts = ["first", "second", "third"]
    model = ConcurrentEntityModel(delays=dict.fromkeys(texts, 0.01))

    results = run_concurrent_batch(model, texts, batch_size=1)

    assert [entities[0]["text"] for entities in results] == texts
    assert model.calls == texts
    assert model.max_active == 1


def test_concurrent_batch_empty_input_does_not_construct_pool(monkeypatch) -> None:
    def fail_pool_construction(*args: object, **kwargs: object) -> None:
        pytest.fail("empty input must not construct a thread pool")

    monkeypatch.setattr(
        gliner_provider_extraction,
        "ThreadPoolExecutor",
        fail_pool_construction,
        raising=False,
    )
    model = ConcurrentEntityModel()

    assert run_concurrent_batch(model, [], batch_size=4) == []
    assert model.calls == []


@pytest.mark.parametrize(
    ("include_confidence", "include_spans", "expected"),
    [
        (False, False, {"text": "Alice", "label": "person"}),
        (
            True,
            True,
            {"text": "Alice", "label": "person", "score": 0.9, "start": 0, "end": 5},
        ),
    ],
)
def test_concurrent_batch_preserves_entity_filters(
    include_confidence: bool,
    include_spans: bool,
    expected: dict[str, object],
) -> None:
    text = "Alice works here"
    model = ConcurrentEntityModel(
        responses={
            text: [
                "not-a-dict",
                {"text": "Alice", "label": "person", "score": True, "start": 0, "end": 5},
                {"text": "Alice", "label": "person", "score": "0.9", "start": 0, "end": 5},
                {"text": "Alice", "label": "person", "score": float("nan"), "start": 0, "end": 5},
                {"text": "Alice", "label": "person", "score": 0.49, "start": 0, "end": 5},
                {"text": "Alice", "label": "person", "score": 0.9, "start": 0, "end": 5},
            ]
        }
    )

    assert run_concurrent_batch(
        model,
        [text],
        batch_size=2,
        include_confidence=include_confidence,
        include_spans=include_spans,
    ) == [[expected]]


def test_concurrent_batch_propagates_single_text_error() -> None:
    model = ConcurrentEntityModel(failure_text="broken")

    with pytest.raises(RuntimeError, match="single-text inference failed"):
        run_concurrent_batch(model, ["first", "broken", "third"], batch_size=2)


def test_concurrent_batch_rejects_non_list_model_result() -> None:
    model = ConcurrentEntityModel(responses={"broken": {"not": "a list"}})

    with pytest.raises(ValueError, match="FastGLiNER2 returned a non-list result"):
        run_concurrent_batch(model, ["broken"], batch_size=2)


def test_extract_memory_requires_schema_version_and_preserves_order() -> None:
    class MemoryModel(FakeModel):
        def batch_extract_memory(
            self,
            texts: list[str],
            *,
            batch_size: int,
            threshold: float,
        ) -> list[dict[str, object]]:
            self.calls.append(
                {
                    "texts": texts,
                    "batch_size": batch_size,
                    "threshold": threshold,
                }
            )
            return [memory_result() for _ in texts]

    model = MemoryModel()
    provider = GLiNERProvider(
        model=model,
        model_name="lion-ai/gliner2-base-v1-onnx",
        device="cuda",
        batch_size=4,
    )

    result = provider.extract_memory(memory_payload(texts=["first", "second"]))

    assert result == {
        "model": "lion-ai/gliner2-base-v1-onnx",
        "device": "cuda",
        "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
        "results": [memory_result(), memory_result()],
    }
    assert model.calls == [{"texts": ["first", "second"], "batch_size": 4, "threshold": 0.5}]


@pytest.mark.parametrize(
    "payload",
    [
        memory_payload(schema_version="memory-v0"),
        memory_payload(schema_version=None),
        memory_payload(threshold=-0.1),
        memory_payload(threshold=float("inf")),
    ],
)
def test_extract_memory_rejects_invalid_contract(payload: dict[str, object]) -> None:
    provider = GLiNERProvider(model=FakeModel())

    with pytest.raises(ValueError):
        provider.extract_memory(payload)


def test_extract_preserves_input_order_and_passes_batch_options() -> None:
    model = FakeModel()
    provider = GLiNERProvider(model=model, model_name="fastino/gliner2-base-v1", batch_size=8)

    result = provider.extract(extract_payload())

    assert result == {
        "model": "fastino/gliner2-base-v1",
        "device": "cpu",
        "results": [
            {
                "entities": {
                    "project": [
                        {
                            "text": "first source text",
                            "start": 0,
                            "end": 17,
                            "confidence": 0.9,
                        }
                    ],
                    "person": [
                        {
                            "text": "first source text",
                            "start": 0,
                            "end": 17,
                            "confidence": 0.9,
                        }
                    ],
                }
            },
            {
                "entities": {
                    "project": [
                        {
                            "text": "second source text",
                            "start": 0,
                            "end": 18,
                            "confidence": 0.9,
                        }
                    ],
                    "person": [
                        {
                            "text": "second source text",
                            "start": 0,
                            "end": 18,
                            "confidence": 0.9,
                        }
                    ],
                }
            },
        ],
    }
    assert model.calls == [
        {
            "texts": ["first source text", "second source text"],
            "labels": ["project", "person"],
            "batch_size": 8,
            "threshold": 0.42,
            "include_confidence": True,
            "include_spans": True,
        }
    ]


def test_health_payload_identifies_model_and_cpu_device() -> None:
    provider = GLiNERProvider(model=FakeModel(), model_name="fastino/gliner2-base-v1")

    assert provider.health_payload() == {
        "status": "ok",
        "model": "fastino/gliner2-base-v1",
        "device": "cpu",
    }


@pytest.mark.parametrize(
    "payload",
    [
        extract_payload(texts=[]),
        extract_payload(labels=[]),
        extract_payload(texts="not-a-list"),
        extract_payload(labels="not-a-list"),
        extract_payload(texts=["valid", "   "]),
        extract_payload(texts=["valid", 1]),
        extract_payload(labels=["valid", "   "]),
        extract_payload(labels=["valid", 1]),
        extract_payload(threshold=-0.01),
        extract_payload(threshold=1.01),
        extract_payload(threshold=float("nan")),
        extract_payload(threshold=True),
        extract_payload(include_confidence="true"),
        extract_payload(include_spans=1),
    ],
)
def test_extract_rejects_invalid_payloads(payload: dict[str, object]) -> None:
    provider = GLiNERProvider(model=FakeModel(), model_name="fastino/gliner2-base-v1")

    with pytest.raises(ValueError):
        provider.extract(payload)


def test_extract_rejects_provider_result_count_mismatch() -> None:
    class MismatchedModel(FakeModel):
        def batch_extract_entities(
            self, *args: object, **kwargs: object
        ) -> list[dict[str, object]]:
            return [{"entities": {}}]

    provider = GLiNERProvider(model=MismatchedModel(), model_name="fastino/gliner2-base-v1")

    with pytest.raises(ValueError, match="result count"):
        provider.extract(extract_payload())


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GLINER_MODEL", "   "),
        ("GLINER_HOST", "   "),
        ("GLINER_BATCH_SIZE", "0"),
        ("GLINER_BATCH_SIZE", "257"),
        ("GLINER_PORT", "0"),
        ("GLINER_PORT", "65536"),
        ("GLINER_MODEL_REVISION", "   "),
        ("GLINER_MODEL_REVISION", "main"),
        ("GLINER_DEVICE", "metal"),
    ],
)
def test_main_validates_settings_before_loading_model(monkeypatch, name: str, value: str) -> None:
    load_calls: list[tuple[str, object]] = []

    class FakeFastGLiNER2:
        @classmethod
        def from_pretrained(cls, model_name: str, **kwargs: object) -> object:
            load_calls.append((model_name, kwargs))
            return object()

    monkeypatch.setitem(sys.modules, "fast_gliner", SimpleNamespace(FastGLiNER2=FakeFastGLiNER2))
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        gliner_provider, "make_server", lambda *args, **kwargs: pytest.fail("server started")
    )

    with pytest.raises(ValueError):
        gliner_provider.main()

    assert load_calls == []


def test_main_loads_the_model_once_after_validating_settings(monkeypatch) -> None:
    load_calls: list[tuple[str, dict[str, object]]] = []
    download_calls: list[dict[str, object]] = []
    server_calls: list[object] = []

    class FakeFastGLiNER2:
        @classmethod
        def from_pretrained(cls, model_name: str, **kwargs: object) -> object:
            load_calls.append((model_name, kwargs))
            return object()

    class FakeServer:
        def serve_forever(self) -> None:
            server_calls.append("serve")

        def server_close(self) -> None:
            server_calls.append("close")

        def shutdown(self) -> None:
            server_calls.append("shutdown")

    def make_fake_server(provider: object, *, host: str, port: int) -> FakeServer:
        server_calls.append((provider, host, port))
        return FakeServer()

    def snapshot_download(**kwargs: object) -> str:
        download_calls.append(kwargs)
        return "/models/snapshot"

    class CacheMiss(Exception):
        pass

    monkeypatch.setitem(sys.modules, "fast_gliner", SimpleNamespace(FastGLiNER2=FakeFastGLiNER2))
    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download)
    )
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub.errors",
        SimpleNamespace(LocalEntryNotFoundError=CacheMiss),
    )
    monkeypatch.setattr(gliner_provider, "make_server", make_fake_server)
    monkeypatch.setattr(gliner_provider.signal, "signal", lambda *args: None)
    monkeypatch.setenv("GLINER_MODEL", "lion-ai/gliner2-base-v1-onnx")
    monkeypatch.setenv("GLINER_MODEL_REVISION", "5551729ccc76b30395bc9600f2348ec52a87cead")
    monkeypatch.setenv("GLINER_HOST", "127.0.0.1")
    monkeypatch.setenv("GLINER_BATCH_SIZE", "1")
    monkeypatch.setenv("GLINER_PORT", "8080")
    monkeypatch.setenv("GLINER_DEVICE", "cpu")

    gliner_provider.main()

    assert download_calls == [
        {
            "repo_id": "lion-ai/gliner2-base-v1-onnx",
            "revision": "5551729ccc76b30395bc9600f2348ec52a87cead",
            "allow_patterns": ["model.onnx", "tokenizer.json"],
            "local_files_only": True,
        }
    ]
    assert load_calls == [("/models/snapshot", {"execution_provider": "cpu"})]
    assert server_calls[1:] == ["serve", "close"]


def test_main_downloads_the_pinned_model_only_when_cache_is_absent(monkeypatch) -> None:
    download_calls: list[dict[str, object]] = []

    class CacheMiss(Exception):
        pass

    class FakeFastGLiNER2:
        @classmethod
        def from_pretrained(cls, model_name: str, **kwargs: object) -> object:
            return object()

    class FakeServer:
        def serve_forever(self) -> None:
            pass

        def server_close(self) -> None:
            pass

        def shutdown(self) -> None:
            pass

    def snapshot_download(**kwargs: object) -> str:
        download_calls.append(kwargs)
        if kwargs.get("local_files_only") is True:
            raise CacheMiss()
        return "/models/downloaded-snapshot"

    monkeypatch.setitem(sys.modules, "fast_gliner", SimpleNamespace(FastGLiNER2=FakeFastGLiNER2))
    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download)
    )
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub.errors",
        SimpleNamespace(LocalEntryNotFoundError=CacheMiss),
    )
    monkeypatch.setattr(gliner_provider, "make_server", lambda *args, **kwargs: FakeServer())
    monkeypatch.setattr(gliner_provider.signal, "signal", lambda *args: None)
    monkeypatch.setenv("GLINER_MODEL", "lion-ai/gliner2-base-v1-onnx")
    monkeypatch.setenv("GLINER_MODEL_REVISION", "5551729ccc76b30395bc9600f2348ec52a87cead")
    monkeypatch.setenv("GLINER_DEVICE", "cpu")

    gliner_provider.main()

    request = {
        "repo_id": "lion-ai/gliner2-base-v1-onnx",
        "revision": "5551729ccc76b30395bc9600f2348ec52a87cead",
        "allow_patterns": ["model.onnx", "tokenizer.json"],
    }
    assert download_calls == [request | {"local_files_only": True}, request]


def test_signal_handlers_shutdown_server_from_another_thread(monkeypatch) -> None:
    handlers: dict[int, object] = {}
    shutdown_called = threading.Event()

    class FakeServer:
        def shutdown(self) -> None:
            shutdown_called.set()

    monkeypatch.setattr(
        gliner_provider.signal,
        "signal",
        lambda signum, handler: handlers.__setitem__(signum, handler),
    )

    gliner_provider._install_shutdown_signal_handlers(FakeServer())

    handler = handlers[signal.SIGTERM]
    assert callable(handler)
    handler(signal.SIGTERM, None)  # type: ignore[operator]
    assert shutdown_called.wait(timeout=5)
