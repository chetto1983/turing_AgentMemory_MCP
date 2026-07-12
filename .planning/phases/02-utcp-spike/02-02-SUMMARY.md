---
phase: 02-utcp-spike
plan: 02
subsystem: testing
tags: [utcp, mcp, live-round-trip, docker, gpu, spike]

# Dependency graph
requires:
  - phase: 02-utcp-spike
    provides: "scripts/spike/requirements.txt (pinned utcp/utcp-mcp/utcp-http/utcp-text/utcp-agent), static SC#1 conformance evidence (tests/test_utcp_conformance.py)"
provides:
  - "scripts/spike/utcp_roundtrip.py — live mcp call-template round-trip harness (D-01/D-02/D-07/D-08), run end-to-end against the real Dockerized MCP server"
  - "scripts/spike/native_http_prototype.py — throwaway native-http prototype (D-06), self-tested end-to-end against a real UtcpClient"
  - "scripts/spike/full_agent_chat.py — optional D-08a full-agent chat harness with mandatory GPU-fallback record"
  - "Live SC#1 evidence: register_manual discovers 26 live FastMCP tools (vs. 19 in AGENTMEMORY_TOOL_SPECS), memory_store_message + memory_search round-trip succeeded with real fusion/rerank scoring, and a newly-observed double-prefix tool-naming gap"
affects: [02-03-utcp-findings]

# Tech tracking
tech-stack:
  added: []
  patterns: ["McpCallTemplate/HttpCallTemplate hand-built by value rather than reused from utcp.py's build_utcp_manual() output, to isolate and document each SC#1 gap independently", "deriving the live tool-name prefix from the registered manual's own tool names instead of assuming it equals the call template's declared name"]

key-files:
  created: [scripts/spike/utcp_roundtrip.py, scripts/spike/native_http_prototype.py, scripts/spike/full_agent_chat.py]
  modified: []

key-decisions:
  - "Brought up the full GPU-backed compose dependency stack (turingdb, agentmemory-embed, agentmemory-rerank, agentmemory-gliner) and ran the live mcp round-trip end-to-end rather than deferring it, since both Docker and an NVIDIA GPU were available in this environment and the plan's own D-01 requirement is to surface gaps as OBSERVED failures, not reasoned ones."
  - "Fixed a Rule-1 bug discovered only by running the live round-trip: call_tool() now derives the actual tool-name prefix from the registered manual's own tool names instead of assuming it equals SERVER_NAME, because UTCP sanitizes non-word characters in manual names (turning 'turing-agentmemory-mcp' into 'turing_agentmemory_mcp') and the live FastMCP server itself already returns tool names pre-namespaced as 'turing-agentmemory-mcp.<tool>' -- compounded, the real callable name is 'turing_agentmemory_mcp.turing-agentmemory-mcp.memory_store_message'."
  - "Did not attempt the optional D-08a full-agent chat (would require building/downloading a ~7-8GB Gemma GGUF via a one-off llama.cpp docker run) since D-08 explicitly designates the LLM-free round-trip as the deterministic core evidence and D-08a as optional color; full_agent_chat.py correctly recorded 'full-agent chat NOT exercised (no GPU / endpoint unavailable)' per the required non-silent-skip behavior."
  - "Left the GPU-backed compose services (turingdb, agentmemory-embed, agentmemory-rerank, agentmemory-gliner) running after the live round-trip rather than tearing them down, since docker compose down is a destructive action outside this plan's scope and the user may want the stack available for further UTCP evidence gathering or other work; run `docker compose down` manually to reclaim GPU memory when finished."

requirements-completed: []

