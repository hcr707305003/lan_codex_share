# Long native history deletion implementation plan

**Goal:** Delete selected user records or grouped Codex responses in compacted native histories, retaining the original Session ID and all unselected visible records.

**Architecture:** Stream the rollout; do not deserialize the complete file. Reuse strict record mapping within each selected turn. Remove obsolete compacted/context and world-state caches, then append a bounded, text-only replacement context built exclusively from retained response messages. This is a recent-context reset, not a model-generated summary: older messages and attachments remain in the original visible history, but are not all sent on the next model request. No inference request is needed to delete history. Rollback histories remain unsupported.

**Constraints:** Same Session ID; no real user history edited during development; Windows native writer exclusion; durable complete backup; revision check before replace; atomic rollback on failed native verification. The selected session must be idle and have an empty queue. No PHP process operations, publishing, or release.

- [x] Add streaming inspection, per-turn reconstruction, bounded context generation, and atomic transactional replacement in `history_rebuild.py`.
- [x] Connect compacted and large histories through `HistoryEditor`, using native paged readback and semantic verification. Remove compaction-only preflight blocking and show the recent-context reset notice.
- [x] Test encrypted old summaries, multiple compactions, partial historical turns, selected user/response isolation, revision races, backup/rollback, context bounds, and memory behavior.
- [x] Extend isolated native probes with more than a hundred compactions and oversized retained messages. Verify unchanged Session ID, retained display records, missing selected/stale content in the next mock request, and a bounded rebuilt context.
- [x] Run targeted backend/frontend checks and perform read-only inspection/planning against the user's long rollout. Report actual limits and restart requirement.

## Evidence and operational limits

- Installed Windows Codex CLI 0.151.0: isolated `tests/probes/history_rebuild_native.py` passed, including the real `HistoryEditor` job, 45 turns, 120 stale compactions, native pagination, same ID, backup, independent user/response removal, bounded next mock-provider input, archive/unarchive, long-lived native reader refresh, and writer lock exclusion. Latest temporary report: `C:/Users/ADMINI~1/AppData/Local/Temp/codex-history-rebuild-probe-g7xzyab8/report.json`.
- Read-only source scan and rewrite planning for the user's 833 MiB / 107-compaction rollout took about 10 seconds with about 55 MiB peak RSS. This measurement excludes native API readback and actual disk backup/replacement. The source was not changed. There is no promise of a fixed deletion time or total-process memory cap; a selected turn and one native page still need decoding, and the existing web projection retains visible history.
- Unit coverage includes backup and verification rollback, stale revisions, cross-turn tool associations, historical interruption boundaries, source files without a final newline, queue snapshots during IO, and reconnect/removal exclusion.
- Validation: 112 targeted Python tests and all 94 JavaScript tests passed; native compatibility probe passed; JavaScript syntax and tracked diff whitespace checks passed.
- Only idle sessions with empty queues can be edited. The per-session Codex process is closed first, so later reconnect starts with the rewritten context. Long IO does not retain the service queue lock. Explicit reconnect remains required after success.
- Windows native sessions only. Rollback records and ambiguous mappings remain rejected. Content repeated in unselected messages remains there; this is selective record deletion, not a semantic redaction of every reference elsewhere.
- This clears all old derived compactions/world-state caches and creates bounded recent text excerpts without inference. It does not retain every attachment/tool result in the next model input and does not change model safety rules. Original retained source records and the complete automatic backup remain available locally.
- No real user records were deleted, no running user service was restarted, and no package/release was produced. Restart the Share Python service and refresh the web page to load the new implementation.
