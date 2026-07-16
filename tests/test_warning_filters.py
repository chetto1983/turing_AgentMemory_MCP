from __future__ import annotations

import asyncio
import subprocess
import sys
from importlib.metadata import version
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
    pyproject = (
        Path(__file__).resolve().parents[1].joinpath("pyproject.toml").read_text(encoding="utf-8")
    )

    assert '"fastmcp>=3.4,<4"' in pyproject


def test_fastmcp_compat_installed_version_satisfies_pin() -> None:
    major, minor = (int(part) for part in version("fastmcp").split(".")[:2])

    assert (major, minor) >= (3, 4) and major < 4


def test_fastmcp_compat_create_mcp_app_registers_tools() -> None:
    from turing_agentmemory_mcp.server import create_mcp_app

    app = create_mcp_app(store=object())  # type: ignore[arg-type]
    tools = asyncio.run(app.list_tools())

    assert len(tools) >= 20
