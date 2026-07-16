---
phase: quick-260716-lel
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/turing_agentmemory_mcp/document_processing.py
  - tests/test_document_processing.py
autonomous: true
requirements:
  - QUICK-260716-lel-strip-html-wikipedia-nav-boilerplate
user_setup: []

must_haves:
  truths:
    - "Converting an .html/.htm file strips Wikipedia/site navigation chrome before it becomes markdown, so nav/sidebar/footer boilerplate never reaches chunks, embeddings, or retrieval."
    - "The ML Wikipedia article text survives cleaning (article body preserved), while boilerplate terms are gone."
    - "PDF/pdfium and all non-HTML MarkItDown paths behave exactly as before (no regression)."
    - "The converter override keyword still works; HTML cleaning applies to real HTML files and the active converter still performs the markdown step."
  artifacts:
    - "src/turing_agentmemory_mcp/document_processing.py with a private _extract_html_main_content helper and an HTML branch in convert_document_to_markdown."
    - "tests/test_document_processing.py with a committed synthetic-HTML unit test and a corpus-guarded real-file E2E test."
  key_links:
    - "convert_document_to_markdown routes .html/.htm through cleaning -> active MarkItDown convert_local -> ConvertedDocument with a boilerplate-stripped metadata marker."
    - "BeautifulSoup (bs4, already a MarkItDown transitive dep) parses the HTML and prunes chrome BEFORE MarkItDown converts."
---

<objective>
Strip HTML/Wikipedia navigation boilerplate during document conversion. Today
`convert_document_to_markdown()` hands the ENTIRE HTML page to MarkItDown, so
nav/sidebar/footer chrome ("ultime modifiche", "index.php", editsection "modifica"
links, message boxes) becomes markdown -> chunks -> embeddings -> searchable noise
that pollutes retrieval for every HTML document (found during the doc-GraphRAG spike,
.planning/spikes/003).

Add an HTML branch that extracts the main content with BeautifulSoup BEFORE calling
MarkItDown, then feeds only the cleaned subtree to the existing convert_local pipeline.

Purpose: keep HTML-sourced chunks and embeddings free of navigation boilerplate so
tenant-scoped retrieval stays clean.
Output: an edited `document_processing.py` (new helper + HTML branch) and an extended
`tests/test_document_processing.py` (committed synthetic regression test + corpus-guarded
real-file E2E test).

Scope guard: touch ONLY `src/turing_agentmemory_mcp/document_processing.py` and
`tests/test_document_processing.py`. Do NOT add any dependency to pyproject.toml — bs4 is
already a MarkItDown transitive dependency (verified: bs4 4.15.0 importable in this venv).
Do NOT touch the PDF/pdfium path or any non-HTML MarkItDown path.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
</execution_context>

<context>
@.planning/STATE.md
@src/turing_agentmemory_mcp/document_processing.py
@tests/test_document_processing.py

# Validated facts from planning-time experiments against the real corpus file
# D:/tmp/baseline-corpus/apprendimento_automatico_wikipedia.html plus en.wikipedia
# (Support_vector_machine), it.wikipedia (Rete_neurale_artificiale), and a real
# e-commerce <main> page (sacchi.it product) — all run through this exact strategy:
#
#   1. bs4 4.15.0 is importable (transitive MarkItDown dep). Use the stdlib
#      "html.parser" (NOT lxml — avoids a new dependency).
#   2. Landmark preference #mw-content-text -> <main> -> <article> extracts the real
#      content region on both MediaWiki and generic sites (e.g. the e-commerce page cut
#      11.9KB -> 2.7KB while preserving the product name/codes).
#   3. Decomposing the boilerplate selector set (below) INSIDE the chosen root is what
#      removes the "index.php" that survives inside #mw-content-text — it lives in
#      .mw-editsection "modifica" anchors AND in .ambox/.metadata/.noprint message-box
#      links. Without .ambox/.metadata/.noprint the corpus assertion for "index.php"
#      absence FAILS. These three selectors are load-bearing, not cosmetic.
#   4. MarkItDown exposes both convert_local(path) and convert_stream(stream). This plan
#      uses convert_local on a temp .html file written from the cleaned HTML, so the
#      active converter (default OR a caller-provided converter that only implements
#      convert_local, as the test fakes do) drives the markdown step unchanged.
#   5. Reading the file as UTF-8 text, cleaning, writing the fragment back as UTF-8, and
#      running convert_local preserves Italian accents (e.g. "Generalità") with zero
#      U+FFFD replacement chars. Verified end-to-end.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add HTML main-content cleaning branch to convert_document_to_markdown</name>
  <files>src/turing_agentmemory_mcp/document_processing.py</files>
  <action>
