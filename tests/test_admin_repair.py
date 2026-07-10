from __future__ import annotations

import json
import sys
from pathlib import Path

from turing_agentmemory_mcp.admin_repair import (
    repair_community_projection,
    repair_sparse_projection,
    repair_vector_index,
)
from turing_agentmemory_mcp.cli import main
from turing_agentmemory_mcp.sparse_index import SparseDocument, SparseIndex


def _corrupt_vector_home(tmp_path: Path) -> Path:
    home = tmp_path / "turing"
    vector = home / "vector"
    data = home / "data"
    vector.mkdir(parents=True)
    data.mkdir()
    (vector / "shard.router").write_text("invalid bit count", encoding="utf-8")
    (data / "graph.cypher").write_text("graph stays intact", encoding="utf-8")
    return home


def test_repair_vector_index_dry_run_reports_quarantine_without_mutating(tmp_path: Path) -> None:
    home = _corrupt_vector_home(tmp_path)

    result = repair_vector_index(home, timestamp="20260709T171500Z", apply=False)

    assert result["operation"] == "vector_index_repair"
    assert result["status"] == "would_repair"
    assert result["applied"] is False
    assert result["vector_dir"] == str(home / "vector")
    assert result["quarantine_dir"] == str(home / "vector.corrupt-20260709T171500Z")
    assert (home / "vector" / "shard.router").read_text(encoding="utf-8") == "invalid bit count"
    assert not (home / "vector.corrupt-20260709T171500Z").exists()
    assert (home / "data" / "graph.cypher").read_text(encoding="utf-8") == "graph stays intact"


def test_repair_vector_index_apply_quarantines_vector_dir_and_recreates_empty_one(
    tmp_path: Path,
) -> None:
    home = _corrupt_vector_home(tmp_path)

    result = repair_vector_index(home, timestamp="20260709T171501Z", apply=True)

    assert result["status"] == "repaired"
    assert result["applied"] is True
    assert (home / "vector").is_dir()
    assert list((home / "vector").iterdir()) == []
    assert (home / "vector.corrupt-20260709T171501Z" / "shard.router").read_text(
        encoding="utf-8"
    ) == "invalid bit count"
    assert (home / "data" / "graph.cypher").read_text(encoding="utf-8") == "graph stays intact"


def test_repair_vector_index_refuses_to_overwrite_existing_quarantine(tmp_path: Path) -> None:
    home = _corrupt_vector_home(tmp_path)
    (home / "vector.corrupt-20260709T171502Z").mkdir()

    try:
        repair_vector_index(home, timestamp="20260709T171502Z", apply=True)
    except FileExistsError as exc:
        assert "vector.corrupt-20260709T171502Z" in str(exc)
    else:
        raise AssertionError("expected existing quarantine directory to be refused")


def test_cli_repair_vector_index_defaults_to_dry_run_json(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    home = _corrupt_vector_home(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "turing-agentmemory-mcp",
            "repair-vector-index",
            "--turing-home",
            str(home),
            "--timestamp",
            "20260709T171503Z",
        ],
    )

    assert main() == 0
    output = json.loads(capsys.readouterr().out)

    assert output["status"] == "would_repair"
    assert output["applied"] is False
    assert (home / "vector" / "shard.router").exists()


def test_readme_documents_vector_index_repair() -> None:
    readme = Path(__file__).resolve().parents[1].joinpath("README.md").read_text(encoding="utf-8")

    assert "## Vector Index Repair" in readme
    assert "repair-vector-index --turing-home /turing" in readme
    assert "repair-vector-index --turing-home /turing --apply" in readme


def test_repair_sparse_projection_dry_run_does_not_mutate(tmp_path: Path) -> None:
    path = tmp_path / "data" / "agent-memory-fts.sqlite3"
    index = SparseIndex(path)
    index.initialize()
    existing = SparseDocument("alice:episode:old", "alice", "old", "episode", "old memory")
    index.upsert_many([existing])
    replacement = SparseDocument("alice:episode:new", "alice", "new", "episode", "new memory")

    result = repair_sparse_projection(path, [replacement], apply=False)

    assert result["status"] == "would_rebuild"
    assert result["canonical_document_count"] == 1
    assert [hit.source_id for hit in index.search(user_identifier="alice", query="old", limit=10)] == [
        "old"
    ]


def test_repair_sparse_projection_rebuilds_from_canonical_documents(tmp_path: Path) -> None:
    path = tmp_path / "data" / "agent-memory-fts.sqlite3"
    replacement = SparseDocument("alice:episode:new", "alice", "new", "episode", "new memory")

    result = repair_sparse_projection(path, [replacement], apply=True)

    index = SparseIndex(path)
    assert result["status"] == "rebuilt"
    assert result["applied"] is True
    assert [hit.source_id for hit in index.search(user_identifier="alice", query="new", limit=10)] == [
        "new"
    ]


class CommunityRepairStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def rebuild_communities(self, *, user_identifier: str) -> dict[str, object]:
        self.calls.append(user_identifier)
        return {"community_count": 4, "backend": "graspologic-native"}


def test_repair_community_projection_is_dry_run_by_default() -> None:
    store = CommunityRepairStore()

    result = repair_community_projection(store, user_identifier="alice")

    assert result["status"] == "would_rebuild"
    assert result["applied"] is False
    assert store.calls == []


def test_repair_community_projection_rebuilds_derived_state() -> None:
    store = CommunityRepairStore()

    result = repair_community_projection(store, user_identifier="alice", apply=True)

    assert result["status"] == "rebuilt"
    assert result["applied"] is True
    assert result["projection"]["community_count"] == 4
    assert store.calls == ["alice"]
