# Hacker News Launch Notes

This is an internal fact sheet and launch checklist. It is deliberately not a
paste-ready Hacker News comment.

Hacker News asks people not to post generated or AI-edited comments. The
maintainer must write the submission discussion in their own voice. See the
[HN guidelines](https://news.ycombinator.com/newsguidelines.html) and
[Show HN rules](https://news.ycombinator.com/showhn.html).

HN also currently restricts some Show HN submissions from accounts that are not
yet familiar with the community. Check the current
[Show HN notice](https://news.ycombinator.com/showlim) before scheduling.

## Launch Gate

Post only when:

- the public repository is on the tested commit;
- a new user can run the project without signup or email collection;
- the default branch contains the operator and security docs;
- the maintainer has personally run the quick start from a clean checkout;
- the maintainer can stay present to answer technical questions;
- no one has been asked to upvote, submit, or comment.

## Candidate Submission

Use the original GitHub repository as the URL:

<https://github.com/chetto1983/turing_AgentMemory_MCP>

Factual title candidate:

```text
Show HN: Turing AgentMemory MCP - tenant-scoped memory and cited document retrieval
```

The maintainer should adjust the title only if it does not match the released
artifact. Avoid superlatives, competitor claims, gratuitous numbers, all caps,
and launch language.

## Facts the Maintainer Can Explain

- The project exposes persistent memory and cited document retrieval through
  MCP.
- TuringDB holds canonical graph records and tenant-specific vector indexes.
- Retrieval combines dense, lexical, entity, fact, graph, community, and rerank
  signals.
- File ingestion returns a durable asynchronous job instead of blocking on PDF
  conversion and embedding.
- Host-local files are streamed through an allowlisted MCP proxy; the container
  does not need a host filesystem mount.
- PDFium preserves page markers for born-digital PDFs. MarkItDown handles other
  supported formats.
- The default Compose stack can run embedding and rerank locally on CUDA; the
  provider clients can also target compatible remote services.
- The project is MIT licensed and pre-1.0.

## Verified Demo Facts

Use these only with the method and limits in `docs/performance.md`:

- A 30,376,574-byte, 830-page manual returned `queued` in 3.737 seconds and
  reached `succeeded` with 841 searchable chunks in 114.174 seconds.
- A 3,386,217-byte, 506-page Italian legal document returned `queued` in 1.021
  seconds and reached `succeeded` with 504 searchable chunks in 41.132 seconds.
- Both tests searched immediately after success and returned three cited hits.
- These are observations from one provider configuration, not SLAs and not a
  comparison with Mem0.

## First Comment Writing Prompts

The maintainer should write a short comment from personal experience. Answer
these prompts in their own words:

1. What problem kept recurring while building agents with long-lived state?
2. Why use TuringDB and MCP instead of embedding memory inside one agent
   framework?
3. What failed during the real 830-page ingest, and what did that reveal about
   truthful success states?
4. Which trade-offs remain, especially tenant authorization, OCR, single-worker
   execution, and provider dependence?
5. What specific feedback would help next: API ergonomics, retrieval quality,
   operations, or deployment portability?

Do not paste generated prose into the HN thread. Do not ask for votes or generic
support. Ask technical questions and answer criticism with concrete evidence.

## Likely Questions to Prepare For

- How does this differ from Mem0, Zep, or a conventional RAG service?
- Is `user_identifier` authorization or only a scope key?
- What happens when MCP restarts during an ingest?
- Why SQLite for jobs and FTS if TuringDB is canonical?
- Can it run without an NVIDIA GPU?
- Does it OCR scanned PDFs or understand tables and charts?
- How are embedding model changes migrated?
- Can a document prompt-inject the consuming agent?
- What is deleted by `memory_delete` and `document_delete`?
- Which benchmark results are independently reproducible?

The public docs already contain direct answers. If a question exposes a gap,
acknowledge it and open an issue instead of improvising a claim.

## Launch-Day Conduct

- Submit once. Do not delete and repost because engagement is low.
- Do not coordinate votes or comments.
- Stay available and respond as a person, not through generated comments.
- Lead with implementation details and trade-offs.
- Link directly to relevant source or docs when answering.
- Record bugs and follow up after the thread rather than debating evidence.
