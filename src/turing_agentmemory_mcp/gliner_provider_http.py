"""BaseHTTPRequestHandler/ThreadingHTTPServer plumbing for the GLiNER provider."""

from __future__ import annotations

import json
import logging
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from turing_agentmemory_mcp.gliner_provider_extraction import (
    ExtractProvider,
    ProviderFailure,
    RequestFailure,
    _validate_extract_memory_payload,
    _validate_extract_payload,
)

MAX_BODY_BYTES = 1024 * 1024
READ_TIMEOUT_SECONDS = 30
MAX_PENDING_EXTRACTION_REQUESTS = 32
MAX_REQUEST_THREADS = MAX_PENDING_EXTRACTION_REQUESTS + 8
INTERNAL_ERROR_BODY = b'{"error": "internal server error"}'
LOGGER = logging.getLogger("turing_agentmemory_mcp.gliner_provider")


class GLiNERHTTPServer(ThreadingHTTPServer):
    request_queue_size = MAX_REQUEST_THREADS + 8

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        max_request_threads: int = MAX_REQUEST_THREADS,
    ) -> None:
        if max_request_threads <= 0:
            raise ValueError("max_request_threads must be positive")
        self.extract_semaphore = threading.BoundedSemaphore(MAX_PENDING_EXTRACTION_REQUESTS)
        self.request_thread_semaphore = threading.BoundedSemaphore(max_request_threads)
        super().__init__(server_address, handler)

    def handle_error(self, request: object, client_address: object) -> None:
        LOGGER.info("method=<unknown> path=<unknown> status=500 count=0 elapsed_ms=0.000")

    def process_request(self, request: object, client_address: object) -> None:
        if not self.request_thread_semaphore.acquire(blocking=False):
            LOGGER.info("method=<unknown> path=<unknown> status=503 count=0 elapsed_ms=0.000")
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.request_thread_semaphore.release()
            raise

    def process_request_thread(self, request: object, client_address: object) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.request_thread_semaphore.release()


def make_handler(provider: ExtractProvider) -> type[BaseHTTPRequestHandler]:
    class GLiNERHandler(BaseHTTPRequestHandler):
        server_version = "GLiNERProvider/1.0"

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(READ_TIMEOUT_SECONDS)

        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
            self._dispatch()

        def _dispatch(self) -> None:
            started = time.perf_counter()
            count = 0
            path = "<unknown>"
            try:
                path = _canonical_path(self.path)
                if self.command == "GET":
                    if path != "/health":
                        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"}, count, started, path)
                        return
                    self._send_json(HTTPStatus.OK, provider.health_payload(), count, started, path)
                    return
                if self.command != "POST" or path not in {"/extract", "/extract-memory"}:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"}, count, started, path)
                    return
                payload = self._read_json_body()
                if path == "/extract-memory":
                    texts, _ = _validate_extract_memory_payload(payload)
                else:
                    texts, _, _, _, _ = _validate_extract_payload(payload)
                count = len(texts)
                server = self.server
                if not isinstance(server, GLiNERHTTPServer):
                    raise ProviderFailure("unexpected HTTP server")
                if not server.extract_semaphore.acquire(blocking=False):
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        {"error": "service unavailable"},
                        count,
                        started,
                        path,
                    )
                    return
                try:
                    response = (
                        provider.extract_memory(payload)
                        if path == "/extract-memory"
                        else provider.extract(payload)
                    )
                finally:
                    server.extract_semaphore.release()
                self._send_json(HTTPStatus.OK, response, count, started, path)
            except RequestFailure as exc:
                error = "request too large" if exc.status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE else "invalid request"
                self._send_json(exc.status, {"error": error}, count, started, path)
            except Exception as exc:
                LOGGER.error(
                    "provider_request_failed method=%s path=%s exception_type=%s",
                    self.command,
                    path,
                    type(exc).__name__,
                )
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "internal server error"},
                    count,
                    started,
                    path,
                )

        def _read_json_body(self) -> dict[str, Any]:
            values = self.headers.get_all("Content-Length") or []
            if len(values) != 1:
                raise RequestFailure()
            value = values[0].strip()
            if not value or not value.isascii() or not value.isdecimal():
                raise RequestFailure()
            length = int(value)
            if length <= 0:
                raise RequestFailure()
            if length > MAX_BODY_BYTES:
                raise RequestFailure(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            try:
                body = self.rfile.read(length)
            except OSError as exc:
                raise RequestFailure() from exc
            if len(body) != length:
                raise RequestFailure()
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RequestFailure() from exc
            if not isinstance(payload, dict):
                raise RequestFailure()
            return payload

        def _send_json(
            self,
            status: HTTPStatus,
            payload: Any,
            count: int,
            started: float,
            path: str,
        ) -> None:
            try:
                body = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("utf-8")
            except (TypeError, ValueError, OverflowError):
                status = HTTPStatus.INTERNAL_SERVER_ERROR
                body = INTERNAL_ERROR_BODY
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                return
            LOGGER.info(
                "method=%s path=%s status=%s count=%s elapsed_ms=%.3f",
                getattr(self, "command", "<unknown>"),
                path,
                status.value,
                count,
                (time.perf_counter() - started) * 1000,
            )

        def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
            try:
                status = HTTPStatus(code)
            except ValueError:
                status = HTTPStatus.BAD_REQUEST
            payload = {"error": "internal server error"} if status >= HTTPStatus.INTERNAL_SERVER_ERROR else {"error": "invalid request"}
            self._send_json(status, payload, 0, time.perf_counter(), "<unknown>")

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            return

        def log_message(self, format: str, *args: Any) -> None:
            return

    return GLiNERHandler


def _canonical_path(target: str) -> str:
    try:
        parsed = urlsplit(target)
    except ValueError as exc:
        raise RequestFailure() from exc
    if parsed.scheme or parsed.netloc or parsed.fragment or not parsed.path.startswith("/"):
        raise RequestFailure()
    if parsed.path == "/health":
        return "/health"
    if parsed.path == "/extract":
        return "/extract"
    if parsed.path == "/extract-memory":
        return "/extract-memory"
    return "<unknown>"


def make_server(
    provider: ExtractProvider,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    max_request_threads: int = MAX_REQUEST_THREADS,
) -> GLiNERHTTPServer:
    return GLiNERHTTPServer(
        (host, port),
        make_handler(provider),
        max_request_threads=max_request_threads,
    )


def start_server(
    provider: ExtractProvider,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    max_request_threads: int = MAX_REQUEST_THREADS,
) -> tuple[GLiNERHTTPServer, threading.Thread]:
    server = make_server(
        provider,
        host=host,
        port=port,
        max_request_threads=max_request_threads,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
