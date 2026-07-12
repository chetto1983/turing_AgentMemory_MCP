# Phase 2: UTCP Spike — Findings

**Phase:** 02-utcp-spike
**Status:** Complete (findings-only spike; zero build work committed)
**Evidence sources:** `02-01-SUMMARY.md` (static conformance, no Docker), `02-02-SUMMARY.md` (live
mcp round-trip + throwaway native-http prototype + optional full-agent chat), `02-RESEARCH.md`
(source-verified conformance analysis against the cloned `d:/tmp/python-utcp` and
`d:/tmp/utcp-agent`).

---

## SC#1 — Documented Gaps

Four gaps were found against the current `utcp` / `utcp-mcp` / `utcp-text` PyPI packages (1.1.3 /
1.1.2 / 1.1.0). Three were static, source-verified, and reproduced by a committed, Docker-free
pytest (`tests/test_utcp_conformance.py`, plan 02-01). One was newly observed only by actually
running the live round-trip (plan 02-02) — exactly the D-01 mandate that "gaps must surface as
observed failures, not reasoned ones."

### Gap #1 — Auth type mismatch (static, reproduced)

`McpCallTemplate.auth` is typed `Optional[OAuth2Auth]` in the current python-utcp, but
`utcp.py`'s `build_utcp_manual()` emits `auth_type: "api_key"` on the mcp `tool_call_template`
whenever `AGENTMEMORY_AUTH_TOKEN` is set. Validating our manual against the real `Tool`/
`McpCallTemplate` pydantic models with auth configured raises a pydantic `UtcpSerializerValidationError`
— `api_key` fields don't satisfy `OAuth2Auth`'s required `token_url`/`client_id`/`client_secret`.

- **Source:** `d:/tmp/python-utcp/plugins/communication_protocols/mcp/src/utcp_mcp/mcp_call_template.py:131-134`
- **Evidence:** `tests/test_utcp_conformance.py::test_manual_with_auth_fails_current_utcp_pydantic_validation` (02-01, PASS — the test asserts the `ValidationError` is raised; confirmed the dummy token never leaks into the dumped manual JSON)

### Gap #2 — `mcpServers` command/args shape mismatch (static evidence + live confirmation)

`McpCallTemplate`'s own docstring example shows `"command": "node", "args": ["mcp-server.js"]` —
a **string** executable plus a separate **args list**. `utcp.py`'s `build_utcp_manual()` instead
emits the entire argv (e.g. `["turing-agentmemory-mcp","serve","--transport","stdio"]`) as a
single `"command"` array, with no `"args"` key and an extra, unrecognized `"transport": "stdio"`
key. This is the shape `mcp_use.MCPClient.from_dict()` (the library `utcp-mcp` delegates to)
receives raw — a real registration-path defect.

- **Source:** `d:/tmp/python-utcp/plugins/communication_protocols/mcp/src/utcp_mcp/mcp_call_template.py:40-56`
- **Evidence:** Plan 02-02's `scripts/spike/utcp_roundtrip.py` had to hand-build a corrected
  `McpCallTemplate` (`command`: string + `args`: list) rather than reuse `utcp.py`'s output
  verbatim — reusing the real output as-is would have failed registration on this exact shape
  mismatch, documented inline in the harness.

### Gap #3 — README `UTCP_CONFIG_FILE` example stale against current spec (static, reproduced)

`README.md`'s `UTCP_CONFIG_FILE` example uses `"call_template_type": "text"` with a `"file_path"`
field. The current `TextCallTemplateSerializer.validate_dict()` explicitly rejects `file_path`
with a migration error pointing callers to `call_template_type: "file"` (a separate `utcp-file`
plugin package, not bundled by `utcp-agent`). This is a spec-drift regression our own docs haven't
caught up to.

- **Source:** `d:/tmp/python-utcp/plugins/communication_protocols/text/src/utcp_text/text_call_template.py:63-73`
- **Evidence:** `tests/test_utcp_conformance.py::test_readme_utcp_config_example_is_stale` (02-01, PASS)

### Gap #4 — Tool-name double-prefixing (NEW, observed only via the live round-trip)