coverage:
  - id: D1
    description: "scripts/spike/utcp_roundtrip.py builds a hand-corrected McpCallTemplate (command: str + args: list) and, via --dry-run, proves the shape offline without Docker"
    requirement: UTCP-01
    verification:
      - kind: unit
        ref: "python scripts/spike/utcp_roundtrip.py --dry-run"
        status: pass
      - kind: unit
        ref: "python -m ruff check scripts/spike/utcp_roundtrip.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Live mcp round-trip against the Dockerized MCP server: register_manual discovers live FastMCP tools, memory_store_message writes a real memory, memory_search finds it back with real fusion/rerank scoring"
    requirement: UTCP-01
    verification:
      - kind: e2e
        ref: "python scripts/spike/utcp_roundtrip.py (live run against docker compose turingdb + agentmemory-embed + agentmemory-rerank + agentmemory-gliner + turing-agentmemory-mcp, this session)"
        status: pass
    human_judgment: false
  - id: D3
    description: "scripts/spike/native_http_prototype.py serves a real UTCP manual over GET and a real tool invocation over POST on one path, self-tested end-to-end against the real UtcpClient, bound to 127.0.0.1 only, never wired into compose.yaml"
    requirement: UTCP-01
    verification:
      - kind: e2e
        ref: "python scripts/spike/native_http_prototype.py --self-test"
        status: pass
      - kind: unit
        ref: "grep -rl 0.0.0.0 scripts/spike/native_http_prototype.py (absent)"
        status: pass
      - kind: unit
        ref: "python -m ruff check scripts/spike/native_http_prototype.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "scripts/spike/full_agent_chat.py probes GPU/llama.cpp endpoint availability and records an explicit non-exercise message when unavailable, never silently skipping (D-08a)"
    requirement: UTCP-01
    verification:
      - kind: unit
        ref: "python scripts/spike/full_agent_chat.py --check"
        status: pass
      - kind: e2e
        ref: "python scripts/spike/full_agent_chat.py (this session, no llama.cpp sidecar running -> printed explicit non-exercise record)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Zero UTCP native-serving code lands under src/ (SC#3 guard)"
    requirement: UTCP-01
    verification:
      - kind: unit
        ref: "grep -rl \"HttpCallTemplate|utcp_http|http_call_template\" src/ (empty, exit 1)"
        status: pass
    human_judgment: false

duration: 35min
completed: 2026-07-12
status: complete
---

# Phase 02 Plan 02: UTCP Live Round-Trip Spike Summary

**Ran the real python-utcp `UtcpClient` end-to-end against the Dockerized MCP server over the mcp call-template — register_manual discovered 26 live FastMCP tools (vs. 19 hand-maintained in `AGENTMEMORY_TOOL_SPECS`), and a real `memory_store_message` -> `memory_search` round-trip succeeded with genuine fusion/rerank scoring, surfacing a new, previously-undocumented tool-name double-prefixing gap.**

## Performance

- **Duration:** ~35 min (including ~5 min for the GPU-backed compose dependency stack to cold-start and download pinned embed/rerank GGUF models)
- **Tasks:** 3
- **Files modified:** 3 created (`scripts/spike/utcp_roundtrip.py`, `scripts/spike/native_http_prototype.py`, `scripts/spike/full_agent_chat.py`)

## Accomplishments

- **`scripts/spike/utcp_roundtrip.py`** (D-01/D-02/D-07/D-08): hand-builds a corrected `McpCallTemplate` (`command`: string + `args`: list, per the real `McpConfig` contract) rather than reusing `utcp.py`'s `build_utcp_manual()` output, which emits the whole argv as a single `"command"` array — that divergence is SC#1 gap #2, documented inline. `--dry-run` proves the shape offline. The full run was executed live against the real Dockerized stack this session:
  - `register_manual` succeeded, discovering **26 live tools** via `session.list_tools()` — confirming the RESEARCH.md structural finding that mcp-call-template discovery is entirely live and does not consult `AGENTMEMORY_TOOL_SPECS` (19 tools) at all. The 7-tool gap between the live registry and the hand-maintained manual is itself informative for D-05.
  - `memory_store_message` wrote a real memory (`mem_3257ccf8a5843684`), and `memory_search` found it back with real fusion scoring and rerank metadata (`Qwen3-Reranker-0.6B-q8_0.gguf`).
  - **New observed SC#1 gap** (not anticipated by 02-RESEARCH.md): `UtcpClientImplementation.register_manual()` sanitizes the manual name with `re.sub(r'[^\w]', '_', name)` before prefixing tool names, AND the live FastMCP server's own tool names already come back pre-namespaced as `"turing-agentmemory-mcp.<tool>"`. Compounded, the real callable tool name is `"turing_agentmemory_mcp.turing-agentmemory-mcp.memory_store_message"` — not `"turing-agentmemory-mcp.memory_store_message"` as a first-time integrator reading `utcp.py`'s hyphenated `server_name` would assume. The script now derives this prefix from the registered manual's own tool names rather than hardcoding it, and prints the gap explicitly.
