"""In-process stub embed/rerank HTTP servers and the local TuringDB daemon wrapper
used by the deterministic E2E score gate (`e2e_score.py`)."""

from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from turingdb import TuringDB

from turing_agentmemory_mcp.embeddings import HashingEmbedder


def free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def wait_rest(port: int, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    client = TuringDB(type="json", host=f"http://127.0.0.1:{port}")
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            client.try_reach(timeout=2)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"TuringDB did not become ready on {port}: {last_error}")


class LocalEmbedServer:
    def __init__(self, dimensions: int = 768) -> None:
        self.dimensions = dimensions
        self.port = free_port()
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        embedder = HashingEmbedder(dimensions=self.dimensions)

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/v1/embeddings":
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                inputs = payload.get("input") or []
                if isinstance(inputs, str):
                    inputs = [inputs]
                data = [
                    {
                        "object": "embedding",
                        "index": idx,
                        "embedding": embedder.embed(str(text)),
                    }
                    for idx, text in enumerate(inputs)
                ]
                body = json.dumps(
                    {
                        "object": "list",
                        "model": payload.get("model") or "local-embedding",
                        "data": data,
                        "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)


class LocalRerankServer:
    def __init__(self) -> None:
        self.port = free_port()
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/v1/rerank":
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                query_tokens = set(str(payload.get("query") or "").lower().split())
                documents = [str(doc) for doc in payload.get("documents") or []]
                results = []
                for index, document in enumerate(documents):
                    doc_tokens = set(document.lower().split())
                    overlap = len(query_tokens & doc_tokens)
                    results.append(
                        {
                            "index": index,
                            "relevance_score": float(overlap) + (1.0 / float(index + 100)),
                        }
                    )
                results.sort(key=lambda row: row["relevance_score"], reverse=True)
                body = json.dumps(
                    {"model": payload.get("model") or "local-rerank", "results": results}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)


class TuringDaemon:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.port = free_port()
        self.log_path = home / "server.log"
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "data").mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("ab")
        self.proc = subprocess.Popen(
            [
                "turingdb",
                "start",
                "-turing-dir",
                str(self.home),
                "-i",
                "127.0.0.1",
                "-p",
                str(self.port),
                "-demon",
                "-start-timeout",
                "5000",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        log.close()
        wait_rest(self.port)

    def stop(self) -> dict[str, Any]:
        if not self.home.exists():
            return {"stopped": False}
        with self.log_path.open("ab") as log:
            proc = subprocess.run(
                ["turingdb", "stop", "-turing-dir", str(self.home), "-timeout", "5000"],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=30,
            )
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return {"stopped": proc.returncode == 0, "returncode": proc.returncode}

    def client(self) -> TuringDB:
        return TuringDB(type="json", host=f"http://127.0.0.1:{self.port}")
