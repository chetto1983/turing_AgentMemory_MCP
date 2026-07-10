"""Shared FastGLiNER2 HTTP provider."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import signal
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol
from urllib.parse import urlsplit

from .memory_extraction import (
    MEMORY_ENTITY_LABELS,
    MEMORY_EXTRACTION_SCHEMA_VERSION,
    MEMORY_KIND_LABELS,
    MEMORY_RELATION_SCHEMA,
)

DEFAULT_MODEL_NAME = "lion-ai/gliner2-base-v1-onnx"
DEFAULT_MODEL_REVISION = "5551729ccc76b30395bc9600f2348ec52a87cead"
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

    def extract_memory(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def health_payload(self) -> dict[str, Any]: ...


@dataclass
class FastGLiNER2Adapter:
    """Adapt FastGLiNER2's one-text API to the provider batch contract."""

    model: Any

    def batch_extract_entities(
        self,
        texts: list[str],
        labels: list[str],
        *,
        batch_size: int,
        threshold: float,
        include_confidence: bool,
        include_spans: bool,
    ) -> list[list[dict[str, Any]]]:
        del batch_size  # FastGLiNER2 currently accepts one text per inference.
        results: list[list[dict[str, Any]]] = []
        for text in texts:
            raw_entities = self.model.predict_entities(text, labels)
            if not isinstance(raw_entities, list):
                raise ValueError("FastGLiNER2 returned a non-list result")
            entities: list[dict[str, Any]] = []
            for raw in raw_entities:
                if not isinstance(raw, dict):
                    continue
                score = raw.get("score")
                if (
                    isinstance(score, bool)
                    or not isinstance(score, (int, float))
                    or not math.isfinite(float(score))
                    or float(score) < threshold
                ):
                    continue
                entity = _normalize_entity_offsets(text, raw)
                if not include_confidence:
                    entity.pop("score", None)
                if not include_spans:
                    entity.pop("start", None)
                    entity.pop("end", None)
                entities.append(entity)
            results.append(entities)
        return results

    def batch_extract_memory(
        self,
        texts: list[str],
        *,
        batch_size: int,
        threshold: float,
    ) -> list[dict[str, Any]]:
        del batch_size  # FastGLiNER2 currently accepts one text per inference.
        results: list[dict[str, Any]] = []
        labels = list(MEMORY_ENTITY_LABELS)
        relation_schema = list(MEMORY_RELATION_SCHEMA)
        memory_kinds = list(MEMORY_KIND_LABELS)
        for text in texts:
            raw_entities = self.model.predict_entities(text, labels)
            raw_relations = self.model.extract_relations(text, labels, relation_schema)
            raw_classifications = self.model.classify(text, memory_kinds)
            entities = _filter_scored_objects(raw_entities, threshold, "entity")
            relations = _filter_scored_objects(raw_relations, threshold, "relation")
            entities = [_normalize_entity_offsets(text, entity) for entity in entities]
            relations = [_normalize_relation_offsets(text, relation) for relation in relations]
            entities = _merge_relation_endpoints(entities, relations)
            classifications = _normalize_classifications(raw_classifications)
            results.append(
                {
                    "entities": entities,
                    "relations": relations,
                    "classifications": {"memory_kind": classifications},
                }
            )
        return results


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
        if self.device not in {"cpu", "cuda"}:
            raise ValueError("GLiNERProvider device must be cpu or cuda")

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

    def extract_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        texts, threshold = _validate_extract_memory_payload(payload)
        try:
            with self.lock:
                results = self.model.batch_extract_memory(
                    texts,
                    batch_size=self.batch_size,
                    threshold=threshold,
                )
        except Exception as exc:
            raise ProviderFailure("model inference failed") from exc
        if not isinstance(results, list):
            raise ProviderFailure("model must return a list of results")
        if len(results) != len(texts):
            raise ProviderFailure("model result count must match text count")
        return {
            "model": self.model_name,
            "device": self.device,
            "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
            "results": results,
        }

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


def _validate_extract_memory_payload(payload: dict[str, Any]) -> tuple[list[str], float]:
    if not isinstance(payload, dict):
        raise RequestFailure()
    if payload.get("schema_version") != MEMORY_EXTRACTION_SCHEMA_VERSION:
        raise RequestFailure()
    texts = _validate_string_list(payload.get("texts"), "texts", MAX_TEXTS, MAX_TEXT_CHARS)
    threshold = payload.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise RequestFailure()
    threshold = float(threshold)
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise RequestFailure()
    return texts, threshold


def _filter_scored_objects(value: object, threshold: float, kind: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"FastGLiNER2 returned non-list {kind} results")
    filtered: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"FastGLiNER2 returned malformed {kind} result")
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError(f"FastGLiNER2 returned malformed {kind} score")
        score = float(score)
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError(f"FastGLiNER2 returned malformed {kind} score")
        if score >= threshold:
            filtered.append(dict(item))
    return filtered


