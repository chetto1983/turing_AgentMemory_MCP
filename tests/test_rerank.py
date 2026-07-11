import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object)

from turing_agentmemory_mcp.models import DocumentHit
from turing_agentmemory_mcp.rerank import (
    OpenAICompatibleReranker,
    RerankLimits,
    Scored,
    apply_rerank_guard,
    assemble_rerank_document,
    bound_rerank_documents,
    identity,
    lexical_rerank,
    truncate_runes,
)
from turing_agentmemory_mcp.store import TuringAgentMemory


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


def test_apply_rerank_guard_preserves_materially_stronger_seed() -> None:
    seed = ["exact-path-seed", "broad-overlap-seed"]

    out = apply_rerank_guard(
        seed,
        [Scored(index=1, score=0.95), Scored(index=0, score=0.8)],
        seed_scores=[0.62, 0.43],
        preserve_seed_margin=0.1,
    )

    assert [item for item, _ in out] == seed
    assert [score for _, score in out] == [None, None]


def test_apply_rerank_guard_allows_rerank_when_seed_margin_is_small() -> None:
    seed = ["seed-0", "seed-1"]

    out = apply_rerank_guard(
        seed,
        [Scored(index=1, score=0.95), Scored(index=0, score=0.8)],
        seed_scores=[0.62, 0.59],
        preserve_seed_margin=0.1,
    )

    assert [item for item, _ in out] == ["seed-1", "seed-0"]
    assert out[0][1] == 0.95


def test_truncate_runes_caps_wire_body() -> None:
    assert truncate_runes("abcdef", 3) == "abc"


def test_openai_compatible_reranker_reads_provider_agnostic_env(monkeypatch) -> None:
    monkeypatch.setenv("RERANK_BASE_URL", "http://rerank.example.test")
    monkeypatch.setenv("RERANK_MODEL", "generic-reranker")
    monkeypatch.setenv("RERANK_API_KEY", "rerank-key")
    monkeypatch.setenv("RERANK_DIMENSIONS", "1024")
    monkeypatch.setenv("RERANK_TIMEOUT_SECONDS", "9.5")
    monkeypatch.setenv("RERANK_PROVIDER_MIN_SCORE", "0.00001")
    monkeypatch.setenv("RERANK_MAX_DOCUMENT_CHARS", "3000")
    monkeypatch.setenv("RERANK_MAX_TOTAL_BYTES", "12000")
    monkeypatch.setenv("RERANK_MAX_ESTIMATED_TOKENS", "2500")
    monkeypatch.setenv("RERANK_CHARS_PER_TOKEN", "3.5")

    reranker = OpenAICompatibleReranker.from_env()

    assert reranker.base_url == "http://rerank.example.test"
    assert reranker.model == "generic-reranker"
    assert reranker.api_key == "rerank-key"
    assert reranker.dimensions == 1024
    assert reranker.timeout_s == 9.5
    assert reranker.provider_min_score == 0.00001
    assert reranker.limits == RerankLimits(
        max_document_chars=3000,
        max_total_bytes=12000,
        max_estimated_tokens=2500,
        chars_per_token=3.5,
    )


def test_assemble_rerank_document_contains_grounded_provenance() -> None:
    value = assemble_rerank_document(
        content="Alice prefers hiking.",
        provenance={
            "memory_id": "m1",
            "source": "locomo",
            "session_id": "s1",
            "created_at": "2026-07-10T10:00:00Z",
            "path": "conversations/conv-26.json",
            "evidence_ids": ["f1", "f2"],
        },
    )

    assert "memory_id: m1" in value
    assert "source: locomo" in value
    assert "created_at: 2026-07-10T10:00:00Z" in value
    assert "path: conversations/conv-26.json" in value
    assert "evidence_ids: f1, f2" in value
    assert value.endswith("Alice prefers hiking.")


def test_bound_rerank_documents_enforces_rune_byte_and_token_budgets() -> None:
    documents = ["é" * 100, "second " * 100]
    limits = RerankLimits(
        max_document_chars=50,
        max_total_bytes=80,
        max_estimated_tokens=20,
        chars_per_token=2.0,
    )

    bounded = bound_rerank_documents(documents, limits)

    assert len(bounded) == 2
    assert all(len(value) <= 50 for value in bounded)
    assert sum(len(value.encode("utf-8")) for value in bounded) <= 80
    assert sum(len(value) for value in bounded) / 2.0 <= 20


def test_rerank_with_status_reports_provider_error_without_private_content(monkeypatch) -> None:
    def unavailable(*args: object, **kwargs: object) -> object:
        raise OSError("private source text must not leak")

    monkeypatch.setattr("turing_agentmemory_mcp.rerank.urlopen", unavailable)
    reranker = OpenAICompatibleReranker(base_url="http://provider")

    result = reranker.rerank_with_status("private query", ["private source text", "other"])

    assert result.status == "provider_error"
    assert result.scores == identity(["a", "b"])
    assert "private" not in json.dumps(result.to_dict())


