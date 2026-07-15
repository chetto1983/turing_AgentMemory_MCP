---
phase: 05-per-tenant-arcadedb-isolation
plan: 01
subsystem: database-security
tags: [python, hmac-sha256, unicode, tenant-isolation, fail-closed]

# Dependency graph
requires:
  - phase: 04-arcadedb-direct-port
    provides: "ArcadeDB as the canonical backend and the physical-database boundary consumed by Phase 5"
provides:
  - "Exact code-point-preserving user_identifier validation for tenant routing"
  - "Strict base64 tenant naming-key loading with a 32-byte minimum and no fallback"
  - "Deterministic agentmem_t_v1_ database names using the full domain-separated HMAC-SHA-256 digest"
  - "Pseudonymous identity metadata containing only database name, digest, naming version, and non-secret key fingerprint"
affects: [05-02-tenant-registry, 05-04-tenant-provisioning, 05-05-tenant-router, phase-06-migration-correctness]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Exact opaque identity: reject unsafe input but never trim, normalize, or case-fold accepted identifiers"
    - "Domain-separated cryptographic derivation: full HMAC-SHA-256 for routing and SHA-256 for non-secret key correlation"

key-files:
  created:
    - src/turing_agentmemory_mcp/tenant_identity.py
    - tests/test_tenant_identity.py
  modified: []

key-decisions:
  - "Accepted identifiers remain code-point-for-code-point unchanged; only surrounding whitespace, Unicode Cc controls, empty values, non-strings, and lone surrogates fail closed."
  - "The non-secret naming-key fingerprint is the full lowercase SHA-256 digest of b'turing-agentmemory/tenant-key-fingerprint/v1\\x00' plus the validated key."
  - "Naming keys are bytes of at least 32 bytes and enter through strict base64 configuration or explicit test injection; there is no development or test fallback."

patterns-established:
  - "Tenant identity objects retain only pseudonymous routing metadata and never retain user_identifier or naming-key bytes."
  - "Validation diagnostics describe the rejected class without echoing attacker-controlled identity material."

requirements-completed: [ARC-07]

coverage:
  - id: D1
    description: "Exact identifiers deterministically derive agentmem_t_v1_ plus the complete lowercase HMAC-SHA-256 digest, while case, normalization, and lookalike variants remain distinct"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_identity.py#test_database_name_uses_full_hmac_sha256_digest"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_identity.py#test_exact_identifier_variants_derive_distinct_database_names"
        status: pass
    human_judgment: false
  - id: D2
    description: "Invalid identifiers fail before routing while valid Cf, Co, Cn, combining, and internal-whitespace identifiers remain unchanged"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_identity.py#test_validator_rejects_invalid_identifiers"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_identity.py#test_validator_preserves_valid_opaque_unicode"
        status: pass
    human_judgment: false
  - id: D3
    description: "Tenant naming-key configuration is strict base64, requires at least 32 decoded bytes, supports explicit injection, and has no implicit fallback"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_identity.py#test_missing_naming_key_fails_closed"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_identity.py#test_naming_key_rejects_malformed_base64"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_identity.py#test_naming_key_rejects_short_decoded_values"
        status: pass
    human_judgment: false
  - id: D4
    description: "Returned identity fields, repr output, fingerprints, and validation diagnostics disclose neither the raw identifier nor naming-key bytes"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_identity.py#test_identity_object_has_only_pseudonymous_fields"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_identity.py#test_identity_repr_does_not_expose_raw_identifier"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_identity.py#test_validation_diagnostic_does_not_expose_raw_identifier"
        status: pass
    human_judgment: false

# Metrics
duration: 8min
completed: 2026-07-15
status: complete
---

# Phase 05 Plan 01: Exact Opaque Tenant Database Identity Summary

**Exact Unicode tenant identifiers now derive full domain-separated HMAC-SHA-256 ArcadeDB names under an explicitly supplied key, with strict fail-closed validation and pseudonymous-only metadata.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-15T09:59:22Z
- **Completed:** 2026-07-15T10:07:28Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Established the irreversible `agentmem_t_v1_<64 lowercase hex>` naming contract from the exact UTF-8 identifier bytes and a dedicated HMAC key.
- Added centralized validation that rejects unsafe identities without transforming accepted Unicode, including explicit coverage for format, private-use, unassigned, and combining code points.
- Added strict configuration loading and pseudonymous key fingerprinting with no fallback key or raw-identity retention.
- Proved the contract through 40 focused tests plus the 544-test repository suite.

