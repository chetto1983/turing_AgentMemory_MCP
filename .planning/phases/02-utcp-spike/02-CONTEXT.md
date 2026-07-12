# Phase 2: UTCP Spike - Context

**Gathered:** 2026-07-12
**Status:** Ready for planning

<domain>
## Phase Boundary

A **findings-only spike** that produces a written verdict on whether to natively
serve tools over UTCP (Universal Tool Calling Protocol) versus staying on the
current manual export (`utcp.py` / `utcp-manual`) versus deferring — backed by
**empirically exercising the current export against the real python-utcp client
and the real consumer (`utcp-agent`)**.

**In scope:** exercise the current UTCP manual against a real client end-to-end,
document the gaps, stand up a *throwaway* native-serving prototype for evidence,
and write a verdict that gates any future UTCP build work.

**Out of scope (SC#3, non-negotiable):** committing any UTCP build work to `src/`.
No native serving code is merged by this phase. The verdict *authorizes* or
*blocks* follow-on work; it does not perform it.

</domain>

<decisions>
## Implementation Decisions

### Spike rigor — how "a real UTCP client" is exercised
- **D-01:** Use a **live round-trip** as the primary evidence, not static
  schema-checking or spec-reading alone. Instantiate the real python-utcp client
  substrate (`UtcpClient` / `utcp-agent`), register our generated manual, and
  **actually call a memory tool through it** — observing whether the manual
  parses, auth flows, inputs validate, and outputs return. Gaps must surface as
  observed failures, not reasoned ones.
- **D-02:** The current export already emits tools with `call_template_type: "mcp"`
  (a UTCP client reaches our server *through* MCP stdio, not native UTCP-over-HTTP).
  The round-trip must exercise **this mcp call-template path first** — it is the
  status-quo behavior under test.

### Verdict driver — what the verdict weighs
- **D-03:** The motivating consumer is **`utcp-agent`**
  (`github.com/universal-tool-calling-protocol/utcp-agent`), a LangGraph/LangChain
  agent that bundles the `utcp`, `utcp-http`, `utcp-mcp`, `utcp-text`, and
  `utcp-cli` plugins and registers tools via `utcp_config.manual_call_templates`.
- **D-04:** **Key evidence for the verdict:** because `utcp-agent` already ships
  the `utcp-mcp` plugin, it *can* consume our tools via the mcp call-template our
  manual already produces — native http serving is **one option it supports, not
  a requirement**. The verdict must weigh: **does mcp-via-UTCP already satisfy the
  real consumer**, or does the consumer genuinely need native http/cli serving?
  Answer this empirically, then recommend build / stay-manual / defer accordingly.
- **D-05:** Secondary dimension to record (not the primary driver): the
  hand-maintained `AGENTMEMORY_TOOL_SPECS` list in `utcp.py` can drift from the
  live FastMCP tool registry. Note whether the verdict path implies
  auto-generating the manual from the registry.

### Native-serving probe — evidence without committing build work
- **D-06:** Stand up a **throwaway native-serving prototype** (a minimal UTCP
  `http` — or `cli`/`text` — call-template endpoint serving ~1 tool) purely to
  observe real behavior, then discard it. It lives in **`d:/tmp` or
  `scripts/spike/`, NOT in `src/`**, and is **never merged**. This gives the
  verdict real evidence about native-serving effort/fit without violating SC#3.
  Guard against scope creep: one tool, throwaway, findings only.

### Round-trip environment
- **D-07:** Run the live round-trip via a **Docker/compose harness**. The MCP
  server imports `turingdb`, which has **no Windows wheel**, so an in-process live
  call on Windows is not possible (the existing E2E already runs under Docker on
  Windows for this reason). Boot the real MCP server in a container (stub
  embed/rerank is acceptable, as E2E does), and run `UtcpClient` / `utcp-agent`
  from the host against it — over the mcp call-template, plus the throwaway native
  http prototype.
- **D-08:** Driving the *full* `utcp-agent` chat loop requires an LLM provider
  key (OpenAI/Anthropic). The tool **registration + call** can be proven through
  the underlying `UtcpClient` directly **without an LLM** — prefer that for the
  deterministic evidence, and treat a full LLM-driven agent chat as optional
  color if a key is readily available.

### Deliverable + gate mechanism
- **D-09:** Write a phase **`FINDINGS.md`** in the phase directory containing:
  (a) the documented gaps of the current export against the real client (SC#1),
  (b) the verdict — native serving / stay-on-manual / defer — with rationale
  (SC#2), and (c) explicit trigger conditions for revisiting if the verdict is
  "defer".
- **D-10:** If the verdict is **build**, add an **explicit, gated phase entry to
  ROADMAP.md** (backlog) whose precondition cites this verdict (SC#3: follow-on
  work is gated on the verdict, never assumed). Also record the verdict as a row
  in `PROJECT.md` Key Decisions.

### Claude's Discretion
- Exact choice of which memory/document tool to exercise in the round-trip
  (e.g., `memory_search` vs a simpler write) — pick the most representative one
  that produces observable, citable output.
- Whether the throwaway native prototype uses the `http` vs `cli`/`text`
  call-template — pick whichever most cheaply yields comparable evidence.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### UTCP spec, client, and the real consumer
- `https://github.com/universal-tool-calling-protocol` — UTCP org / spec root (ROADMAP ref for this phase).
- `https://github.com/universal-tool-calling-protocol/python-utcp` — the reference UTCP client + core models the manual is validated against. **Cloned locally at `d:/tmp/python-utcp`.**
  - `d:/tmp/python-utcp/core/src/utcp/data/` — pydantic models: `utcp_manual.py`, `tool.py`, `call_template.py`, `auth.py` (validate our emitted manual against these).
  - `d:/tmp/python-utcp/core/src/utcp/utcp_client.py` — `UtcpClient` used for the live round-trip.
  - `d:/tmp/python-utcp/plugins/communication_protocols/mcp/` — the mcp call-template plugin (status-quo path under test).
  - `d:/tmp/python-utcp/plugins/communication_protocols/http/` — the http plugin (native-serving prototype target).
- `https://github.com/universal-tool-calling-protocol/utcp-agent` — the **real motivating consumer**. **Cloned locally at `d:/tmp/utcp-agent`.**
  - `d:/tmp/utcp-agent/src/utcp_agent/utcp_agent.py` — `UtcpAgent` / `UtcpAgentConfig`; registers tools via `utcp_config.manual_call_templates`.
  - `d:/tmp/utcp-agent/examples/` — `basic_anthropic.py`, `basic_openai.py`, `streaming_example.py` — reference registration + call usage.
  - `d:/tmp/utcp-agent/pyproject.toml` — confirms bundled plugins (`utcp-http`, `utcp-mcp`, `utcp-text`, `utcp-cli`) and optional LLM extras.

### The artifact under test (this repo)
- `src/turing_agentmemory_mcp/utcp.py` — current manual builder: `build_utcp_manual()`, `utcp_manual_from_env()`, hand-maintained `AGENTMEMORY_TOOL_SPECS`; emits `utcp_version 1.0.2`, `call_template_type "mcp"`.
- `tests/test_utcp_manual.py` — existing tests for the manual export.
- `src/turing_agentmemory_mcp/cli.py` §`utcp-manual` — CLI entrypoint that prints the manual.

### Phase governance
- `.planning/ROADMAP.md` §"Phase 2: UTCP Spike" — the three success criteria this phase must satisfy.
- `.planning/REQUIREMENTS.md` — UTCP-01 (the single mapped requirement).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `build_utcp_manual()` in `utcp.py` already produces a complete UTCP manual — the
  round-trip registers *its output* directly; no new manual code needed to run the spike.
- The existing E2E Docker harness (`scripts/e2e_score.py`, compose stubs) is the
  proven pattern for booting the MCP server + stub embed/rerank under Docker on
  Windows — reuse it as the round-trip's server side rather than inventing a new one.

### Established Patterns
- Reference repos are cloned under `d:/tmp/` (matches the ArcadeDB precedent
  `d:/tmp/arcadedb`) — `d:/tmp/python-utcp` and `d:/tmp/utcp-agent` follow the same pattern.
- `AGENTMEMORY_TOOL_SPECS` is hand-maintained — any drift-vs-registry finding is a
  known-shape observation, not a surprise.

### Integration Points
- The spike touches the boundary between `utcp.py`'s emitted manual and the
  python-utcp client's parser/executor — that seam is exactly what the round-trip probes.
- No changes to `store.py`, retrieval, or the backend port — this phase is
  independent of the ArcadeDB migration (runs early to de-risk).

</code_context>

<specifics>
## Specific Ideas

- The user explicitly named the real consumer to test against: **`utcp-agent`**,
  and asked that both `python-utcp` and `utcp-agent` be cloned to `d:/tmp` (done).
- The user chose the **most rigorous** path at every decision point: live
  round-trip, real consumer, a throwaway native prototype for real evidence, and
  a FINDINGS.md + gated roadmap phase — signaling they want the verdict backed by
  observed behavior, not desk analysis.

</specifics>

<deferred>
## Deferred Ideas

- **Native UTCP serving implementation** — explicitly deferred to a gated future
  phase (if the verdict recommends it). This phase writes zero serving code into `src/`.
- **Auto-generating the UTCP manual from the live FastMCP tool registry** (to kill
  `AGENTMEMORY_TOOL_SPECS` drift) — record as a candidate in FINDINGS.md; it is a
  build change and belongs to whatever follow-on the verdict authorizes, not here.

None of these are acted on in Phase 2 — discussion stayed within the spike's
findings-only boundary.

</deferred>

---

*Phase: 2-UTCP Spike*
*Context gathered: 2026-07-12*
