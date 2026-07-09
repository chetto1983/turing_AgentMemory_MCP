import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from turing_agentmemory_mcp.rerank import (
    OpenAICompatibleReranker,
    Scored,
    apply_rerank_guard,
    identity,
    truncate_runes,
)


def test_identity_is_input_order() -> None:
    assert identity(["a", "b"]) == [Scored(index=0, score=0.0), Scored(index=1, score=0.0)]


def test_apply_rerank_guard_reorders_confident_scores() -> None:
    seed = ["seed-0", "seed-1", "seed-2"]
    out = apply_rerank_guard(
        seed,
        [Scored(index=2, score=0.9), Scored(index=0, score=0.2), Scored(index=1, score=0.1)],
        threshold=0.5,
    )
    assert [item for item, _ in out] == ["seed-2", "seed-0", "seed-1"]
    assert out[0][1] == 0.9


def test_apply_rerank_guard_keeps_seed_below_threshold() -> None:
    seed = ["seed-0", "seed-1"]
    out = apply_rerank_guard(
        seed,
        [Scored(index=1, score=0.2), Scored(index=0, score=0.1)],
        threshold=0.5,
    )
    assert [item for item, _ in out] == seed
    assert [score for _, score in out] == [None, None]


def test_truncate_runes_caps_wire_body() -> None:
    assert truncate_runes("abcdef", 3) == "abc"


def test_openai_compatible_reranker_reads_provider_agnostic_env(monkeypatch) -> None:
    monkeypatch.setenv("RERANK_BASE_URL", "http://rerank.example.test")
    monkeypatch.setenv("RERANK_MODEL", "generic-reranker")
    monkeypatch.setenv("RERANK_API_KEY", "rerank-key")
    monkeypatch.setenv("RERANK_DIMENSIONS", "1024")
    monkeypatch.setenv("RERANK_TIMEOUT_SECONDS", "9.5")

    reranker = OpenAICompatibleReranker.from_env()

    assert reranker.base_url == "http://rerank.example.test"
    assert reranker.model == "generic-reranker"
    assert reranker.api_key == "rerank-key"
    assert reranker.dimensions == 1024
    assert reranker.timeout_s == 9.5


def test_openai_compatible_reranker_sends_provider_api_key_and_dimensions(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            seen["path"] = self.path
            seen["api_key"] = self.headers.get("x-api-key")
            seen["payload"] = json.loads(self.rfile.read(length).decode("utf-8"))
            body = json.dumps(
                {
                    "model": seen["payload"]["model"],
                    "results": [
                        {"index": 0, "relevance_score": 0.9},
                        {"index": 1, "relevance_score": 0.1},
                    ],
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("RERANK_BASE_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("RERANK_MODEL", "cloud-reranker")
        monkeypatch.setenv("RERANK_DIMENSIONS", "1024")
        monkeypatch.setenv("PROVIDER_API_KEY", "cloud-secret")
        monkeypatch.setenv("PROVIDER_API_KEY_HEADER", "x-api-key")
        monkeypatch.setenv("PROVIDER_API_KEY_SCHEME", "")

        scored = OpenAICompatibleReranker.from_env().rerank("needle", ["needle doc", "other"])

        assert [item.index for item in scored] == [0, 1]
        assert seen["path"] == "/v1/rerank"
        assert seen["api_key"] == "cloud-secret"
        assert seen["payload"]["model"] == "cloud-reranker"
        assert seen["payload"]["dimensions"] == 1024
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
