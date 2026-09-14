# JSON Resource Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make same-backend resource URLs returned by JSON APIs usable through Share, including HTTPS URLs synthesized from forwarded protocol plus internal Host.

**Architecture:** Buffer only small uncompressed JSON responses. Validate JSON, then replace complete URL string-value tokens pointing at the exact current backend authority with the validated public/LAN Share origin and proxy prefix. Preserve all other bytes, including numeric precision, keys and whitespace.

**Tech Stack:** Python standard library, pytest, existing Chromium fixture.

**Spec:** User-approved restriction: modify only `lan_codex_share`; no frontend/backend PHP changes, configuration changes, service restarts, commits or releases. This extends the resource rewriting design in `../specs/2026-09-14-cross-port-proxy-design.md` with a narrowly scoped JSON exception.

## Global Constraints

- Only HTTP/HTTPS URLs with exact current backend host and port are rewritten. Do not proxy unrelated HTTPS services or change transport selection.
- Keep query strings/fragments and non-URL data unchanged; do not deserialize and reserialize business numbers.
- Existing 2 MiB rewrite bound, compression/range bypass, authentication and destination validation remain intact.

---

### Task 1: Implement bounded JSON resource rewriting

**Files:** `lan_codex_share/proxy_rewrite.py`, `lan_codex_share/dynamic_proxy.py`, `tests/test_dynamic_proxy.py`, `README.md`.

**Interfaces:** Add `rewrite_json(data: bytes, content_type: str, prefix: str, authority: str, origin: str) -> bytes | None`. `forward` selects it for `application/json` and `application/*+json`; other media keep existing behavior.

- [x] Add and run failing regression:

```python
result = rewrite_json(b'{"qrcode":"https://localhost:13333/image?scene=x"}', 'application/json', '/proxy/localhost:13333/', 'localhost:13333', 'https://share.example.com')
assert result == b'{"qrcode":"https://share.example.com/proxy/localhost:13333/image?scene=x"}'
```

- [x] Implement JSON validation with `json.loads(text, parse_int=str, parse_float=str)`, then scan JSON string tokens. Skip object keys; decode and rewrite only complete same-authority URL values; emit unchanged tokens for all others. Return `None` for invalid/unchanged input. Use original charset when decoding/encoding.
- [x] Integrate into the existing bounded response branch; let existing length/digest header handling account for changed content.
- [x] Verify exact bytes for high-precision numbers, escaped slashes, nested arrays, keys, public URLs, other ports, malformed JSON and oversize/compressed payload bypass.
- [x] Exercise a fake API returning an HTTPS internal image URL in Chromium; assert successful image load through Share and no direct local requests. Run full pytest and diff checks; document the scoped exception.

## Verification

Chromium fixture loaded the JSON-returned image with naturalWidth=1, preserving its query string; no direct backend requests or page errors. No real QR scene or login was created. An intermediate CSS regression was caught by the full suite and corrected before the final verification. Only files within this repository changed; no production service was managed or release created.