def test_rerank_with_status_rejects_duplicate_provider_indices(monkeypatch) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "results": [
                        {"index": 0, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.8},
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr("turing_agentmemory_mcp.rerank.urlopen", lambda *args, **kwargs: Response())

    result = OpenAICompatibleReranker(base_url="http://provider").rerank_with_status(
        "query", ["one", "two"]
    )

    assert result.status == "invalid_response"
    assert result.scores == identity(["one", "two"])


def test_reranker_retries_embedded_provider_overload(monkeypatch) -> None:
    responses = [
        {"error": {"code": 429, "message": "Model busy, retry later"}},
        {
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.1},
            ]
        },
    ]
    calls = 0

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            nonlocal calls
            payload = responses[calls]
            calls += 1
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr("turing_agentmemory_mcp.rerank.urlopen", lambda *args, **kwargs: Response())
    reranker = OpenAICompatibleReranker(
        base_url="http://provider",
        max_attempts=2,
        retry_base_s=0,
    )

    result = reranker.rerank_with_status("query", ["one", "two"])

    assert result.status == "applied"
    assert [item.index for item in result.scores] == [1, 0]
    assert calls == 2


def test_reranker_retries_transient_read_timeout(monkeypatch) -> None:
    calls = 0

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.1},
                    ]
                }
            ).encode("utf-8")

    def flaky_urlopen(*args: object, **kwargs: object) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("private provider timeout detail")
        return Response()

    monkeypatch.setattr("turing_agentmemory_mcp.rerank.urlopen", flaky_urlopen)
    reranker = OpenAICompatibleReranker(
        base_url="http://provider",
        max_attempts=2,
        retry_base_s=0,
    )

    result = reranker.rerank_with_status("query", ["one", "two"])

    assert result.status == "applied"
    assert [item.index for item in result.scores] == [1, 0]
    assert calls == 2


def test_lexical_rerank_prioritizes_query_overlap() -> None:
    scored = lexical_rerank(
        "blue key interlock",
        ["monthly maintenance logging", "blue key interlock reset procedure"],
    )

    assert [item.index for item in scored] == [1, 0]


def test_lexical_rerank_matches_accented_latin_casefolded_text() -> None:
    scored = lexical_rerank("É", ["tea", "é"])

    assert scored[0].index == 1


def test_lexical_rerank_matches_cyrillic_casefolded_text() -> None:
    scored = lexical_rerank("МОСКВА", ["Санкт-Петербург", "Москва"])

    assert scored[0].index == 1


def test_lexical_rerank_matches_cjk_text() -> None:
    scored = lexical_rerank("检索", ["写入记忆", "检索记忆"])

    assert scored[0].index == 1


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


def test_openai_compatible_reranker_falls_back_on_tiny_provider_scores(monkeypatch) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            body = json.dumps(
                {
                    "model": "qwen-gguf",
                    "results": [
                        {"index": 0, "relevance_score": 3.0e-7},
                        {"index": 1, "relevance_score": 1.0e-8},
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
        monkeypatch.setenv("RERANK_MODEL", "qwen-gguf")
        monkeypatch.setenv("RERANK_PROVIDER_MIN_SCORE", "0.00001")

        scored = OpenAICompatibleReranker.from_env().rerank(
            "blue key interlock",
            ["monthly maintenance logging", "blue key interlock reset procedure"],
        )

        assert [item.index for item in scored] == [1, 0]
        assert scored[0].score > scored[1].score
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class StaticReranker:
    def rerank(self, query: str, documents: list[str]) -> list[Scored]:
        return [Scored(index=1, score=0.95), Scored(index=0, score=0.8)]


def test_document_rerank_preserves_stronger_hybrid_seed(tmp_path) -> None:
    store = TuringAgentMemory(
        client=object(),  # type: ignore[arg-type]
        turing_home=tmp_path,
        reranker=StaticReranker(),  # type: ignore[arg-type]
        rerank_preserve_seed_margin=0.1,
    )
    exact = DocumentHit(
        chunk_id="voice#1",
        document_id="aura-web-voice-runtime",
        title="Aura Web Voice Runtime",
        locator="chunk=1",
        text="Aura useVoiceRuntime voice runtime hook microphone speech audio",
        score=0.62,
    )
    broad = DocumentHit(
        chunk_id="readme#1",
        document_id="aura-readme",
        title="Aura README",
        locator="chunk=1",
        text="Aura README local-first provider-neutral agent platform",
        score=0.43,
    )

    hits = store._rerank_documents(
        "Aura useVoiceRuntime voice runtime hook microphone speech audio", [exact, broad]
    )

    assert [hit.document_id for hit in hits] == ["aura-web-voice-runtime", "aura-readme"]
