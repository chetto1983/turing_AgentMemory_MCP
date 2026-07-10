from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import yaml

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.cli import main
from turing_agentmemory_mcp.utcp import build_utcp_manual, utcp_manual_from_env

ROOT = Path(__file__).resolve().parents[1]


def _tools_by_name(manual: dict[str, object]) -> dict[str, dict[str, object]]:
    return {tool["name"]: tool for tool in manual["tools"]}  # type: ignore[index]


def test_build_utcp_manual_describes_agentmemory_mcp_tools() -> None:
    command = ["python", "-m", "turing_agentmemory_mcp", "serve", "--transport", "stdio"]

    manual = build_utcp_manual(server_name="agentmemory", command=command)

    assert manual["manual_version"] == "1.0.0"
    assert manual["utcp_version"] == "1.0.2"
    tools = _tools_by_name(manual)
    assert {
        "memory_store_message",
        "memory_store_messages",
        "memory_search",
        "memory_get_context",
        "document_ingest_text",
        "document_ingest_file",
        "document_search",
    } <= set(tools)
    assert len(tools) == 16

    search_tool = tools["memory_search"]
    assert "fused" in search_tool["description"].lower()
    assert search_tool["inputs"]["required"] == ["query"]  # type: ignore[index]
    assert search_tool["inputs"]["properties"]["user_identifier"]["default"] == "default"  # type: ignore[index]
    assert "created_after" in search_tool["inputs"]["properties"]  # type: ignore[index]
    assert "tags" in tools["document_search"]["inputs"]["properties"]  # type: ignore[index]
    assert search_tool["outputs"]["type"] == "array"  # type: ignore[index]

    ingest_tool = tools["document_ingest_text"]
    assert ingest_tool["inputs"]["required"] == ["title", "text"]  # type: ignore[index]
    ingest_file_tool = tools["document_ingest_file"]
    assert ingest_file_tool["inputs"]["required"] == ["title", "path"]  # type: ignore[index]
    assert "MarkItDown" in ingest_file_tool["description"]
    assert "citations" in tools["document_search"]["description"]

    for tool in tools.values():
        template = tool["tool_call_template"]  # type: ignore[index]
        assert template["name"] == "agentmemory"  # type: ignore[index]
        assert template["call_template_type"] == "mcp"  # type: ignore[index]
        assert template["allowed_communication_protocols"] == ["mcp"]  # type: ignore[index]
        mcp_server = template["config"]["mcpServers"]["agentmemory"]  # type: ignore[index]
        assert mcp_server == {"transport": "stdio", "command": command}


def test_utcp_manual_from_env_uses_command_json_and_never_leaks_static_auth_token(
    monkeypatch,
) -> None:
    command = [
        "docker.exe",
        "compose",
        "-f",
        "D:\\turing_AgentMemory_MCP\\compose.yaml",
        "run",
        "--rm",
        "-T",
        "turing-agentmemory-mcp",
        "serve",
        "--transport",
        "stdio",
    ]
    monkeypatch.setenv("AGENTMEMORY_UTCP_SERVER_NAME", "turing-agentmemory-mcp")
    monkeypatch.setenv("AGENTMEMORY_UTCP_MCP_COMMAND", json.dumps(command))
    monkeypatch.setenv("AGENTMEMORY_AUTH_TOKEN", "super-secret-token")

    manual = utcp_manual_from_env()

    assert "super-secret-token" not in json.dumps(manual)
    template = _tools_by_name(manual)["memory_search"]["tool_call_template"]  # type: ignore[index]
    assert template["config"]["mcpServers"]["turing-agentmemory-mcp"]["command"] == command  # type: ignore[index]
    assert template["auth"] == {  # type: ignore[index]
        "auth_type": "api_key",
        "api_key": "Bearer ${AGENTMEMORY_AUTH_TOKEN}",
        "var_name": "Authorization",
        "location": "header",
    }


def test_cli_prints_utcp_manual_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "turing-agentmemory-mcp",
            "utcp-manual",
            "--server-name",
            "agentmemory",
            "--command-json",
            '["python","-m","turing_agentmemory_mcp"]',
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out

    manual = json.loads(output)
    template = _tools_by_name(manual)["memory_search"]["tool_call_template"]  # type: ignore[index]
    assert template["name"] == "agentmemory"  # type: ignore[index]
    assert template["config"]["mcpServers"]["agentmemory"]["command"] == [  # type: ignore[index]
        "python",
        "-m",
        "turing_agentmemory_mcp",
    ]


def test_utcp_manual_export_is_documented_and_exposed_in_compose() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    env = set(compose["services"]["turing-agentmemory-mcp"]["environment"])
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "AGENTMEMORY_UTCP_MCP_COMMAND" in env
    assert "AGENTMEMORY_UTCP_SERVER_NAME" in env
    assert "utcp-manual" in readme
    assert "UTCP_CONFIG_FILE" in readme
