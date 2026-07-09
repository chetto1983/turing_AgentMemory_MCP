from __future__ import annotations

import argparse
import json
from pathlib import Path

from turing_agentmemory_mcp.server import create_mcp_app


def main() -> int:
    parser = argparse.ArgumentParser(prog="turing-agentmemory-mcp")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the FastMCP server")
    serve.add_argument("--transport", choices=["stdio", "http", "sse"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)

    score = sub.add_parser("e2e-score", help="Run deterministic 10/10 E2E score")
    score.add_argument("--out", default="e2e-results.json")

    args = parser.parse_args()
    if args.command == "serve":
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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
