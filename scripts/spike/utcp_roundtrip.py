"""Live mcp call-template round-trip against the Dockerized MCP server (D-01/D-02/D-07/D-08).

Spike-only, throwaway evidence-gathering tool for `.planning/phases/02-utcp-spike/02-FINDINGS.md`
(Phase 2: UTCP Spike). This script is NEVER merged as native-UTCP-serving code (SC#3) -- it lives
only under scripts/spike/.

Why this hand-builds the McpCallTemplate instead of reusing
`src/turing_agentmemory_mcp/utcp.py`'s `build_utcp_manual()` output: the real python-utcp
`McpConfig.mcpServers` entry wants `"command"` as a STRING plus a separate `"args"` LIST
(see McpCallTemplate's own docstring examples in the installed `utcp-mcp` package), while
`utcp.py` emits the entire argv as a single `"command"` array with an extra, unrecognized
`"transport"` key. That divergence IS a documented SC#1 conformance gap (02-RESEARCH.md finding
#2) -- this harness works around it explicitly rather than silently papering over it, and the
gap itself is printed as part of the evidence below.

Requires the packages pinned in scripts/spike/requirements.txt (utcp, utcp-mcp) to be installed:
    .venv\\Scripts\\python -m pip install -r scripts/spike/requirements.txt

Requires the compose stack's dependent services to be healthy BEFORE running without --dry-run --
`docker compose run --rm -T turing-agentmemory-mcp ...` waits on
`depends_on: condition: service_healthy` for turingdb, agentmemory-embed, agentmemory-rerank, and
agentmemory-gliner. The GPU-backed embed/rerank sidecars can take up to ~20 minutes to cold-start
(model download via agentmemory-model-init). Bring them up first:
    docker compose up -d turingdb agentmemory-embed agentmemory-rerank agentmemory-gliner
then wait for `docker compose ps` to report all healthy before running this script without
--dry-run. REGISTER_TIMEOUT_S below is deliberately generous so a slow-but-valid boot is not
misreported as a false negative (02-RESEARCH.md Pitfall 3).

A failed `register_manual()`/`call_tool()` call is itself valid SC#1 evidence (D-01) -- this
script never swallows such a failure; it prints the observed error and returns a non-zero exit
code.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "compose.yaml"
SERVER_NAME = "turing-agentmemory-mcp"
NO_LEAK_TOKEN_ENV = "AGENTMEMORY_AUTH_TOKEN"

# GPU embed/rerank sidecars can take up to ~20 min to cold-start (02-RESEARCH.md Pitfall 3).
REGISTER_TIMEOUT_S = 1200.0


def build_docker_stdio_template() -> Any:
    """Hand-build the McpCallTemplate with the CORRECTED command/args shape.

    Diverges from utcp.py's build_utcp_manual(), which emits the whole argv as a single
    "command" array with no "args" key. McpConfig's own docstring contract wants
    "command": <str executable> plus a separate "args": <list[str]> -- documented SC#1 gap #2.
    """
    from utcp_mcp.mcp_call_template import McpCallTemplate, McpConfig

    args = [
        "compose",
        "-f",
        str(COMPOSE_PATH),
        "run",
        "--rm",
        "-T",
        SERVER_NAME,
        "serve",
        "--transport",
        "stdio",
    ]
    return McpCallTemplate(
        name=SERVER_NAME,
        call_template_type="mcp",
        config=McpConfig(mcpServers={SERVER_NAME: {"command": "docker.exe", "args": args}}),
    )


def _assert_no_leak(payload: object) -> None:
    """Reuse tests/test_utcp_manual.py's no-leak discipline for anything this harness prints."""
    token = os.environ.get(NO_LEAK_TOKEN_ENV)
    if not token:
        return
    dumped = json.dumps(payload, default=str)
    if token in dumped:
        raise AssertionError(f"{NO_LEAK_TOKEN_ENV} leaked into printed evidence")


async def _run_round_trip() -> int:
    from utcp.utcp_client import UtcpClient

    print("=== UTCP live round-trip (mcp call-template, D-01/D-02/D-07/D-08) ===")
    print(
        "NOTE: this template is hand-corrected (command=str + args=list); "
        "utcp.py's build_utcp_manual() emits a single combined 'command' array -- SC#1 gap #2."
    )
    template = build_docker_stdio_template()
    client = await UtcpClient.create()

    try:
        result = await asyncio.wait_for(
            client.register_manual(template), timeout=REGISTER_TIMEOUT_S
        )
    except Exception as exc:  # noqa: BLE001 -- a failed register IS the evidence (D-01)
        print(f"register_manual FAILED (observed): {exc!r}")
        return 1

    _assert_no_leak({"success": result.success, "errors": list(result.errors)})
    print(f"register_manual success={result.success}")
    if not result.success:
        print(f"register_manual errors: {result.errors}")
        return 1

    live_tool_count = len(result.manual.tools)
    print(
        f"Live-discovered tool count (via session.list_tools(), not AGENTMEMORY_TOOL_SPECS): {live_tool_count}"
    )

    write_result: object = None
    search_result: object = None
    try:
        write_result = await client.call_tool(
            f"{SERVER_NAME}.memory_store_message",
            {
                "session_id": "utcp-spike",
                "role": "user",
                "content": "UTCP round-trip probe",
                "user_identifier": "utcp-spike-tenant",
            },
        )
        print(f"memory_store_message call_tool result: {write_result}")

        search_result = await client.call_tool(
            f"{SERVER_NAME}.memory_search",
            {"query": "UTCP round-trip probe", "user_identifier": "utcp-spike-tenant"},
        )
        print(f"memory_search call_tool result: {search_result}")
    except Exception as exc:  # noqa: BLE001 -- a failed call_tool IS the evidence (D-01)
        print(f"call_tool FAILED (observed): {exc!r}")
        return 1

    _assert_no_leak({"write": str(write_result), "search": str(search_result)})
    print("=== round-trip evidence captured successfully ===")
    return 0


def _dry_run() -> int:
    template = build_docker_stdio_template()
    dumped = template.model_dump()
    _assert_no_leak(dumped)
    print(json.dumps(dumped, indent=2))
    mcp_server = dumped["config"]["mcpServers"][SERVER_NAME]
    assert isinstance(mcp_server["command"], str), "expected command to be a string"
    assert isinstance(mcp_server["args"], list), "expected args to be a list"
    print(
        f"OK: command={mcp_server['command']!r} is a string, "
        f"args is a {len(mcp_server['args'])}-element list (corrected shape)."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print the McpCallTemplate JSON without invoking Docker. Exits 0.",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        return _dry_run()
    return asyncio.run(_run_round_trip())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
