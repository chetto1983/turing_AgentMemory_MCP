# Performance

These measurements validate one real asynchronous document path. They are not
an SLA and are not a comparison with another memory product.

## Method

On 2026-07-11, a fresh MCP client called the actual remote MCP tools:

1. Hash the host PDF.
2. Call `document_upload_begin`.
3. Send ordered 512 KiB base64 chunks with `document_upload_chunk`.
4. Call `document_upload_commit` and record time to `queued`.
5. Poll `document_ingest_status` every 10 seconds.
6. After `succeeded`, call `document_search` immediately without restarting MCP.

The stack used ArcadeDB locally, PDFium page extraction, 768-dimensional
embeddings, and the provider identities reported by runtime health:
`qwen/qwen3-embedding-4b` for embedding and `cohere/rerank-4-pro` for reranking.
Network and provider conditions are part of these observations. Host CPU and RAM
were not captured, so the results must not be generalized across machines.

## Results

| Document | Bytes | PDF pages | Text pages | Chunks | Time to queued | Indexing stage observed | Time to succeeded | Search |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| G220 operating instructions | 30,376,574 | 830 | 828 | 841 | 3.737 s | 23.911 s | 114.174 s | 3 cited hits |
| Italian Constitution and Senate Rules | 3,386,217 | 506 | 504 | 504 | 1.021 s | 11.050 s | 41.132 s | 3 cited hits |

The G220 search returned page-aware chunks including `chunk=2`, `chunk=50`,
and `chunk=256`. The Italian query about the Constitution's fundamental
principles returned `chunk=10` first, containing page 12 and Articles 1-3.

## Interpretation

- Caller-visible request latency is the hash, MCP transfer, integrity check,
  durable copy, and queue write. Conversion and embedding do not block the tool
  response.
- Document size alone does not predict ingest duration. Page count, extracted
  text, chunk count, provider latency, graph payloads, and vector load all
  contribute.
- Stage timestamps are coarse because status was sampled every 10 seconds.
- A `succeeded` job was accepted only after a cited search returned real chunks.
- The test discovered and fixed a transaction bug where a document node could
  exist without dependent chunk batches. The final numbers use submitted graph
  batches and real searchable chunks.

## Reproduce

Use a dedicated tenant and stable document ID. Record provider identity and
dimensions from `/health`, then call MCP rather than internal store methods.
Success criteria are:

1. commit returns `queued` promptly;
2. state advances through `converting` and `indexing`;
3. terminal state is `succeeded` on the first attempt;
4. `result.chunk_count` is positive;
5. a tenant- and document-scoped query returns cited text;
6. the staging directory is empty after success.

For comparative benchmarks, fix corpus, provider revisions, dimensions,
hardware, concurrency, warmup, and scoring protocol. Publish failures and
variance, not only the best run.
