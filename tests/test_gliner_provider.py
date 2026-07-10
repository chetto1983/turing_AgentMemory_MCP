from __future__ import annotations

import json
import logging
import signal
import socket
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import turing_agentmemory_mcp.gliner_provider as gliner_provider
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


def raw_http_request(base_url: str, request: bytes) -> bytes:
    host, port = base_url.removeprefix("http://").rsplit(":", 1)
    with socket.create_connection((host, int(port)), timeout=5) as client:
        client.settimeout(5)
        client.sendall(request)
        client.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while chunk := client.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


def assert_json_response(raw: bytes, status: int) -> dict[str, object]:
    header_block, body = raw.split(b"\r\n\r\n", 1)
    lines = header_block.decode("iso-8859-1").split("\r\n")
    headers = {
        name.lower(): value.strip()
        for line in lines[1:]
        for name, value in [line.split(":", 1)]
    }
    assert int(lines[0].split()[1]) == status
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert headers["content-length"] == str(len(body))
    return json.loads(body.decode("utf-8"))


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


class StaticProvider:
    def health_payload(self) -> dict[str, object]:
        return {"status": "ok", "model": "test", "device": "cpu"}

    def extract(self, payload: dict[str, object]) -> dict[str, object]:
        return {"model": "test", "device": "cpu", "results": [{"entities": {}}]}


@pytest.mark.parametrize(
    "headers",
    [
        b"",
        b"Content-Length: 2\r\nContent-Length: 2\r\n",
        b"Content-Length: +2\r\n",
        b"Content-Length: 0\r\n",
    ],
)
def test_raw_requests_reject_invalid_content_length_with_json_framing(headers: bytes) -> None:
    request = b"POST /extract HTTP/1.1\r\nHost: localhost\r\n" + headers + b"\r\n{}"

    with running_server(StaticProvider()) as base_url:
        raw = raw_http_request(base_url, request)

    assert assert_json_response(raw, 400) == {"error": "invalid request"}


def test_raw_requests_reject_short_body_oversize_and_malformed_target() -> None:
    body = json.dumps(extract_payload()).encode("utf-8")
    requests = [
        (
            b"POST /extract HTTP/1.1\r\nHost: localhost\r\nContent-Length: "
            + str(len(body) + 1).encode("ascii")
            + b"\r\n\r\n"
            + body,
            400,
            {"error": "invalid request"},
        ),
        (
            b"POST /extract HTTP/1.1\r\nHost: localhost\r\nContent-Length: "
            + str(gliner_provider.MAX_BODY_BYTES + 1).encode("ascii")
            + b"\r\n\r\n",
            413,
            {"error": "request too large"},
        ),
        (
            b"GET malformed-target HTTP/1.1\r\nHost: localhost\r\n\r\n",
            400,
            {"error": "invalid request"},
        ),
    ]

    with running_server(StaticProvider()) as base_url:
        for request, status, expected in requests:
            assert assert_json_response(raw_http_request(base_url, request), status) == expected