- **`scripts/spike/native_http_prototype.py`** (D-06): a single-path (`/tools/memory_search`) stdlib `ThreadingHTTPServer` bound to `127.0.0.1` only — GET serves a real UTCP manual for live discovery, POST invokes the declared tool. `register_manual()`'s discovery POST always sends an empty body (confirmed by reading the installed `utcp-http` source), so the handler distinguishes discovery from invocation on `Content-Length` rather than a separate route. Backed by an honest in-memory stand-in (no `turingdb` import — no Windows wheel) implementing real endpoint routing, body unwrapping, tenant-scope read, an auth-header check, and output-schema mapping. `--self-test` ran the full start -> register -> call -> teardown cycle against the real `UtcpClient` successfully — this IS live, real evidence (not merely offline-verifiable), captured in this session.
- **`scripts/spike/full_agent_chat.py`** (D-03/D-08a): probes `nvidia-smi` and the local llama.cpp OpenAI-compatible endpoint before attempting a chat. Ran in this session with GPU present but no llama.cpp sidecar running, and correctly printed the explicit `"full-agent chat NOT exercised (no GPU / endpoint unavailable)"` record rather than silently skipping — the required D-08a fallback behavior.
- Confirmed the SC#3 guard: `grep -rl "HttpCallTemplate|utcp_http|http_call_template" src/` is empty — zero UTCP native-serving code landed under `src/`.
- Full repo gate re-verified after the change: `python -m pytest -q` (374 passed), `python -m ruff check src tests scripts` (clean), `docker compose config --quiet` (valid).

## Task Commits

Each task was committed atomically:

1. **Task 1: Live mcp call-template round-trip harness (D-01/D-02/D-07/D-08)** - `e3cdd52` (feat)
2. **Task 2: Throwaway native-http prototype for D-06 effort evidence** - `b1558ac` (feat)
3. **Task 3: Optional full utcp-agent chat with mandatory GPU-fallback record (D-03/D-08a)** - `c066561` (feat)
4. **Fix (Rule 1, found during the live round-trip): derive live tool-name prefix from the registered manual** - `7f48022` (fix)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified

- `scripts/spike/utcp_roundtrip.py` - Live mcp call-template round-trip harness; `--dry-run` for offline shape verification, full run registers against the Dockerized MCP server and calls `memory_store_message` then `memory_search` through the real `UtcpClient`.
- `scripts/spike/native_http_prototype.py` - Throwaway 127.0.0.1-only http prototype for D-06 native-serving effort evidence; `--self-test` runs the full cycle against a real `UtcpClient`.
- `scripts/spike/full_agent_chat.py` - Optional D-08a full-agent chat harness with a mandatory, non-silent GPU-fallback record; `--check` runs only the probe.

## Decisions Made