Add an HTML-cleaning path to `convert_document_to_markdown` and factor the bs4 work into a
small private helper, following the module's existing lazy-import and private-helper style
(mirror `_convert_pdfium` / `_markitdown_converter`).

1. Module-level constant (near the top, after imports) holding the boilerplate CSS selector
   group used to prune chrome. Use EXACTLY this selector set (validated against the real
   corpus; the last three are load-bearing for removing message-box index.php links):
   nav, header, footer, aside, script, style, .navbox, .catlinks, #mw-navigation,
   .mw-jump-link, a `[class*="vector-"]` attribute-substring selector (CSS class wildcards
   are not supported, so use the attribute-substring form), #footer, #siteNotice,
   .printfooter, .mw-editsection, .ambox, .metadata, .noprint

2. Private helper `_extract_html_main_content(html: str) -> str`:
   - Lazily `from bs4 import BeautifulSoup` INSIDE the helper (same lazy pattern as the
     markitdown/pypdfium2 imports). If the import raises ImportError, re-raise as a clear
     error stating bs4 is required and is normally provided transitively by MarkItDown —
     do NOT add bs4 to pyproject.toml (per the task spec: stop and report, never add a dep).
   - Parse with the stdlib parser: `BeautifulSoup(html, "html.parser")` (NOT lxml).
   - Choose the working root by landmark preference: first `select_one("#mw-content-text")`,
     else `find("main")`, else `find("article")`, else the whole parsed document.
   - Decompose every element matching the boilerplate selector group WITHIN the chosen root
     (`for el in root.select(SELECTOR): el.decompose()`). Applying this even when a landmark
     was found is intentional and required — it strips editsection/message-box chrome that
     lives INSIDE #mw-content-text.
   - Return `str(root)` (the serialized cleaned subtree/document).

3. Private helper `_convert_html_cleaned(source, converter)` (keeps the main function
   readable and every helper well under the 600-LOC cap):
   - Read the file as UTF-8 text: `source.read_text(encoding="utf-8", errors="replace")`.
   - `cleaned = _extract_html_main_content(html)`.
   - Resolve the active converter: `converter if converter is not None else _markitdown_converter()`.
     A caller-provided converter is still used for the markdown step (satisfies the override
     contract; the test fakes implement convert_local).
   - Write `cleaned` to a temp file with a `.html` suffix and run the active converter's
     `convert_local` on it, so the existing convert_local markdown pipeline is preserved.
     Use `tempfile.NamedTemporaryFile("w", suffix=".html", encoding="utf-8", delete=False)`,
     write, close, convert, and `Path(tmp.name).unlink(missing_ok=True)` in a `finally`
     (delete=False + explicit unlink is the Windows-safe pattern — convert_local reopens the
     path, so our handle must be closed first).
   - Extract text the same way the existing markitdown path does:
     `str(getattr(result, "text_content", "") or getattr(result, "markdown", "") or "")`.
   - Reuse the existing empty-output guard: raise `ValueError(f"MarkItDown produced empty markdown for {source}")`
     when the stripped text is empty.
   - Return a `ConvertedDocument` whose metadata marks the cleaned path observably:
     converter set to "markitdown-html-cleaned", a `boilerplate_stripped: True` flag, plus
     the existing `source_filename` and `source_path` keys.

4. Wire the branch into `convert_document_to_markdown`: after the existing PDF fast-path
   block, add `if source.suffix.lower() in (".html", ".htm"): return _convert_html_cleaned(source, converter)`.
   HTML cleaning applies to real HTML files regardless of whether a converter was provided.
   Leave the PDF/pdfium block and the final generic markitdown.convert_local block UNCHANGED
   (they still handle .pdf, .docx, and every other suffix exactly as today).

Do a deep-refactor-on-touch pass on the file: keep it self-documenting, add a comment ONLY
where the "why" is non-obvious (e.g. why decompose runs inside a found landmark, why
delete=False). Do not churn unrelated code.
  </action>
  <verify>
    <automated>python -m ruff format --check src/turing_agentmemory_mcp/document_processing.py &amp;&amp; python -m ruff check src/turing_agentmemory_mcp/document_processing.py &amp;&amp; bash scripts/check-file-size.sh</automated>
  </verify>
  <done>