def test_extract_saturation_limits_pending_work_and_serializes_inference() -> None:
    class SlowModel:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def batch_extract_entities(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                time.sleep(0.025)
                return [{"entities": {}}]
            finally:
                with self.lock:
                    self.active -= 1

    model = SlowModel()
    provider = GLiNERProvider(model=model, model_name="fastino/gliner2-base-v1")
    start = threading.Event()

    def request_extract(base_url: str) -> int:
        start.wait(timeout=5)
        return request_json(f"{base_url}/extract", extract_payload(texts=["bounded"]))[0]

    with running_server(provider) as base_url:
        with ThreadPoolExecutor(max_workers=40) as pool:
            requests = [pool.submit(request_extract, base_url) for _ in range(40)]
            start.set()
            statuses = [request.result(timeout=10) for request in requests]

    assert model.max_active == 1
    assert 503 in statuses
    assert statuses.count(503) >= 1


def test_server_drops_connections_above_worker_cap() -> None:
    class CountingHealthProvider(StaticProvider):
        def __init__(self) -> None:
            self.health_calls = 0

        def health_payload(self) -> dict[str, object]:
            self.health_calls += 1
            return super().health_payload()

    provider = CountingHealthProvider()
    server, thread = start_server(provider, max_request_threads=1)
    held_connection = socket.create_connection(("127.0.0.1", server.server_port), timeout=5)
    held_connection.sendall(b"GET /health HTTP/1.1\r\n")
    try:
        try:
            response = raw_http_request(
                f"http://127.0.0.1:{server.server_port}",
                b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )
        except (ConnectionAbortedError, ConnectionResetError):
            response = b""
        assert b" 200 " not in response
        assert provider.health_calls == 0
    finally:
        held_connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_unknown_path_logs_only_canonical_unknown_path(caplog: pytest.LogCaptureFixture) -> None:
    sensitive_path = "/unrecognized?token=super-secret-query"
    caplog.set_level(logging.INFO, logger="turing_agentmemory_mcp.gliner_provider")

    with running_server(StaticProvider()) as base_url:
        assert request_json(f"{base_url}{sensitive_path}") == (404, {"error": "not found"})

    assert sensitive_path not in caplog.text
    assert "super-secret-query" not in caplog.text
    assert "path=<unknown>" in caplog.text


@pytest.mark.parametrize(
    "response_payload",
    [
        {"secret": "nonserializable-secret", "value": object()},
        {"secret": "nonfinite-secret", "score": float("nan")},
    ],
)
def test_unencodable_provider_response_returns_private_generic_json_error(
    caplog: pytest.LogCaptureFixture,
    response_payload: dict[str, object],
) -> None:
    class UnencodableProvider(StaticProvider):
        def extract(self, payload: dict[str, object]) -> dict[str, object]:
            return response_payload

    caplog.set_level(logging.INFO, logger="turing_agentmemory_mcp.gliner_provider")
    with running_server(UnencodableProvider()) as base_url:
        request = Request(
            f"{base_url}/extract",
            data=json.dumps(extract_payload(texts=["private source"])).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=5)

    response = error.value
    body = response.read().decode("utf-8")
    assert response.code == 500
    assert response.headers["Content-Type"] == "application/json; charset=utf-8"
    assert response.headers["Content-Length"] == str(len(body.encode("utf-8")))
    assert json.loads(body) == {"error": "internal server error"}
    assert "secret" not in body
    assert "private source" not in caplog.text
    assert "secret" not in caplog.text
    assert "status=500" in caplog.text


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GLINER_MODEL", "   "),
        ("GLINER_HOST", "   "),
        ("GLINER_BATCH_SIZE", "0"),
        ("GLINER_BATCH_SIZE", "257"),
        ("GLINER_PORT", "0"),
        ("GLINER_PORT", "65536"),
    ],
)
def test_main_validates_settings_before_loading_model(monkeypatch, name: str, value: str) -> None:
    load_calls: list[tuple[str, object]] = []

    class FakeGLiNER2:
        @classmethod
        def from_pretrained(cls, model_name: str, **kwargs: object) -> object:
            load_calls.append((model_name, kwargs))
            return object()

    monkeypatch.setitem(sys.modules, "gliner2", SimpleNamespace(GLiNER2=FakeGLiNER2))
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(gliner_provider, "make_server", lambda *args, **kwargs: pytest.fail("server started"))

    with pytest.raises(ValueError):
        gliner_provider.main()

    assert load_calls == []


def test_main_loads_the_model_once_after_validating_settings(monkeypatch) -> None:
    load_calls: list[tuple[str, dict[str, object]]] = []
    server_calls: list[object] = []

    class FakeGLiNER2:
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

    monkeypatch.setitem(sys.modules, "gliner2", SimpleNamespace(GLiNER2=FakeGLiNER2))
    monkeypatch.setattr(gliner_provider, "make_server", make_fake_server)
    monkeypatch.setattr(gliner_provider.signal, "signal", lambda *args: None)
    monkeypatch.setenv("GLINER_MODEL", "fastino/gliner2-base-v1")
    monkeypatch.setenv("GLINER_HOST", "127.0.0.1")
    monkeypatch.setenv("GLINER_BATCH_SIZE", "8")
    monkeypatch.setenv("GLINER_PORT", "8080")

    gliner_provider.main()

    assert load_calls == [("fastino/gliner2-base-v1", {"map_location": "cpu"})]
    assert server_calls[1:] == ["serve", "close"]


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
