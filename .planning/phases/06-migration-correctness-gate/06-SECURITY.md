---
phase: 6
slug: migration-correctness-gate
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-16
---

# Phase 6 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> This phase's deliverable is the ARC-09 migration-correctness gate that authorizes
> the irreversible Phase-7 TuringDB removal, so its threat model centers on preventing
> a fabricated, tampered, or fail-open GO verdict.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| external corpus files → `verify_corpus` | Files under `--corpus-root` are untrusted until sha256-matched against the committed manifest | Untrusted benchmark corpus (12 files) |
| e2e capture provider URLs → `is_stub_provider` | Recorded embed/rerank endpoints decide whether a run is a real-GPU (quality-valid) or stub (invalid) measurement | Provider config detail from the e2e capture |
| 06-03 captures → `gate_diff` → `gate-result.json` | Untrusted-until-verified capture JSON crosses into the committed verdict | Real-provider benchmark + e2e JSON |
| committed `gate-result.json` → `assert_gate_go` | The verdict file is the sole authority gating the irreversible Phase-7 TuringDB removal | GO/NO_GO verdict + D-09 fields |
| Phase-7 tooling → `gate_guard` | Phase 7 invokes the guard; a fail-open bug here would authorize an irreversible destructive action | Verdict read result |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-06-01-01 | Tampering/Spoofing | `verify_corpus` (corpus substitution) | high | mitigate | Re-hashes every manifest file; missing/drift → `ok:False` → NO_GO. Verified in code + re-run live (12/12 zero drift). | closed |
| T-06-01-02 | Tampering | `is_stub_provider` (stub masquerading as GPU) | high | mitigate | Localhost embed/rerank hosts force True → NO_GO in `compute_verdict`; real capture uses sidecar hostnames. | closed |
| T-06-01-03 | Repudiation | `diff_metrics` (aggregate hides per-doc regression) | medium | mitigate | Per-document AND aggregate diff both emitted in `gate-result.json` (7 per-doc entries confirmed). | closed |
| T-06-01-04 | Tampering | `corrected_checks` (silent no-op / D-05 mis-derivation) | medium | mitigate | Pure transform `ok = False if error else bool(detail)`; tested to 14/5 split; no edit to `check()`. | closed |
| T-06-02-01 | Tampering | `assert_gate_go` (tampered gate-result.json authorizing removal) | high | mitigate | `load_verdict` reads fresh (no cache), validates D-09 schema, fails closed on parse error. | closed |
| T-06-02-02 | Elevation of Privilege | `assert_gate_go` (missing artifact silently passing) | high | mitigate | Missing file → `AssertionError` (via OSError); zero `pytest.skip()` in all 3 test files. | closed |
| T-06-02-03 | Repudiation | `validate_gate_result_schema` (partial/NO_GO artifact trusted) | medium | mitigate | Full D-09 field-completeness check; verdict constrained to {GO, NO_GO}, else ValueError. | closed |
| T-06-03-01 | Spoofing/Tampering | corpus under `--root` (substitution) | high | mitigate | Same `verify_corpus` pre-flight fails closed before any capture is trusted (D-11). | closed |
| T-06-03-02 | Tampering | provider identity (stub masquerading as GPU) | high | mitigate | `E2E_USE_EXTERNAL_*=1` + sidecar hostnames; check #1 detail non-127.0.0.1; `is_stub_provider` re-check. | closed |
| T-06-03-03 | Tampering | question drift (regeneration instead of replay) | medium | mitigate | `--frozen-questions` replays the committed 60 (count re-verified = 60); no regeneration. | closed |
| T-06-04-01 | Tampering | `gate-result.json` (stub/mismatch capture emitting GO) | high | mitigate | `build_gate_result` re-runs `verify_corpus` + `is_stub_provider`; either failure forces NO_GO before write. | closed |
| T-06-04-02 | Repudiation | `GATE.md` (grading against deflated aggregate / flattered bar) | high | mitigate | Figures equal `gate-result.json`; bar is bug-corrected 7-doc subset; per-doc diff present; honesty confirmed in UAT test 2 read-through. | closed |
| T-06-04-03 | Tampering | provenance loss (overwriting the inflated baseline) | medium | mitigate | Corrected baseline written to NEW `e2e-baseline-corrected.json`; original `03-turingdb` capture byte-intact vs HEAD. | closed |
| T-06-04-04 | Elevation of Privilege | committed-verdict test skipping instead of failing | high | mitigate | `assert_gate_go`-based test has no `pytest.skip`; NO_GO/missing artifact hard-fails. | closed |
| T-06-01-SC | Tampering | package installs | low | accept | No new dependencies — stdlib only (json, hashlib, statistics, pathlib). See Accepted Risks. | closed |
| T-06-02-SC | Tampering | package installs | low | accept | No new dependencies — stdlib only (json, pathlib). See Accepted Risks. | closed |
| T-06-03-SC | Tampering | package installs | low | accept | No new dependencies — existing scripts against the pinned compose stack. See Accepted Risks. | closed |
| T-06-03-04 | Repudiation | GLiNER-on-one-side latency confound | low | accept | Documented in `capture-provider-env.txt` + GATE.md deviation log; `document_search` consumes no entity channel (D-06). See Accepted Risks. | closed |
| T-06-04-SC | Tampering | package installs | low | accept | No new dependencies — stdlib + existing scripts only. See Accepted Risks. | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on (high) count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-06-01 | T-06-01-SC, T-06-02-SC, T-06-03-SC, T-06-04-SC | No new npm/pip/cargo dependencies introduced — gate engine + guard use Python stdlib only and drive existing scripts against the pinned compose stack; no supply-chain surface added. | dvdmarchetto@gmail.com | 2026-07-16 |
| AR-06-02 | T-06-03-04 | GLiNER left ON (compose default) for the capture. `document_search` ranking is legacy dense+lexical+rerank RAG and consumes no entity/graph channel (verified in `store_documents.py`), so the locked metrics and per-query search latency are unaffected; only ingestion wall-clock (not gated) is heavier. | dvdmarchetto@gmail.com | 2026-07-16 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-16 | 18 | 18 | 0 | Claude (gsd-secure-phase, ASVS-L1 orchestrator verification) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-16