- Brought up the full GPU-backed compose dependency stack and ran the live mcp round-trip end-to-end (rather than deferring to a later manual session), since Docker + an NVIDIA GPU were both available and D-01 requires OBSERVED, not reasoned, evidence.
- Fixed a Rule-1 bug in `utcp_roundtrip.py`'s `call_tool()` prefix assumption, discovered only by actually running the live round-trip (see Deviations below) — this is itself valuable SC#1 evidence, not incidental cleanup.
- Did not pursue the optional D-08a full-agent chat with a real Gemma sidecar (would require a ~7-8GB one-off GGUF download plus a `docker run` outside `docker compose`) since D-08 explicitly designates the LLM-free round-trip as the deterministic core evidence and D-08a as optional color that must record non-exercise rather than block the plan.
- Left the GPU-backed compose services running after the live round-trip (not torn down) since `docker compose down` is a destructive, out-of-scope action; the user can run it manually to reclaim GPU memory.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `utcp_roundtrip.py` assumed the live tool-name prefix equals the hyphenated `SERVER_NAME`**
- **Found during:** Task 1's live-run verification (running `python scripts/spike/utcp_roundtrip.py` against the real Dockerized stack, not anticipated by 02-RESEARCH.md)
- **Issue:** The script called `client.call_tool(f"{SERVER_NAME}.memory_store_message", ...)` assuming the registered tool name would be `"turing-agentmemory-mcp.memory_store_message"`. The real `UtcpClientImplementation.register_manual()` sanitizes non-word characters in the manual name (`re.sub(r'[^\w]', '_', name)`) before prefixing tool names, AND the live FastMCP server's own tool names already arrive pre-namespaced as `"turing-agentmemory-mcp.<tool>"`. The actual registered name was `"turing_agentmemory_mcp.turing-agentmemory-mcp.memory_store_message"` — `call_tool` failed with `ValueError('Tool not found: turing-agentmemory-mcp.memory_store_message')`.
- **Fix:** `call_tool()` now derives the real prefix from `result.manual.tools[0].name.rsplit(".", 1)[0]` (the actual registered manual, not an assumption), and prints an explicit `"OBSERVED SC#1 gap"` line documenting the mismatch for FINDINGS.md.
- **Files modified:** `scripts/spike/utcp_roundtrip.py`
- **Verification:** Re-ran the live round-trip against the still-healthy Dockerized stack — `register_manual` succeeded (26 tools), `memory_store_message` and `memory_search` both succeeded with real evidence (see Accomplishments above).
- **Committed in:** `7f48022`

---

**Total deviations:** 1 auto-fixed (1 bug — Rule 1). This fix is itself part of the SC#1 evidence gathered by this plan, not unrelated cleanup — it surfaced by actually running the live round-trip per D-01's mandate that gaps must be observed, not reasoned.
**Impact on plan:** Necessary correctness fix required to complete the live round-trip; no scope creep — the fix only changed how the already-planned `call_tool` invocation derives its target name.

## Issues Encountered

- The GPU-backed compose dependency stack (`agentmemory-embed`, `agentmemory-rerank`) took several minutes to become healthy because `agentmemory-model-init` had to download two pinned GGUF models (~241MB granite-embedding + a Qwen3-Reranker model) from HuggingFace, including one transient HTTP/2 stream error that the built-in `curl --retry-all-errors` logic recovered from automatically. No script change was needed; this matches 02-RESEARCH.md Pitfall 3's documented cold-start caveat.

## Next Phase Readiness

- Both halves of SC#1 evidence are now complete: static (plan 02-01's `tests/test_utcp_conformance.py`, gaps #1 and #3) and live (this plan's `utcp_roundtrip.py` run, gap #2 confirmed plus the newly-observed tool-name double-prefixing gap).
- D-04's key verdict input is directly answered: mcp-via-UTCP **does** already satisfy the real consumer path end-to-end (register + write + search all succeeded), with fixable emission bugs in `utcp.py` (command/args shape, auth type, tool-name prefix expectations) rather than a fundamental blocker.
- D-05 has fresh data: the live registry exposes 26 tools vs. 19 in `AGENTMEMORY_TOOL_SPECS` — confirms the hand-maintained manual has already drifted from the live FastMCP registry.
- D-06 (native-http effort evidence) and D-08a (full-agent GPU-fallback record) are both captured.
- Plan 02-03 can now write `02-FINDINGS.md` (D-09) weighing all of the above into a native-serving / stay-manual / defer verdict, and gate any follow-on UTCP build work on it (D-10).
- No blockers. The GPU-backed compose services (`turingdb`, `agentmemory-embed`, `agentmemory-rerank`, `agentmemory-gliner`) remain running from this session's live verification; run `docker compose down` to reclaim resources when no longer needed.

---
*Phase: 02-utcp-spike*
*Completed: 2026-07-12*

## Self-Check: PASSED

- FOUND: scripts/spike/utcp_roundtrip.py
- FOUND: scripts/spike/native_http_prototype.py
- FOUND: scripts/spike/full_agent_chat.py
- FOUND: .planning/phases/02-utcp-spike/02-02-SUMMARY.md
- FOUND commit: e3cdd52
- FOUND commit: b1558ac
- FOUND commit: c066561
- FOUND commit: 7f48022
