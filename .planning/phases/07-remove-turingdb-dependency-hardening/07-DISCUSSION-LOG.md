# Phase 7: Remove TuringDB + Dependency Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-16
**Phase:** 7-Remove TuringDB + Dependency Hardening
**Areas discussed:** Cut depth & legacy code, App-state naming, Invariants & docs sweep, Dependency version-gates & cut proof

---

## Cut depth & legacy code

| Option | Description | Selected |
|--------|-------------|----------|
| Full purge | Delete what ArcadeDB obsoletes (repair-vector-index, superseded legacy benchmark/eval harnesses), drop turingdb_version, remove the sys.modules stub, sweep every import. | ✓ |
| Port, don't delete | Port the legacy benchmark/eval harnesses to ArcadeDB; only delete genuinely dead code. | |
| Minimal neutralize | Keep the legacy files but strip their turingdb imports. | |

**User's choice:** Full purge
**Notes:** Fix-on-touch caveat added — confirm actual supersession/non-use before deleting each legacy harness; never delete a still-wired path. `baseline/03-turingdb/` and `baseline/06-gate/` are historical artifacts and are KEPT.

---

## App-state naming

| Option | Description | Selected |
|--------|-------------|----------|
| Rename to neutral now | Rename TURINGDB_HOME→AGENTMEMORY_HOME, /turing→/app-state, delete dead TURINGDB_* connection vars. | |
| Keep transitional names | Leave /turing + TURINGDB_HOME as-is (per current CLAUDE.md). | |
| Delete dead vars only | Remove superseded connection vars, keep /turing + TURINGDB_HOME. | |
| **Other (free text)** | **"we call the repo BertoniAgentMemory"** | ✓ |

**User's choice:** Free-text — rename toward a **Bertoni** identity, not neutral.
**Notes:** Clarified in plain-text follow-up. Confirmed scope: the **full `turing → bertoni` package/product rebrand** is wanted but as its **own dedicated phase/task AFTER Phase 7's cut** (kept out of the irreversible removal). Phase 7 **adopts Bertoni-based app-state env/volume names now** for forward-consistency: `TURINGDB_HOME`→`BERTONI_HOME`, `/turing`→`/bertoni`, `turing-data`→`bertoni-data`, `TURINGDB_EMBED_DIMENSIONS`→`EMBED_DIMENSIONS`; delete the dead `TURINGDB_URL/GRAPH/*_INDEX` vars. User replied "confirm" to this structure.

---

## Invariants & docs sweep

| Option | Description | Selected |
|--------|-------------|----------|
| Full + new invariants | Rewrite both CLAUDE.md files' invariants (#2/#4/#5/#6/#1/#3) + codify new ArcadeDB-era invariants + sweep README/architecture/env/skills/CHANGELOG. | ✓ |
| Invariants only | Rewrite just the CLAUDE.md invariants per SC#2; leave broader docs for later. | |
| Minimal (SC#2 literal) | Only the exact invariant changes SC#2 names (#2/#4/#6). | |

**User's choice:** Full + new invariants
**Notes:** New invariants to codify: MVCC-503 retry via run_in_transaction, native vector+Lucene ACID-with-graph, per-tenant DB + TenantBinding.

---

## Dependency version-gates & cut proof

| Option | Description | Selected |
|--------|-------------|----------|
| pytest smoke + no-import guard | DEP-01/02 as pytest version-range + API smoke; a no-`import turingdb` guard test; removal proven by full green suite + docker compose config. | ✓ |
| CI job / scripts checker | Version-gates as a scripts/ checker wired into CI/pre-push. | |
| You decide | Planner's discretion within DEP-01/02 intent + a no-turingdb guard. | |

**User's choice:** pytest smoke + no-import guard
**Notes:** Both compat tests under the no-skip-as-green tier. Entry is already hard-gated by gate_guard.py (Phase 6 D-10) — consumed, not rebuilt.

---

## Claude's Discretion

- Exact set of legacy harnesses to delete vs. keep (by actual usage/supersession).
- Precise new Bertoni env-var names + default paths + whether a compose migration note is needed.
- Exact wording of the rewritten/added invariants.
- Concrete shape of the compat-smoke + no-import guard tests (must fail closed).

## Deferred Ideas

- Full `turing → bertoni` package/product rebrand → its own dedicated phase after Phase 7 (add a ROADMAP phase).
- GLiNER GPU sidecar (ingestion perf) — its own concern; not blocking (spike 003 evidence).
- Document-GraphRAG build — gated on a new multi-hop eval (spike 001-003 verdict).
- Fix-on-touch gaps from the spike, already mapped: whole-doc GLiNER→HTTP 400 (TEST-08, Phase 9); type-keyed entity fragmentation (TEST-03, Phase 11).
