"""Shared CPU-only GLiNER2 HTTP provider."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol
from urllib.parse import urlsplit

DEFAULT_MODEL_NAME = "fastino/gliner2-base-v1"
LOGGER = logging.getLogger(__name__)


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
        with self.lock:
            results = self.model.batch_extract_entities(
                texts,
                labels,
                batch_size=self.batch_size,
                threshold=threshold,
                include_confidence=include_confidence,
                include_spans=include_spans,
            )
        if not isinstance(results, list):
            raise ValueError("model must return a list of results")
        if len(results) != len(texts):
            raise ValueError("model result count must match text count")
        return {"model": self.model_name, "device": self.device, "results": results}

    def health_payload(self) -> dict[str, str]:
        return {"status": "ok", "model": self.model_name, "device": self.device}


def _validate_extract_payload(payload: dict[str, Any]) -> tuple[list[str], list[str], float, bool, bool]:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    texts = _validate_string_list(payload.get("texts"), "texts")
    labels = _validate_string_list(payload.get("labels"), "labels")
    threshold = payload.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("threshold must be a finite number between 0 and 1")
    threshold = float(threshold)
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be a finite number between 0 and 1")
    include_confidence = payload.get("include_confidence")
    include_spans = payload.get("include_spans")
    if not isinstance(include_confidence, bool) or not isinstance(include_spans, bool):
        raise ValueError("include_confidence and include_spans must be booleans")
    return texts, labels, threshold, include_confidence, include_spans


def _validate_string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list of non-empty strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{name} must be a non-empty list of non-empty strings")
    return value


def make_handler(provider: ExtractProvider) -> type[BaseHTTPRequestHandler]:
    class GLiNERHandler(BaseHTTPRequestHandler):
        server_version = "GLiNERProvider/1.0"

        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            started = time.perf_counter()
            path = urlsplit(self.path).path
            if path == "/health":
                self._send_json(HTTPStatus.OK, provider.health_payload(), count=0, started=started)
                return
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "not found"},
                count=0,
                started=started,
            )

        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
            started = time.perf_counter()
            path = urlsplit(self.path).path
            if path != "/extract":
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"error": "not found"},
                    count=0,
                    started=started,
                )
                return
            count = 0
            try:
                payload = self._read_json_body()
                count = len(payload.get("texts", [])) if isinstance(payload.get("texts"), list) else 0
                response = provider.extract(payload)
            except ValueError:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid request"},
                    count=count,
                    started=started,
                )
                return
            except Exception:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "internal server error"},
                    count=count,
                    started=started,
                )
                return
            self._send_json(HTTPStatus.OK, response, count=count, started=started)

        def _read_json_body(self) -> dict[str, Any]:
            header = self.headers.get("Content-Length")
            if header is None:
                raise ValueError("Content-Length is required")
            try:
                length = int(header)
            except ValueError as exc:
                raise ValueError("Content-Length must be an integer") from exc
            if length < 0:
                raise ValueError("Content-Length must not be negative")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("request body must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

        def _send_json(
            self,
            status: HTTPStatus,
            payload: dict[str, Any],
            *,
            count: int,
            started: float,
        ) -> None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            LOGGER.info(
                "method=%s path=%s status=%s count=%s elapsed_ms=%.3f",
                self.command,
                urlsplit(self.path).path,
                status.value,
                count,
                (time.perf_counter() - started) * 1000,
            )

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            return

        def log_message(self, format: str, *args: Any) -> None:
            return

    return GLiNERHandler


def make_server(
    provider: ExtractProvider,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(provider))


def start_server(
    provider: ExtractProvider,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = make_server(provider, host=host, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def main() -> None:
    model_name = os.environ.get("GLINER_MODEL", DEFAULT_MODEL_NAME).strip() or DEFAULT_MODEL_NAME
    batch_size = int(os.environ.get("GLINER_BATCH_SIZE", "8"))
    host = os.environ.get("GLINER_HOST", "0.0.0.0")
    port = int(os.environ.get("GLINER_PORT", "8080"))
    try:
        from gliner2 import GLiNER2
    except ImportError as exc:
        raise RuntimeError("gliner2 is required to run the GLiNER provider") from exc

    model = GLiNER2.from_pretrained(model_name, map_location="cpu")
    provider = GLiNERProvider(model=model, model_name=model_name, device="cpu", batch_size=batch_size)
    server = make_server(provider, host=host, port=port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
