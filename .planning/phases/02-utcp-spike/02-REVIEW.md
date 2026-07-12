---
phase: 02-utcp-spike
reviewed: 2026-07-12T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - scripts/spike/full_agent_chat.py
  - scripts/spike/native_http_prototype.py
  - scripts/spike/requirements.txt
  - scripts/spike/utcp_roundtrip.py
  - tests/test_utcp_conformance.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-12T00:00:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Reviewed the four throwaway UTCP spike scripts and one committed conformance test.
Severity was calibrated per the phase brief: the spike scripts are evidence-gathering
throwaway code (not shipped, not imported by `src/`), so I focused on whether they
produce **correct, non-misleading spike evidence** rather than production hardening.
`tests/test_utcp_conformance.py` is a committed pytest and was held to normal test
standards.

No BLOCKERs found (no security exposure, no data-loss path; the `api_key="not-needed"`
and `"throwaway-dummy-token"` literals are intentional dummies, and the no-leak guard in
`utcp_roundtrip.py` is correct). The findings center on two things that matter most for a
findings-only spike: (a) a spike script that can **print misleading "available" evidence**
because a probe result is computed but ignored, and (b) two committed conformance tests
that assert a failure occurred without verifying the failure *cause*, so they can record a
UTCP gap that isn't the gap they claim.

## Warnings

### WR-01: `full_agent_chat.py` ignores the GPU probe result, can print misleading "GPU/endpoint available" evidence

**File:** `scripts/spike/full_agent_chat.py:140-146`
**Issue:** The module docstring (lines 22-25) states the recorded non-exercise condition
is "no GPU **or** the llama.cpp endpoint unavailable". `_probe()` computes both `gpu` and
`endpoint`, but `main()` gates only on `not endpoint`:

```python
gpu, endpoint = _probe(args.llama_base_url)

if not endpoint:
    print(NOT_EXERCISED_MESSAGE)
    return 0

print("GPU/endpoint available")
```

`gpu` is unpacked and then never used for any decision. When the endpoint is reachable but
`nvidia-smi` reported no GPU, `_probe()` prints `GPU (nvidia-smi) available: False` and then
the code prints the contradictory line `GPU/endpoint available` and proceeds to run the
chat. For a script whose sole product is FINDINGS.md evidence, emitting
"GPU/endpoint available" while the GPU probe said `False` is exactly the kind of misleading
evidence this phase must avoid — a reader capturing the transcript records a GPU-present
run that the tool's own probe contradicts.
**Fix:** Either gate on both signals to match the documented OR-contract, or drop the unused
`gpu` from the decision path and stop claiming GPU availability. Minimal correct version:

```python
gpu, endpoint = _probe(args.llama_base_url)

if not (gpu and endpoint):
    print(NOT_EXERCISED_MESSAGE)
    return 0

print("GPU and endpoint available")
```

(If the intent is that a reachable llama.cpp endpoint *implies* a GPU, then the docstring's
"no GPU" clause and the `gpu` probe are dead and should be removed so the evidence isn't
self-contradictory.)

### WR-02: `test_manual_with_auth_fails_current_utcp_pydantic_validation` asserts *that* validation failed, never *why* — can record the wrong conformance gap

**File:** `tests/test_utcp_conformance.py:26-40`
**Issue:** The test's claim (and name) is that `api_key` auth on an `mcp` call template is
what current python-utcp rejects. But it only asserts a bare boolean:

```python
try:
    UtcpManualSerializer().validate_dict(manual)
    raised = False
except UtcpSerializerValidationError:
    raised = True
assert raised, "expected api_key-on-mcp-template to fail current python-utcp validation"
```

`utcp_manual_from_env()` builds the manual via `build_utcp_manual()`, which hardcodes
`utcp_version="1.0.2"` (`src/turing_agentmemory_mcp/utcp.py:483`) while the installed
serializer is `utcp==1.1.3`, and emits a non-standard `"transport"` key plus a combined
`"command"` array (the very shapes the sibling spike scripts call out as gaps). If
validation fails for **any** of those unrelated reasons, `raised` is still `True` and the
test passes — recording "api_key auth is rejected" as conformance evidence when the real
cause may be the version field or manual shape. That is a false-attribution risk in a
committed test whose purpose is to document a specific UTCP gap.
**Fix:** Assert on the failure cause, not just its occurrence. Capture the exception and
assert its message/paths reference the auth field, e.g.:

