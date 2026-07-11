# Contributing

Contributions are welcome when they preserve tenant isolation, durability, and
evidence-bearing retrieval.

## Before You Start

Open an issue for large behavior changes. Describe the user problem, expected
contract, security impact, and validation plan. Small fixes can go directly to
a pull request.

Never include real API keys, customer data, private documents, benchmark gold
answers, or local `.env` files.

## Development Setup

```powershell
git clone https://github.com/chetto1983/turing_AgentMemory_MCP.git
Set-Location turing_AgentMemory_MCP
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check src tests scripts
```

Docker integration requires Docker Compose. The default model sidecars also
require an NVIDIA GPU visible to Docker.

## Change Rules

1. Keep every operation explicitly scoped by `user_identifier`.
2. Treat TuringDB as canonical and local indexes as recoverable projections.
3. Use stable IDs and structured parsers instead of ad hoc text rewriting.
4. Preserve idempotency and restart recovery for writes and jobs.
5. Keep retrieved content untrusted across the agent boundary.
6. Add tests before or with behavior changes.
7. Update public docs and `CHANGELOG.md` when contracts change.
8. Avoid unrelated refactors and generated metadata churn.

## Tests

Run the narrowest affected tests while developing, then run the full gate:

```powershell
python -m pytest -p no:cacheprovider -q
python -m ruff check src tests scripts
docker compose config --quiet
```

For document changes, verify a real file through MCP:

- request returns an asynchronous job;
- job reaches a truthful terminal state;
- canonical chunks exist;
- a tenant- and document-scoped search returns cited text;
- staged bytes are removed after success.

Do not report a benchmark win from one corpus, one run, or unmatched provider
configurations.

## Pull Requests

Keep pull requests focused. Include:

- the problem and behavior change;
- security and tenant-isolation impact;
- tests run and their exact result;
- migration or rollback steps;
- measured performance impact when relevant;
- documentation changed.

Maintainers may request a smaller change when review risk is too broad.

## Commit Messages

Use an imperative conventional prefix where practical:

```text
feat: add durable document jobs
fix: submit dependent graph batches
docs: publish operator runbook
test: cover stale lease recovery
```

## License

By contributing, you agree that your contribution is licensed under the
repository's MIT License.
