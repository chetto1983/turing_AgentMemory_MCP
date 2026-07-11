from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

import pytest

import turing_agentmemory_mcp.entity_extraction as entity_extraction
from turing_agentmemory_mcp.entity_extraction import entity_processor_from_env


def test_gliner2_http_processor_batches_ordered_nested_results(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "model": "fastino/gliner2-base-v1",
                    "device": "cpu",
                    "results": [
                        {
                            "entities": {
                                "person": [
                                    {"text": "Alice", "start": 0, "end": 5, "confidence": 0.91}
                                ],
                                "project": [
                                    {"text": "TuringDB", "start": 13, "end": 21, "confidence": 0.88}
                                ],
                            }
                        },
                        {
                            "entities": {
                                "person": [
                                    {"text": "Bob", "start": 0, "end": 3, "confidence": 0.93}
                                ],
                                "project": [
                                    {"text": "FastMCP", "start": 10, "end": 17, "confidence": 0.87}
                                ],
                            }
                        },
                    ],
                }
            ).encode("utf-8")

    def fake_urlopen(request, *, timeout: float):
        requests.append(
            {
                "url": request.full_url,
                "method": request.method,
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr(entity_extraction, "urlopen", fake_urlopen, raising=False)
    monkeypatch.setenv("GLINER_ENABLED", "1")
    monkeypatch.setenv("GLINER_BACKEND", "gliner2_http")
    monkeypatch.setenv("GLINER_BASE_URL", "http://agentmemory-gliner:8080")
    monkeypatch.setenv("GLINER_MODEL", "fastino/gliner2-base-v1")
    monkeypatch.setenv("GLINER_LABELS", "person,project")
    monkeypatch.setenv("GLINER_THRESHOLD", "0.42")
    monkeypatch.setenv("GLINER_TIMEOUT_SECONDS", "7.5")

    processor = entity_processor_from_env()
    results = processor.process_many(["Alice builds TuringDB", "Bob tests FastMCP"])

    assert requests == [
        {
            "url": "http://agentmemory-gliner:8080/extract",
            "method": "POST",
            "payload": {
                "texts": ["Alice builds TuringDB", "Bob tests FastMCP"],
                "labels": ["person", "project"],
                "threshold": 0.42,
                "include_confidence": True,
                "include_spans": True,
            },
            "timeout": 7.5,
        }
    ]
    assert [result.metadata["entity_extraction"]["model"] for result in results] == [
        "fastino/gliner2-base-v1",
        "fastino/gliner2-base-v1",
    ]
    assert results[0].metadata["entity_extraction"]["entities"] == [
        {"text": "Alice", "label": "person", "start": 0, "end": 5, "score": 0.91},
        {"text": "TuringDB", "label": "project", "start": 13, "end": 21, "score": 0.88},
    ]
    assert results[1].metadata["entity_extraction"]["entities"] == [
        {"text": "Bob", "label": "person", "start": 0, "end": 3, "score": 0.93},
        {"text": "FastMCP", "label": "project", "start": 10, "end": 17, "score": 0.87},
    ]


def test_gliner2_http_processor_redacts_normalized_entities(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "model": "fastino/gliner2-base-v1",
                    "device": "cpu",
                    "results": [
                        {
                            "entities": {
                                "person": [
                                    {"text": "Alice", "start": 0, "end": 5, "confidence": 0.91}
                                ],
                                "email": [
                                    {
                                        "text": "alice@example.com",
                                        "start": 11,
                                        "end": 28,
                                        "confidence": 0.98,
                                    }
                                ],
                            }
                        }
                    ],
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        entity_extraction,
        "urlopen",
        lambda request, *, timeout: FakeResponse(),
        raising=False,
    )
    monkeypatch.setenv("GLINER_ENABLED", "1")
    monkeypatch.setenv("GLINER_BACKEND", "gliner2_http")
    monkeypatch.setenv("GLINER_BASE_URL", "http://agentmemory-gliner:8080")
    monkeypatch.setenv("GLINER_MODEL", "fastino/gliner2-base-v1")
    monkeypatch.setenv("GLINER_LABELS", "person,email")
    monkeypatch.setenv("GLINER_REDACT", "1")

    result = entity_processor_from_env().process("Alice uses alice@example.com")

    assert result.text == "[PERSON] uses [EMAIL]"
    assert result.metadata["entity_extraction"]["redacted"] is True
    assert result.metadata["entity_extraction"]["entities"] == [
        {"label": "person", "start": 0, "end": 5, "score": 0.91},
        {"label": "email", "start": 11, "end": 28, "score": 0.98},
    ]


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (HTTPError("http://agentmemory-gliner:8080/extract", 500, "error", None, None), "HTTP 500"),
        (
            {"model": "fastino/gliner2-base-v1", "device": "cpu", "results": [{"entities": {}}]},
            "1 results for 2 texts",
        ),
    ],
)
def test_gliner2_http_processor_fails_closed_without_source_text(
    monkeypatch,
    failure: object,
    expected: str,
) -> None:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(failure).encode("utf-8")

    def fake_urlopen(request, *, timeout: float):
        if isinstance(failure, Exception):
            raise failure
        return FakeResponse()

    monkeypatch.setattr(entity_extraction, "urlopen", fake_urlopen, raising=False)
    monkeypatch.setenv("GLINER_ENABLED", "1")
    monkeypatch.setenv("GLINER_BACKEND", "gliner2_http")
    monkeypatch.setenv("GLINER_BASE_URL", "http://agentmemory-gliner:8080")
    monkeypatch.setenv("GLINER_LABELS", "person")

    processor = entity_processor_from_env()
    with pytest.raises(RuntimeError, match=expected) as error:
        processor.process_many(["private first source", "private second source"])

    assert "private first source" not in str(error.value)
    assert "private second source" not in str(error.value)


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (URLError("connection refused"), "unavailable"),
        (b"{", "invalid JSON"),
        (
            {"model": "wrong-model", "device": "cpu", "results": [{"entities": {}}]},
            "model mismatch",
        ),
    ],
)
def test_gliner2_http_processor_rejects_invalid_provider_responses(
    monkeypatch,
    failure: object,
    expected: str,
) -> None:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            if isinstance(failure, bytes):
                return failure
            return json.dumps(failure).encode("utf-8")

    def fake_urlopen(request, *, timeout: float):
        if isinstance(failure, Exception):
            raise failure
        return FakeResponse()

    monkeypatch.setattr(entity_extraction, "urlopen", fake_urlopen, raising=False)
    monkeypatch.setenv("GLINER_ENABLED", "1")
    monkeypatch.setenv("GLINER_BACKEND", "gliner2_http")
    monkeypatch.setenv("GLINER_BASE_URL", "http://agentmemory-gliner:8080")
    monkeypatch.setenv("GLINER_MODEL", "fastino/gliner2-base-v1")
    monkeypatch.setenv("GLINER_LABELS", "person")

    with pytest.raises(RuntimeError, match=expected) as error:
        entity_processor_from_env().process("private source")

    assert "private source" not in str(error.value)