## Task Commits

Each TDD gate was committed atomically:

1. **Task 1 (RED): Specify the exact tenant identity and naming contract** - `eeb55dd` (test)
2. **Task 2 (GREEN): Implement strict validation, keyed naming, and safe fingerprints** - `b122dc9` (feat)

No REFACTOR commit was needed; the GREEN implementation is already a focused 87-line standard-library module with no duplication or unnecessary abstraction.

## Files Created/Modified

- `src/turing_agentmemory_mcp/tenant_identity.py` - Exact identifier validation, strict naming-key loading, key fingerprinting, and opaque tenant database identity derivation.
- `tests/test_tenant_identity.py` - Known-vector, adversarial Unicode, configuration failure, immutability, and leakage coverage.

## Decisions Made

- Used constant-time byte comparison for the validation-only `strip()` equivalence check, so surrounding whitespace is rejected while the original accepted string is returned unchanged.
- Used a separate fingerprint domain from the database-name HMAC domain to prevent cross-purpose cryptographic material reuse.
- Kept the identity value object intentionally small and frozen; it contains no field capable of retaining the raw identifier or key.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- On this Windows checkout, the tracked `scripts/check-file-size.sh` contains CRLF line endings, so direct Git Bash execution stops at `set -euo pipefail` with `pipefail\r: invalid option name`. This predates the plan and was not modified. The same tracked script normalized in-memory to LF passed, and an independent PowerShell scan confirmed every tracked Python file is at or below 600 lines; `tenant_identity.py` is 87 lines.

## Verification Results

- `python -m pytest tests/test_tenant_identity.py -q`: **40 passed**.
- `python -m pytest -p no:cacheprovider -q`: **544 passed, 9 skipped** (the existing local integration/GPU skip policy; no new skips).
- `python -m ruff check src tests scripts`: **All checks passed**.
- `python -m ruff format --check src tests scripts`: **140 files already formatted**.
- Normalized-LF execution of `scripts/check-file-size.sh`: **all tracked `*.py` files within the 600-LOC cap**.
- Independent PowerShell 600-LOC scan: **PASS**.
- `docker compose config --quiet`: **exit 0**.
- Identifier-transformation grep (`strip\\(\\).*return|casefold|normalize`): **no matches**.
- Stub scan (`NotImplementedError|TODO|FIXME|placeholder|coming soon|not available`): **no matches**.

## TDD Gate Compliance

| Gate | Commit | Result |
|------|--------|--------|
| RED | `eeb55dd` | 39 tests failed on `NotImplementedError`; the interface-only dataclass test passed |
| GREEN | `b122dc9` | 40 focused tests passed; full repository gate passed |
| REFACTOR | Not needed | Minimal implementation remained green without a cleanup change |

## User Setup Required

None for this plan. Later router assembly must provide `AGENTMEMORY_TENANT_NAMING_KEY` as strict base64 encoding of at least 32 random bytes; this plan intentionally defines no implicit development value.

## Next Phase Readiness

- Plan 05-02 can bind the durable pseudonymous registry to `TENANT_NAMING_VERSION` and `tenant_key_fingerprint()` without storing a reversible tenant mapping.
- Plans 05-04 and 05-05 can use `TenantDatabaseIdentity.database_name` as the database, cache, and single-flight key.
- No implementation blocker remains.

---
*Phase: 05-per-tenant-arcadedb-isolation*
*Completed: 2026-07-15*

## Self-Check: PASSED

- FOUND: `.planning/phases/05-per-tenant-arcadedb-isolation/05-01-SUMMARY.md`
- FOUND: `src/turing_agentmemory_mcp/tenant_identity.py`
- FOUND: `tests/test_tenant_identity.py`
- FOUND: `eeb55dd` (RED commit)
- FOUND: `b122dc9` (GREEN commit)
- VERIFIED ORDER: `eeb55dd` before `b122dc9`
