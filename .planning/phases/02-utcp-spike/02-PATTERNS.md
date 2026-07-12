# Phase 2: UTCP Spike - Pattern Map

**Mapped:** 2026-07-12
**Files analyzed:** 5
**Analogs found:** 5 / 5

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `scripts/spike/requirements.txt` | config | file-I/O | none (no existing pinned-requirements file in this repo — deps live in `pyproject.toml`) | no-analog |
| `scripts/spike/utcp_roundtrip.py` | utility (spike harness) | request-response (stdio subprocess bridge) | `scripts/e2e_score.py` + `src/turing_agentmemory_mcp/e2e_score_stubs.py` + `tests/test_utcp_manual.py` | role-match |
| `scripts/spike/native_http_prototype.py` | service (throwaway HTTP endpoint) | request-response | `src/turing_agentmemory_mcp/e2e_score_stubs.py` (`LocalEmbedServer`/`LocalRerankServer`) | exact (stdlib `http.server` stub-server shape) |
| `scripts/spike/full_agent_chat.py` | utility (spike harness) | request-response (LLM chat over OpenAI-compatible endpoint) | `docker/llama-provider.Dockerfile` (sidecar pattern) + Pattern 1 harness above | role-match |
| `tests/test_utcp_conformance.py` | test | transform (schema validation, no I/O) | `tests/test_utcp_manual.py` | exact |

## Pattern Assignments

### `scripts/spike/requirements.txt` (config, file-I/O)