document_processing.py has `_extract_html_main_content` and an HTML branch that prunes
boilerplate before MarkItDown; PDF and generic paths untouched; ruff format --check, ruff
check, and check-file-size.sh all pass; no dependency added to pyproject.toml.
  </done>
</task>

<task type="auto">
  <name>Task 2: Add synthetic-HTML unit test + corpus-guarded real-file E2E test</name>
  <files>tests/test_document_processing.py</files>
  <action>
Extend the existing test module (do not remove or weaken the current tests — the docx/pdf
cases must keep passing, and they will: they exercise .docx/.pdf, not the new HTML branch).

Add TWO tests:

1. Committed, CI-runnable regression unit test (no external corpus). Build an inline
   synthetic HTML string containing a MediaWiki-shaped main region plus chrome, e.g. a
   `<div id="mw-content-text">` wrapping real body text (include the phrases the article
   assertions use, such as "apprendimento automatico" and "clustering"), a
   `<nav>ultime modifiche</nav>`, and a `<footer>` with an `index.php` link. Write it to a
   `tmp_path / "page.html"` file (pytest tmp_path fixture) and call
   `convert_document_to_markdown(that_file)` with NO converter (real MarkItDown must run so
   stripping is actually exercised — a fake converter would echo fixed text and prove
   nothing). Assert, case-insensitively, that "ultime modifiche" and "index.php" are ABSENT
   from `result.text` and that the body content survives. Also assert
   `result.metadata["converter"] == "markitdown-html-cleaned"` and
   `result.metadata["boilerplate_stripped"] is True`.

2. Real-file E2E test against the corpus, guarded so CI without the corpus skips cleanly.
   Define a module-level path constant
   `Path("D:/tmp/baseline-corpus/apprendimento_automatico_wikipedia.html")` and decorate the
   test with `@pytest.mark.skipif(not <that path>.exists(), reason="baseline corpus HTML not present")`.
   The test runs `convert_document_to_markdown(<corpus path>)` (no converter) and asserts,
   case-insensitively on the lowercased result text: "ultime modifiche" NOT in text,
   "index.php" NOT in text, "apprendimento automatico" IN text, and "clustering" IN text.
   (All four were confirmed at planning time against this exact file with this exact
   strategy.) On this dev host the file exists, so this test MUST run and pass here.

Follow the file's existing style (plain pytest functions, tmp_path fixture, top-level
imports). Keep the test file under the 600-LOC cap.
  </action>
  <verify>
    <automated>python -m pytest tests/test_document_processing.py -q</automated>
  </verify>
  <done>
Both new tests plus all pre-existing tests in test_document_processing.py pass. The corpus
E2E test actually executes (not skipped) on this dev host and confirms the ML article text
survives while "ultime modifiche"/"index.php" are gone. The synthetic unit test is
CI-safe (skip-free) and asserts the boilerplate-stripped metadata marker.
  </done>
</task>

</tasks>

<verification>
Run the project's post-edit / pre-commit gate in order after both tasks:

- `python -m ruff format --check src tests scripts`
- `python -m ruff check src tests scripts`
- `bash scripts/check-file-size.sh`
- `python -m pytest tests/test_document_processing.py -q` (narrowest), then `python -m pytest -q`

Definition of Done for this document-processing change (per CLAUDE.md): a real HTML file
flows through `convert_document_to_markdown` and the resulting text is free of nav/footer
boilerplate while the article body survives — proven by the corpus E2E test running green on
this host. No new dependency was introduced (bs4 is transitive). Only
`document_processing.py` and `tests/test_document_processing.py` changed.
</verification>

<success_criteria>
- .html/.htm conversion strips Wikipedia/site chrome (nav, sidebar, footer, editsection and
  message-box links) before MarkItDown, via a bs4 landmark-preference + boilerplate-decompose
  helper.
- Corpus E2E test: "ultime modifiche" and "index.php" absent; "apprendimento automatico" and
  "clustering" present.
- Synthetic unit test committed and CI-runnable (skip-free), asserting stripping and the
  `markitdown-html-cleaned` / `boilerplate_stripped` metadata marker.
- PDF/pdfium and all non-HTML paths unchanged; converter override still works.
- No pyproject.toml dependency added.
- Full gate green (ruff format --check, ruff check, check-file-size.sh, pytest).
- Only two files touched.
</success_criteria>

<output>
Create `.planning/quick/260716-lel-strip-html-wikipedia-navigation-boilerpl/260716-lel-SUMMARY.md` when done.
</output>
