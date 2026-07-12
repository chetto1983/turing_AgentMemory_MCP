"""Throwaway native-http prototype for native-serving effort/behavior evidence (D-06).

Spike-only, evidence-gathering tool for `.planning/phases/02-utcp-spike/02-FINDINGS.md`
(Phase 2: UTCP Spike). NEVER merged as native-UTCP-serving code, NEVER wired into compose.yaml
(SC#3) -- it lives only under scripts/spike/, binds 127.0.0.1 only, and tears itself down in a
`finally` block.

Serves ONE path (`/tools/memory_search`) with two methods against a single stdlib
ThreadingHTTPServer:
  - GET  -- discovery: python-utcp's `HttpCommunicationProtocol.register_manual()` fetches this
            path with the call template's own http_method to discover tools. This handler
            responds with a real UTCP manual JSON declaring one tool (`memory_search`) whose own
            `tool_call_template` points back at this same URL with `http_method="POST"` and
            `body_field="body"` -- i.e. tool discovery is genuinely dynamic, not a canned client
            registration.
  - POST -- invocation: the real UtcpClient's HttpCommunicationProtocol.call_tool() POSTs the
            tool's `body` field here. The handler reads `user_identifier` for tenant scoping and
            returns a realistic memory_search-shaped JSON result.

register_manual() always sends an EMPTY body for http discovery (see the installed utcp-http
package's HttpCommunicationProtocol.register_manual -- body_content is unconditionally None for
discovery), so the handler distinguishes discovery-POST (Content-Length 0) from invocation-POST
(a real JSON body) on the same path/method, matching the real client's actual behavior rather
than a hand-waved assumption.

Per 02-RESEARCH.md Open Question #3, the backing lookup is wired to a real-ish in-memory store
(not a bare canned blob) so the effort estimate stays honest: it implements endpoint routing,
body unwrapping, tenant-scope read, an auth-header check, and output-schema mapping. `turingdb`
has no Windows wheel and this harness runs on the host, so it uses an in-memory stand-in for the
backing store rather than importing real turingdb (CLAUDE.md NEVER SUPPOSE / respect the platform
constraint) -- the printed output states which backing mode was used.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PATH = "/tools/memory_search"
BACKING_MODE = "in-memory stand-in (host, no turingdb -- no Windows wheel)"

# Realistic-enough in-memory "store": tenant_id -> list[{"content": str}]
_STORE: dict[str, list[dict[str, str]]] = {
    "utcp-spike-tenant": [{"content": "UTCP native-http prototype seed memory"}],
}


def free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _memory_search_manual(base_url: str) -> dict[str, Any]:
    """A real UTCP manual JSON, discovered live over GET -- not hardcoded client-side."""
    return {
        "utcp_version": "1.1.3",
        "manual_version": "1.0.0",
        "tools": [
            {
                "name": "memory_search",
                "description": "Search scoped memory (native-http prototype, D-06 throwaway).",
                "tags": ["memory", "search", "native-http-spike"],
                "inputs": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "user_identifier": {"type": "string"},
                    },
                    "required": ["query"],
                },
                "outputs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"content": {"type": "string"}, "score": {"type": "number"}},
                    },
                },
                "tool_call_template": {
                    "name": "native_memory_search",
                    "call_template_type": "http",
                    "http_method": "POST",
                    "url": f"{base_url}{PATH}",
                    "content_type": "application/json",
                    "body_field": "body",
                },
            }
        ],
    }


def _make_handler(base_url: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 -- discovery (UTCP manual)
            if self.path != PATH:
                self.send_error(404)
                return
            self._write_json(200, _memory_search_manual(base_url))

        def do_POST(self) -> None:  # noqa: N802 -- discovery (empty body) OR invocation (real body)
            if self.path != PATH:
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                # register_manual()'s discovery POST always sends an empty body.
                self._write_json(200, _memory_search_manual(base_url))
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            body = payload.get("body", payload)
            user_identifier = str(body.get("user_identifier") or "default")
            query = str(body.get("query") or "")
            auth_header = self.headers.get("Authorization")
            rows = _STORE.get(user_identifier, [])
            results = [
                {"content": row["content"], "score": 1.0 if query in row["content"] else 0.5}
                for row in rows
            ]
            self._write_json(
                200,
                {
                    "results": results,
                    "backing_mode": BACKING_MODE,
                    "auth_header_present": auth_header is not None,
                },
            )

        def _write_json(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    return Handler


async def _register_and_call(base_url: str) -> int:
    from utcp.utcp_client import UtcpClient
    from utcp_http.http_call_template import HttpCallTemplate

    client = await UtcpClient.create()
    manual_template = HttpCallTemplate(
        name="native_memory_search",
        call_template_type="http",
        url=f"{base_url}{PATH}",
        http_method="GET",
        content_type="application/json",
    )

    result = await client.register_manual(manual_template)
    print(f"register_manual success={result.success}")
    if not result.success:
        print(f"register_manual errors: {result.errors}")
        return 1
    print(f"Discovered {len(result.manual.tools)} tool(s) via live GET {base_url}{PATH}")

    call_result = await client.call_tool(
        "native_memory_search.memory_search",
        {
            "body": {
                "query": "UTCP native-http prototype seed memory",
                "user_identifier": "utcp-spike-tenant",
            }
        },
    )
    print(f"call_tool result: {call_result}")
    return 0


INTEGRATION_SURFACE = [
    "endpoint routing (GET discovery vs POST invocation on one path)",
    "request body unwrapping (body_field='body' contract)",
    "tenant-scope read (user_identifier lookup against the backing store)",
    "output-schema mapping (raw store rows -> memory_search-shaped JSON)",
    "auth-header presence check (Authorization header observed, not enforced -- throwaway)",
    "teardown discipline (server.shutdown() in a finally block)",
]


def _self_test() -> int:
    import asyncio

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(base_url))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(
        f"=== D-06 native-http prototype self-test on {base_url}{PATH} (backing: {BACKING_MODE}) ==="
    )
    print("Integration surface implemented by this throwaway prototype:")
    for item in INTEGRATION_SURFACE:
        print(f"  - {item}")
    try:
        exit_code = asyncio.run(_register_and_call(base_url))
    except Exception as exc:  # noqa: BLE001 -- an observed failure IS evidence, never swallow it
        print(f"self-test FAILED (observed): {exc!r}")
        exit_code = 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        print("=== server torn down ===")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        default=True,
        help="Run start -> register -> call -> teardown in-process (default, always-on).",
    )
    parser.parse_args(argv)
    return _self_test()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
