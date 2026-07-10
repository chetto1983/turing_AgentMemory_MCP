from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_fastmcp_import_is_deprecation_clean() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "error",
            "-c",
            "from importlib.metadata import version; import fastmcp; print(version('fastmcp'))",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_project_requires_fastmcp_v3() -> None:
    pyproject = Path(__file__).resolve().parents[1].joinpath("pyproject.toml").read_text(
        encoding="utf-8"
    )

    assert '"fastmcp>=3.4,<4"' in pyproject
