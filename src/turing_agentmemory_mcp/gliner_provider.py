"""Shared FastGLiNER2 HTTP provider."""

from __future__ import annotations

import os
import re
import signal
import threading
from http.server import ThreadingHTTPServer

from turing_agentmemory_mcp.gliner_provider_extraction import (
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_REVISION,
    MAX_TEXTS,
    FastGLiNER2Adapter,
    GLiNERProvider,
)
from turing_agentmemory_mcp.gliner_provider_http import (  # noqa: F401 - preserved public import path
    MAX_BODY_BYTES,
    make_server,
    start_server,
)


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
