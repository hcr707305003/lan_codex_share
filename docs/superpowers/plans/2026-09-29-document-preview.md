# Uploaded Document Preview Implementation Plan

> **For agentic workers:** Use executing-plans inline, task-by-task. User chose this branch; preserve existing upload changes.

**Goal:** Click a sent attachment's name to preview it in the existing right panel.

**Architecture:** DocumentStore persists bounded extracted text in its private record, with lazy extraction for old records. A protected preview endpoint returns text JSON or inline PDF. The current panel dispatches by reference type and guards stale requests.

**Tech Stack:** Python, SQLite, existing document extractor, vanilla JavaScript/CSS, pytest, Node test runner, Playwright CLI.

**Spec:** `docs/superpowers/specs/2026-09-29-document-preview-design.md`

## Global Constraints

- Current branch, local changes only; no push/release or live service operations.
- Preserve the existing upload implementation and private configuration.
- No additional dependency or Office conversion service; DOCX is extracted text, PDF is original bytes.
- Use existing extraction limits (30 seconds, one process, memory monitoring, text and file bounds).
- Keep preview text out of snapshots; authenticate and verify Session before resolving ID.

## Task 1: Store and HTTP preview

Files: `document_store.py`, `lan_web.py`, `tests/test_document_store.py`, `tests/test_document_web.py` under existing package/test directories.

Interface: `DocumentStore.preview(document_id, session_id)` returns JSON-compatible `{name, size, kind, content, warning}` for text documents. HTTP `GET /api/documents/<id>/preview?session_id=...` returns this JSON or PDF with inline disposition; existing download remains unchanged.

- [x] Add failing tests for cache/restart/legacy/missing/session/cleanup and HTTP preview/auth/inline PDF. Core assertion:
  ```python
  result = store.preview(docs[0]['id'], 's')
  assert result['content'] == '# Content'
  assert 'content' not in store.metadata('s', 'm')['documents'][0]
  ```
- [x] Run `.venv-desktop/Scripts/python.exe -m pytest tests/test_document_store.py tests/test_document_web.py -q` and confirm new assertions fail before implementation.
- [x] Persist `text` only in private document records; lazy old-record extraction outside SQLite transaction, update existing row only (never resurrect cancelled uploads). Resolve again before returning; enforce file bounds before extraction.
  ```python
  path, record = self.resolve(document_id, session_id)
  if 'text' not in record:
      record.update(extract_isolated(path))
  ```
- [x] Route preview separately from download; JSON for MD/TXT/DOCX, PDF bytes with `application/pdf` and `inline`, no-store/nosniff. Run focused tests until passing.

## Task 2: Attachment button and shared panel

Files: `lan_codex_share/web/app.js`, `style.css`, `tests/javascript/document-preview.test.cjs`.

Interface: upload reference `{documentId, sessionId, name, size}`; workspace reference retains `{path, line, column}`. `documentEndpoint(reference, preview=false)` builds session-bound endpoint. `openFilePreview` handles both.

- [x] Add failing Node tests for reference-specific endpoints/downloads, text safety, stale JSON completion after switching files/closing, and independent button/download semantics.
  ```javascript
  assert.equal(context.documentEndpoint({documentId: 'id', sessionId: 's'}, true), '/api/documents/id/preview?session_id=s');
  ```
- [x] Add optional preview callback to `documentCard`; render the name as a button for sent records, disabled when missing. Keep draft names as plain text and download outside the button.
- [x] Route panel requests by reference type. MD uses existing safe Markdown; TXT/DOCX append a plain-text `pre`; PDF uses existing object display plus an always-visible browser-support/download hint. Validate request generation after every await before DOM updates.
- [x] Closing clears current reference/body and invalidates requests; switching Session already closes the panel. Preserve focus return. Add visible filename button focus and bounded text styling.
- [x] Run `node --test tests/javascript/*.test.cjs` and `node --check lan_codex_share/web/app.js`.

## Task 3: Browser verification and documentation

Files: `README.md`, test-only fixtures as needed, this plan and spec status.

- [x] Start only the temporary fake-model preview fixture. Create synthetic MD/TXT/DOCX/PDF fixtures; upload through real UI and verify filename opens panel, refresh/reload, original download, close, desktop/mobile overflow and Word disclaimer. Use Playwright CLI; screenshots stay in ignored `output/playwright/`.
- [x] Check malicious markup remains inert (browser and unit tests) and old workspace preview still works (renderer/route regression tests); close isolated browser and temporary fixture afterward.
- [x] Document sent-file preview, limitations and unchanged pending-file behavior in README.
- [x] Run full Python/JavaScript suites, `git diff --check`; record actual results and manual source-service restart instruction. Keep implementation uncommitted for local testing (as agreed), no production archive.

## Review

All spec sections mapped to tasks above; no additional architecture or user choice required. UI skill focus-state guidance applies to the filename button; keep existing theme and panel geometry.

## Verification record

- Final full Python suite: 775 passed in 71.12 seconds; JavaScript: 44 passed; syntax and `git diff --check` passed. User must manually restart the source Share service and refresh the browser; existing release binaries are unchanged.
- Initial new Python tests: 8 failures before implementation, then 35 focused tests passed. Initial new JavaScript tests: 6 failures before implementation; final JS suite has 44 passing tests.
- Real browser: four formats uploaded, filename click, MD table/HTML inertness, DOCX body/table text, PDF visibly rendered, reload and refresh, download SHA-256 equality, 1280px desktop and 375px narrow layout verified. Closing restores the header at top with no page overflow.
- Browser testing found that the global X-Frame-Options DENY blocked the PDF viewer. Only the uploaded PDF preview endpoint now uses SAMEORIGIN; downloads and other responses retain DENY, verified by HTTP tests.
- UI skill guidance resulted in a real filename button with visible keyboard focus, disabled missing-file state and independent download link; no new theme or layout system.
- Synthetic preview fixtures and isolated browser were stopped; user services and private configs untouched. No push, release or new executable package.
