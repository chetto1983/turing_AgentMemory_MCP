"""Measure the existing FastGLiNER2 ``POST /extract`` CPU path."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from turing_agentmemory_mcp.entity_extraction import DEFAULT_GLINER_LABELS  # noqa: E402
from turing_agentmemory_mcp.gliner_provider_extraction import (  # noqa: E402
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_REVISION,
    MAX_TEXTS,
)

COMPOSE_GLINER_URL = "http://agentmemory-gliner:8080"
DEFAULT_CONCURRENCY_WIDTH = 1
DEFAULT_RUN_COUNT = 3
DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_THRESHOLD = 0.5

Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]
Clock = Callable[[], float]


class ProbeError(RuntimeError):
    pass


def load_corpus(path: Path) -> tuple[list[str], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProbeError(f"cannot read corpus: {path}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError("corpus must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"texts"}:
        raise ProbeError('corpus must be an object containing only a "texts" array')
    texts = payload["texts"]
    if not isinstance(texts, list) or not texts:
        raise ProbeError("corpus texts must be a non-empty array")
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ProbeError("every corpus text must be a non-empty string")
    if any(len(text) > 16_384 for text in texts):
        raise ProbeError("corpus text exceeds the provider 16384-character limit")
    return list(texts), hashlib.sha256(raw).hexdigest()


def resolve_endpoint(
    explicit_url: str | None,
    environment: Mapping[str, str],
    *,
    in_container: bool,
) -> str:
    candidate = (explicit_url or environment.get("GLINER_BASE_URL") or "").strip()
    if not candidate:
        if not in_container:
            raise ProbeError("--url or GLINER_BASE_URL is required outside a container")
        candidate = COMPOSE_GLINER_URL
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProbeError("GLiNER URL must be an absolute http(s) URL")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ProbeError("GLiNER URL must not contain credentials, a query, or a fragment")
    path = parsed.path.rstrip("/")
    if path not in {"", "/extract"}:
        raise ProbeError("GLiNER URL path must be empty or /extract")
    return urlunsplit((parsed.scheme, parsed.netloc, "/extract", "", ""))


def post_extract(endpoint: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ProbeError(f"GLiNER provider returned HTTP {exc.code}") from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise ProbeError(f"GLiNER provider unavailable at {endpoint}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError("GLiNER provider returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise ProbeError("GLiNER provider response must be a JSON object")
    return decoded


def validate_provider_response(
    response: dict[str, Any],
    *,
    expected_count: int,
    expected_model: str,
    expected_device: str,
) -> list[list[dict[str, Any]]]:
    model = response.get("model")
    device = response.get("device")
    results = response.get("results")
    if model != expected_model:
        raise ProbeError(f"provider model mismatch: expected {expected_model!r}, got {model!r}")
    if device != expected_device:
        raise ProbeError(f"provider device mismatch: expected {expected_device!r}, got {device!r}")
    if not isinstance(results, list):
        raise ProbeError("provider results must be an array")
    if len(results) != expected_count:
        raise ProbeError(
            f"provider returned {len(results)} results for {expected_count} ordered texts"
        )
    if any(
        not isinstance(entities, list) or any(not isinstance(entity, dict) for entity in entities)
        for entities in results
    ):
        raise ProbeError("provider results must contain one entity-object array per text")
    return results


def run_corpus_once(
    *,
    endpoint: str,
    texts: Sequence[str],
    labels: Sequence[str],
    threshold: float,
    request_batch_size: int,
    expected_model: str,
    expected_device: str,
    timeout_s: float,
    transport: Transport = post_extract,
) -> int:
    result_count = 0
    for start in range(0, len(texts), request_batch_size):
        batch = list(texts[start : start + request_batch_size])
        response = transport(
            endpoint,
            {
                "texts": batch,
                "labels": list(labels),
                "threshold": threshold,
                "include_confidence": True,
                "include_spans": True,
            },
            timeout_s,
        )
        results = validate_provider_response(
            response,
            expected_count=len(batch),
            expected_model=expected_model,
            expected_device=expected_device,
        )
        result_count += len(results)
    if result_count != len(texts):
        raise ProbeError(f"provider returned {result_count} results for {len(texts)} texts")
    return result_count


def aggregate_measurement(
    *,
    endpoint: str,
    model: str,
    model_revision: str,
    device: str,
    concurrency_width: int,
    input_count: int,
    request_batch_size: int,
    warmup_runs: int,
    wall_times_seconds: Sequence[float],
    corpus_sha256: str,
) -> dict[str, Any]:
    if input_count <= 0:
        raise ProbeError("input count must be positive")
    if not wall_times_seconds:
        raise ProbeError("at least one timed run is required")
    times = [float(value) for value in wall_times_seconds]
    if any(not math.isfinite(value) or value <= 0 for value in times):
        raise ProbeError("wall times must be positive finite numbers")
    throughputs = [input_count / value for value in times]
    return {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "endpoint": endpoint,
        "model": model,
        "model_revision": model_revision,
        "device": device,
        "concurrency_width": concurrency_width,
        "input_count": input_count,
        "request_batch_size": request_batch_size,
        "warmup_runs": warmup_runs,
        "run_count": len(times),
        "per_run_wall_times_seconds": times,
        "mean_wall_time_seconds": statistics.fmean(times),
        "standard_deviation_seconds": statistics.pstdev(times),
        "per_run_chunks_per_second": throughputs,
        "mean_chunks_per_second": statistics.fmean(throughputs),
        "corpus_sha256": corpus_sha256,
    }


def measure_cpu(
    *,
    endpoint: str,
    texts: Sequence[str],
    labels: Sequence[str],
    threshold: float,
    request_batch_size: int,
    model: str,
    model_revision: str,
    concurrency_width: int,
    run_count: int,
    warmup_runs: int,
    timeout_s: float,
    corpus_sha256: str,
    transport: Transport = post_extract,
    clock: Clock = time.perf_counter,
) -> dict[str, Any]:
    if not texts:
        raise ProbeError("corpus must not be empty")
    if run_count <= 0:
        raise ProbeError("run count must be positive")
    if warmup_runs < 0:
        raise ProbeError("warm-up run count must not be negative")
    if not 1 <= request_batch_size <= MAX_TEXTS:
        raise ProbeError(f"request batch size must be between 1 and {MAX_TEXTS}")
    if concurrency_width <= 0:
        raise ProbeError("concurrency width must be positive")
    if not labels or any(not label.strip() for label in labels):
        raise ProbeError("labels must be non-empty strings")
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ProbeError("threshold must be between 0 and 1")
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ProbeError("timeout must be a positive finite number")

    def run_once() -> int:
        return run_corpus_once(
            endpoint=endpoint,
            texts=texts,
            labels=labels,
            threshold=threshold,
            request_batch_size=request_batch_size,
            expected_model=model,
            expected_device="cpu",
            timeout_s=timeout_s,
            transport=transport,
        )

    for _ in range(warmup_runs):
        run_once()
    wall_times: list[float] = []
    for _ in range(run_count):
        started = clock()
        run_once()
        wall_times.append(clock() - started)
    return aggregate_measurement(
        endpoint=endpoint,
        model=model,
        model_revision=model_revision,
        device="cpu",
        concurrency_width=concurrency_width,
        input_count=len(texts),
        request_batch_size=request_batch_size,
        warmup_runs=warmup_runs,
        wall_times_seconds=wall_times,
        corpus_sha256=corpus_sha256,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, help='UTF-8 JSON object with a "texts" array')
    parser.add_argument("--out", required=True, help="machine-readable JSON result path")
    parser.add_argument(
        "--url",
        default="",
        help="provider base URL or /extract URL; GLINER_BASE_URL is also accepted",
    )
    parser.add_argument("--model", default=os.environ.get("GLINER_MODEL", DEFAULT_MODEL_NAME))
    parser.add_argument(
        "--model-revision",
        default=os.environ.get("GLINER_MODEL_REVISION", DEFAULT_MODEL_REVISION),
    )
    parser.add_argument(
        "--concurrency-width",
        type=int,
        default=int(os.environ.get("GLINER_BATCH_SIZE", DEFAULT_CONCURRENCY_WIDTH)),
    )
    parser.add_argument("--runs", type=int, default=DEFAULT_RUN_COUNT)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--request-batch-size", type=int, default=MAX_TEXTS)
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.environ.get("GLINER_THRESHOLD", DEFAULT_THRESHOLD)),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.environ.get("GLINER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
    )
    parser.add_argument(
        "--labels",
        default=os.environ.get("GLINER_LABELS", ",".join(DEFAULT_GLINER_LABELS)),
        help="comma-separated entity labels",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        texts, corpus_sha256 = load_corpus(Path(args.corpus))
        endpoint = resolve_endpoint(
            args.url,
            os.environ,
            in_container=Path("/.dockerenv").exists(),
        )
        labels = [label.strip() for label in args.labels.split(",") if label.strip()]
        result = measure_cpu(
            endpoint=endpoint,
            texts=texts,
            labels=labels,
            threshold=args.threshold,
            request_batch_size=args.request_batch_size,
            model=args.model.strip(),
            model_revision=args.model_revision.strip(),
            concurrency_width=args.concurrency_width,
            run_count=args.runs,
            warmup_runs=args.warmup_runs,
            timeout_s=args.timeout_seconds,
            corpus_sha256=corpus_sha256,
        )
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ProbeError, ValueError) as exc:
        print(f"GLINER_CPU_PROBE_FAILED {exc}", file=sys.stderr, flush=True)
        return 1
    print(f"GLINER_CPU_PROBE_COMPLETE {output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
