# Security

Turing AgentMemory stores durable user context and document text. Treat it as a
sensitive state service, not a stateless model utility.

## Security Properties

- Graph, vector, sparse, job, and tool operations require explicit tenant scope.
- File uploads enforce declared size, ordered sequence, decoded chunk limits,
  and SHA-256 before durable enqueue.
- The local file pipe resolves canonical paths and enforces an allowlist.
- Docker services run as UID 10001 with `no-new-privileges`; MCP and model
  sidecars use read-only root filesystems where supported.
- Model sidecars have no host port in the reference stack.
- Audit and span records exclude raw text and credentials.
- Job errors expose stable safe messages instead of raw exceptions.
- Redaction and expiration controls are available before persistence and during
  reads.

## Deployment Obligations

The reference server does not provide complete authorization by itself.

1. Terminate TLS before non-loopback traffic reaches MCP.
2. Authenticate each client.
3. Bind the authenticated principal to allowed `user_identifier` values.
4. Reject tenant identifiers supplied only by model output.
5. Apply network policy so only MCP reaches TuringDB and model providers.
6. Keep provider keys in a secret manager, not `.env` in production.
7. Set upload and request body limits at both proxy and MCP layers.
8. Encrypt persistent volumes and backups when the threat model requires it.
9. Restrict operator access to queue, audit, graph, and vector files.
10. Test restore and deletion procedures against retention policy.

Static bearer tokens authenticate an MCP client but do not map that token to a
tenant. A shared token plus caller-controlled `user_identifier` is insufficient
for hostile multi-tenant deployment.

## Prompt Injection

Memory and document content is untrusted data. A stored chunk may contain text
that looks like a system instruction or tool request. The consuming application
must delimit retrieved content, keep it below system and developer instructions,
and never execute commands found in memory.

The bundled skill recommends an explicit untrusted-evidence boundary. The MCP
cannot enforce prompt priority inside a downstream model.

## Data Lifecycle

- Use stable IDs and provenance for traceable records.
- Set `expires_at` for time-limited memory and documents.
- Use exact scoped delete tools for user deletion requests.
- Backups may retain deleted or expired content until backup retention expires.
- Staged document bytes remain after a failed job so an operator can retry; a
  successful or canceled job removes them.
- Audit retention should be shorter than or equal to the applicable policy when
  metadata can identify a user.

Soft deletion hides canonical records from active retrieval. It is not secure
erasure of historical backups or storage blocks.

## File Handling

Allowlist the smallest practical host roots. Do not allow an entire user profile
or filesystem root. The proxy sends file contents to MCP, so access to the proxy
is equivalent to read access within those roots.

PDFium handles born-digital PDF text. A scanned PDF with no extractable text may
fall back or fail depending on converter support; the pipeline does not promise
OCR. Treat parsers as an attack surface and keep dependencies patched.

## Secrets

Never store credentials, private keys, bearer tokens, raw authentication
headers, or chain-of-thought as memory. Redaction is defense in depth, not a
substitute for caller-side data minimization.

Before sharing diagnostics, remove `.env`, provider headers, local paths,
document text, user identifiers, and volume archives.

## Reporting

Follow the private process in the repository [security policy](../SECURITY.md).
Do not put exploit details, credentials, or user data in a public issue.