Not anticipated by 02-RESEARCH.md. `UtcpClientImplementation.register_manual()` sanitizes the
manual name with `re.sub(r'[^\w]', '_', name)` before prefixing tool names, AND the live FastMCP
server's own tool names already arrive pre-namespaced as `"turing-agentmemory-mcp.<tool>"`.
Compounded, the real registered/callable tool name is
`"turing_agentmemory_mcp.turing-agentmemory-mcp.memory_store_message"` — not
`"turing-agentmemory-mcp.memory_store_message"` as a first-time integrator reading `utcp.py`'s
hyphenated `server_name` would assume.

- **Evidence:** 02-02's live run against the Dockerized stack: `call_tool("turing-agentmemory-mcp.memory_store_message", ...)` failed with `ValueError('Tool not found: turing-agentmemory-mcp.memory_store_message')` until the harness was fixed (Rule-1 deviation, commit `7f48022`) to derive the prefix from the registered manual's own tool names.
- **Severity:** integration-friction, not a hard blocker — the workaround (derive the prefix from
  `result.manual.tools[0].name.rsplit(".", 1)[0]` instead of hardcoding it) is a few lines on the
  client side, and once applied the round-trip succeeded end-to-end.

### Informational drift (not a validation failure today)

`utcp.py` hardcodes `utcp_version="1.0.2"` while the real spec/library is already at 1.1 (PyPI
`utcp` 1.1.3; utcp.io states current spec version "1.1"). Nothing in the current pydantic models
enforces this field against the installed library version, so it does not cause a validation
failure today — worth fixing if/when `utcp.py` is next touched, not blocking for this verdict.

- **Source:** `d:/tmp/python-utcp/core/src/utcp/data/utcp_manual.py` — no version-compat check in the model (RESEARCH.md Pitfall 4)

---

## D-05 — Manual vs Registry Drift

The most important **structural** finding for D-04/D-05: for the mcp call-template path,
`McpCommunicationProtocol.register_manual()` does **not** consult our manual's hand-written
per-tool `inputs`/`outputs` JSON Schemas at all. It connects live over MCP stdio and calls
`session.list_tools()` on the real FastMCP server, converting the server's own live `mcp.Tool`
objects into UTCP `Tool` objects directly.

This was confirmed empirically in 02-02: the live round-trip's `register_manual()` discovered
**26 live tools** via `session.list_tools()`, versus the **19** hand-maintained entries in
`AGENTMEMORY_TOOL_SPECS` (`utcp.py`). The 7-tool gap is exactly the drift D-05 asked us to record
— and it confirms the registry has already drifted from the hand-maintained manual, independent of
this spike.

