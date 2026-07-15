# Deferred Items

- **Pre-existing E2E entrypoint debt:** `python scripts/e2e_score.py --out e2e-results.json`
  cannot start because `src/turing_agentmemory_mcp/e2e_score.py` still imports the retired
  `turingdb` package. This predates 05-03 and is already identified in Phase 4 state as a
  benchmark/E2E caller follow-up; repairing the E2E harness is outside this query-scope plan.