```python
with pytest.raises(UtcpSerializerValidationError) as exc:
    UtcpManualSerializer().validate_dict(manual)
assert "auth" in str(exc.value).lower(), (
    f"expected an auth-related validation failure, got: {exc.value}"
)
```

### WR-03: `test_readme_utcp_config_example_is_stale` matches substrings anywhere in the README, not within the UTCP example

**File:** `tests/test_utcp_conformance.py:43-46`
**Issue:** The staleness claim is that the README's `UTCP_CONFIG_FILE` example uses the
deprecated `file_path` field. But the guard only checks that the two tokens exist *somewhere*
in the whole README:

```python
assert "call_template_type" in readme
assert "file_path" in readme
```

`file_path` (or `call_template_type`) appearing in any unrelated section — a code fence, a
changelog line, a path reference — satisfies the assertion, so the test can pass while the
actual UTCP example is fine, or keep passing after the example is fixed but a stray
`file_path` remains elsewhere. The test does not bind the two tokens to the same example
block, so it does not actually prove the README example is stale.
**Fix:** Scope the assertion to the config example. Extract the fenced block that contains
`call_template_type` and assert `file_path` occurs *inside that block*, or match the pair on
one contiguous example substring rather than two independent `in readme` checks.

## Info

### IN-01: `native_http_prototype.py` claims to exercise discovery-POST vs invocation-POST, but the self-test never hits the discovery-POST branch

**File:** `scripts/spike/native_http_prototype.py:107-114`, `149-160`
**Issue:** The module docstring (lines 20-24) and the `do_POST` empty-body branch present
"distinguishes discovery-POST (Content-Length 0) from invocation-POST on the same
path/method" as verified behavior. But `_register_and_call()` registers with
`http_method="GET"`, so discovery goes through `do_GET`; the `length == 0` POST branch is
never executed during the self-test. That specific claim in the evidence is therefore
asserted in prose but not actually exercised by the run.
**Fix:** Either register discovery with `http_method="POST"` to exercise the empty-body
branch, or soften the docstring to state discovery is GET-based in this harness and the
POST-discovery branch is defensive/unexercised.

### IN-02: `--self-test` flag is decorative and can never be false

**File:** `scripts/spike/native_http_prototype.py:221-228`
**Issue:** `add_argument("--self-test", action="store_true", default=True, ...)` yields
`True` whether or not the flag is passed, and `main()` discards the parsed args entirely,
always calling `_self_test()`. The flag suggests a toggle that does not exist.
**Fix:** Drop the flag (the self-test is unconditional) or make it a real toggle with
`default=False` and honor it in `main()`.

### IN-03: `free_port()` returns a port after closing the socket — bind race before `ThreadingHTTPServer` reclaims it

**File:** `scripts/spike/native_http_prototype.py:53-58`, `195-197`
**Issue:** The probe socket is closed before the port is handed to `ThreadingHTTPServer`,
leaving a small TOCTOU window where another process could claim the port and the self-test
would fail to bind. Low impact for a single-process throwaway self-test, noted for
completeness.
**Fix:** Bind the `ThreadingHTTPServer` directly to port `0` and read the assigned port from
`server.server_address[1]`, eliminating the intermediate probe socket.

### IN-04: No-leak assertion in the auth test is near-vacuous

**File:** `tests/test_utcp_conformance.py:40`
**Issue:** `assert "throwaway-dummy-token" not in json.dumps(manual)` can essentially never
fail: `build_utcp_manual()` only ever emits the placeholder `Bearer ${AGENTMEMORY_AUTH_TOKEN}`
(the env-var *name*), never the resolved value, so the token string is never in the manual by
construction. It retains marginal value as a regression guard against a future change that
resolves the env var, but as written it gives more assurance than it actually tests.
**Fix:** Keep it if desired as a cheap regression guard, but pair it with a positive assertion
that the placeholder form (`${AGENTMEMORY_AUTH_TOKEN}`) *is* present, so the test proves the
manual carries an unresolved reference rather than nothing at all.

---

_Reviewed: 2026-07-12T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
