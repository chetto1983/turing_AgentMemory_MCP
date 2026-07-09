from __future__ import annotations

from turing_agentmemory_mcp import benchmark
from turing_agentmemory_mcp.benchmark import REQUIRED_FIELDS, make_result_row


def test_result_row_contains_required_machine_readable_fields() -> None:
    row = make_result_row(
        timestamp="2026-07-09T12:00:00Z",
        git_commit="abc123",
        turingdb_version="1.35",
        embedding_model="local-embedding",
        rerank_model="local-rerank",
        dataset="synthetic",
        operation="memory_search",
        durations_ms=[10.0, 20.0, 30.0, 40.0],
        successes=3,
        notes="top_k=5",
    )

    assert set(REQUIRED_FIELDS) <= set(row)
    assert row["count"] == 4
    assert row["p50_ms"] == 20.0
    assert row["p95_ms"] == 40.0
    assert row["p99_ms"] == 40.0
    assert row["success_rate"] == 0.75


def test_git_commit_can_come_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("BENCHMARK_GIT_COMMIT", "687e9d8")

    assert benchmark._git_commit() == "687e9d8"


def test_git_commit_can_come_from_git_head_without_git_binary(monkeypatch, tmp_path) -> None:
    git_dir = tmp_path / ".git"
    ref = git_dir / "refs" / "heads" / "main"
    ref.parent.mkdir(parents=True)
    ref.write_text("0123456789abcdef\n", encoding="utf-8")
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    def missing_git(*_args, **_kwargs) -> None:
        raise FileNotFoundError("git")

    monkeypatch.delenv("BENCHMARK_GIT_COMMIT", raising=False)
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    monkeypatch.setattr(benchmark, "ROOT", tmp_path)
    monkeypatch.setattr(benchmark.subprocess, "run", missing_git)

    assert benchmark._git_commit() == "0123456"


def test_memoryarena_case_builder_handles_backgrounds_and_markers() -> None:
    sample = {
        "id": 7,
        "_source_url": "https://huggingface.co/buckets/Chetro983/memoryarena-bucket/resolve/main/formal_reasoning_math/data.jsonl",
        "backgrounds": ["definition alpha", "definition beta"],
        "questions": ["What follows from alpha?", "What follows from beta?"],
        "answers": ["alpha answer", {"target_asin": "B012345"}],
    }

    cases = benchmark._memoryarena_cases_from_sample("formal_reasoning_math", sample)

    assert [case.sample_id for case in cases] == ["7", "7"]
    assert [case.background for case in cases] == ["definition alpha", "definition beta"]
    assert [case.marker for case in cases] == ["alpha answer", "B012345"]
    assert "answer_marker: B012345" in cases[1].content


def test_parse_memoryarena_configs_accepts_all_and_skip() -> None:
    assert benchmark._parse_memoryarena_configs("none") == []
    assert "progressive_search" in benchmark._parse_memoryarena_configs("all")
    assert benchmark._parse_memoryarena_configs("progressive_search, formal_reasoning_math") == [
        "progressive_search",
        "formal_reasoning_math",
    ]
