"""Small stdlib web console for local AgentMemory benchmark inspection."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

FRONTEND_PACKAGE = "turing_agentmemory_mcp.frontend"
REQUIRED_BENCHMARK_FIELDS = (
    "timestamp",
    "git_commit",
    "turingdb_version",
    "embedding_model",
    "rerank_model",
    "dataset",
    "operation",
    "count",
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "success_rate",
    "notes",
)


@dataclass(frozen=True)
class BenchmarkFile:
    name: str
    path: Path
    mtime: float
    rows: int


def default_benchmark_dir() -> Path:
    configured = os.environ.get("AGENTMEMORY_LAB_BENCHMARK_DIR")
    return Path(configured) if configured else Path.cwd() / ".benchmarks"


def frontend_asset(name: str) -> bytes:
    return files(FRONTEND_PACKAGE).joinpath(name).read_bytes()


def list_benchmark_files(benchmark_dir: str | Path | None = None) -> list[BenchmarkFile]:
    bench_dir = Path(benchmark_dir) if benchmark_dir is not None else default_benchmark_dir()
    if not bench_dir.exists():
        return []

    found: list[BenchmarkFile] = []
    paths = sorted(
        bench_dir.glob("benchmark-*.json"),
        key=lambda item: (item.stat().st_mtime, item.name),
        reverse=True,
    )
    for path in paths:
        rows = 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = len(payload) if isinstance(payload, list) else 0
        except (OSError, json.JSONDecodeError):
            rows = 0
        found.append(BenchmarkFile(path.name, path, path.stat().st_mtime, rows))
    return found


def load_latest_benchmark(benchmark_dir: str | Path | None = None) -> tuple[Path | None, list[dict[str, Any]]]:
    files_found = list_benchmark_files(benchmark_dir)
    if not files_found:
        return None, []

    latest = files_found[0].path
    payload = json.loads(latest.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{latest} must contain a JSON array")
    return latest, [row for row in payload if isinstance(row, dict)]


def benchmark_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "operation_count": 0,
            "success_rate": 0,
            "best_p50_ms": 0,
            "slowest_p95_ms": 0,
            "required_fields_ok": False,
        }

    success_rates = [float(row.get("success_rate", 0) or 0) for row in rows]
    p50_values = [float(row.get("p50_ms", 0) or 0) for row in rows if row.get("p50_ms") is not None]
    p95_values = [float(row.get("p95_ms", 0) or 0) for row in rows if row.get("p95_ms") is not None]
    required_ok = all(all(field in row for field in REQUIRED_BENCHMARK_FIELDS) for row in rows)
    return {
        "operation_count": len(rows),
        "success_rate": round(sum(success_rates) / len(success_rates), 4),
        "best_p50_ms": round(min(p50_values), 3) if p50_values else 0,
        "slowest_p95_ms": round(max(p95_values), 3) if p95_values else 0,
        "required_fields_ok": required_ok,
    }


def build_lab_payload(benchmark_dir: str | Path | None = None) -> dict[str, Any]:
    latest, rows = load_latest_benchmark(benchmark_dir)
    summary = benchmark_summary(rows)

    nodes: list[dict[str, Any]] = [
        {"id": "mcp", "label": "AgentMemory MCP", "type": "service", "x": 500, "y": 92},
        {"id": "turingdb", "label": "TuringDB", "type": "store", "x": 326, "y": 238},
        {"id": "aura_embed", "label": "Aura Embed", "type": "provider", "x": 684, "y": 230},
        {"id": "aura_rerank", "label": "Aura Rerank", "type": "provider", "x": 804, "y": 380},
        {"id": "memories", "label": "Memory Tools", "type": "memory", "x": 205, "y": 390},
        {"id": "documents", "label": "Document Tools", "type": "document", "x": 430, "y": 464},
        {"id": "benchmark", "label": latest.name if latest else "No benchmark", "type": "benchmark", "x": 650, "y": 502},
    ]
    edges: list[dict[str, str]] = [
        {"source": "mcp", "target": "turingdb", "label": "persists"},
        {"source": "mcp", "target": "aura_embed", "label": "embeds"},
        {"source": "mcp", "target": "aura_rerank", "label": "reranks"},
        {"source": "mcp", "target": "memories", "label": "serves"},
        {"source": "mcp", "target": "documents", "label": "serves"},
        {"source": "benchmark", "target": "mcp", "label": "measures"},
    ]

    operation_offsets = [
        (120, 160),
        (210, 108),
        (315, 106),
        (438, 126),
        (570, 144),
        (716, 114),
        (850, 170),
        (878, 510),
        (760, 580),
        (528, 580),
    ]
    for index, row in enumerate(rows[:10]):
        operation_id = f"op_{index}"
        x, y = operation_offsets[index % len(operation_offsets)]
        nodes.append(
            {
                "id": operation_id,
                "label": str(row.get("operation", operation_id)),
                "type": "operation",
                "x": x,
                "y": y,
                "p50_ms": row.get("p50_ms"),
                "p95_ms": row.get("p95_ms"),
                "success_rate": row.get("success_rate"),
                "count": row.get("count"),
                "dataset": row.get("dataset"),
            }
        )
        edges.append({"source": "benchmark", "target": operation_id, "label": "row"})

    return {
        "benchmark": {
            "name": latest.name if latest else None,
            "path": str(latest) if latest else None,
            "rows": rows,
            "summary": summary,
        },
        "graph": {
            "nodes": nodes,
            "edges": edges,
        },
        "required_fields": list(REQUIRED_BENCHMARK_FIELDS),
    }


def _json_response(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _static_response(handler: BaseHTTPRequestHandler, name: str, content_type: str) -> None:
    try:
        body = frontend_asset(name)
    except FileNotFoundError:
        _json_response(handler, HTTPStatus.NOT_FOUND, {"error": "asset not found"})
        return
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(benchmark_dir: str | Path | None = None) -> type[BaseHTTPRequestHandler]:
    resolved_benchmark_dir = Path(benchmark_dir) if benchmark_dir is not None else default_benchmark_dir()

    class LabHandler(BaseHTTPRequestHandler):
        server_version = "AgentMemoryLab/1.0"

        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                _static_response(self, "index.html", "text/html; charset=utf-8")
                return
            if path == "/styles.css":
                _static_response(self, "styles.css", "text/css; charset=utf-8")
                return
            if path == "/app.js":
                _static_response(self, "app.js", "text/javascript; charset=utf-8")
                return
            if path == "/api/benchmarks":
                payload = [
                    {
                        "name": item.name,
                        "path": str(item.path),
                        "mtime": item.mtime,
                        "rows": item.rows,
                    }
                    for item in list_benchmark_files(resolved_benchmark_dir)
                ]
                _json_response(self, HTTPStatus.OK, payload)
                return
            if path in ("/api/benchmarks/latest", "/api/graph/sample"):
                try:
                    _json_response(self, HTTPStatus.OK, build_lab_payload(resolved_benchmark_dir))
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return

            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})

        def log_message(self, format: str, *args: Any) -> None:
            print(f"[lab] {self.address_string()} - {format % args}")

    return LabHandler


def run_lab(host: str = "127.0.0.1", port: int = 8096, benchmark_dir: str | Path | None = None) -> None:
    handler = make_handler(benchmark_dir)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"AgentMemory Lab listening on http://{host}:{port}")
    print(f"Benchmark directory: {Path(benchmark_dir) if benchmark_dir is not None else default_benchmark_dir()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("AgentMemory Lab stopped")
    finally:
        server.server_close()
