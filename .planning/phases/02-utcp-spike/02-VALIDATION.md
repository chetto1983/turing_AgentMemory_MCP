---
phase: 2
slug: utcp-spike
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-12
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> **Findings-only spike:** the deliverable is `02-FINDINGS.md` + a reproducible harness,
> not shipped code. Validation here proves the *evidence* is real (conformance gaps
> reproduce; the live round-trip actually ran), not that a feature works.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2+ (existing repo framework) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths=tests`, `pythonpath=src`; markers `slow`/`integration`/`gpu` |
| **Quick run command** | `python -m pytest tests/test_utcp_conformance.py -q` (Docker-free static conformance) |
| **Full suite command** | `python scripts/spike/utcp_roundtrip.py` (live Docker round-trip — NOT a pytest target; evidence tooling, run manually) |
| **Estimated runtime** | Conformance pytest: ~seconds. Live round-trip: ~10–20 min (GPU sidecar cold start) |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_utcp_conformance.py -q`
- **After every plan wave:** Run the same conformance pytest (the live Docker round-trip is deliberately manual — GPU + ~20 min cold start is disproportionate as a per-commit gate)
- **Before `/gsd-verify-work`:** Conformance pytest green AND `02-FINDINGS.md` exists with SC#1 gaps + SC#2 verdict AND `git diff` confirms SC#3 (no UTCP serving code in `src/`)
- **Max feedback latency:** ~5 seconds (conformance path)

---

## Per-Task Verification Map

*Task IDs bind when PLAN.md files are written; rows below are the behavior-level contract from RESEARCH.md §Validation Architecture that the plans must satisfy.*

| Behavior | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|----------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| `utcp.py`'s auth-enabled manual fails current python-utcp `Tool`/`McpCallTemplate` validation (api_key ≠ OAuth2Auth) | UTCP-01 SC#1 | — | Dummy token only; never print raw `AGENTMEMORY_AUTH_TOKEN` | unit (static, no Docker) | `pytest tests/test_utcp_conformance.py::test_manual_with_auth_fails_current_utcp_pydantic_validation -x` | ❌ W0 | ⬜ pending |
| README's `UTCP_CONFIG_FILE` text/`file_path` example is stale vs current `TextCallTemplateSerializer` | UTCP-01 SC#1 | — | N/A | unit (static, no Docker) | `pytest tests/test_utcp_conformance.py::test_readme_utcp_config_example_is_stale -x` | ❌ W0 | ⬜ pending |
| mcp call-template register + call against the real Dockerized server (live evidence; success or observed failure) | UTCP-01 SC#1 | T-spike-01 | Bind nothing to `0.0.0.0`; dummy auth | manual/scripted (Docker + GPU, not pytest) | `python scripts/spike/utcp_roundtrip.py` (exits non-zero on failure; prints structured evidence) | ❌ W0 | ⬜ pending |
| Throwaway native-http prototype (D-06) yields effort/behavior evidence, never merged to `src/` | UTCP-01 SC#1/SC#3 | T-spike-02 | Bind `127.0.0.1` only; tear down after | manual/scripted | `python scripts/spike/native_http_prototype.py` | ❌ W0 | ⬜ pending |
| Verdict document exists with rationale + trigger conditions | UTCP-01 SC#2 | — | N/A | manual review (written deliverable) | N/A — reviewed at phase verification | ❌ W0 (`02-FINDINGS.md`) | ⬜ pending |
| Zero UTCP native-serving code under `src/`; prototype only in `scripts/spike/` or `d:/tmp` | UTCP-01 SC#3 | — | N/A | automated guard | `grep -rl "HttpCallTemplate\|utcp_http\|http_call_template" src/` must be empty | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scripts/spike/requirements.txt` — pinned `utcp==1.1.3`, `utcp-mcp==1.1.2`, `utcp-http==1.1.11`, `utcp-text==1.1.0`, `utcp-agent==1.0.3` (spike-only; NOT added to `pyproject.toml` `dependencies`)
- [ ] `tests/test_utcp_conformance.py` — Docker-free static conformance stubs for the two SC#1 gaps (needs `utcp`/`utcp-text` importable; scope as opt-in `integration`-marked if it must not become a silent CI dep — see RESEARCH Open Question #1)
- [ ] `scripts/spike/utcp_roundtrip.py` — D-01/D-02/D-07/D-08 live round-trip harness stub
- [ ] `scripts/spike/native_http_prototype.py` — D-06 throwaway (never merged)
- [ ] Framework install: none beyond the pip installs above — pytest/ruff already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live mcp round-trip against Dockerized server | UTCP-01 SC#1 | Requires Docker + GPU sidecars up (~10–20 min cold start); live subprocess/stdio behavior — disproportionate as an automated per-commit gate | Bring up deps, run `python scripts/spike/utcp_roundtrip.py`, capture structured output into `02-FINDINGS.md` |
| Optional full utcp-agent chat via local llama.cpp Gemma (D-08a) | UTCP-01 SC#1 (color) | GPU-mandatory optional path; needs GGUF download + sidecar | Run `python scripts/spike/full_agent_chat.py`; if no GPU, record "full-agent chat not exercised (no GPU)" — never silently skip |
| Verdict rationale + trigger conditions | UTCP-01 SC#2 | Written-document deliverable — judged, not asserted | Review `02-FINDINGS.md` at phase verification |

---

## Validation Sign-Off

- [ ] Every committed task has an `<automated>` verify (conformance pytest) or an explicit Wave 0 / manual-only classification
- [ ] Sampling continuity: no 3 consecutive committed tasks without automated verify
- [ ] Wave 0 covers all MISSING references (new spike files + conformance test)
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s (conformance path)
- [ ] SC#3 guard present: `grep` confirms no UTCP serving code merged under `src/`
- [ ] `nyquist_compliant: true` set in frontmatter once the above hold

**Approval:** pending
