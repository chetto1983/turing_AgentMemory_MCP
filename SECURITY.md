# Security Policy

## Supported Versions

This project is pre-1.0. Security fixes are applied to the latest release and
the default branch. Older commits and local forks are not maintained.

## Report a Vulnerability

Do not open a public issue with exploit details, credentials, user identifiers,
memory text, documents, or volume contents.

Use GitHub private vulnerability reporting for this repository when available:

<https://github.com/chetto1983/turing_AgentMemory_MCP/security/advisories/new>

If private reporting is unavailable, contact the maintainer through the GitHub
profile before sending sensitive details. Include:

- affected commit or release;
- deployment topology;
- reproduction steps using synthetic data;
- impact and tenant-boundary implications;
- suggested mitigation if known.

Expect an acknowledgement within five business days. Timelines for validation,
fix, disclosure, and release depend on severity and reproducibility. Please
allow coordinated disclosure before publishing details.

## Scope

High-priority reports include:

- cross-tenant reads or writes;
- authentication or scope bypass;
- arbitrary host-file access through the file pipe;
- path traversal or upload integrity bypass;
- remote code execution in file conversion;
- credential or memory text leakage in logs and errors;
- durable job state manipulation across tenants;
- unsafe restore or repair behavior that destroys canonical data.

Provider outages, model quality disagreements, and documented pre-1.0 limits
are not vulnerabilities unless they create a security boundary failure.

See [docs/security.md](docs/security.md) for the deployment threat model.
