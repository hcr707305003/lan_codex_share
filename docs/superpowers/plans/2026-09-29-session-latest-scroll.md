# Session Latest Scroll Implementation Plan

**Goal:** On entering a session show the latest messages at the bottom, including delayed layout changes; preserve deliberate history reading.
**Architecture:** HistoryTimeline owns bottom-follow state and observes rendered turn sizes plus the viewport. Reset enables following; upward user scrolling disables it. No message ordering or server changes.
**Tech Stack:** JavaScript, ResizeObserver, Node tests.
**Approved behavior:** User confirmed switching sessions should land at the latest message, with no forced scrolling while reading history.

## Task: Scroll lifecycle
- [x] Add tests in tests/javascript/history.test.cjs for delayed growth, upward reading, and session reset.
- [x] Update lan_codex_share/web/history.js to observe current nodes, disconnect on reset, follow only when enabled, and stop on upward input.
- [x] Run all JavaScript tests and isolated browser checks. Do not restart live services or publish.

## Verification
- 59 JavaScript tests passed; 35 related Python history/web tests passed.
- Real browser on isolated fake sessions: switch to bottom, delayed turn border-box growth stays at bottom, upward wheel input preserves reading position through more growth, next switch resets following.
- Queued programmatic scroll events after layout growth must not disable following; covered by regression test.
- No real session, live configuration or user service changed.
