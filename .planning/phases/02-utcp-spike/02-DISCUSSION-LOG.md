# Phase 2: UTCP Spike - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-12
**Phase:** 2-UTCP Spike
**Areas discussed:** Spike rigor, Verdict driver, Native probe, Deliverable/gate, Round-trip environment

---

## Spike rigor — how "a real UTCP client" is exercised

| Option | Description | Selected |
|--------|-------------|----------|
| Live round-trip | Install python-utcp UtcpClient, register our manual, actually call a tool through it end-to-end (mcp call-template). Strongest evidence. | ✓ |
| Static conformance | Validate manual JSON against python-utcp pydantic models/serializers; no live calls. | |
| Spec/code read only | Read spec + cloned source, compare to utcp.py by inspection. Weakest evidence. | |

**User's choice:** Live round-trip
**Notes:** Gaps must surface as observed failures, not reasoned ones. The status-quo mcp call-template path is exercised first.

---

## Verdict driver — what the verdict weighs

| Option | Description | Selected |
|--------|-------------|----------|
| Real consumer exists | A real/planned UTCP client needs our tools; weigh whether mcp-via-UTCP suffices vs native http serving. | ✓ |
| Reduce maintenance | Pain is hand-maintained AGENTMEMORY_TOOL_SPECS drift; weigh auto-generating manual from registry. | |
| Ecosystem/optionality | Speculative, no committed consumer; likely defer-with-trigger. | |

**User's choice:** Real consumer exists → named as **`utcp-agent`** (`github.com/universal-tool-calling-protocol/utcp-agent`)
**Notes:** utcp-agent is a LangGraph agent bundling `utcp`, `utcp-http`, `utcp-mcp`, `utcp-text`, `utcp-cli`. Because it already ships `utcp-mcp`, it can consume our tools via the mcp call-template the current manual emits — native http serving is an option it supports, not a requirement. The verdict must determine empirically whether mcp-via-UTCP satisfies this consumer.

---

## Native probe — prototype vs reason-only

| Option | Description | Selected |
|--------|-------------|----------|
| No prototype (findings only) | Assess native serving from http/cli plugins + spec by inspection; write no serving code. | |
| Throwaway spike prototype | Stand up a minimal native UTCP http (or cli) endpoint in a throwaway location (d:/tmp or scripts/spike, not src/); observe, then discard. | ✓ |

**User's choice:** Throwaway spike prototype
**Notes:** One tool, throwaway, never merged — gives the verdict real evidence about native-serving effort/fit without violating SC#3 (no build work committed to src/). Scope-creep guard noted.

---

## Deliverable / gate mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| FINDINGS.md + gated roadmap phase | Phase FINDINGS.md (gaps + verdict + rationale); if verdict is build, add explicit gated ROADMAP phase. | ✓ |
| FINDINGS.md only | Single findings doc; follow-on as a backlog todo, no roadmap edit. | |
| Decision-log entry only | Record verdict in PROJECT.md Key Decisions; minimal prose. | |

**User's choice:** FINDINGS.md + gated roadmap phase
**Notes:** Verdict also recorded as a PROJECT.md Key Decisions row. Follow-on build work is explicitly gated on the verdict per SC#3.

---

## Round-trip environment

| Option | Description | Selected |
|--------|-------------|----------|
| Docker/compose harness | Boot real MCP server in a container (as E2E does on Windows); run UtcpClient/utcp-agent from host against it. Most faithful. | ✓ |
| WSL in-process | Run server + client in WSL/Linux where turingdb installs natively; in-process, no container build. | |
| Provider-free tool path | Exercise UTCP transport against a store-free tool; proves wiring, not retrieval E2E. Lightest, weaker. | |

**User's choice:** Docker/compose harness
**Notes:** The MCP server imports `turingdb`, which has no Windows wheel, so in-process live calls are impossible on Windows (E2E already runs under Docker here). Stub embed/rerank is acceptable. Tool registration + call can be proven via the underlying UtcpClient without an LLM key; full utcp-agent chat is optional color if a key is available.

---

## Claude's Discretion

- Which specific memory/document tool to exercise in the round-trip (pick the most representative one with observable, citable output).
- Whether the throwaway native prototype uses the `http` vs `cli`/`text` call-template (pick whichever most cheaply yields comparable evidence).

## Deferred Ideas

- Native UTCP serving implementation — deferred to a gated future phase (only if the verdict recommends build); zero serving code in `src/` this phase.
- Auto-generating the UTCP manual from the live FastMCP tool registry (to kill AGENTMEMORY_TOOL_SPECS drift) — recorded as a FINDINGS.md candidate; belongs to whatever follow-on the verdict authorizes.
