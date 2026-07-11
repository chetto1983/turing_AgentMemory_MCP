from __future__ import annotations

import signal
import sys
import threading
from types import SimpleNamespace

import pytest
from _gliner_provider_shared import extract_payload, memory_payload, memory_result

import turing_agentmemory_mcp.gliner_provider as gliner_provider
from turing_agentmemory_mcp.gliner_provider import GLiNERProvider
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
    assert model.calls == [
        {"texts": ["first", "second"], "batch_size": 4, "threshold": 0.5}
    ]


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
        def batch_extract_entities(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
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
    monkeypatch.setattr(gliner_provider, "make_server", lambda *args, **kwargs: pytest.fail("server started"))

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
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))
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
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))
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

    monkeypatch.setattr(gliner_provider.signal, "signal", lambda signum, handler: handlers.__setitem__(signum, handler))

    gliner_provider._install_shutdown_signal_handlers(FakeServer())

    handler = handlers[signal.SIGTERM]
    assert callable(handler)
    handler(signal.SIGTERM, None)  # type: ignore[operator]
    assert shutdown_called.wait(timeout=5)
