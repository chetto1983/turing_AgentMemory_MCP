from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from scripts.gliner_cpu_probe import (
    ProbeError,
    aggregate_measurement,
    load_corpus,
    measure_cpu,
    resolve_endpoint,
    run_corpus_once,
    validate_provider_response,
)
from turing_agentmemory_mcp.gliner_provider_extraction import DEFAULT_MODEL_NAME


@contextmanager
def extraction_stub(
    requests: list[list[str]],
) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            payload = json.loads(self.rfile.read(length))
            texts = payload["texts"]
            requests.append(texts)
            body = json.dumps(
                {
                    "model": DEFAULT_MODEL_NAME,
                    "device": "cpu",
                    "results": [[] for _ in texts],
                }
            ).encode()
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
        yield f"http://127.0.0.1:{server.server_port}/extract"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_load_corpus_preserves_order_and_records_exact_bytes(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.json"
    corpus.write_text('{"texts":["primo","secondo"]}', encoding="utf-8")

    texts, digest = load_corpus(corpus)

    assert texts == ["primo", "secondo"]
    assert digest == "a8e6cdfee47ec00bd7d44a60047202cba0088e0472730ef5548fe87ae61540e0"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"texts": []},
        {"texts": [""]},
        {"texts": [1]},
        {"texts": ["ok"], "metadata": {}},
    ],
)
def test_load_corpus_rejects_malformed_or_empty_input(tmp_path: Path, payload: object) -> None:
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProbeError):
        load_corpus(corpus)


def test_host_endpoint_requires_explicit_url_or_environment() -> None:
    with pytest.raises(ProbeError, match="required outside a container"):
        resolve_endpoint(None, {}, in_container=False)

    assert (
        resolve_endpoint(None, {"GLINER_BASE_URL": "http://localhost:8080"}, in_container=False)
        == "http://localhost:8080/extract"
    )
    assert resolve_endpoint(None, {}, in_container=True) == "http://agentmemory-gliner:8080/extract"


def test_run_corpus_batches_requests_without_reordering() -> None:
    captured: list[list[str]] = []
    texts = [f"text-{index}" for index in range(5)]

    with extraction_stub(captured) as endpoint:
        count = run_corpus_once(
            endpoint=endpoint,
            texts=texts,
            labels=["technology"],
            threshold=0.5,
            request_batch_size=2,
            expected_model=DEFAULT_MODEL_NAME,
            expected_device="cpu",
            timeout_s=5,
        )

    assert count == 5
    assert captured == [["text-0", "text-1"], ["text-2", "text-3"], ["text-4"]]


@pytest.mark.parametrize(
    "response, message",
    [
        ({"model": DEFAULT_MODEL_NAME, "device": "cpu"}, "results must be an array"),
        (
            {"model": DEFAULT_MODEL_NAME, "device": "cpu", "results": [[]]},
            "1 results for 2",
        ),
        (
            {"model": DEFAULT_MODEL_NAME, "device": "cpu", "results": [{}, []]},
            "entity-object array",
        ),
        (
            {"model": "wrong", "device": "cpu", "results": [[], []]},
            "model mismatch",
        ),
        (
            {"model": DEFAULT_MODEL_NAME, "device": "cuda", "results": [[], []]},
            "device mismatch",
        ),
    ],
)
def test_provider_response_validation_fails_closed(response: dict[str, Any], message: str) -> None:
    with pytest.raises(ProbeError, match=message):
        validate_provider_response(
            response,
            expected_count=2,
            expected_model=DEFAULT_MODEL_NAME,
            expected_device="cpu",
        )


def test_aggregate_measurement_emits_complete_result_contract() -> None:
    result = aggregate_measurement(
        endpoint="http://localhost:8080/extract",
        model=DEFAULT_MODEL_NAME,
        model_revision="a" * 40,
        device="cpu",
        concurrency_width=4,
        input_count=8,
        request_batch_size=8,
        warmup_runs=1,
        wall_times_seconds=[2.0, 4.0],
        corpus_sha256="b" * 64,
    )

    assert result.keys() == {
        "schema_version",
        "created_at",
        "endpoint",
        "model",
        "model_revision",
        "device",
        "concurrency_width",
        "input_count",
        "request_batch_size",
        "warmup_runs",
        "run_count",
        "per_run_wall_times_seconds",
        "mean_wall_time_seconds",
        "standard_deviation_seconds",
        "per_run_chunks_per_second",
        "mean_chunks_per_second",
        "corpus_sha256",
    }
    assert result["run_count"] == 2
    assert result["mean_wall_time_seconds"] == 3.0
    assert result["standard_deviation_seconds"] == 1.0
    assert result["per_run_chunks_per_second"] == [4.0, 2.0]
    assert result["mean_chunks_per_second"] == 3.0


def test_measure_cpu_repeats_warmup_and_timed_runs_over_same_order() -> None:
    payloads: list[list[str]] = []
    clock_values = iter([10.0, 12.0, 20.0, 24.0])

    def transport(url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        payloads.append(payload["texts"])
        return {
            "model": DEFAULT_MODEL_NAME,
            "device": "cpu",
            "results": [[] for _ in payload["texts"]],
        }

    result = measure_cpu(
        endpoint="http://localhost:8080/extract",
        texts=["a", "b"],
        labels=["technology"],
        threshold=0.5,
        request_batch_size=2,
        model=DEFAULT_MODEL_NAME,
        model_revision="a" * 40,
        concurrency_width=1,
        run_count=2,
        warmup_runs=1,
        timeout_s=5,
        corpus_sha256="b" * 64,
        transport=transport,
        clock=lambda: next(clock_values),
    )

    assert payloads == [["a", "b"], ["a", "b"], ["a", "b"]]
    assert result["per_run_wall_times_seconds"] == [2.0, 4.0]
    assert result["mean_chunks_per_second"] == 0.75


@pytest.mark.parametrize(
    ("run_count", "warmup_runs"),
    [(0, 0), (1, -1)],
)
def test_measure_cpu_rejects_invalid_run_counts(run_count: int, warmup_runs: int) -> None:
    with pytest.raises(ProbeError):
        measure_cpu(
            endpoint="http://localhost:8080/extract",
            texts=["a"],
            labels=["technology"],
            threshold=0.5,
            request_batch_size=1,
            model=DEFAULT_MODEL_NAME,
            model_revision="a" * 40,
            concurrency_width=1,
            run_count=run_count,
            warmup_runs=warmup_runs,
            timeout_s=5,
            corpus_sha256="b" * 64,
            transport=lambda *args: {
                "model": DEFAULT_MODEL_NAME,
                "device": "cpu",
                "results": [[]],
            },
        )
