from __future__ import annotations

import json
from pathlib import Path

from turing_agentmemory_mcp.agent_quality_eval import (
    build_agent_quality_corpus,
    default_agent_quality_out,
    evaluate_case,
    summarize_case_results,
)


def test_build_agent_quality_corpus_reads_selected_aura_files(tmp_path: Path) -> None:
    aura = tmp_path / "Aura"
    (aura / "web" / "src" / "chat" / "voice").mkdir(parents=True)
    (aura / "web" / "src" / "chat").mkdir(parents=True, exist_ok=True)
    (aura / "README.md").write_text(
        "Aura is a local-first provider-neutral AI agent platform in Go with graph-backed memory.",
        encoding="utf-8",
    )
    (aura / "CLAUDE.md").write_text(
        "Senza PRD completo non si scrive una riga di codice.",
        encoding="utf-8",
    )
    (aura / "web" / "src" / "chat" / "voice" / "AutoSpeak.tsx").write_text(
        "export function AutoSpeak() { return null }",
        encoding="utf-8",
    )
    (aura / "web" / "src" / "chat" / "ExternalStoreChat.tsx").write_text(
        "export function ExternalStoreChat() { return null }",
        encoding="utf-8",
    )

    corpus = build_agent_quality_corpus(aura)

    assert {memory.memory_id for memory in corpus.memories} >= {
        "agentmemory-docker-stdio",
        "davide-entity-extraction-priority",
        "aura-readonly-boundary",
    }
    assert {document.document_id for document in corpus.documents} >= {
        "aura-readme",
        "aura-claude-guidance",
        "aura-web-autospeak",
        "aura-web-external-store-chat",
    }
    assert any("local-first provider-neutral" in document.text for document in corpus.documents)
    assert any(case.expected_id == "aura-readme" for case in corpus.cases)


def test_evaluate_case_tracks_top1_top3_and_scores() -> None:
    result = evaluate_case(
        query_id="aura-readme-local-first",
        kind="document",
        query="local-first Go agent",
        expected_id="aura-readme",
        hit_ids=["wrong", "aura-readme", "other"],
        latency_ms=12.3456,
        top_score=0.81234,
    )

    assert result == {
        "query_id": "aura-readme-local-first",
        "kind": "document",
        "query": "local-first Go agent",
        "expected_id": "aura-readme",
        "hit_ids": ["wrong", "aura-readme", "other"],
        "top1": False,
        "top3": True,
        "latency_ms": 12.346,
        "top_score": 0.8123,
    }


def test_summarize_case_results_reports_machine_readable_quality() -> None:
    rows = [
        evaluate_case(
            query_id="m1",
            kind="memory",
            query="one",
            expected_id="m1",
            hit_ids=["m1"],
            latency_ms=1,
            top_score=1.0,
        ),
        evaluate_case(
            query_id="d1",
            kind="document",
            query="two",
            expected_id="d1",
            hit_ids=["x", "d1"],
            latency_ms=3,
            top_score=0.5,
        ),
    ]

    summary = summarize_case_results(rows)

    assert summary["count"] == 2
    assert summary["top1_accuracy"] == 0.5
    assert summary["top3_accuracy"] == 1.0
    assert summary["p50_ms"] == 2.0
    assert summary["verdict"] == "NEEDS_ATTENTION"


def test_default_agent_quality_out_uses_benchmarks_directory(monkeypatch, tmp_path: Path) -> None:
    import turing_agentmemory_mcp.agent_quality_eval as quality

    monkeypatch.setattr(quality, "ROOT", tmp_path)

    out = default_agent_quality_out()

    assert out.parent == tmp_path / ".benchmarks"
    assert out.name.startswith("agent-quality-")
    assert out.suffix == ".json"
    json.dumps({"out": str(out)})