def _normalize_entity_offsets(text: str, entity: dict[str, Any]) -> dict[str, Any]:
    value = entity.get("text")
    start = entity.get("start")
    end = entity.get("end")
    if (
        not isinstance(value, str)
        or not value
        or isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
    ):
        raise ValueError("FastGLiNER2 returned malformed entity offsets")
    normalized = dict(entity)
    if 0 <= start < end <= len(text) and text[start:end] == value:
        return normalized

    encoded = text.encode("utf-8")
    if not 0 <= start < end <= len(encoded):
        raise ValueError("FastGLiNER2 returned invalid entity offsets")
    try:
        prefix = encoded[:start].decode("utf-8")
        byte_value = encoded[start:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("FastGLiNER2 returned invalid UTF-8 entity offsets") from exc
    if byte_value != value:
        raise ValueError("FastGLiNER2 entity offsets match neither characters nor UTF-8 bytes")
    normalized["start"] = len(prefix)
    normalized["end"] = len(prefix) + len(byte_value)
    return normalized


def _normalize_relation_offsets(text: str, relation: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(relation)
    for endpoint_name in ("subject", "object"):
        endpoint = relation.get(endpoint_name)
        if not isinstance(endpoint, dict):
            raise ValueError("FastGLiNER2 returned malformed relation endpoint")
        normalized[endpoint_name] = _normalize_entity_offsets(text, endpoint)
    return normalized


def _merge_relation_endpoints(
    entities: list[dict[str, Any]], relations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = list(entities)
    identities = {_raw_entity_identity(entity) for entity in merged}
    for relation in relations:
        for endpoint_name in ("subject", "object"):
            endpoint = relation.get(endpoint_name)
            if not isinstance(endpoint, dict):
                raise ValueError("FastGLiNER2 returned malformed relation endpoint")
            identity = _raw_entity_identity(endpoint)
            if identity not in identities:
                merged.append(dict(endpoint))
                identities.add(identity)
    return merged


def _raw_entity_identity(entity: dict[str, Any]) -> tuple[object, object, object, object]:
    required = ("text", "label", "start", "end", "score")
    if any(name not in entity for name in required):
        raise ValueError("FastGLiNER2 returned incomplete entity provenance")
    return entity["text"], entity["label"], entity["start"], entity["end"]


def _normalize_classifications(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError("FastGLiNER2 returned malformed classification results")
    classifications: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("FastGLiNER2 returned malformed classification result")
        label, raw_score = item
        if not isinstance(label, str) or not label or label in seen:
            raise ValueError("FastGLiNER2 returned malformed classification label")
        if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
            raise ValueError("FastGLiNER2 returned malformed classification score")
        score = float(raw_score)
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("FastGLiNER2 returned malformed classification score")
        seen.add(label)
        classifications.append({"label": label, "score": score})
    return classifications


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


def _read_settings() -> tuple[str, str, int, str, int, str]:
    model_name = os.environ.get("GLINER_MODEL", DEFAULT_MODEL_NAME).strip()
    revision = os.environ.get("GLINER_MODEL_REVISION", DEFAULT_MODEL_REVISION).strip()
    host = os.environ.get("GLINER_HOST", "0.0.0.0").strip()
    device = os.environ.get("GLINER_DEVICE", "cuda").strip().lower()
    if not model_name:
        raise ValueError("GLINER_MODEL must be non-empty")
    if not revision:
        raise ValueError("GLINER_MODEL_REVISION must be non-empty")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("GLINER_MODEL_REVISION must be a 40-character lowercase commit SHA")
    if not host:
        raise ValueError("GLINER_HOST must be non-empty")
    if device not in {"cpu", "cuda"}:
        raise ValueError("GLINER_DEVICE must be cpu or cuda")
    batch_size = _read_bounded_int("GLINER_BATCH_SIZE", "8", 1, MAX_TEXTS)
    port = _read_bounded_int("GLINER_PORT", "8080", 1, 65_535)
    return model_name, revision, batch_size, host, port, device


def _read_bounded_int(name: str, default: str, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def main() -> None:
    model_name, revision, batch_size, host, port, device = _read_settings()
    try:
        from fast_gliner import FastGLiNER2
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError
    except ImportError as exc:
        raise RuntimeError("fast_gliner is required to run the GLiNER provider") from exc

    model_request = {
        "repo_id": model_name,
        "revision": revision,
        "allow_patterns": ["model.onnx", "tokenizer.json"],
    }
    try:
        model_dir = snapshot_download(**model_request, local_files_only=True)
    except LocalEntryNotFoundError:
        model_dir = snapshot_download(**model_request)
    model = FastGLiNER2.from_pretrained(model_dir, execution_provider=device)
    provider = GLiNERProvider(
        model=FastGLiNER2Adapter(model),
        model_name=model_name,
        device=device,
        batch_size=batch_size,
    )
    server = make_server(provider, host=host, port=port)
    _install_shutdown_signal_handlers(server)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
