from __future__ import annotations

import argparse
import json
from pathlib import Path

from turing_agentmemory_mcp.utcp import build_utcp_manual, parse_command_json, utcp_manual_from_env


def main() -> int:
    parser = argparse.ArgumentParser(prog="turing-agentmemory-mcp")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the FastMCP server")
    serve.add_argument("--transport", choices=["stdio", "http", "sse"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)

    score = sub.add_parser("e2e-score", help="Run deterministic 10/10 E2E score")
    score.add_argument("--out", default="e2e-results.json")

    quality = sub.add_parser("agent-quality-eval", help="Run real-agent memory/document retrieval eval")
    quality.add_argument("--aura-root", default=r"D:\Aura")
    quality.add_argument("--out", default=None)
    quality.add_argument("--keep-home", action="store_true")
    quality.add_argument("--use-external-embed", action="store_true")
    quality.add_argument("--use-external-rerank", action="store_true")

    manual = sub.add_parser("utcp-manual", help="Print a UTCP manual for this MCP server")
    manual.add_argument("--server-name", default=None)
    manual.add_argument("--command-json", default=None)

    args = parser.parse_args()
    if args.command == "serve":
        from turing_agentmemory_mcp.server import create_mcp_app

        app = create_mcp_app()
        kwargs = {}
        if args.transport in {"http", "sse"}:
            kwargs = {"host": args.host, "port": args.port}
        app.run(transport=args.transport, **kwargs)
        return 0
    if args.command == "e2e-score":
        from turing_agentmemory_mcp.e2e_score import run_e2e

        result = run_e2e(Path(args.out))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("score") == 10.0 else 1
    if args.command == "agent-quality-eval":
        from turing_agentmemory_mcp.agent_quality_eval import (
            default_agent_quality_out,
            run_agent_quality_eval,
        )

        result = run_agent_quality_eval(
            aura_root=Path(args.aura_root),
            out=Path(args.out) if args.out else default_agent_quality_out(),
            keep_home=args.keep_home,
            use_external_embed=args.use_external_embed,
            use_external_rerank=args.use_external_rerank,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["summary"]["verdict"] == "VALIDATED_AGENT_QUALITY" else 1
    if args.command == "utcp-manual":
        if args.server_name is None and args.command_json is None:
            manual_json = utcp_manual_from_env()
        else:
            try:
                command = parse_command_json(args.command_json) if args.command_json else None
            except (json.JSONDecodeError, ValueError) as exc:
                parser.error(str(exc))
            manual_json = build_utcp_manual(
                server_name=args.server_name or "turing-agentmemory-mcp",
                command=command,
            )
        print(json.dumps(manual_json, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
