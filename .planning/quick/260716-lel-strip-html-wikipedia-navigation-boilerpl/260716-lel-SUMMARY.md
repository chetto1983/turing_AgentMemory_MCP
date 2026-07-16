---
phase: quick-260716-lel
plan: 01
subsystem: document-processing
tags: [bs4, beautifulsoup, markitdown, html, wikipedia, boilerplate-stripping]

# Dependency graph
requires:
  - phase: spike-003
    provides: identified the HTML nav boilerplate pollution problem (doc-GraphRAG spike)
provides:
  - HTML/.htm branch in convert_document_to_markdown that strips nav/sidebar/footer/editsection/message-box chrome via BeautifulSoup before MarkItDown converts
  - "_extract_html_main_content and _convert_html_cleaned private helpers"
  - markitdown-html-cleaned / boilerplate_stripped metadata marker for observability
affects: [document ingestion, HTML/Wikipedia document search retrieval quality]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Landmark-preference content extraction: #mw-content-text -> <main> -> <article> -> whole doc, then decompose boilerplate selectors WITHIN the chosen root (chrome can live inside a landmark too)"
    - "bs4 stdlib html.parser (no lxml) reused as a MarkItDown transitive dependency, not a new pyproject dependency"

key-files:
  created: []
  modified:
    - src/turing_agentmemory_mcp/document_processing.py
    - tests/test_document_processing.py

key-decisions:
  - "No new dependency added — bs4 4.15.0 confirmed importable as a MarkItDown transitive dep"
  - "Cleaned HTML is written to a temp .html file (delete=False + explicit unlink) and run through the existing convert_local pipeline, so the caller-provided-converter override contract is preserved unchanged"
  - "Boilerplate decompose runs even when a landmark (#mw-content-text) was found, because editsection/message-box chrome lives inside it on MediaWiki pages"

patterns-established:
  - "HTML documents get a dedicated conversion branch in convert_document_to_markdown, parallel to the existing PDF/pdfium fast-path branch, both preceding the generic markitdown.convert_local fallback"

requirements-completed:
  - QUICK-260716-lel-strip-html-wikipedia-nav-boilerplate

coverage:
  - id: D1
    description: "Converting an .html/.htm file strips Wikipedia/site navigation chrome (nav, editsection, message-box/footer links) before it becomes markdown, so boilerplate never reaches chunks/embeddings/retrieval, while the article body survives"
    requirement: QUICK-260716-lel-strip-html-wikipedia-nav-boilerplate
    verification:
      - kind: unit
        ref: "tests/test_document_processing.py#test_convert_html_strips_wikipedia_nav_boilerplate"
        status: pass
      - kind: e2e
        ref: "tests/test_document_processing.py#test_convert_html_strips_boilerplate_from_real_corpus_file"
        status: pass
    human_judgment: false
  - id: D2
    description: "PDF/pdfium and all non-HTML MarkItDown paths behave exactly as before (no regression); converter override still works"
    verification:
      - kind: unit
        ref: "tests/test_document_processing.py#test_convert_pdf_uses_pagewise_pdfium_fast_path"
        status: pass
      - kind: unit
        ref: "tests/test_document_processing.py#test_convert_document_to_markdown_uses_markitdown_convert_local"
        status: pass
      - kind: unit
        ref: "tests/test_document_processing.py#test_convert_document_to_markdown_rejects_empty_output"
        status: pass
    human_judgment: false

# Metrics
duration: 18min
completed: 2026-07-16
status: complete
---

# Phase quick-260716-lel: Strip HTML/Wikipedia Navigation Boilerplate Summary

**HTML/.htm documents now route through a BeautifulSoup landmark-extraction + boilerplate-decompose pass before MarkItDown, cutting Wikipedia nav/editsection/message-box chrome out of chunks and embeddings.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-07-16T00:00:00Z (approx)
- **Completed:** 2026-07-16
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- Added `_extract_html_main_content` (bs4 `html.parser`, landmark preference `#mw-content-text` -> `<main>` -> `<article>` -> whole doc, decompose boilerplate selector set inside the chosen root) and `_convert_html_cleaned` (temp-file + `convert_local` bridge) to `document_processing.py`.
- Wired an `.html`/`.htm` branch into `convert_document_to_markdown`, ahead of the generic MarkItDown fallback and unrelated to the PDF/pdfium branch.
- Added a committed synthetic-HTML regression test (real MarkItDown, no fake) asserting boilerplate absence, article-body survival, and the `markitdown-html-cleaned` / `boilerplate_stripped` metadata marker.
- Added a corpus-guarded real-file E2E test against `D:/tmp/baseline-corpus/apprendimento_automatico_wikipedia.html`; it ran (not skipped) on this dev host and passed.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add HTML main-content cleaning branch to convert_document_to_markdown** - `764302a` (feat)
2. **Task 2: Add synthetic-HTML unit test + corpus-guarded real-file E2E test** - `05998d4` (test)

**Plan metadata:** commit handled by orchestrator (docs artifacts excluded from this executor's commits per constraints)

## Files Created/Modified
- `src/turing_agentmemory_mcp/document_processing.py` - Added `_HTML_BOILERPLATE_SELECTOR` constant, `_extract_html_main_content`, `_convert_html_cleaned`, and the `.html`/`.htm` branch in `convert_document_to_markdown`
- `tests/test_document_processing.py` - Added `test_convert_html_strips_wikipedia_nav_boilerplate` (synthetic, CI-safe) and `test_convert_html_strips_boilerplate_from_real_corpus_file` (corpus-guarded E2E)

## Decisions Made
- No new dependency added to `pyproject.toml`; bs4 4.15.0 confirmed importable in-venv as a MarkItDown transitive dependency.
- Used the exact validated boilerplate selector set from planning-time experiments (`.mw-editsection`, `.ambox`, `.metadata`, `.noprint` are load-bearing for removing `index.php` message-box links that survive inside `#mw-content-text`).
- Preserved the existing converter-override contract by running the caller-provided (or default) MarkItDown converter's `convert_local` on a cleaned temp `.html` file, using `delete=False` + explicit `unlink` (Windows-safe pattern: `convert_local` reopens the path so our handle must be closed first).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- HTML document ingestion now produces cleaner, boilerplate-free chunks for embeddings and retrieval.
- No blockers; this quick task's scope (only `document_processing.py` + `tests/test_document_processing.py`) was fully self-contained.

---
*Phase: quick-260716-lel*
*Completed: 2026-07-16*

## Self-Check: PASSED

- FOUND: src/turing_agentmemory_mcp/document_processing.py
- FOUND: tests/test_document_processing.py
- FOUND: 764302a (feat commit)
- FOUND: 05998d4 (test commit)
