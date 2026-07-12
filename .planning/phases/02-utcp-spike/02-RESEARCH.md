# Phase 2: UTCP Spike - Research

**Researched:** 2026-07-12
**Domain:** UTCP (Universal Tool Calling Protocol) client/consumer conformance — findings-only spike
**Confidence:** HIGH (all core findings are read directly from the cloned `d:/tmp/python-utcp` and `d:/tmp/utcp-agent` source, cross-checked against this repo's `utcp.py`/`README.md`/`tests/test_utcp_manual.py`, and confirmed live against PyPI)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Use a **live round-trip** as the primary evidence, not static schema-checking or spec-reading alone. Instantiate the real python-utcp client substrate (`UtcpClient` / `utcp-agent`), register our generated manual, and **actually call a memory tool through it** — observing whether the manual parses, auth flows, inputs validate, and outputs return. Gaps must surface as observed failures, not reasoned ones.
- **D-02:** The current export already emits tools with `call_template_type: "mcp"` (a UTCP client reaches our server *through* MCP stdio, not native UTCP-over-HTTP). The round-trip must exercise **this mcp call-template path first** — it is the status-quo behavior under test.
- **D-03:** The motivating consumer is **`utcp-agent`** (`github.com/universal-tool-calling-protocol/utcp-agent`), a LangGraph/LangChain agent that bundles the `utcp`, `utcp-http`, `utcp-mcp`, `utcp-text`, and `utcp-cli` plugins and registers tools via `utcp_config.manual_call_templates`.
- **D-04:** **Key evidence for the verdict:** because `utcp-agent` already ships the `utcp-mcp` plugin, it *can* consume our tools via the mcp call-template our manual already produces — native http serving is **one option it supports, not a requirement**. The verdict must weigh: **does mcp-via-UTCP already satisfy the real consumer**, or does the consumer genuinely need native http/cli serving? Answer this empirically, then recommend build / stay-manual / defer accordingly.
- **D-05:** Secondary dimension to record (not the primary driver): the hand-maintained `AGENTMEMORY_TOOL_SPECS` list in `utcp.py` can drift from the live FastMCP tool registry. Note whether the verdict path implies auto-generating the manual from the registry.
- **D-06:** Stand up a **throwaway native-serving prototype** (a minimal UTCP `http` — or `cli`/`text` — call-template endpoint serving ~1 tool) purely to observe real behavior, then discard it. It lives in **`d:/tmp` or `scripts/spike/`, NOT in `src/`**, and is **never merged**. Guard against scope creep: one tool, throwaway, findings only.
- **D-07:** Run the live round-trip via a **Docker/compose harness**. The MCP server imports `turingdb`, which has **no Windows wheel**, so an in-process live call on Windows is not possible. Boot the real MCP server in a container (stub embed/rerank is acceptable, as E2E does), and run `UtcpClient` / `utcp-agent` from the **host** against it — over the mcp call-template, plus the throwaway native http prototype.
- **D-08:** The tool **registration + call** can be proven through the underlying `UtcpClient` directly **without an LLM** — this is the deterministic core evidence. A full LLM-driven `utcp-agent` chat loop is **optional color**.
- **D-08a:** When the optional full-agent chat is run, drive the LLM with a **local llama.cpp server hosting the Gemma GGUF** (`unsloth/gemma-4-12B-it-qat-GGUF`, file `gemma-4-12B-it-qat-UD-Q4_K_XL.gguf`), served via the repo's existing llama.cpp sidecar pattern (`docker/llama-provider.Dockerfile`), exposing `/v1/chat/completions`. Point `utcp-agent`'s `langchain-openai` extra at it (dummy API key). GPU-mandatory; if no GPU, fall back to the LLM-free `UtcpClient` round-trip and record that full-agent chat was not exercised — never silently skip it.
- **D-09:** Write a phase **`FINDINGS.md`** in the phase directory containing: (a) documented gaps of the current export against the real client (SC#1), (b) the verdict — native serving / stay-on-manual / defer — with rationale (SC#2), and (c) explicit trigger conditions for revisiting if the verdict is "defer".
- **D-10:** If the verdict is **build**, add an **explicit, gated phase entry to ROADMAP.md** (backlog) whose precondition cites this verdict. Also record the verdict as a row in `PROJECT.md` Key Decisions.

### Claude's Discretion

- Exact choice of which memory/document tool to exercise in the round-trip (e.g., `memory_search` vs a simpler write) — pick the most representative one that produces observable, citable output.
- Whether the throwaway native prototype uses the `http` vs `cli`/`text` call-template — pick whichever most cheaply yields comparable evidence.

### Deferred Ideas (OUT OF SCOPE)

- **Native UTCP serving implementation** — explicitly deferred to a gated future phase (if the verdict recommends it). This phase writes zero serving code into `src/`.
- **Auto-generating the UTCP manual from the live FastMCP tool registry** (to kill `AGENTMEMORY_TOOL_SPECS` drift) — record as a candidate in FINDINGS.md; it is a build change and belongs to whatever follow-on the verdict authorizes, not here.

None of these are acted on in Phase 2 — discussion stayed within the spike's findings-only boundary.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UTCP-01 | Early findings-gated spike on deeper UTCP support (native serving over UTCP vs the current `utcp.py` manual export), validated against real UTCP clients/spec; produces a verdict — any build work is gated on it | This research documents the *exact* current python-utcp/utcp-agent APIs (§Standard Stack, §Code Examples), enumerates concrete, source-verified conformance gaps between `utcp.py`'s emitted manual and the live pydantic models (§Common Pitfalls), traces how `utcp-agent` actually consumes mcp-call-template tools (§Architecture Patterns), and lays out a Docker harness + Nyquist validation plan (§Validation Architecture) so the planner can sequence a spike that produces `FINDINGS.md` with zero `src/` build work. |
</phase_requirements>

## Summary

This is a **findings-only spike**, not a build phase — the "stack" being researched is the
reference UTCP client (`d:/tmp/python-utcp`) and the real consumer (`d:/tmp/utcp-agent`), read
directly from their cloned source, not training-data assumptions. Three concrete, source-verified
conformance gaps were found between our emitted manual (`src/turing_agentmemory_mcp/utcp.py`) and
the CURRENT python-utcp pydantic models — all reproducible without Docker, and one is already
broken in our own README:

1. **Auth type mismatch (real bug, will fail validation):** `McpCallTemplate.auth` is typed
   `Optional[OAuth2Auth]` in the current python-utcp, but `utcp.py` emits `auth_type: "api_key"`
   on the mcp `tool_call_template` whenever `AGENTMEMORY_AUTH_TOKEN` is set. Validating our manual
   against the real `Tool`/`McpCallTemplate` pydantic models with auth configured **raises a
   pydantic `ValidationError`** — `api_key` fields don't satisfy `OAuth2Auth`'s required
   `token_url`/`client_id`/`client_secret`. [VERIFIED: d:/tmp/python-utcp/plugins/communication_protocols/mcp/src/utcp_mcp/mcp_call_template.py:131-134]
2. **`mcpServers` config shape mismatch:** `McpCallTemplate`'s own docstring example shows
   `"command": "node", "args": ["mcp-server.js"]` — a **string** executable plus a separate
   **args list**. `utcp.py`'s `build_utcp_manual()` instead emits the *entire argv* (e.g.
   `["turing-agentmemory-mcp","serve","--transport","stdio"]`) as a single `"command"` array, with
   no `"args"` key and an extra, unrecognized `"transport": "stdio"` key. This is the shape
   `mcp_use.MCPClient.from_dict()` (the library the `utcp-mcp` plugin delegates to) receives raw —
   a real, reproducible registration-path defect for D-01's live round-trip.
   [VERIFIED: d:/tmp/python-utcp/plugins/communication_protocols/mcp/src/utcp_mcp/mcp_call_template.py:40-56]
3. **README's own UTCP config example is broken against the current spec:** `README.md`'s
   `UTCP_CONFIG_FILE` example uses `"call_template_type": "text"` with a `"file_path"` field.
   The current `TextCallTemplateSerializer.validate_dict()` **explicitly rejects `file_path`**
   with a migration error telling the caller to use `call_template_type: "file"` (a *separate*
   `utcp-file` plugin package, not bundled by `utcp-agent`). This is a spec-drift regression our
   own docs haven't caught up to — trivially reproducible with zero server, zero Docker.
   [VERIFIED: d:/tmp/python-utcp/plugins/communication_protocols/text/src/utcp_text/text_call_template.py:63-73]

The most important **structural** finding for the D-04 verdict: for the mcp call-template path,
`McpCommunicationProtocol.register_manual()` does **not** consume our manual's hand-written
per-tool `inputs`/`outputs` JSON Schemas at all — it connects live over MCP stdio and calls
`session.list_tools()` on the real FastMCP server, converting `mcp.Tool` objects (with FastMCP's
own live-generated schemas) into UTCP `Tool` objects. **`AGENTMEMORY_TOOL_SPECS` is effectively
dead weight for anyone consuming us via the mcp call-template** — registration only needs *one*
`McpCallTemplate` pointing at our server's stdio command, not our 19-tool manual JSON. This
directly informs D-05 (manual/registry drift is largely moot for this consumption path) and D-04
(the real consumer already gets accurate, live schemas without any export at all).
[VERIFIED: d:/tmp/python-utcp/plugins/communication_protocols/mcp/src/utcp_mcp/mcp_communication_protocol.py:176-247]

Also directly relevant to the verdict: UTCP's own stated philosophy (utcp.io) positions itself
**against** MCP's "wrapper server" model — "no wrapper servers required... if a human can call
your API, an AI agent should be able to call it too." The mcp-call-template path we already
implement is explicitly the interop/legacy bridge UTCP itself frames as the thing native serving
is meant to obsolete. [CITED: https://www.utcp.io/]

**Primary recommendation:** Run the D-01 live round-trip using a hand-built `McpCallTemplate`
(bypassing `utcp.py`'s buggy `command`/`args` shape) against the Dockerized MCP server via
`docker compose run --rm -T turing-agentmemory-mcp serve --transport stdio`, confirm the mcp path
works end-to-end for `utcp-agent`, separately assert-via-fast-pytest that `utcp.py`'s *own* output
fails `Tool`/`McpCallTemplate` validation when auth is set (SC#1 evidence, no Docker needed), spin
up the throwaway `http` prototype only long enough to compare effort, and write `FINDINGS.md`
weighing "mcp-via-UTCP already works for the real consumer, minus two fixable emission bugs"
against "native http serving buys UTCP's stated no-wrapper benefit at nonzero build cost."

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| UTCP manual generation (`build_utcp_manual`) | API / Backend (this repo, `utcp.py`) | — | Pure data-shape builder; no runtime dependency on a live client |
| MCP tool serving (stdio transport) | API / Backend (FastMCP `server.py`) | — | Already exists; unaffected by this spike |
| UTCP tool discovery for the mcp call-template | Client-side (python-utcp `utcp-mcp` plugin, host process) | — | Discovery happens live via `session.list_tools()` over stdio — it is the *client's* responsibility, not something our manual controls |
| UTCP manual validation/conformance check | Client-side (python-utcp pydantic models) | Spike test tooling (this phase) | The spike's job is to feed our manual through the real models and observe pass/fail — no production code changes |
| Throwaway native-http prototype (D-06) | Spike-only scratch tier (`d:/tmp` or `scripts/spike/`) | — | Explicitly never merged; not part of any production tier |
| Docker round-trip harness | CI/spike tooling (compose `run --rm -T`) | Host process (UtcpClient) | Server runs in-container (turingdb has no Windows wheel); client runs on host and reaches it via subprocess-over-docker stdio bridge |
| Verdict + gaps documentation | Planning artifact (`FINDINGS.md`) | — | Not a runtime tier at all — the actual phase deliverable |

## Standard Stack

### Core

| Library | Version (verified) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `utcp` | 1.1.3 latest on PyPI (repo default constant hardcodes 1.0.2) [VERIFIED: npm registry — `pip index versions utcp`] | Core UTCP client (`UtcpClient`, pydantic data models) | Official reference implementation, org-backed (`universal-tool-calling-protocol`), 21 published releases since 0.1.0 |
| `utcp-mcp` | 1.1.2 latest [VERIFIED: `pip index versions utcp-mcp`] | mcp call-template plugin — the status-quo path under test (D-02) | Only plugin that speaks our current `call_template_type: "mcp"` export |
| `utcp-http` | 1.1.11 latest [VERIFIED: `pip index versions utcp-http`] | http call-template plugin — target for the D-06 throwaway prototype | Needed to register/call the native-http prototype |
| `utcp-text` | 1.1.0 latest [VERIFIED: `pip index versions utcp-text`] | text call-template plugin — validates a raw JSON/YAML manual (incl. our `build_utcp_manual()` output) against the live pydantic models with **zero server, zero Docker** | Cheapest way to get SC#1 static-conformance evidence |
| `utcp-cli` | 1.1.3 latest [VERIFIED: `pip index versions utcp-cli`] | cli call-template plugin (alternative to http for D-06) | Bundled by `utcp-agent`; not otherwise needed unless the cli variant is chosen |
| `utcp-agent` | 1.0.3 latest [VERIFIED: `pip index versions utcp-agent`]; `requires-python = ">=3.9"` — compatible with this repo's 3.11–3.14 | The real motivating consumer (D-03) — LangGraph agent, registers tools via `utcp_config.manual_call_templates`, bundles `utcp`, `utcp-http`, `utcp-mcp`, `utcp-text`, `utcp-cli` as hard deps | User-named as the concrete thing the verdict must satisfy |
| `mcp-use` | 1.7.0 latest [VERIFIED: `pip index versions mcp-use`] | Transitive dep of `utcp-mcp` — the actual stdio session manager (`MCPClient.from_dict`) that receives our `mcpServers` config | Not installed directly; installed automatically with `utcp-mcp` |
| `langchain-openai` | 1.3.5 latest [VERIFIED: `pip index versions langchain-openai`] | Optional D-08a LLM path — points `ChatOpenAI(base_url=...)` at the local llama.cpp Gemma sidecar | Only needed for the optional full-agent-chat color evidence |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pyyaml` (already a dep via `test_utcp_manual.py`) | repo-pinned | `TextCommunicationProtocol` tries JSON then YAML when parsing manual content | Only relevant if hand-authoring a YAML manual; our manual is JSON |
| `aiohttp` (transitive, via `utcp-mcp`) | — | Used internally for OAuth2 token exchange in the mcp protocol's `_handle_oauth2` | Not directly invoked by the spike unless testing OAuth2 auth |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-building an `McpCallTemplate` in the harness script | Fixing `utcp.py`'s command/args shape first, then reusing `build_utcp_manual()` output directly | Fixing `utcp.py` is itself a `src/` change; SC#3 forbids "UTCP build work" in `src/` during this phase, so the harness must work around the bug rather than fix it. Document the fix as a candidate for the gated follow-on (D-10) if the verdict is "build" or "stay-manual-but-patch". |
| `utcp-http` for the D-06 prototype | `utcp-cli` (Claude's discretion) | `http` needs a tiny running server (stdlib `http.server` or FastAPI in `scripts/spike/`); `cli` needs zero server (just a shell command echoing JSON) — `cli` is cheaper to stand up but weaker evidence for "native serving effort," since our real tools are HTTP-shaped (MCP itself is JSON-RPC-over-transport, closer in spirit to http/sse than to a CLI wrapper). Recommend `http` unless time-boxed tightly. |
| Docker `run --rm -T` per-call | `docker compose up -d` then reach the running container over a network transport | `run --rm -T` matches this repo's *existing, tested* pattern (already anticipated in `tests/test_utcp_manual.py`'s `AGENTMEMORY_UTCP_MCP_COMMAND` test with the literal `docker.exe compose ... run --rm -T ... serve --transport stdio` command) — reuse it rather than invent a new bridging mechanism. |

**Installation (host-side, spike-only — NOT added to `pyproject.toml` `dependencies`):**
```powershell
.venv\Scripts\python -m pip install utcp utcp-mcp utcp-http utcp-text utcp-agent
# Optional D-08a LLM color:
.venv\Scripts\python -m pip install "langchain-openai>=1.0.0" python-dotenv
```
These belong in a spike-scoped requirements file (e.g. `scripts/spike/requirements.txt`) or an
ephemeral venv, not `pyproject.toml`'s `dev` extra — adding them as a committed project dependency
is itself infrastructure the verdict should gate, not something this phase presupposes.

## Package Legitimacy Audit

> `gsd-tools query package-legitimacy check` was not reachable in this environment (no
> `gsd-core/bin/gsd-tools.cjs` found on this machine). Verification below was done manually:
> `pip index versions <pkg>` against the real PyPI registry for every package (ecosystem: pypi),
> cross-checked against the actual cloned source at `d:/tmp/python-utcp` and `d:/tmp/utcp-agent`
> (i.e., stronger than a registry-existence check — the packages' own code was read directly).

| Package | Registry | Release history | Source Repo | Verdict | Disposition |
|---------|----------|-----|-------------|---------|-------------|
| `utcp` | PyPI | 21 releases, 0.1.0 → 1.1.3 | `github.com/universal-tool-calling-protocol/python-utcp` (cloned locally, org-backed, has a dedicated `utcp-specification` repo) | OK | Approved (spike-only dep) |
| `utcp-mcp` | PyPI | 6 releases, 1.0.0 → 1.1.2 | same org, `plugins/communication_protocols/mcp` subpath | OK | Approved |
| `utcp-http` | PyPI | 17 releases, 1.0.0 → 1.1.11 | same org, `plugins/communication_protocols/http` subpath | OK | Approved |
| `utcp-text` | PyPI | 5 releases, 1.0.0 → 1.1.0 | same org, `plugins/communication_protocols/text` subpath | OK | Approved |
| `utcp-cli` | PyPI | 6 releases, 1.0.0 → 1.1.3 | same org | OK | Approved (only if D-06 prototype uses cli) |
| `utcp-agent` | PyPI | 4 releases, 1.0.0 → 1.0.3 | `github.com/universal-tool-calling-protocol/utcp-agent` (cloned locally) | OK | Approved |
| `mcp-use` | PyPI | 30+ releases, 0.0.3 → 1.7.0 (transitive via `utcp-mcp`) | Not independently inspected — installed transitively; flagged for awareness only | SUS (unverified transitively-pulled dep) | Not directly installed — planner should note it arrives automatically with `utcp-mcp` and does not need separate vetting/checkpoint since it's not user-selected |
| `langchain-openai` | PyPI | 90+ releases | `github.com/langchain-ai/langchain` — large, well-known org | OK | Approved (D-08a optional path only) |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** `mcp-use` (transitive, not directly installed by this
phase's harness — no `checkpoint:human-verify` needed since it is never a direct pip-install
target of any task in this phase's plan; only `utcp-mcp` is installed directly and that pulls it
in).

*All package names above were discovered from the packages' own cloned source code and PyPI's
registry directly — not from web search or training-data recall — so they are treated as
[VERIFIED: PyPI + local source clone] rather than [ASSUMED].*

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────── HOST (Windows, .venv python) ───────────────────────────┐
│                                                                                      │
│  scripts/spike/utcp_roundtrip.py  (NEW, spike-only, never merged to src/)          │
│                                                                                      │
│   1. Build McpCallTemplate directly (bypassing utcp.py's buggy command/args shape) │
│        config.mcpServers["turing-agentmemory-mcp"] = {                             │
│          "command": "docker.exe",                                                  │
│          "args": ["compose","-f",<repo>/compose.yaml,"run","--rm","-T",            │
│                    "turing-agentmemory-mcp","serve","--transport","stdio"]         │
│        }                                                                            │
│   2. client = await UtcpClient.create()                                            │
│   3. result = await client.register_manual(mcp_call_template)  ───────────┐        │
│   4. result2 = await client.call_tool(                                    │        │
│        "turing-agentmemory-mcp.memory_store_message", {...})              │        │
│   5. result3 = await client.call_tool(                                    │        │
│        "turing-agentmemory-mcp.memory_search", {...})                     │        │
│                                                                            │        │
└────────────────────────────────────────────────────────────────────────  │  ───────┘
                                                                             │ subprocess
                                                                             │ (spawns docker.exe)
                                                                             ▼
┌────────────────────────── docker compose run --rm -T ──────────────────────────────┐
│  turing-agentmemory-mcp container                                                   │
│    entrypoint: turing-agentmemory-mcp serve --transport stdio                       │
│    depends_on (service_healthy): turingdb, agentmemory-embed,                       │
│                                   agentmemory-rerank, agentmemory-gliner             │
│    stdin/stdout: MCP JSON-RPC over stdio  ◄──── bridged to host subprocess pipes    │
│                                                                                       │
│    FastMCP app (create_mcp_app()) → server.list_tools() / server.call_tool()        │
│    → TuringAgentMemory store (real TuringDB, GPU embed/rerank sidecars)             │
└───────────────────────────────────────────────────────────────────────────────────┘

Separately, NO Docker needed for static conformance evidence (SC#1, fast):

┌────────── tests/ or scripts/spike/ — fast pytest, <1s ──────────┐
│  from turing_agentmemory_mcp.utcp import utcp_manual_from_env    │
│  from utcp.data.utcp_manual import UtcpManualSerializer          │
│  manual_dict = utcp_manual_from_env()  # AGENTMEMORY_AUTH_TOKEN set│
│  UtcpManualSerializer().validate_dict(manual_dict)                │
│    → raises UtcpSerializerValidationError                         │
│      (api_key auth doesn't satisfy McpCallTemplate's OAuth2Auth)  │
└─────────────────────────────────────────────────────────────────┘

Throwaway D-06 prototype (never merged):

┌── scripts/spike/native_http_tool.py (stdlib http.server, 1 endpoint) ──┐
│  POST /tools/memory_search  { "body": {...} } → JSON result             │
└───────────────────────────────────────────────────────────────────────┘
                              ▲
                              │ HttpCallTemplate(url=..., http_method="POST")
              client.register_manual(http_call_template)
              client.call_tool("native.memory_search", {...})
```

### Recommended Spike Directory Structure
```
scripts/spike/                      # NEW — spike-only, never merged as "build" work
├── requirements.txt                 # utcp, utcp-mcp, utcp-http, utcp-text, utcp-agent (pinned)
├── utcp_roundtrip.py                # D-01/D-02/D-07/D-08 — mcp call-template live round-trip
├── native_http_prototype.py         # D-06 — throwaway 1-tool http endpoint (or cli variant)
└── full_agent_chat.py               # D-08a optional — utcp-agent + local llama.cpp Gemma

tests/test_utcp_conformance.py       # NEW, committed — fast, Docker-free static conformance
                                      # check (text call-template validates utcp.py's own output
                                      # against real python-utcp pydantic models); this is TEST
                                      # tooling, not native-serving build work, and directly
                                      # produces the SC#1 evidence D-09 requires in FINDINGS.md

.planning/phases/02-utcp-spike/
└── 02-FINDINGS.md                   # D-09 deliverable — gaps + verdict + trigger conditions
```

### Pattern 1: Registering the mcp call-template directly (bypass utcp.py's manual for discovery)
**What:** For the mcp call-template path, tool discovery happens live via MCP `list_tools()`, not
from a pre-built manual — so the round-trip only needs ONE `McpCallTemplate`, not the full 19-tool
`build_utcp_manual()` output.
**When to use:** D-01/D-02's primary live round-trip evidence.
**Example:**
```python
# Source: d:/tmp/python-utcp/core/src/utcp/utcp_client.py (UtcpClient.create/register_manual/call_tool)
#         d:/tmp/python-utcp/plugins/communication_protocols/mcp/src/utcp_mcp/mcp_call_template.py
import asyncio
from utcp.utcp_client import UtcpClient
from utcp_mcp.mcp_call_template import McpCallTemplate, McpConfig

async def main() -> None:
    client = await UtcpClient.create()

    mcp_template = McpCallTemplate(
        name="turing-agentmemory-mcp",
        call_template_type="mcp",
        config=McpConfig(
            mcpServers={
                "turing-agentmemory-mcp": {
                    # NOTE: command is a STRING; args is a SEPARATE list.
                    # utcp.py's build_utcp_manual() gets this wrong (single "command" array) —
                    # this is one of the documented conformance gaps (SC#1).
                    "command": "docker.exe",
                    "args": [
                        "compose", "-f", r"D:\Repo\turing_AgentMemory_MCP\compose.yaml",
                        "run", "--rm", "-T",
                        "turing-agentmemory-mcp", "serve", "--transport", "stdio",
                    ],
                }
            }
        ),
    )

    result = await client.register_manual(mcp_template)
    assert result.success, result.errors
    print(f"Discovered {len(result.manual.tools)} live tools")  # real FastMCP-generated schemas

    write_result = await client.call_tool(
        "turing-agentmemory-mcp.memory_store_message",
        {"session_id": "utcp-spike", "role": "user", "content": "UTCP round-trip probe"},
    )
    print(write_result)

    search_result = await client.call_tool(
        "turing-agentmemory-mcp.memory_search", {"query": "UTCP round-trip probe"}
    )
    print(search_result)

asyncio.run(main())
```

### Pattern 2: Static conformance check — validate `utcp.py`'s own manual (no Docker, no server)
**What:** The `text` call-template protocol validates raw manual JSON against the real
`UtcpManual`/`Tool`/`McpCallTemplate` pydantic models — this is how you get SC#1 evidence for the
auth-type mismatch (finding #1) cheaply and deterministically, in a committed pytest.
**When to use:** Fast Wave 0 evidence; complements (does not replace) the D-01 live round-trip.
**Example:**
```python
# Source: d:/tmp/python-utcp/core/src/utcp/data/utcp_manual.py (UtcpManualSerializer)
#         d:/tmp/python-utcp/plugins/communication_protocols/mcp/src/utcp_mcp/mcp_call_template.py
import os
from utcp.data.utcp_manual import UtcpManualSerializer
from utcp.exceptions import UtcpSerializerValidationError
from turing_agentmemory_mcp.utcp import build_utcp_manual

def test_manual_with_auth_fails_current_utcp_pydantic_validation() -> None:
    manual = build_utcp_manual(auth_env="AGENTMEMORY_AUTH_TOKEN")
    try:
        UtcpManualSerializer().validate_dict(manual)
        raised = False
    except UtcpSerializerValidationError:
        raised = True
    # Documents the KNOWN gap: api_key auth on an mcp call-template does not validate
    # against the current McpCallTemplate.auth: Optional[OAuth2Auth].
    assert raised, "expected api_key-on-mcp-template to fail current python-utcp validation"
```

### Pattern 3: Throwaway native-http prototype (D-06)
**What:** Minimal 1-tool `http` call-template endpoint, purely for effort/behavior comparison.
**When to use:** D-06 only; discard after the spike, never merge.
**Example:**
```python
# Source: d:/tmp/python-utcp/plugins/communication_protocols/http/src/utcp_http/http_call_template.py
from utcp_http.http_call_template import HttpCallTemplate

http_template = HttpCallTemplate(
    name="native_memory_search",
    call_template_type="http",
    url="http://127.0.0.1:8199/tools/memory_search",
    http_method="POST",
    content_type="application/json",
    body_field="body",   # tool args are wrapped under {"body": {...}} by default
)
# client.register_manual(http_template) then client.call_tool("native_memory_search.<tool-name>", {...})
# Server side: stdlib http.server or a 10-line FastAPI app in scripts/spike/native_http_prototype.py
# that reads the tool's declared inputs schema, does *nothing real* (or proxies to the same
# TuringAgentMemory store used by e2e_score.py's in-process pattern), and returns JSON.
```

### Anti-Patterns to Avoid
- **Reusing `build_utcp_manual()`'s output verbatim for the D-01 live round-trip:** it will fail
  registration (wrong `mcpServers` shape) and — if auth is configured — fail validation entirely.
  Build a corrected `McpCallTemplate` by hand for the harness; document the bug, don't silently
  work around it without noting it in `FINDINGS.md`.
- **Treating a failed `register_manual()` call as inconclusive:** per D-01, a failure IS evidence
  — it's what SC#1 asks for ("gaps must surface as observed failures, not reasoned ones").
- **Committing the D-06 http prototype's server code anywhere under `src/`:** SC#3 is a hard gate;
  keep it in `scripts/spike/` or `d:/tmp` only, and do not wire it into `compose.yaml`.
- **Skipping the D-08a GPU fallback silently:** if no GPU is available for the optional Gemma
  sidecar, `FINDINGS.md` must explicitly say "full-agent chat not exercised (no GPU)" — this
  machine *does* have a GPU (`nvidia-smi` reports CUDA 13.1 available), so the fallback likely
  won't be needed, but the harness script should still check and report, not assume.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Parsing/validating a UTCP manual JSON | A custom JSON-schema-diff script comparing our manual to python-utcp's models by hand | `TextCallTemplate` + `UtcpManualSerializer().validate_dict()` (Pattern 2 above) | The real library already does exactly this validation — running our manual through it IS the ground truth, not an approximation of it |
| Bridging host→container stdio for the mcp call-template | A custom subprocess/pipe-relay script | `docker compose run --rm -T <service> serve --transport stdio` as the `command`/`args` in the `McpCallTemplate`'s `mcpServers` entry — `mcp_use.MCPClient` already spawns and manages the subprocess and its stdio pipes | This repo's own `tests/test_utcp_manual.py` already encodes this exact command shape as the expected Docker stdio path; `mcp_use` (transitive via `utcp-mcp`) already implements MCP stdio session management correctly |
| A mock/stub UTCP client to "simulate" the round-trip | Any hand-rolled fake of `register_manual`/`call_tool` | The real `UtcpClient.create()` + real `utcp-mcp`/`utcp-http` plugins | D-01 explicitly requires *live* evidence — a mock defeats the entire purpose of the spike |

**Key insight:** Because this is a findings-only spike, the biggest "don't hand-roll" risk is
reasoning about python-utcp's behavior from memory/training data instead of running the real
package against the real manual. Every conformance claim in this document was produced by reading
the actual pydantic model source, not by inference — the plan's tasks should preserve that
discipline (write the fast pytest in Pattern 2, actually run it, actually attempt the Docker
round-trip, actually observe the failure/success — don't stop at "this looks like it would fail").

## Common Pitfalls

### Pitfall 1: Assuming the manual's per-tool `inputs`/`outputs` schemas matter for mcp consumption
**What goes wrong:** Spending spike time hardening `AGENTMEMORY_TOOL_SPECS` schemas, believing
they're what `utcp-agent` sees.
**Why it happens:** The manual *looks* like the single source of truth because it's the only
artifact `utcp.py` produces.
**How to avoid:** Remember `McpCommunicationProtocol.register_manual()` discovers tools live via
`session.list_tools()` on the real MCP server — the manual's tool array is not consulted at all
for the mcp call-template path. Only the `tool_call_template` (server connection info) matters.
**Warning signs:** Any FINDINGS.md language implying "the search tool description was wrong so
utcp-agent picked the wrong tool" — that can only be true if FastMCP's own live tool metadata is
wrong, not `utcp.py`'s.

### Pitfall 2: Auth silently dropped instead of raising
**What goes wrong:** Assuming a schema mismatch degrades gracefully (auth ignored, tool still
callable). It does not — `Tool.tool_call_template`'s field validator calls
`CallTemplateSerializer().validate_dict(v)` unconditionally, which raises
`UtcpSerializerValidationError` and aborts registration/parsing entirely for that call template.
**Why it happens:** Pydantic strict validation on nested discriminated unions.
**How to avoid:** Test with `AGENTMEMORY_AUTH_TOKEN` set (the realistic prod config) AND unset —
the bug only manifests when auth is configured, so an auth-free test run will falsely look green.
**Warning signs:** FINDINGS.md claiming "the manual validates cleanly" without having tested the
auth-enabled path.

### Pitfall 3: `docker compose run` needing dependent services healthy
**What goes wrong:** `docker compose run --rm -T turing-agentmemory-mcp serve --transport stdio`
will start (and wait on) `turingdb`, `agentmemory-embed`, `agentmemory-rerank`, and
`agentmemory-gliner` per `depends_on: condition: service_healthy` in `compose.yaml` — the embed
and rerank sidecars are GPU-mandatory (`gpus: all`) and have `start_period: 60s` /
`retries: 80` healthchecks (up to ~20 min cold-start for model download via
`agentmemory-model-init`). A round-trip script naively timing out after a short window will
report a false negative.
**Why it happens:** The compose stack is the full production topology, not a lightweight stub —
unlike `e2e_score.py`, which runs in-process with `LocalEmbedServer`/`LocalRerankServer` stubs and
never touches FastMCP transport machinery at all.
**How to avoid:** Either (a) run `docker compose up -d` for dependencies first and wait for health
before the `run --rm -T` step, or (b) override `EMBED_BASE_URL`/`RERANK_BASE_URL` via compose env
overrides to point at lightweight stub servers (mirroring `e2e_score_stubs.py`'s
`LocalEmbedServer`/`LocalRerankServer`, but exposed over the network for the container to reach,
since e2e's in-process stubs aren't directly reusable across a process boundary). This machine has
an NVIDIA GPU (`nvidia-smi` confirms CUDA 13.1), so the real GPU sidecars are actually usable here
— prefer them for stronger evidence unless start-up time is prohibitive.
**Warning signs:** Round-trip script exits with a generic timeout/connection-refused instead of an
actual MCP protocol error.

### Pitfall 4: Version-string drift (informational only, not currently enforced)
**What goes wrong:** `utcp.py` hardcodes `utcp_version="1.0.2"` while the real spec/library is
already at 1.1 (PyPI: `utcp` 1.1.3; utcp.io states current spec version "1.1"). Nothing in the
current pydantic models enforces this field against the installed library version — `UtcpManual`
does not compare `utcp_version` to `utcp.python_specific_tooling.version.__version__` at
validation time — so this does NOT cause a validation failure today. [VERIFIED:
d:/tmp/python-utcp/core/src/utcp/data/utcp_manual.py — no version-compat check in the model]
**Why it happens:** Hardcoded default at write time, never revisited.
**How to avoid:** Note in FINDINGS.md as a low-severity drift item (informational, not a bug) —
worth fixing if/when `utcp.py` is next touched, but not blocking for the verdict.
**Warning signs:** N/A — currently silent, would only matter if a future python-utcp release adds
version-gating.

## Code Examples

Verified patterns from official sources (all four snippets above under §Architecture Patterns are
the canonical code examples for this phase — repeated here by reference to avoid duplication):
Pattern 1 (mcp live round-trip), Pattern 2 (static conformance pytest), Pattern 3 (D-06 http
prototype). One additional snippet:

### utcp-agent registration via `manual_call_templates` config dict (D-08a optional full-agent path)
```python
# Source: d:/tmp/utcp-agent/examples/basic_openai.py (adapted: http example → mcp example)
from langchain_openai import ChatOpenAI
from utcp_agent import UtcpAgent, UtcpAgentConfig

llm = ChatOpenAI(
    model="local-gemma",
    base_url="http://127.0.0.1:8199/v1",   # local llama.cpp Gemma sidecar (D-08a)
    api_key="not-needed",
    temperature=0.1,
)

utcp_config = {
    "manual_call_templates": [
        {
            "name": "turing-agentmemory-mcp",
            "call_template_type": "mcp",
            "config": {
                "mcpServers": {
                    "turing-agentmemory-mcp": {
                        "command": "docker.exe",
                        "args": [
                            "compose", "-f", r"D:\Repo\turing_AgentMemory_MCP\compose.yaml",
                            "run", "--rm", "-T",
                            "turing-agentmemory-mcp", "serve", "--transport", "stdio",
                        ],
                    }
                }
            },
        }
    ]
}

agent = await UtcpAgent.create(llm=llm, utcp_config=utcp_config)
response = await agent.chat("Store the note 'UTCP spike ran successfully' and then search for it.")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| UTCP spec/monolith client (pre-1.0) | Modular core + per-protocol plugin packages (`utcp`, `utcp-http`, `utcp-mcp`, `utcp-text`, `utcp-cli`, `utcp-file`, ...) | UTCP 1.0.0 [CITED: PyPI release history + `d:/tmp/python-utcp` repo layout] | Consumers must install the specific plugin(s) they need; our manual only needs `utcp-mcp` for the status-quo path |
| `TextCallTemplate` with `file_path` (older UTCP) | `TextCallTemplate.content` (direct string) + separate `FileCallTemplate.file_path` (new `utcp-file` plugin) | Some point before the currently-cloned version — the serializer has an explicit backward-compat rejection message for `file_path` | Our own `README.md`'s `UTCP_CONFIG_FILE` example is written against the OLD shape and is currently broken |
| MCP "wrapper server" model as the default integration path | UTCP's stated philosophy: direct native-protocol calls, "no wrapper servers required" | Ongoing/current framing per utcp.io | Directly informs the D-04 verdict — the org that built the client we're testing against explicitly frames mcp-as-transport as the thing native serving supersedes |

**Deprecated/outdated:**
- `file_path` field on `TextCallTemplate`: replaced by `FileCallTemplate` (separate `utcp-file`
  package). Our README documents the deprecated shape.
- Hardcoded `utcp_version: "1.0.2"` in `utcp.py`: not yet broken, but behind the current spec
  version ("1.1" per utcp.io) and the current `utcp` package's own default (still reads 1.0.2 from
  the cloned repo's fallback constant, but the *installed* PyPI package would report its actual
  installed version via `importlib.metadata.version("utcp")` if that path were hit — i.e. our
  hardcode diverges from whatever real client version a consumer has installed).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `mcp_use.MCPClient.from_dict()` requires `"command"` as a string plus a separate `"args"` list (not a single combined array) — inferred from `McpCallTemplate`'s docstring examples, not from reading `mcp_use`'s own source (not cloned locally) | Common Pitfalls / Standard Stack (finding #2) | If wrong, this specific gap may not reproduce as described; the live round-trip (D-01) will still empirically confirm or refute it regardless, since it's the *primary* evidence source per D-01 — low risk because the plan already treats live observation as authoritative over this document |
| A2 | `docker compose run --rm -T` on this Windows Docker Desktop setup correctly bridges stdin/stdout for MCP JSON-RPC without extra TTY/line-buffering interference | Architecture Patterns / Pitfall 3 | If wrong, the harness needs `stdbuf`/explicit unbuffered I/O flags; would surface immediately as a protocol handshake failure during D-01, not silently |
| A3 | `mcp-use` (transitive dep) itself has no additional conformance requirements beyond what's visible in `utcp-mcp`'s `mcp_call_template.py`/`mcp_communication_protocol.py` (not independently source-read) | Package Legitimacy Audit | Low risk — flagged SUS/informational only, not a direct install target of this phase |

**If this table is empty:** N/A — three low-risk assumptions logged above; all are self-correcting
via the D-01 live round-trip (i.e., the phase's own primary evidence mechanism resolves them).

## Open Questions

1. **Does adding `utcp`/`utcp-mcp`/`utcp-http`/`utcp-text`/`utcp-agent` as spike-scoped
   dependencies (e.g. `scripts/spike/requirements.txt`, or a temporary venv) count as "UTCP build
   work" under SC#3?**
   - What we know: SC#3 explicitly forbids "native serving code" being committed to `src/` and
     forbids merging the D-06 throwaway prototype. It does not explicitly address test/dev-only
     dependencies used to *exercise* the client.
   - What's unclear: Whether the committed `tests/test_utcp_conformance.py` (Pattern 2) — which
     requires `utcp`/`utcp-mcp`/`utcp-text` to be importable in the test environment — should add
     these to `pyproject.toml`'s `dev` extra (a small, real, permanent `pyproject.toml` change) or
     stay fully scratch/uncommitted (spike-only, run manually, not part of CI).
   - Recommendation: Treat the *test* as optional/discretionary for the planner — if included,
     scope it as a `pytest.mark.slow` or `pytest.mark.integration`-style opt-in test (matching this
     repo's existing marker conventions in `pyproject.toml`) so it doesn't silently become a new CI
     dependency without an explicit decision. If the user wants zero footprint in the tracked repo
     beyond `FINDINGS.md` itself, keep Pattern 2 as an ad hoc script in `scripts/spike/` instead of
     `tests/`.

2. **Which specific tool(s) best demonstrate "observable, citable output" for the round-trip
   (Claude's Discretion)?**
   - What we know: `memory_search`/`memory_store_message` are the simplest full write→read loop;
     `document_search` returns actual citation metadata (`locator`, `context` array) matching the
     word "citable" more literally, but requires the async `document_ingest_text`/`document_search`
     path and a real embedding round-trip.
   - What's unclear: Whether the extra complexity of demonstrating `document_search`'s citations is
     worth it for a findings-only spike, versus the simpler memory write/search loop.
   - Recommendation: Use `memory_store_message` → `memory_search` as the PRIMARY round-trip (fast,
     deterministic, no async job polling); optionally add a `document_ingest_text` →
     `document_search` pass as a stretch goal if time/GPU budget allows, since it more literally
     exercises "citations" and stresses the schema surface harder (nested `context` arrays, richer
     output schema).

3. **Should the throwaway D-06 prototype proxy real store logic (via the same
   `TuringAgentMemory`/in-process pattern `e2e_score.py` uses) or just return canned JSON?**
   - What we know: The goal is "real evidence about native-serving effort/fit," not a functioning
     feature.
   - What's unclear: Whether canned JSON is honest enough evidence, or whether it risks
     understating the true integration effort (auth wiring, tenant scoping, error mapping) that a
     real native-http tool would need.
   - Recommendation: Wire it to a real (or realistic-stub) call — e.g. reuse `e2e_score.py`'s
     `LocalEmbedServer`/`TuringDaemon`/`TuringAgentMemory` pattern in-process inside the throwaway
     script — so FINDINGS.md's effort estimate reflects genuine integration surface, not just
     "we can stand up an HTTP endpoint."

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Desktop / Docker Engine | D-07 round-trip harness (server-in-container) | ✓ | Docker 29.6.1, Compose v5.3.0 | — |
| NVIDIA GPU + CUDA | D-08a optional Gemma sidecar; real (non-stub) embed/rerank sidecars for the round-trip | ✓ | Driver 591.86, CUDA 13.1 (`nvidia-smi` confirmed) | If unavailable at execution time: record "full-agent chat not exercised (no GPU)" per D-08a; the LLM-free `UtcpClient` round-trip (D-08) has no GPU dependency |
| Host Python (for `UtcpClient`) | D-01/D-02 live round-trip runs on the HOST per D-07, not inside the container | ✓ | Python 3.12.10 (`.venv\Scripts\python`) | — |
| `d:/tmp/python-utcp` clone | All API/model verification in this research | ✓ | Cloned locally, exact commit not pinned/verified — recommend `git -C d:/tmp/python-utcp log -1` be checked at plan/execute time in case the clone has moved since this research | Re-clone from `https://github.com/universal-tool-calling-protocol/python-utcp` if stale |
| `d:/tmp/utcp-agent` clone | D-03/D-04 consumer verification | ✓ | Cloned locally | Re-clone from `https://github.com/universal-tool-calling-protocol/utcp-agent` if stale |
| `utcp`/`utcp-mcp`/`utcp-http`/`utcp-text`/`utcp-agent` PyPI packages | Actually running the round-trip (not just reading source) | Not yet installed in `.venv` — needs `pip install` per §Standard Stack | 1.1.3 / 1.1.2 / 1.1.11 / 1.1.0 / 1.0.3 respectively (latest, confirmed via `pip index versions`) | — |
| llama.cpp Gemma GGUF (`unsloth/gemma-4-12B-it-qat-GGUF`) | D-08a optional full-agent chat | Not yet downloaded | — | Skip D-08a, use D-08 LLM-free round-trip as primary/sole evidence |

**Missing dependencies with no fallback:** none — every dependency either is already present or
has an explicit, D-08-sanctioned fallback (skip the optional LLM color, keep the deterministic
core evidence).

**Missing dependencies with fallback:**
- UTCP Python packages: install into `.venv` or a spike-scoped venv before running the harness
  (not yet done — first task of the plan).
- Gemma GGUF for D-08a: only needed for optional full-agent chat; falls back to D-08's LLM-free
  round-trip, which is sufficient for the phase's SC#1/SC#2 core evidence.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.2+ (existing repo framework) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths=tests`, `pythonpath=src`, markers `slow`/`integration`/`gpu` already defined |
| Quick run command | `python -m pytest tests/test_utcp_conformance.py -q` (proposed new file, Docker-free) |
| Full suite command | Manual/scripted: `python scripts/spike/utcp_roundtrip.py` (not a pytest target — a live Docker round-trip script; see rationale below) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UTCP-01 (SC#1: gaps documented) | `utcp.py`'s auth-enabled manual fails current python-utcp `Tool`/`McpCallTemplate` validation | unit (static conformance, no Docker) | `pytest tests/test_utcp_conformance.py::test_manual_with_auth_fails_current_utcp_pydantic_validation -x` | ❌ Wave 0 — new file, see Pattern 2 above |
| UTCP-01 (SC#1: gaps documented) | README's `UTCP_CONFIG_FILE` text/`file_path` example fails current `TextCallTemplateSerializer` | unit (static conformance, no Docker) | `pytest tests/test_utcp_conformance.py::test_readme_utcp_config_example_is_stale -x` | ❌ Wave 0 — new file |
| UTCP-01 (SC#1: live round-trip) | mcp call-template register + call succeeds/fails against the real Dockerized server | manual/scripted, NOT pytest-automated (requires Docker + GPU sidecars up, 10-20 min cold start, live network/subprocess behavior) | `python scripts/spike/utcp_roundtrip.py` (exits non-zero on failure; prints structured evidence for FINDINGS.md) | ❌ Wave 0 — new spike script |
| UTCP-01 (SC#2: verdict) | Verdict document exists with rationale + trigger conditions | manual review (not automated — a written-document deliverable) | N/A — reviewed as part of phase verification | ❌ Wave 0 — `02-FINDINGS.md` |
| UTCP-01 (SC#3: no build work) | Zero UTCP native-serving code under `src/`; D-06 prototype lives only in `scripts/spike/`/`d:/tmp` | automated guard | `git diff --stat <base>..HEAD -- src/` reviewed for zero UTCP-serving additions (or a simple grep/CI check: `grep -rl "http_call_template\|HttpCallTemplate\|utcp_http" src/` must be empty) | Recommend planner add a trivial guard task/assertion, not a full test file |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_utcp_conformance.py -q` (fast, seconds, no Docker)
- **Per wave merge:** same — the Docker round-trip (`scripts/spike/utcp_roundtrip.py`) is
  deliberately NOT part of the automated pytest suite; it's evidence-gathering tooling for
  FINDINGS.md, run manually/interactively once (and re-run if the manual/harness changes), not a
  regression gate. Running it on every commit would require GPU + ~20 min cold Docker start —
  disproportionate for a phase whose deliverable is a document, not shipped code.
- **Phase gate:** `02-FINDINGS.md` exists, documents SC#1 gaps (both static + live), states the
  SC#2 verdict with rationale, and `git diff` confirms SC#3 (no `src/` build work merged).

### Wave 0 Gaps
- [ ] `tests/test_utcp_conformance.py` — Docker-free static conformance checks (Pattern 2); depends
  on `utcp`/`utcp-text` being installed (see Open Question #1 for whether this becomes a
  `pyproject.toml` dev-extra or stays ad hoc)
- [ ] `scripts/spike/requirements.txt` — pinned `utcp==1.1.3`, `utcp-mcp==1.1.2`,
  `utcp-http==1.1.11`, `utcp-text==1.1.0`, `utcp-agent==1.0.3` (spike-only, not `pyproject.toml`)
- [ ] `scripts/spike/utcp_roundtrip.py` — the D-01/D-02/D-07/D-08 live round-trip harness (Pattern 1)
- [ ] `scripts/spike/native_http_prototype.py` (or `d:/tmp` equivalent) — D-06 throwaway, never merged
- [ ] Framework install: none needed beyond the pip installs above — pytest/ruff already present

## Security Domain

> `security_enforcement` is enabled in `.planning/config.json` (ASVS level 1). This phase produces
> no production auth/session/access-control code — it is a findings-only spike. The applicable
> surface is narrow: don't leak secrets in spike artifacts, and correctly characterize the one
> auth-shaped bug this research already found.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Marginal — the spike observes (not implements) an auth mismatch | No new auth code; `utcp.py`'s existing `_auth_env_placeholder()` pattern (never embeds the raw token, only `Bearer ${ENV_VAR}`) must be preserved by anything the harness scripts print/log |
| V6 Cryptography | No | No crypto surface touched by this phase |
| V5 Input Validation | Marginal | The static conformance test (Pattern 2) IS an input-validation check, but of a third-party library's behavior against our output, not new validation code in this repo |
| V14 Configuration | Yes | `scripts/spike/` artifacts must not commit real `AGENTMEMORY_AUTH_TOKEN` values, real API keys, or the downloaded GGUF model binary; `.gitignore` should cover `scripts/spike/*.gguf` / any spike-local `.env` if the plan creates one |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Spike harness script accidentally prints/logs a real bearer token when testing the auth-enabled manual path | Information Disclosure | Reuse `utcp.py`'s existing pattern: only ever set `AGENTMEMORY_AUTH_TOKEN` to a throwaway/dummy value in the spike environment (`.env`-style, gitignored); assert (as the existing `tests/test_utcp_manual.py::test_utcp_manual_from_env_uses_command_json_and_never_leaks_static_auth_token` already does) that the token string never appears in printed/dumped manual JSON |
| Native-http prototype (D-06) exposed on a host port with no auth, even temporarily | Elevation of Privilege / Information Disclosure | Bind the throwaway http server to `127.0.0.1` only, never `0.0.0.0`; tear it down immediately after the D-06 evidence is gathered; never add it to `compose.yaml` (SC#3) |

## Sources

### Primary (HIGH confidence — read directly from cloned source)
- `d:/tmp/python-utcp/core/src/utcp/utcp_client.py` — `UtcpClient` abstract interface: `create()`,
  `register_manual()`, `register_manuals()`, `call_tool()`, `call_tool_streaming()`,
  `search_tools()`, `get_required_variables_for_*()`
- `d:/tmp/python-utcp/core/src/utcp/data/utcp_manual.py` — `UtcpManual`, `UtcpManualSerializer`
- `d:/tmp/python-utcp/core/src/utcp/data/tool.py` — `Tool`, `JsonSchema`, `ToolSerializer`
- `d:/tmp/python-utcp/core/src/utcp/data/call_template.py` — `CallTemplate` base, `CallTemplateSerializer`
- `d:/tmp/python-utcp/core/src/utcp/data/auth.py`, `auth_implementations/api_key_auth.py`,
  `auth_implementations/oauth2_auth.py` — `Auth`, `ApiKeyAuth`, `OAuth2Auth`
- `d:/tmp/python-utcp/core/src/utcp/data/utcp_client_config.py` — `UtcpClientConfig`,
  `manual_call_templates`
- `d:/tmp/python-utcp/core/src/utcp/python_specific_tooling/version.py` — `__version__` default 1.0.2
- `d:/tmp/python-utcp/plugins/communication_protocols/mcp/src/utcp_mcp/mcp_call_template.py` —
  `McpCallTemplate`, `McpConfig` (docstring config examples, `auth: Optional[OAuth2Auth]`)
- `d:/tmp/python-utcp/plugins/communication_protocols/mcp/src/utcp_mcp/mcp_communication_protocol.py`
  — `McpCommunicationProtocol.register_manual/call_tool`, live `session.list_tools()` discovery
- `d:/tmp/python-utcp/plugins/communication_protocols/http/src/utcp_http/http_call_template.py` —
  `HttpCallTemplate`
- `d:/tmp/python-utcp/plugins/communication_protocols/text/src/utcp_text/text_call_template.py`,
  `text_communication_protocol.py` — `TextCallTemplate`, the `file_path` rejection message
- `d:/tmp/python-utcp/plugins/communication_protocols/file/src/utcp_file/file_call_template.py` —
  `FileCallTemplate`
- `d:/tmp/python-utcp/core/tests/client/test_utcp_client.py` — real usage patterns in the library's
  own test suite (confirms `UtcpClientConfig`, `manual_call_templates`, imports)
- `d:/tmp/utcp-agent/src/utcp_agent/utcp_agent.py` — `UtcpAgent`, `UtcpAgentConfig`, `.create()`,
  `.chat()`, internal use of `utcp_client.call_tool`/`search_tools`
- `d:/tmp/utcp-agent/pyproject.toml` — bundled plugin deps, `requires-python = ">=3.9"`
- `d:/tmp/utcp-agent/examples/basic_openai.py` — `manual_call_templates` dict usage pattern
- `src/turing_agentmemory_mcp/utcp.py` (this repo) — `build_utcp_manual()`, `utcp_manual_from_env()`
- `tests/test_utcp_manual.py` (this repo) — existing coverage, Docker command pattern precedent
- `README.md` (this repo) — the `UTCP_CONFIG_FILE` example, now confirmed stale against current spec
- `compose.yaml`, `scripts/e2e_score.py`, `src/turing_agentmemory_mcp/e2e_score.py`,
  `e2e_score_stubs.py` — Docker/E2E harness precedent
- `docker/llama-provider.Dockerfile` — llama.cpp sidecar pattern for D-08a
- `pip index versions utcp / utcp-mcp / utcp-http / utcp-text / utcp-cli / utcp-agent / mcp-use /
  langchain-openai` — live PyPI registry confirmation of current versions

### Secondary (MEDIUM confidence)
- `https://www.utcp.io/` (WebFetch) — UTCP's stated "no wrapper servers required" philosophy,
  supported protocol list, current spec version "1.1"
- WebSearch confirming `python-utcp`/`utcp-agent` GitHub org presence and dedicated
  `utcp-specification` repo (legitimacy signal for Package Legitimacy Audit)

### Tertiary (LOW confidence)
- None used for load-bearing claims in this document — every technical claim about API shape or
  validation behavior traces to a Primary source above.

## Metadata

**Confidence breakdown:**
- Standard stack (versions, plugin structure): HIGH — confirmed live against PyPI and read from cloned source
- Architecture / conformance gaps (auth mismatch, command/args shape, README drift, live-discovery
  behavior): HIGH — each is a direct read of the current pydantic model source, not inference
- Docker harness wiring: HIGH for the `docker compose run --rm -T ... serve --transport stdio`
  pattern (already present in this repo's own tests); MEDIUM for exact GPU-sidecar cold-start
  timing behavior under the harness (not empirically timed in this research pass)
- Verdict-relevant framing (UTCP's own "no wrapper" positioning): MEDIUM — CITED from utcp.io, a
  single official source, not independently cross-verified against a second source

**Research date:** 2026-07-12
**Valid until:** ~14 days (fast-moving ecosystem — `utcp` has shipped 3+ releases in recent
history; re-verify package versions and the two documented pydantic-model gaps immediately before
planning/execution if this research is more than 2 weeks old)
