from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from fastmcp import Client
from turingdb import TuringDB
from turingdb import __version__ as turingdb_version

from turing_agentmemory_mcp.embeddings import HashingEmbedder
from turing_agentmemory_mcp.memoryarena import answer_marker, load_sample
from turing_agentmemory_mcp.rerank import truncate_runes
from turing_agentmemory_mcp.server import create_mcp_app
from turing_agentmemory_mcp.store import TuringAgentMemory

ROOT = Path(__file__).resolve().parents[2]


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


class LocalAuraEmbedServer:
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
                        "model": payload.get("model") or "aura-local-embedding",
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


class LocalAuraRerankServer:
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
                body = json.dumps({"model": payload.get("model") or "aura-rerank", "results": results}).encode(
                    "utf-8"
                )
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


def payload(result: Any) -> Any:
    if hasattr(result, "structured_content") and result.structured_content is not None:
        value = result.structured_content
        if isinstance(value, dict) and set(value) == {"result"}:
            return value["result"]
        return value
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "content"):
        text = "".join(getattr(item, "text", "") for item in result.content)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return result


def check(checks: list[dict[str, Any]], name: str, fn: Callable[[], Any]) -> None:
    started = time.perf_counter()
    try:
        detail = fn()
        checks.append(
            {
                "name": name,
                "ok": True,
                "points": 1.0,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "detail": detail,
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": name,
                "ok": False,
                "points": 1.0,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "error": {"type": type(exc).__name__, "message": str(exc)[:1000]},
            }
        )


async def run_mcp_checks(store: TuringAgentMemory, checks: list[dict[str, Any]]) -> None:
    app = create_mcp_app(store)
    async with Client(app) as client:
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        expected = {
            "memory_search",
            "memory_get_context",
            "memory_store_message",
            "memory_add_entity",
            "memory_add_preference",
            "memory_add_fact",
            "document_ingest_text",
            "document_search",
        }
        check(checks, "mcp_exposes_expected_tool_surface", lambda: expected <= tool_names)

        alice_message = payload(
            await client.call_tool(
                "memory_store_message",
                {
                    "user_identifier": "alice",
                    "session_id": "s1",
                    "role": "user",
                    "content": "Davide prefers espresso after lunch when reviewing TuringDB memory.",
                },
            )
        )
        payload(
            await client.call_tool(
                "memory_store_message",
                {
                    "user_identifier": "bob",
                    "session_id": "s2",
                    "role": "user",
                    "content": "Bob tracks espresso grinder prices but not Aura memory.",
                },
            )
        )
        check(
            checks,
            "memory_store_message_writes_scoped_memory",
            lambda: alice_message["user_identifier"] == "alice"
            and alice_message["kind"] == "message",
        )

        alice_search = payload(
            await client.call_tool(
                "memory_search",
                {"user_identifier": "alice", "query": "espresso TuringDB memory", "limit": 3},
            )
        )
        check(
            checks,
            "memory_search_retrieves_alice_exact_top1",
            lambda: alice_search[0]["content"].startswith("Davide prefers espresso"),
        )
        check(
            checks,
            "memory_search_does_not_leak_bob",
            lambda: all(row["user_identifier"] == "alice" for row in alice_search),
        )

        context = payload(
            await client.call_tool(
                "memory_get_context",
                {"user_identifier": "alice", "query": "what drink during memory review", "limit": 3},
            )
        )
        check(
            checks,
            "memory_get_context_returns_prompt_ready_context",
            lambda: "espresso" in context["context"].lower() and bool(context["items"]),
        )

        document_text = (
            "Emergency stop reset requires the blue key and a safety guard interlock check.\n"
            "After reset, verify guard interlock lights before restarting the conveyor.\n"
            "Monthly maintenance records include oil inspection and checklist logging."
        )
        doc = payload(
            await client.call_tool(
                "document_ingest_text",
                {
                    "user_identifier": "alice",
                    "document_id": "doc-machine-safety",
                    "title": "Machine Safety Manual",
                    "text": document_text,
                },
            )
        )
        check(
            checks,
            "document_ingest_text_writes_chunks",
            lambda: doc["document_id"] == "doc-machine-safety" and doc["chunk_count"] == 3,
        )

        doc_hits = payload(
            await client.call_tool(
                "document_search",
                {
                    "user_identifier": "alice",
                    "query": "reset safety guard interlock",
                    "limit": 3,
                },
            )
        )
        check(
            checks,
            "document_search_retrieves_exact_top1_with_citation_and_neighbor_context",
            lambda: doc_hits[0]["chunk_id"] == "doc-machine-safety#1"
            and doc_hits[0]["locator"] == "chunk=1"
            and doc_hits[0]["context"][0]["chunk_id"] == "doc-machine-safety#2",
        )

        sample = load_sample("progressive_search", index=0)
        question = sample["questions"][0]
        answer = sample["answers"][0]
        marker = answer_marker(answer)
        memoryarena_message = (
            f"MemoryArena progressive_search id={sample['id']} subtask=0\n"
            f"question: {question}\n"
            f"answer_json: {json.dumps(answer, sort_keys=True)}"
        )
        payload(
            await client.call_tool(
                "memory_store_message",
                {
                    "user_identifier": "memoryarena",
                    "session_id": "memoryarena-progressive-search",
                    "role": "assistant",
                    "content": memoryarena_message,
                },
            )
        )
        arena_hits = payload(
            await client.call_tool(
                "memory_search",
                {
                    "user_identifier": "memoryarena",
                    "query": f"MemoryArena progressive_search subtask 0 {question}",
                    "limit": 1,
                },
            )
        )
        check(
            checks,
            "memoryarena_bucket_sample_retrieves_answer_context",
            lambda: marker in arena_hits[0]["content"]
            and "Chetro983/memoryarena-bucket" in sample["_source_url"],
        )


