from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from turing_agentmemory_mcp.gliner_provider import GLiNERProvider, start_server


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


def extract_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "texts": ["first source text", "second source text"],
        "labels": ["project", "person"],
        "threshold": 0.42,
        "include_confidence": True,
        "include_spans": True,
    }
    payload.update(overrides)
    return payload


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


@contextmanager
def running_server(provider: object) -> Iterator[str]:
    server, thread = start_server(provider, host="127.0.0.1", port=0)
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request_json(url: str, payload: object | None = None) -> tuple[int, dict[str, object]]:
    request = Request(url, method="GET")
    if payload is not None:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def post_bytes(url: str, body: bytes) -> tuple[int, dict[str, object]]:
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_contract_includes_errors_and_private_logs(caplog: pytest.LogCaptureFixture) -> None:
    class ExplodingProvider:
        def health_payload(self) -> dict[str, object]:
            return {"status": "ok", "model": "test", "device": "cpu"}

        def extract(self, payload: dict[str, object]) -> dict[str, object]:
            if "labels" not in payload:
                raise ValueError("labels are required")
            if payload["texts"] == ["explode"]:
                raise RuntimeError("provider exploded")
            return {"model": "test", "device": "cpu", "results": [{"entities": {}}]}

    caplog.set_level(logging.INFO, logger="turing_agentmemory_mcp.gliner_provider")
    with running_server(ExplodingProvider()) as base_url:
        assert request_json(f"{base_url}/health") == (
            200,
            {"status": "ok", "model": "test", "device": "cpu"},
        )
        assert request_json(f"{base_url}/extract", extract_payload(texts=["private source text"])) == (
            200,
            {"model": "test", "device": "cpu", "results": [{"entities": {}}]},
        )
        assert post_bytes(f"{base_url}/extract", b"{")[0] == 400
        assert request_json(f"{base_url}/extract", {"texts": ["private malformed text"]})[0] == 400
        assert request_json(f"{base_url}/extract", extract_payload(texts=["explode"]))[0] == 500
        assert request_json(f"{base_url}/missing")[0] == 404

    assert "private source text" not in caplog.text
    assert "private malformed text" not in caplog.text
    assert "explode" not in caplog.text
    assert "method=POST" in caplog.text
    assert "path=/extract" in caplog.text
    assert "status=200" in caplog.text
    assert "count=1" in caplog.text


def test_http_health_failure_returns_private_generic_json_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_value = "health-secret-value"
    exception_text = f"health provider crashed: {sensitive_value}"

    class FailingHealthProvider:
        def health_payload(self) -> dict[str, object]:
            raise RuntimeError(exception_text)

        def extract(self, payload: dict[str, object]) -> dict[str, object]:
            return {"model": "test", "device": "cpu", "results": []}

    caplog.set_level(logging.INFO, logger="turing_agentmemory_mcp.gliner_provider")
    with running_server(FailingHealthProvider()) as base_url:
        with pytest.raises(HTTPError) as error:
            urlopen(Request(f"{base_url}/health", method="GET"), timeout=5)

    response = error.value
    body = response.read().decode("utf-8")
    assert response.code == 500
    assert response.headers["Content-Type"] == "application/json; charset=utf-8"
    assert response.headers["Content-Length"] == str(len(body.encode("utf-8")))
    assert json.loads(body) == {"error": "internal server error"}
    assert exception_text not in body
    assert sensitive_value not in body
    assert exception_text not in caplog.text
    assert sensitive_value not in caplog.text
    assert "method=GET" in caplog.text
    assert "path=/health" in caplog.text
    assert "status=500" in caplog.text
    assert "count=0" in caplog.text
