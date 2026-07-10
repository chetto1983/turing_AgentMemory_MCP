"""Shared CPU-only GLiNER2 HTTP provider."""

from __future__ import annotations

import json
import logging
import math
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol
from urllib.parse import urlsplit

DEFAULT_MODEL_NAME = "fastino/gliner2-base-v1"
MAX_BODY_BYTES = 1024 * 1024
MAX_TEXTS = 256
MAX_LABELS = 64
MAX_TEXT_CHARS = 16_384
MAX_LABEL_CHARS = 256
READ_TIMEOUT_SECONDS = 30
MAX_PENDING_EXTRACTION_REQUESTS = 32
MAX_REQUEST_THREADS = MAX_PENDING_EXTRACTION_REQUESTS + 8
INTERNAL_ERROR_BODY = b'{"error": "internal server error"}'
LOGGER = logging.getLogger(__name__)


class RequestFailure(ValueError):
    def __init__(self, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self.status = status
        super().__init__(status.phrase)


class ProviderFailure(ValueError):
    pass


class ExtractProvider(Protocol):
    def extract(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def health_payload(self) -> dict[str, Any]: ...


@dataclass
class GLiNERProvider:
    model: Any
    model_name: str = DEFAULT_MODEL_NAME
    device: str = "cpu"
    batch_size: int = 8
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.batch_size, bool) or not isinstance(self.batch_size, int) or self.batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        if self.device != "cpu":
            raise ValueError("GLiNERProvider only supports the cpu device")

    def extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        texts, labels, threshold, include_confidence, include_spans = _validate_extract_payload(payload)
        try:
            with self.lock:
                results = self.model.batch_extract_entities(
                    texts,
                    labels,
                    batch_size=self.batch_size,
                    threshold=threshold,
                    include_confidence=include_confidence,
                    include_spans=include_spans,
                )
        except Exception as exc:
            raise ProviderFailure("model inference failed") from exc
        if not isinstance(results, list):
            raise ProviderFailure("model must return a list of results")
        if len(results) != len(texts):
            raise ProviderFailure("model result count must match text count")
        return {"model": self.model_name, "device": self.device, "results": results}

    def health_payload(self) -> dict[str, str]:
        return {"status": "ok", "model": self.model_name, "device": self.device}


def _validate_extract_payload(payload: dict[str, Any]) -> tuple[list[str], list[str], float, bool, bool]:
    if not isinstance(payload, dict):
        raise RequestFailure()
    texts = _validate_string_list(payload.get("texts"), "texts", MAX_TEXTS, MAX_TEXT_CHARS)
    labels = _validate_string_list(payload.get("labels"), "labels", MAX_LABELS, MAX_LABEL_CHARS)
    threshold = payload.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise RequestFailure()
    threshold = float(threshold)
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise RequestFailure()
    include_confidence = payload.get("include_confidence")
    include_spans = payload.get("include_spans")
    if not isinstance(include_confidence, bool) or not isinstance(include_spans, bool):
        raise RequestFailure()
    return texts, labels, threshold, include_confidence, include_spans


def _validate_string_list(value: Any, name: str, max_items: int, max_chars: int) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > max_items:
        raise RequestFailure()
    if any(not isinstance(item, str) or not item.strip() or len(item) > max_chars for item in value):
        raise RequestFailure()
    return value


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
                if self.command != "POST" or path != "/extract":
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"}, count, started, path)
                    return
                payload = self._read_json_body()
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
                    response = provider.extract(payload)
                finally:
                    server.extract_semaphore.release()
                self._send_json(HTTPStatus.OK, response, count, started, path)
            except RequestFailure as exc:
                error = "request too large" if exc.status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE else "invalid request"
                self._send_json(exc.status, {"error": error}, count, started, path)
            except Exception:
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


def _install_shutdown_signal_handlers(server: ThreadingHTTPServer) -> None:
    lock = threading.Lock()
    shutdown_started = False

    def shutdown_handler(signum: int, frame: object) -> None:
        nonlocal shutdown_started
        with lock:
            if shutdown_started:
                return
            shutdown_started = True
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)


def _read_settings() -> tuple[str, int, str, int]:
    model_name = os.environ.get("GLINER_MODEL", DEFAULT_MODEL_NAME).strip()
    host = os.environ.get("GLINER_HOST", "0.0.0.0").strip()
    if not model_name:
        raise ValueError("GLINER_MODEL must be non-empty")
    if not host:
        raise ValueError("GLINER_HOST must be non-empty")
    batch_size = _read_bounded_int("GLINER_BATCH_SIZE", "8", 1, MAX_TEXTS)
    port = _read_bounded_int("GLINER_PORT", "8080", 1, 65_535)
    return model_name, batch_size, host, port


def _read_bounded_int(name: str, default: str, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def main() -> None:
    model_name, batch_size, host, port = _read_settings()
    try:
        from gliner2 import GLiNER2
    except ImportError as exc:
        raise RuntimeError("gliner2 is required to run the GLiNER provider") from exc

    model = GLiNER2.from_pretrained(model_name, map_location="cpu")
    provider = GLiNERProvider(model=model, model_name=model_name, device="cpu", batch_size=batch_size)
    server = make_server(provider, host=host, port=port)
    _install_shutdown_signal_handlers(server)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
