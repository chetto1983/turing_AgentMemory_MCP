# Phase 4 ArcadeDB E2E Capture (04-09 scope item D)

## What this is

`e2e-results.json` in this directory is a REAL, live capture of the deterministic
E2E score gate (`scripts/e2e_score.py` / `src/turing_agentmemory_mcp/e2e_score.py`)
run against the ArcadeDB-backed store (the direct-port target of this whole
phase), produced by actually executing the gate against a live
`arcadedata/arcadedb:26.7.1` container (the `arcadedb` compose service) on
2026-07-14. It is in the exact field shape as `baseline/03-turingdb/e2e-results.json`
(`check_count`, `checks`, `cleanup`, `score`, `score_gate`, `turingdb_version`,
`verdict`, plus two new fields: `backend`/`arcadedb_image`) so it is directly
diffable field-by-field.

**Result: `VALIDATED_10_10`, score 10.0, 19/19 checks passing** — every
deterministic MCP-tool-level scenario check (memory CRUD/search/lifecycle,
document ingest/search/reindex/delete, hybrid lexical-match explain, the
MemoryArena bucket sample, and a genuine ArcadeDB-container restart-durability
check) passes against the real ArcadeDB port.

## How it was captured (reproducible)

```bash
docker compose up -d arcadedb   # if not already running
python scripts/e2e_score.py --out baseline/04-arcadedb/e2e-results.json
```

(On this Windows dev host, `turingdb` has no wheel and isn't installed in the
project `.venv`, so `e2e_score.py`'s own `from turingdb import __version__`
import was satisfied via a `sys.modules["turingdb"]` stub for this one
capture run, matching the same stub convention `tests/conftest.py`/every
`test_*.py` file in this repo already uses on Windows. On a normal Linux
CI/Docker run — e.g. `docker compose run --rm e2e` once that service is wired
to reach `arcadedb` — `turingdb_version` below reflects the real installed
package version, not a stub string.)

## Scope of this capture vs. `baseline/03-turingdb`

**This is the CORRECTNESS-parity capture, not the retrieval-QUALITY-parity
capture.** `baseline/03-turingdb/e2e-results.json` was captured with
`E2E_USE_EXTERNAL_EMBED=1 E2E_USE_EXTERNAL_RERANK=1` against the REAL
GPU-backed `agentmemory-embed`/`agentmemory-rerank` sidecars (granite-embedding
+ bge-reranker). This capture used `e2e_score.py`'s own in-process
deterministic stub embed/rerank servers (`HashingEmbedder`/keyword-overlap
rerank) — the default mode when those two env vars are unset — because
standing up the GPU sidecars requires downloading several GB of pinned GGUF
model weights (`agentmemory-model-init`'s provisioning step), which was not
attempted in this session for time/bandwidth reasons, NOT because GPU is
unavailable (this host has an NVIDIA GPU visible to Docker, confirmed via
`nvidia-smi`).

This distinction matters and is called out explicitly, per CLAUDE.md's own
rule: **do not claim a benchmark win from one corpus, one run, or mismatched
provider configs.** The 10/10 result above validates that the ArcadeDB port's
tool surface, tenant scoping, hybrid lexical explain plumbing, idempotency,
and restart durability are ALL correct end-to-end — it does NOT claim
anything about retrieval quality/recall parity with the TuringDB baseline's
real embedding/rerank models, since the embed/rerank layer here is a
deterministic stub, not the real provider stack.

**To capture the GPU-backed, quality-comparable e2e-results.json** (what
Phase 6's actual meet-or-exceed gate should use), run:

```bash
docker compose up -d arcadedb agentmemory-model-init agentmemory-embed agentmemory-rerank
E2E_USE_EXTERNAL_EMBED=1 E2E_USE_EXTERNAL_RERANK=1 \
  EMBED_BASE_URL=http://127.0.0.1:<embed-port> RERANK_BASE_URL=http://127.0.0.1:<rerank-port> \
  python scripts/e2e_score.py --out baseline/04-arcadedb/e2e-results-gpu.json
```

(substituting the sidecars' actual published ports, or running the whole
thing through the `e2e` compose profile once it is pointed at `arcadedb` on
the compose network). Phase 6 "owns the pass/fail threshold" per this
phase's own scope framing — Phase 4's job is comparability, not the verdict.

## `real-document-benchmark.json` — NOT captured (documented, not fabricated)

`baseline/03-turingdb/real-document-benchmark.json` was produced by
`scripts/real_document_benchmark.py` against an EXTERNAL, uncommitted corpus
at `D:/tmp/baseline-corpus` (per `baseline/03-turingdb/BASELINE.md`). That
path does not exist on this host/session, so an ArcadeDB-backed equivalent
could not be captured here — attempting to fabricate one without the actual
corpus would violate the same CLAUDE.md rule above. The reproducible command
for whoever has that corpus (or an equivalent one, same file identities per
`corpus-manifest.json`) is:

```bash
python scripts/real_document_benchmark.py \
  --root <path-to-baseline-corpus> \
  --frozen-questions baseline/03-turingdb/frozen-questions.json \
  --out baseline/04-arcadedb/real-document-benchmark.json
```

Per the plan's own instruction: do NOT change fusion weights, the corpus, or
the frozen questions when this is eventually run — `git diff --stat
src/turing_agentmemory_mcp/retrieval_fusion.py baseline/03-turingdb/frozen-questions.json`
must show no changes, confirmed clean as of this capture.
