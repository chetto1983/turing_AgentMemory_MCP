"""In-process stub embed/rerank HTTP servers and the ArcadeDB E2E backend
used by the deterministic E2E score gate (`e2e_score.py`).

`ArcadeE2EBackend` (04-09) connects to the already-running `arcadedb`
compose service for the E2E score gate's own ArcadeDB-backed rewire -- see
its own docstring for why it reuses the existing service rather than
spawning its own container.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from turing_agentmemory_mcp.arcadedb_client import ArcadeDBClient
from turing_agentmemory_mcp.embeddings import HashingEmbedder
from turing_agentmemory_mcp.provider_config import provider_env


def free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


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


ARCADEDB_E2E_DATABASE = "e2e_agent_memory"
ARCADEDB_E2E_IMAGE = "arcadedata/arcadedb:26.7.1"


class ArcadeE2EBackend:
    """Connects the E2E score gate to the EXISTING `arcadedb` compose service
    (04-09) -- unlike the retired container-lifecycle approach, this does NOT
    spawn its own Docker container: it reuses whatever `arcadedb` instance is
    already running (`docker compose up -d arcadedb`), the same way the
    production `turing-agentmemory-mcp` service and every live-container test
    in this repo (`tests/test_arcadedb_client.py`, `tests/test_arcadedb_chaos_restart.py`)
    already do. This sidesteps needing Docker-outside-of-Docker plumbing
    (a docker socket mount + `docker` CLI baked into the mcp image) purely
    for a throwaway ephemeral container -- the `arcadedb` service is already
    the one lightweight, already-running dependency every other part of this
    stack shares.

    A dedicated, isolated database (`ARCADEDB_E2E_DATABASE`) is dropped and
    recreated on `start()` for a clean slate, so repeated runs never see
    stale data from a previous run.
    """

    def __init__(self) -> None:
        self.client = ArcadeDBClient(
            base_url=provider_env("ARCADEDB_URL", default="http://127.0.0.1:2480"),
            database=ARCADEDB_E2E_DATABASE,
            username=provider_env("ARCADEDB_USER", default="root"),
            password=provider_env("ARCADEDB_PASSWORD", default="agentmemory-arcadedb-dev"),
        )

    def start(self) -> None:
        if not self.client.is_ready():
            raise RuntimeError(
                f"ArcadeDB not reachable at {self.client.base_url} -- start it with "
                "`docker compose up -d arcadedb` before running the E2E score gate."
            )
        try:
            self.client._server_command(f"drop database {ARCADEDB_E2E_DATABASE}")
        except RuntimeError:
            pass
        self.client.ensure_database()

    def stop(self) -> dict[str, Any]:
        # Nothing to shut down -- the `arcadedb` service is shared, long-lived
        # infrastructure this backend does not own the lifecycle of.
        return {"stopped": True, "owns_container_lifecycle": False}

    def restart_backend_and_wait_ready(self, *, timeout_s: float = 60.0) -> None:
        """Force-restarts the `arcadedb` compose service itself (the D-10
        chaos-restart property `tests/test_arcadedb_chaos_restart.py` already
        proves in isolation) so `run_e2e`'s own restart-durability check
        exercises a REAL restart, not a same-process no-op. Requires `docker
        compose` on PATH and this process to run on the host the `arcadedb`
        service is orchestrated from (not nested inside another container
        without a docker socket) -- raises with a clear, actionable message
        otherwise; the calling `check()` records that as a failed check, not
        a silent pass.
        """
        if shutil.which("docker") is None:
            raise RuntimeError("docker is not on PATH -- cannot restart the arcadedb service")
        stop_result = subprocess.run(
            ["docker", "compose", "stop", "arcadedb"], capture_output=True, timeout=60
        )
        if stop_result.returncode != 0:
            raise RuntimeError(
                f"docker compose stop arcadedb failed: "
                f"{stop_result.stderr.decode('utf-8', errors='replace')}"
            )
        start_result = subprocess.run(
            ["docker", "compose", "start", "arcadedb"], capture_output=True, timeout=60
        )
        if start_result.returncode != 0:
            raise RuntimeError(
                f"docker compose start arcadedb failed: "
                f"{start_result.stderr.decode('utf-8', errors='replace')}"
            )
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.client.is_ready():
                return
            time.sleep(0.5)
        raise RuntimeError(f"arcadedb did not become ready again within {timeout_s}s")
