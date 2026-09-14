# Cross-port Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route a proxied frontend's local cross-port API and resource requests through the same Share origin.

**Architecture:** Extend the existing URL rewriters, not the proxy transport. Each allowed local authority selects its own prefix; existing proxy paths are idempotent. Leave public and TLS-only upstream URLs untouched.

**Tech Stack:** Python standard library, browser JavaScript, pytest, node:test, Chromium.

**Spec:** `docs/superpowers/specs/2026-09-14-cross-port-proxy-design.md`

## Global Constraints

- No new dependencies, per-service configuration, or production service restarts.
- No arbitrary JavaScript/JSON string rewriting.
- Preserve server authentication, address validation, blocked ports and cookie scoping.
- No commit, push or release in this task. Execute inline; the referenced execution skills are unavailable in this session.

---

### Task 1: Server URL rewriting

**Files:** Modify `lan_codex_share/proxy_rewrite.py`; test `tests/test_dynamic_proxy.py`.

**Interfaces:** Preserve `rewrite_url(value: str, prefix: str, authority: str) -> str` and `rewrite_document(...) -> bytes | None`.

- [x] Add regressions including this assertion and HTML/CSS coverage:

```python
assert rewrite_url('http://localhost:13333/api?q=1#x', '/proxy/localhost:3301/', 'localhost:3301') == '/proxy/localhost:13333/api?q=1#x'
```

- [x] Run `.venv/Scripts/python.exe -m pytest tests/test_dynamic_proxy.py -q`; confirm cross-port assertions fail.
- [x] Extend URL classification with `ip_address` and existing `PRIVATE_V4`; accept canonical localhost/IPv4/[::1], port 1..65535 (default 80), no credentials. For local HTTP/ws or protocol-relative URLs construct `'/proxy/' + authority + (parsed.path or '/')`, preserving query/fragment. Keep `/proxy/` paths idempotent and root paths scoped to current prefix.
- [x] Rerun tests; confirm unchanged public, metadata, credentials and HTTPS/WSS cases as well as cross-port redirects.

### Task 2: Browser request mapping

**Files:** Modify `lan_codex_share/web/proxy-client.js`; test `tests/javascript/proxy-client.test.cjs`.

**Interfaces:** Existing network and DOM wrappers consume internal `proxyURL(value, websocket=false)`; no public API change.

- [x] Add failing fetch, Request, XHR, WS, EventSource and DOM tests. Core expected mapping:

```javascript
c.fetch('http://localhost:13333/api?q=1');
assert.equal(sent.at(-1)[0], 'https://codex.example.com/proxy/localhost:13333/api?q=1');
```

- [x] Run `node --test tests/javascript/proxy-client.test.cjs` and confirm failure.
- [x] Classify same-origin URLs before local targets. For a local target set `targetPrefix = '/proxy/' + hostname + ':' + (port || '80') + '/'`. Prefix its original path once, switch to the Share scheme/host/port, preserve query/hash; leave nonlocal and TLS upstreams untouched. Retain `url.port = location.port` to avoid leaking the upstream port onto the public domain.
- [x] Run Node tests including already-proxied cross-service paths and nondefault public ports.

### Task 3: Integration and documentation

**Files:** Update `README.md`, `RELEASE_README.md`; use ignored `output/playwright/` for the isolated browser fixture.

**Interfaces:** HTTP frontend references a different ephemeral HTTP backend; both accessed through a password-protected fake Share service, never the real Codex/PHP services.

- [x] Validate fetch POST body, XHR, WebSocket, SSE, static/dynamic images, redirected links and backend cookie use in Chromium. Confirm browser requests use Share, not direct backend addresses.
- [x] Document cross-port examples and retain caveats for Workers, CSP and unsupported dynamic patterns.
- [x] Run `.venv/Scripts/python.exe -m pytest -q`, `node --check lan_codex_share/web/proxy-client.js`, and `git diff --check`.
- [x] Stop only isolated fixture processes; report results and user-managed restart requirement.

## Verification results

- Initial regressions: eight Python cases and three Node cases failed as expected.
- Chromium exposed two additional issues: remapped Request bodies became streaming uploads unsupported over HTTP/1.1, and detached image setters initiated a direct local request before MutationObserver ran. Fixed with buffered remapped Request bodies and synchronous URL attribute/property adaptation; added Request/FormData/init-override and detached-image regressions.
- Final Chromium run: API POST/XHR payloads, cookies, static/dynamic images, SSE, WebSocket and redirect passed; no direct backend requests and no page errors. Isolated fixture processes exited and cleaned up.
- Final suite: 249 pytest cases passed (including seven Node adapter cases through the JavaScript test runner). JavaScript syntax and diff whitespace checks passed.
- Production services and actual configuration unchanged in this task; no commit, push or release performed.