**Conclusion:** `AGENTMEMORY_TOOL_SPECS` (and the manual's tool array generally) is largely dead
weight for the mcp-call-template consumption path specifically — registration only needs *one*
`McpCallTemplate` pointing at the server's stdio command; the manual's per-tool schemas are never
read for this path. Auto-generating the manual from the live FastMCP registry (killing this drift)
is noted here as a **candidate for gated follow-on only** — it is a `src/` build change and is
explicitly not acted on in this findings-only phase (per 02-CONTEXT.md §Deferred Ideas).

---

## D-04 — Does mcp-via-UTCP already satisfy `utcp-agent`?

**Empirical answer: yes.** The live round-trip (02-02) ran the real `UtcpClient` end-to-end
against the Dockerized MCP server over the mcp call-template — the exact path `utcp-agent` uses
via its bundled `utcp-mcp` plugin (D-03):

- `register_manual()` succeeded — discovered 26 live tools via `session.list_tools()`.
- `memory_store_message` wrote a real memory (`mem_3257ccf8a5843684`).
- `memory_search` found it back with real fusion scoring and rerank metadata
  (`Qwen3-Reranker-0.6B-q8_0.gguf`).

This is the full write→read consumer loop succeeding over the status-quo mcp call-template, using
the real `utcp-mcp` plugin `utcp-agent` already bundles. `utcp-agent` does **not** require native
http/cli serving to consume our tools today — it can consume us via the mcp call-template our
manual already emits, exactly as D-04 framed the question ("native http serving is one option
`utcp-agent` supports, not a requirement").

The gaps found (auth type mismatch, command/args shape, tool-name prefix assumption) are all
**fixable emission/harness bugs in the mcp-call-template integration path**, not architectural
blockers: each was worked around with a small, targeted fix (hand-corrected `McpCallTemplate` for
the harness; deriving the tool-name prefix from the registered manual) and the round-trip then
succeeded. None of them required native http/cli serving to resolve.

On the cost side: the throwaway D-06 native-http prototype (`scripts/spike/native_http_prototype.py`)
needed real endpoint routing, discovery-vs-invocation disambiguation (register_manual's discovery
POST always sends an empty body — confirmed by reading the installed `utcp-http` source), body
unwrapping, tenant-scope read, an auth-header check, and output-schema mapping — a real, nonzero
integration-effort surface, even for a single tool on a throwaway harness. Building this out for
all 26 live tools, with actual auth/tenant-scope wiring backed by `TuringAgentMemory` rather than
the prototype's in-memory stand-in, is a materially larger effort than fixing the three mcp-path
emission bugs above.

**Weighing "mcp-via-UTCP already works for the real consumer, minus fixable emission bugs" (strong,
observed, low remaining cost) against "native http serving buys UTCP's stated no-wrapper benefit at
nonzero build cost" (real, demonstrated, but not currently required by the actual consumer) — the
evidence favors NOT building native serving now.**

---

## Verdict

**stay-manual**

**Rationale:** The real, named consumer (`utcp-agent`, D-03) already succeeds end-to-end against
our current manual-export path (mcp call-template) — proven by a genuine live round-trip against
the Dockerized MCP server, not reasoned or assumed. The four gaps found (auth type, command/args
shape, README staleness, tool-name double-prefixing) are all fixable defects in the existing
`utcp.py` emission logic and the client-side harness assumptions about it, not evidence that the
mcp path is architecturally insufficient for the consumer. UTCP's own "no wrapper servers"
philosophy (utcp.io) is a real, cited design goal, but this phase's D-06 prototype demonstrated
concretely that native http serving carries nonzero integration cost (auth, tenant scope,
discovery/invocation disambiguation, output-schema mapping) that is not currently justified by any
observed consumer failure — `utcp-agent` never needed it in this spike's evidence.

This is a **stay-manual**, not a **build**, verdict: keep the current mcp-call-template manual
export as the supported UTCP integration path. The three static emission bugs (gap #1/#2/#3) are
low-cost, narrowly-scoped fixes to `utcp.py` that would make the manual export itself more
correct — they are not "native serving" in the sense D-10's gating applies to, and are not
authorized or actioned by this phase (SC#3 forbids any `src/` change here). Per D-10, because the
verdict is not "build," no gated ROADMAP backlog phase is added; this decision is recorded solely
as a PROJECT.md Key Decisions row (see below).

---

## Trigger Conditions

*(Included for completeness per D-09's structure, though the verdict is `stay-manual`, not
`defer`. If circumstances below change, revisit this verdict.)*

Revisit the "stay-manual" verdict (i.e., re-open the build-vs-stay-manual question) if any of the
following become true:

1. **`utcp-agent` (or another concrete, named consumer) demonstrates a real failure to consume our
   tools via the mcp call-template** that cannot be resolved by fixing the emission bugs
   documented in SC#1 (gaps #1-#4) — e.g. a consumer that specifically requires native http/cli
   serving and cannot use the `utcp-mcp` plugin at all.
2. **The mcp call-template path itself is deprecated or de-prioritized upstream** in `python-utcp`
   (e.g. UTCP's stated "no wrapper servers" philosophy becomes an enforced constraint rather than a
   framing, or `utcp-mcp` support is dropped/frozen).
3. **A second, independent consumer** (beyond `utcp-agent`) is identified that specifically wants
   native http/cli tool-calling and cannot practically bridge through mcp.
4. **The manual-export emission bugs (gaps #1/#2/#3) are fixed** in a future `src/` change and a
   *new* round-trip subsequently still fails for reasons unrelated to those bugs — that would be
   new SC#1 evidence not covered by this verdict.

If none of these occur, no further UTCP spend is warranted beyond the low-cost bug fixes noted in
the Verdict section, whenever `utcp.py` is next touched for other reasons.

---

*Phase: 02-utcp-spike*
*Findings completed: 2026-07-12*
