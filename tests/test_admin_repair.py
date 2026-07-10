from __future__ import annotations

import json
import sys
from pathlib import Path

from turing_agentmemory_mcp.admin_repair import repair_vector_index
from turing_agentmemory_mcp.cli import main


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