**No in-repo analog** — this repo pins all deps in `pyproject.toml`'s `[project.dependencies]` /
`[project.optional-dependencies]`, not a `requirements.txt`. RESEARCH.md §Standard Stack already
specifies exact pinned versions to use; treat this file as a flat `pkg==version` list, one per
line, explicitly kept OUT of `pyproject.toml` (SC#3 — spike-only, not a project dependency):

```
utcp==1.1.3
utcp-mcp==1.1.2
utcp-http==1.1.11
utcp-text==1.1.0
utcp-agent==1.0.3
```

Do not add a `[dev]`/`[spike]` extra to `pyproject.toml` for this — Open Question #1 in
RESEARCH.md explicitly leaves that undecided; keep it fully out-of-tree.

---

### `scripts/spike/utcp_roundtrip.py` (utility/harness, request-response over stdio subprocess)

**Analog 1 — Docker/stub-server boot sequence:** `src/turing_agentmemory_mcp/e2e_score_stubs.py`
(imports/class shapes, lines 1-25, 42-101):
```python
from __future__ import annotations
import json, socket, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from turingdb import TuringDB
from turing_agentmemory_mcp.embeddings import HashingEmbedder

def free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port
```
`LocalEmbedServer`/`LocalRerankServer` (lines 42-155) show the exact `ThreadingHTTPServer` +
`BaseHTTPRequestHandler` idiom to reuse if the round-trip needs the container's
`EMBED_BASE_URL`/`RERANK_BASE_URL` pointed at lightweight host-side stubs (per RESEARCH.md
Pitfall 3 fallback option) instead of the real GPU sidecars — bind `127.0.0.1` only.

**Analog 2 — the exact `docker compose run --rm -T ... serve --transport stdio` command shape:**
`tests/test_utcp_manual.py` lines 73-85 (already encodes the literal argv this repo expects for
the mcp call-template's `mcpServers` command):
```python
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
```
`compose.yaml` service name confirmed at line 124: `turing-agentmemory-mcp:` (also referenced at
`src/turing_agentmemory_mcp/agent_quality_eval.py:107-108` with the same `docker.exe compose -f
... run --rm -T` shape — a second in-repo confirmation of this exact invocation pattern).
**Correction needed vs. `utcp.py`'s own emission (documented gap, do NOT copy from `utcp.py`):**
python-utcp's real `McpConfig.mcpServers` entry wants `"command"` as a **string** plus a separate
`"args"` **list** (RESEARCH.md finding #2) — build the `McpCallTemplate` by hand per RESEARCH.md
§Pattern 1, splitting `"docker.exe"` into `command` and the rest into `args`, rather than reusing
`build_utcp_manual()`'s single combined array.

**Analog 3 — module boot shape (sys.path bootstrap, `if __name__ == "__main__"` entry):**
`scripts/e2e_score.py` (whole file, 12 lines):
```python
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from turing_agentmemory_mcp.e2e_score import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
```
Mirror this thin-wrapper-over-a-`main()` shape for `utcp_roundtrip.py`: keep the actual round-trip
logic in a `main() -> int` function that returns a process exit code (per RESEARCH.md's Validation
Architecture table: "exits non-zero on failure; prints structured evidence for FINDINGS.md").

**Core pattern (from RESEARCH.md §Pattern 1, already source-verified against
`d:/tmp/python-utcp`):** `UtcpClient.create()` → build `McpCallTemplate`/`McpConfig` by hand →
`register_manual()` → `call_tool()` twice (`memory_store_message` then `memory_search`, per
Claude's Discretion in CONTEXT.md). Treat `register_manual()` failure as a valid, expected
observation (RESEARCH.md Anti-Patterns: "a failed `register_manual()` call as inconclusive" is
itself a documented anti-pattern to avoid — a failure IS SC#1 evidence).

**No-leak assertion style to reuse for anything the harness prints:** `tests/test_utcp_manual.py`
lines 88-92 (asserts the raw token never appears in dumped JSON) — apply the same discipline if
the harness prints the manual/call-template JSON for FINDINGS.md evidence:
```python
monkeypatch.setenv("AGENTMEMORY_AUTH_TOKEN", "super-secret-token")
manual = utcp_manual_from_env()
assert "super-secret-token" not in json.dumps(manual)
```

---

### `scripts/spike/native_http_prototype.py` (service, request-response, throwaway)

**Analog — stdlib `http.server` stub-server pattern:** `src/turing_agentmemory_mcp/e2e_score_stubs.py`
`LocalEmbedServer` class (lines 42-101), reuse verbatim shape:
```python
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, socket, threading

class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/tools/memory_search":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        body = json.dumps({...}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return

server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
```
Security constraint (RESEARCH.md §Security Domain, D-06): bind `127.0.0.1` only, never `0.0.0.0`;
never wired into `compose.yaml`; tear down immediately after evidence gathered.
Per RESEARCH.md Open Question #3 recommendation, wire this to a real-ish call (reuse
`e2e_score_stubs.py`'s `TuringDaemon` + `HashingEmbedder` pattern in-process) rather than canned
JSON, to make effort estimates honest — same file gives the `TuringDaemon` class (lines 158-208)
for spinning up a throwaway in-process TuringDB if the prototype needs to actually answer
`memory_search`.

---

### `scripts/spike/full_agent_chat.py` (utility/harness, request-response, D-08a optional)

**Analog 1 — the harness registration shape:** reuse `scripts/spike/utcp_roundtrip.py`'s
`McpCallTemplate`/`mcpServers` construction (same Pattern 1 above) inside `UtcpAgentConfig`'s
`manual_call_templates`, per RESEARCH.md §Code Examples:
```python
from langchain_openai import ChatOpenAI
from utcp_agent import UtcpAgent, UtcpAgentConfig

llm = ChatOpenAI(
    model="local-gemma",
    base_url="http://127.0.0.1:8199/v1",
    api_key="not-needed",
    temperature=0.1,
)
utcp_config = {"manual_call_templates": [{"name": "turing-agentmemory-mcp",
    "call_template_type": "mcp", "config": {"mcpServers": {...}}}]}
agent = await UtcpAgent.create(llm=llm, utcp_config=utcp_config)
response = await agent.chat("Store the note '...' and then search for it.")
```

**Analog 2 — the LLM sidecar itself:** `docker/llama-provider.Dockerfile` (full file, 16 lines) —
`ghcr.io/ggml-org/llama.cpp:server-cuda` base image, non-root `app` user (uid 10001), env vars
`LLAMA_CACHE=/models/llama.cpp` for GGUF caching, `HF_HOME=/models/huggingface`. Reuse this exact
image/user pattern for a throwaway compose override or a one-off `docker run` invocation hosting
`gemma-4-12B-it-qat-UD-Q4_K_XL.gguf` and exposing `/v1/chat/completions` — do NOT add a permanent
service block to `compose.yaml` (SC#3). GPU-mandatory (`gpus: all`, matching the embed/rerank
sidecars in `compose.yaml`); implement the GPU-fallback check explicitly (RESEARCH.md Pitfall/
CONTEXT.md D-08a: report "full-agent chat not exercised (no GPU)" rather than silently skipping).

---

### `tests/test_utcp_conformance.py` (test, transform/validation, no I/O)

**Analog:** `tests/test_utcp_manual.py` — mirror its structure exactly (same subject module
`src/turing_agentmemory_mcp/utcp.py`).

**Imports pattern** (lines 1-14, adapt for the new file — add `utcp` package imports):
```python
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
```
The `turingdb` stub-module shim (lines 10-11) is load-bearing — `turing_agentmemory_mcp.utcp`
transitively imports `store.py`/`turingdb`, and `turingdb` has no Windows wheel; this shim is how
`test_utcp_manual.py` already runs Docker-free on Windows. Copy it verbatim into
`test_utcp_conformance.py`.

**Fixture/helper shape** (lines 16-20):
```python
ROOT = Path(__file__).resolve().parents[1]

def _tools_by_name(manual: dict[str, object]) -> dict[str, dict[str, object]]:
    return {tool["name"]: tool for tool in manual["tools"]}  # type: ignore[index]
```

**Auth-enabled manual construction pattern** (lines 70-100, adapt into the new conformance test
per RESEARCH.md §Pattern 2 — this is the exact `monkeypatch.setenv` shape to reuse for triggering
the auth-enabled path that the real `utcp` pydantic models reject):
```python
def test_manual_with_auth_fails_current_utcp_pydantic_validation(monkeypatch) -> None:
    monkeypatch.setenv("AGENTMEMORY_UTCP_SERVER_NAME", "turing-agentmemory-mcp")
    monkeypatch.setenv("AGENTMEMORY_AUTH_TOKEN", "throwaway-dummy-token")
    manual = utcp_manual_from_env()

    from utcp.data.utcp_manual import UtcpManualSerializer
    from utcp.exceptions import UtcpSerializerValidationError

    try:
        UtcpManualSerializer().validate_dict(manual)
        raised = False
    except UtcpSerializerValidationError:
        raised = True
    assert raised, "expected api_key-on-mcp-template to fail current python-utcp validation"
```

**No-leak assertion style to mirror** (from
`test_utcp_manual_from_env_uses_command_json_and_never_leaks_static_auth_token`, lines 70-100):
```python
assert "super-secret-token" not in json.dumps(manual)
```
Apply the same pattern with the dummy token value used above — any new test touching
`AGENTMEMORY_AUTH_TOKEN` must assert non-leakage, per this repo's established convention.

**README staleness check pattern** (new test, same style as
`test_utcp_manual_export_is_documented_and_exposed_in_compose`, lines 130-138 — reads README.md
directly and asserts against real library behavior):
```python
def test_readme_utcp_config_example_is_stale() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "call_template_type" in readme and "file_path" in readme  # documents the OLD shape present today
    from utcp_text.text_call_template import TextCallTemplateSerializer
    from utcp.exceptions import UtcpSerializerValidationError
    try:
        TextCallTemplateSerializer().validate_dict(
            {"call_template_type": "text", "file_path": "some/path.json"}
        )
        raised = False
    except UtcpSerializerValidationError:
        raised = True
    assert raised, "README's UTCP_CONFIG_FILE example uses the deprecated file_path field"
```

**Pytest marker convention** (`pyproject.toml` lines 61-64) — if this test requires
`utcp`/`utcp-text` to be pip-installed and the planner decides (per RESEARCH.md Open Question #1)
to keep it opt-in rather than a hard CI dependency, mark it:
```python
import pytest
pytestmark = pytest.mark.integration  # requires utcp/utcp-text installed; skip is a CI failure under CI=true
```
(`markers = ["slow: ...", "integration: requires a live external service; a skip is a CI failure under CI=true", "gpu: ..."]`)

---

## Shared Patterns

### Docker-free "stub the native module" pattern (avoids Windows `turingdb` wheel issue)
**Source:** `tests/test_utcp_manual.py` lines 10-11
**Apply to:** `tests/test_utcp_conformance.py` (any test importing `turing_agentmemory_mcp.utcp`,
which transitively imports `store.py`)
```python
if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")
```

### `docker compose run --rm -T <service> serve --transport stdio` invocation shape
**Source:** `tests/test_utcp_manual.py` lines 73-85; corroborated by
`src/turing_agentmemory_mcp/agent_quality_eval.py:107-108`; service name `turing-agentmemory-mcp`
confirmed in `compose.yaml:124`.
**Apply to:** `scripts/spike/utcp_roundtrip.py`, `scripts/spike/full_agent_chat.py` — both need the
exact stdio bridge command for the `McpCallTemplate`'s `mcpServers` entry.
```python
["docker.exe", "compose", "-f", r"D:\Repo\turing_AgentMemory_MCP\compose.yaml",
 "run", "--rm", "-T", "turing-agentmemory-mcp", "serve", "--transport", "stdio"]
```
Note the real python-utcp `McpConfig` wants this split into `command="docker.exe"` (string) +
`args=[...]` (list) — see RESEARCH.md finding #2; do not copy `utcp.py`'s single-array shape.

### Stub embed/rerank HTTP server pattern (fallback if GPU sidecars are too slow to boot)
**Source:** `src/turing_agentmemory_mcp/e2e_score_stubs.py` `LocalEmbedServer`/`LocalRerankServer`
(lines 42-155)
**Apply to:** `scripts/spike/utcp_roundtrip.py` (optional, per RESEARCH.md Pitfall 3) and
`scripts/spike/native_http_prototype.py` (the throwaway endpoint itself)
```python
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
# bind 127.0.0.1 only; daemon thread; explicit Content-Length/Content-Type headers; silent log_message
```

### No-secret-leak assertion discipline
**Source:** `tests/test_utcp_manual.py` line 92
**Apply to:** any spike script or test that prints/dumps a manual or call-template JSON while
`AGENTMEMORY_AUTH_TOKEN` (or a dummy stand-in) is set.
```python
assert "super-secret-token" not in json.dumps(manual)
```

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `scripts/spike/requirements.txt` | config | file-I/O | Repo has no precedent `requirements.txt`; all deps pinned in `pyproject.toml`. Use RESEARCH.md §Standard Stack pinned versions directly; keep out of `pyproject.toml` per SC#3. |

## Metadata

**Analog search scope:** `tests/`, `scripts/`, `src/turing_agentmemory_mcp/`, `docker/`, `compose.yaml`, `pyproject.toml`
**Files scanned:** `tests/test_utcp_manual.py`, `scripts/e2e_score.py`, `src/turing_agentmemory_mcp/e2e_score_stubs.py`, `src/turing_agentmemory_mcp/agent_quality_eval.py`, `docker/llama-provider.Dockerfile`, `compose.yaml`, `pyproject.toml`
**Pattern extraction date:** 2026-07-12
