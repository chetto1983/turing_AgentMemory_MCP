# Release Checklist

Use this checklist before tagging a public release or submitting a Show HN.

## Repository

- [ ] Default branch contains the intended release commit.
- [ ] Worktree is clean and no `.env`, credentials, customer data, PDFs, or
  local benchmark artifacts are tracked unintentionally.
- [ ] `LICENSE`, `README.md`, `CHANGELOG.md`, `SECURITY.md`, `SUPPORT.md`, and
  `CONTRIBUTING.md` are current.
- [ ] Repository description, topics, and website fields are accurate.
- [ ] GitHub Issues and private vulnerability reporting are enabled.
- [ ] Release tag and package version agree.

## Verification

- [ ] Full `pytest` suite passes.
- [ ] Ruff passes for `src`, `tests`, and `scripts`.
- [ ] `docker compose config --quiet` passes.
- [ ] Images build from a clean checkout using cache only when available.
- [ ] Compose health reaches `ok` with document worker running.
- [ ] Tenant isolation tests pass.
- [ ] One real asynchronous document reaches `succeeded`.
- [ ] A scoped query returns cited content immediately after ingest.
- [ ] Successful staging directory is empty.
- [ ] Backup and isolated restore have been exercised for the release.

## Security

- [ ] Non-loopback deployment uses TLS and authentication.
- [ ] Principal-to-tenant mapping is enforced outside model control.
- [ ] Secrets are sourced from a secret manager or untracked local env.
- [ ] Dependency, image, and secret scans are reviewed.
- [ ] Pinned model revisions and checksums are documented.
- [ ] Upload limits and file-pipe roots are intentionally configured.
- [ ] Audit and retention settings match deployment policy.

## Claims

- [ ] Every performance number names corpus, provider identity, dimensions,
  date, method, and limitations.
- [ ] No Mem0 or competitor superiority claim is published without a matched,
  reproducible comparison.
- [ ] Pre-1.0 limitations are visible from the README.
- [ ] Screenshots and examples contain synthetic data only.

## Release

- [ ] Create a signed or annotated tag.
- [ ] Publish release notes from `CHANGELOG.md`.
- [ ] Attach provenance and SBOM for release images when distributed.
- [ ] Verify links from the public repository without maintainer credentials.
- [ ] Keep an operator available during the release window.
- [ ] Record rollback image tags and backup identifier.

## After Release

- [ ] Monitor health, queue failures, provider errors, and issue reports.
- [ ] Respond to technical questions with measured facts.
- [ ] Record confirmed regressions in the changelog and issue tracker.
- [ ] Do not solicit votes, comments, or coordinated engagement on Hacker News.
