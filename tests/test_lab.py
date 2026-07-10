import json

from turing_agentmemory_mcp.lab import build_lab_payload, frontend_asset, list_benchmark_files


def _benchmark_row(operation: str) -> dict[str, object]:
    return {
        "timestamp": "2026-07-09T20:45:57Z",
        "git_commit": "fdd2450",
        "turingdb_version": "test",
        "embedding_model": "aura-llama-embed",
        "rerank_model": "aura-rerank",
        "dataset": "unit",
        "operation": operation,
        "count": 3,
        "p50_ms": 12.5,
        "p95_ms": 24.0,
        "p99_ms": 31.0,
        "success_rate": 1.0,
        "notes": {},
    }


def test_lab_payload_reads_latest_benchmark(tmp_path):
    bench_dir = tmp_path / ".benchmarks"
    bench_dir.mkdir()
    old = bench_dir / "benchmark-20260709T100000Z.json"
    latest = bench_dir / "benchmark-20260709T204557Z.json"
    old.write_text(json.dumps([_benchmark_row("old")]), encoding="utf-8")
    latest.write_text(json.dumps([_benchmark_row("memory_search_top_k")]), encoding="utf-8")

    files = list_benchmark_files(bench_dir)
    payload = build_lab_payload(bench_dir)

    assert files[0].name == latest.name
    assert payload["benchmark"]["name"] == latest.name
    assert payload["benchmark"]["summary"]["required_fields_ok"] is True
    assert any(node["label"] == "memory_search_top_k" for node in payload["graph"]["nodes"])


def test_frontend_assets_are_packaged():
    html = frontend_asset("index.html").decode("utf-8")
    css = frontend_asset("styles.css").decode("utf-8")
    js = frontend_asset("app.js").decode("utf-8")

    assert 'id="graph-canvas"' in html
    assert "graph-view" in css
    assert "/api/graph/sample" in js
