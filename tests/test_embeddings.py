import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from turing_agentmemory_mcp.embeddings import HashingEmbedder, OpenAICompatibleEmbedder


def test_hashing_embedder_is_deterministic_and_normalized() -> None:
    embedder = HashingEmbedder(dimensions=16)
    first = embedder.embed("espresso memory")
    second = embedder.embed("espresso memory")
    assert first == second
    assert round(sum(value * value for value in first), 6) == 1.0
    assert len(first) == 16


def test_openai_compatible_embedder_reads_provider_agnostic_env(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_BASE_URL", "http://embed.example.test")
    monkeypatch.setenv("EMBED_DIMENSIONS", "384")
    monkeypatch.setenv("EMBED_MODEL", "generic-embedder")
    monkeypatch.setenv("EMBED_API_KEY", "embed-key")
    monkeypatch.setenv("EMBED_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("EMBED_BATCH_SIZE", "2")
    monkeypatch.setenv("EMBED_REQUEST_DIMENSIONS", "384")

    embedder = OpenAICompatibleEmbedder.from_env()

    assert embedder.base_url == "http://embed.example.test"
    assert embedder.dimensions == 384
    assert embedder.model == "generic-embedder"
    assert embedder.api_key == "embed-key"
    assert embedder.timeout_s == 12.5
    assert embedder.batch_size == 2
    assert embedder.request_dimensions == 384


def test_openai_compatible_embedder_bounds_provider_batches(monkeypatch) -> None:
    payloads: list[list[str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            inputs = json.loads(self.rfile.read(length).decode("utf-8"))["input"]
            payloads.append(inputs)
            body = json.dumps(
                {
                    "data": [
                        {"index": index, "embedding": [float(index), 1.0]}
                        for index, _ in enumerate(inputs)
                    ]
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
        embedder = OpenAICompatibleEmbedder(
            base_url=f"http://127.0.0.1:{server.server_port}",
            dimensions=2,
            batch_size=2,
        )

        vectors = embedder.embed_many(["a", "b", "c", "d", "e"])

        assert payloads == [["a", "b"], ["c", "d"], ["e"]]
        assert len(vectors) == 5
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_openai_compatible_embedder_reads_retrieval_prompts(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_QUERY_PREFIX", "task: search result | query: ")
    monkeypatch.setenv("EMBED_DOCUMENT_PREFIX", "title: none | text: ")

    embedder = OpenAICompatibleEmbedder.from_env()

    assert embedder.query_prefix == "task: search result | query: "
    assert embedder.document_prefix == "title: none | text: "


def test_openai_compatible_embedder_sends_provider_api_key_header(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            seen["path"] = self.path
            seen["api_key"] = self.headers.get("x-api-key")
            seen["payload"] = json.loads(self.rfile.read(length).decode("utf-8"))
            body = json.dumps(
                {
                    "object": "list",
                    "data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}],
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
        monkeypatch.setenv("EMBED_BASE_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("EMBED_DIMENSIONS", "3")
        monkeypatch.setenv("EMBED_MODEL", "cloud-embedder")
        monkeypatch.setenv("PROVIDER_API_KEY", "cloud-secret")
        monkeypatch.setenv("PROVIDER_API_KEY_HEADER", "x-api-key")
        monkeypatch.setenv("PROVIDER_API_KEY_SCHEME", "")
        monkeypatch.setenv("EMBED_REQUEST_DIMENSIONS", "3")

        vector = OpenAICompatibleEmbedder.from_env().embed("hello cloud")

        assert vector == [1.0, 0.0, 0.0]
        assert seen["path"] == "/v1/embeddings"
        assert seen["api_key"] == "cloud-secret"
        assert seen["payload"]["model"] == "cloud-embedder"
        assert seen["payload"]["dimensions"] == 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_openai_compatible_embedder_applies_distinct_query_and_document_prefixes(monkeypatch) -> None:
    payloads: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            payloads.append(payload)
            body = json.dumps(
                {
                    "object": "list",
                    "data": [
                        {"index": index, "embedding": [1.0, 0.0]}
                        for index, _ in enumerate(payload["input"])
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
        monkeypatch.setenv("EMBED_BASE_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("EMBED_DIMENSIONS", "2")
        monkeypatch.setenv("EMBED_QUERY_PREFIX", "query: ")
        monkeypatch.setenv("EMBED_DOCUMENT_PREFIX", "document: ")
        embedder = OpenAICompatibleEmbedder.from_env()

        assert embedder.embed_documents(["memory one", "memory two"]) == [[1.0, 0.0], [1.0, 0.0]]
        assert embedder.embed_query("who owns Aurora?") == [1.0, 0.0]

        assert [payload["input"] for payload in payloads] == [
            ["document: memory one", "document: memory two"],
            ["query: who owns Aurora?"],
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_openai_compatible_embedder_retries_embedded_provider_overload() -> None:
    calls = 0

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            nonlocal calls
            calls += 1
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            if calls == 1:
                payload = {
                    "error": {
                        "code": 429,
                        "message": "Model busy, retry later",
                    }
                }
            else:
                payload = {"data": [{"index": 0, "embedding": [1.0, 0.0]}]}
            body = json.dumps(payload).encode("utf-8")
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
        embedder = OpenAICompatibleEmbedder(
            base_url=f"http://127.0.0.1:{server.server_port}",
            dimensions=2,
            max_attempts=2,
            retry_base_s=0,
        )

        assert embedder.embed("retry me") == [1.0, 0.0]
        assert calls == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_openai_compatible_embedder_retries_transient_read_timeout(monkeypatch) -> None:
    calls = 0

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {"data": [{"index": 0, "embedding": [1.0, 0.0]}]}
            ).encode("utf-8")

    def flaky_urlopen(*args: object, **kwargs: object) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("private provider timeout detail")
        return Response()

    monkeypatch.setattr("turing_agentmemory_mcp.embeddings.urlopen", flaky_urlopen)
    embedder = OpenAICompatibleEmbedder(
        base_url="http://provider",
        dimensions=2,
        max_attempts=2,
        retry_base_s=0,
    )

    assert embedder.embed("retry timeout") == [1.0, 0.0]
    assert calls == 2
