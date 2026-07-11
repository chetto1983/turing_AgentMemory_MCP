from __future__ import annotations

import json
import logging
import socket
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from _gliner_provider_shared import extract_payload, memory_payload, memory_result

import turing_agentmemory_mcp.gliner_provider as gliner_provider
from turing_agentmemory_mcp.gliner_provider import GLiNERProvider, start_server
from turing_agentmemory_mcp.memory_extraction import MEMORY_EXTRACTION_SCHEMA_VERSION


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
        name.lower(): value.strip() for line in lines[1:] for name, value in [line.split(":", 1)]
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
        assert request_json(
            f"{base_url}/extract", extract_payload(texts=["private source text"])
        ) == (
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
    assert "provider_request_failed" in caplog.text
    assert "exception_type=RuntimeError" in caplog.text


def test_extract_memory_http_contract_is_versioned_and_private(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class MemoryProvider:
        def health_payload(self) -> dict[str, object]:
            return {"status": "ok", "model": "test", "device": "cpu"}

        def extract(self, payload: dict[str, object]) -> dict[str, object]:
            raise AssertionError("legacy extraction must not be called")

        def extract_memory(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "model": "test",
                "device": "cpu",
                "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
                "results": [memory_result()],
            }

    caplog.set_level(logging.INFO, logger="turing_agentmemory_mcp.gliner_provider")
    with running_server(MemoryProvider()) as base_url:
        status, body = request_json(
            f"{base_url}/extract-memory",
            memory_payload(texts=["private memory source"]),
        )
        invalid_status, invalid_body = request_json(
            f"{base_url}/extract-memory",
            memory_payload(texts=["private invalid source"], schema_version="memory-v0"),
        )

    assert status == 200
    assert body["schema_version"] == MEMORY_EXTRACTION_SCHEMA_VERSION
    assert invalid_status == 400
    assert invalid_body == {"error": "invalid request"}
    assert "private memory source" not in caplog.text
    assert "private invalid source" not in caplog.text
    assert "path=/extract-memory" in caplog.text
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

        def batch_extract_entities(
            self, *args: object, **kwargs: object
        ) -> list[dict[str, object]]:
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
