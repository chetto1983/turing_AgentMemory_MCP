from __future__ import annotations

from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp"


def test_no_turingdb_import_anywhere_in_src() -> None:
    offenders = []
    for path in _SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import turingdb" in text or "from turingdb" in text:
            offenders.append(str(path.relative_to(_SRC_ROOT.parents[1])))
    assert not offenders, f"turingdb import still present in: {offenders}"
