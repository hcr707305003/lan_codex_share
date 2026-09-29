# Document Attachments Implementation Plan

> **For agentic workers:** Use executing-plans to implement task-by-task in the current branch, as requested by the user. No release or push.

**Goal:** Upload MD/TXT/DOCX/PDF from the web, pass extracted text to AI, retain downloadable attachment cards.

**Architecture:** A document store owns validated uploads and persistent message associations. A bounded subprocess extracts document text; the existing service queue supplies text items and the projection substitutes the original user text and attachment metadata by exact message identifiers.

**Tech Stack:** Python 3.11+, pypdf, defusedxml, SQLite, standard-library ZIP/XML, existing vanilla JS/CSS.

**Spec:** ../specs/2026-09-28-document-attachments-design.md

## Global Constraints

- Current branch, existing services untouched; no PHP, Share or tunnel restarts.
- MD/TXT/DOCX/PDF only, legacy DOC rejected with conversion guidance.
- Default 20 MiB per document, 5 documents, aggregate 100 MiB; image limits independent.
- ZIP maximum 1,000 entries/50 MiB expansion/100x ratio; PDF maximum 500 pages; text 100,000 chars/file and 200,000/message.
- Extraction subprocess deadline 30 seconds and one concurrent extraction per server; no OCR/macros/external resources.
- Same password/Host/CSRF checks; files addressed by opaque IDs, session checked; no arbitrary paths.

## Task 1: Validated storage and extraction

Files: create `lan_codex_share/document_store.py`, `document_extract.py`, `tests/test_document_store.py`; modify `requirements.txt`, executable entry points for frozen multiprocessing support.

Interfaces: `DocumentStore(directory, max_bytes=20971520, max_documents=5)`, `save_many(payloads) -> list[dict]`, `delete_many(records)`, `bind(session_id, message_id, text, records)`, `metadata(session_id, client_id, item_id=None)`, `resolve(document_id, session_id)`; `extract_document(path) -> dict` with text/warning.

- [x] Red test: `assert store.save_many([payload('note.md', b'# hello')])[0]['text'] == '# hello'`; test bad extension, bytes, encodings, DOCX paragraphs/tables, PDF, limits and rollback.
- [x] Implement extension/content checks and UUID paths; SQLite associations persist original user text and public cards without returning internal paths.
- [x] Run extraction in spawn subprocess with bounded pipe results, deadline, cleanup; enable `multiprocessing.freeze_support()` before executable imports.
- [x] Run `.venv-desktop/Scripts/python.exe -m pytest tests/test_document_store.py -q` and verify malicious XML/archive cases.

## Task 2: Message queue and history integration

Files: `lan_config.py`, `lan_main.py`, `lan_service.py`, `session_hub.py`, `session_projection.py`; tests `test_document_messages.py`.

- [x] Red test using FakeCodex: submit only documents, assert `calls[0]['items'][0]['type'] == 'text'` and extracted text present.
- [x] Add keyword-optional `documents` to hub/service submit; persist association before enqueue; call `delete_many` on queued cancellation only.
- [x] Supply content as untrusted document text, not additionalContext. Restore metadata by clientId and persist upstream itemId for restart; never match by content similarity.
- [x] Normalize document messages to original text/cards; if metadata unavailable leave upstream text visible. Keep pending/completed/failed metadata and image behavior compatible.
- [x] Validate config integers and inject one store instance into all services; run message/config/projection regression tests.

## Task 3: HTTP and web interface

Files: `lan_web.py`, `web/app.js`, `web/index.html`, `web/style.css`; tests `test_document_web.py`, JS/UI coverage.

- [x] Test unauthenticated download rejected; valid session download returns byte-identical file; wrong session/ID returns 404; invalid mixed upload queues nothing and removes new files.
- [x] Add optional documents array on `/api/messages`, authenticated `/api/documents/<id>?session_id=...`, and limits in auth bootstrap metadata. Preserve old requests without documents.
- [x] Expose upload limits from configuration and account for base64 request sizes with a hard ceiling.
- [x] Generalize existing selectedFiles rendering/selection; add safe text file cards, downloads and queue counts; preserve image galleries.
- [x] Freeze draft selection during send, prevent duplicate Enter sends, capture target session before async file reads, retain draft on errors.
- [x] Verify real browser with a fake local HTTP backend at desktop/mobile widths; file picker, drag/drop, mixed image/document send, errors, refresh and download. No real model invocation.

## Task 4: Regression and handoff

Files: README, example config, packaging smoke tests if required; update this checklist.

- [x] Document formats, extraction limitations, defaults, storage and security behavior, no release version bump.
- [x] Run `.venv-desktop/Scripts/python.exe -m pytest -q`, `node --test tests/javascript/*.test.cjs`, `git diff --check`.
- [x] Build a local CLI smoke executable if needed to verify frozen extraction children, not a release archive; no runtime files enter git.
- [x] Inspect diff, report exact tests and limitations, leave code local for user testing.

## 验证记录

- 最终全量 Python 回归通过：767 项，耗时 72.83 秒；包含同名跨会话附件清理与文档专项测试。
- JavaScript 37 项通过，覆盖文档/图片独立数量、无效文档、防重复发送、捕获目标 Session、失败保留草稿。
- 真实浏览器模拟会话验证：文件选择、拖拽、文图混合、刷新、另一页面同步、下载 SHA-256 一致、损坏 DOCX 错误保留输入；375px 和 1280px 截图检查通过。
- PyInstaller 本地独立解析程序：MD/DOCX/PDF 子进程提取 PASS；仅冒烟程序，不是新发行版，也未发布。
- 两个项目虚拟环境新增依赖已安装。测试浏览器和临时模拟服务已关闭；用户服务与私人配置未操作。
- UI 数据集查询没有匹配到针对文件上传的专门条目，采用通用的可访问按钮、文字反馈和保留输入原则，沿用现有设计。