def run_e2e(out: Path) -> dict[str, Any]:
    home = Path(os.environ.get("TURINGDB_E2E_HOME", ROOT / ".turingdb" / "e2e"))
    if home.exists():
        shutil.rmtree(home)
    daemon = TuringDaemon(home)
    embed_server: LocalAuraEmbedServer | None = None
    rerank_server: LocalAuraRerankServer | None = None
    checks: list[dict[str, Any]] = []
    cleanup: dict[str, Any] = {}
    store_holder: dict[str, TuringAgentMemory] = {}
    previous_env = {
        key: os.environ.get(key)
        for key in (
            "AURA_EMBED_BASE_URL",
            "AURA_EMBED_DIMENSIONS",
            "AURA_EMBED_MODEL",
            "AURA_RERANK_BASE_URL",
            "AURA_RERANK_MODEL",
        )
    }
    try:
        if os.environ.get("AURA_E2E_USE_EXTERNAL_EMBED") != "1":
            embed_server = LocalAuraEmbedServer(dimensions=768)
            embed_server.start()
            os.environ["AURA_EMBED_BASE_URL"] = embed_server.base_url
            os.environ["AURA_EMBED_DIMENSIONS"] = "768"
            os.environ["AURA_EMBED_MODEL"] = "aura-local-embedding"
        if os.environ.get("AURA_E2E_USE_EXTERNAL_RERANK") != "1":
            rerank_server = LocalAuraRerankServer()
            rerank_server.start()
            os.environ["AURA_RERANK_BASE_URL"] = rerank_server.base_url
            os.environ["AURA_RERANK_MODEL"] = "aura-rerank"

        def start_infra() -> dict[str, Any]:
            daemon.start()
            store = TuringAgentMemory(daemon.client(), turing_home=home, graph="e2e_agent_memory")
            store.bootstrap()
            vector = store.embedder.embed("aura-llama-embed contract ping")
            scored = store.reranker.rerank(
                "blue key interlock",
                [
                    "monthly maintenance logging",
                    truncate_runes("blue key interlock reset procedure", 480),
                ],
            )
            if not scored or scored[0].index != 1:
                raise RuntimeError(f"aura-rerank did not reorder seed pool: {scored}")
            store_holder["store"] = store
            return {
                "port": daemon.port,
                "graph": store.graph,
                "embedding_base_url": os.environ.get("AURA_EMBED_BASE_URL"),
                "embedding_dimensions": len(vector),
                "rerank_base_url": os.environ.get("AURA_RERANK_BASE_URL"),
                "rerank_top_index": scored[0].index,
            }

        check(checks, "turingdb_starts_schema_aura_embed_and_rerank_contracts", start_infra)
        store = store_holder.get("store")
        if store is not None:
            asyncio.run(run_mcp_checks(store, checks))
            cleanup = daemon.stop()

            daemon = TuringDaemon(home)
            daemon.start()
            restarted = TuringAgentMemory(daemon.client(), turing_home=home, graph="e2e_agent_memory")
            restarted.load_graph_after_restart()
            memory = restarted.search_memory(
                user_identifier="alice", query="espresso TuringDB memory", limit=1
            )
            docs = restarted.search_documents(
                user_identifier="alice", query="reset safety guard interlock", limit=1
            )
            check(
                checks,
                "restart_preserves_memory_and_document_retrieval",
                lambda: memory[0].content.startswith("Davide prefers espresso")
                and docs[0].chunk_id == "doc-machine-safety#1",
            )
    finally:
        cleanup = daemon.stop()
        if embed_server is not None:
            embed_server.stop()
        if rerank_server is not None:
            rerank_server.stop()
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    total = sum(item["points"] for item in checks)
    earned = sum(item["points"] for item in checks if item["ok"])
    score = round((earned / total) * 10.0, 3) if total else 0.0
    result = {
        "verdict": "VALIDATED_10_10" if score == 10.0 and len(checks) == 10 else "FAILED_SCORE_GATE",
        "score": score,
        "score_gate": "10/10",
        "check_count": len(checks),
        "turingdb_version": turingdb_version,
        "checks": checks,
        "cleanup": cleanup,
    }
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="e2e-results.json")
    args = parser.parse_args()
    result = run_e2e(Path(args.out))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["score"] == 10.0 and result["check_count"] == 10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
