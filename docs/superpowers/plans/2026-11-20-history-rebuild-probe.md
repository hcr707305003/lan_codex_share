# Same-ID history rebuild prototype

**Historical prototype notes:** The restrictions below describe the initial short-history experiment, not the final implementation. Compacted/large Windows histories are now integrated through the streaming recent-context reset described in [the long-history deletion plan](2026-11-20-long-history-delete.md). Rollback and ambiguous mappings remain blocked. The newer plan records current verification and limitations.

**Goal:** Test whether a synthetic, multiply compacted conversation can be rebuilt with its ID unchanged and consistent native history/context.

**Architecture:** An opt-in probe creates a temporary CODEX_HOME and a loopback mock Responses provider. It compares native paginated reads and the next outbound model input before/after rebuilding synthetic rollout records. No production history is edited; no real model is called.

**Tech Stack:** Python, installed Codex app-server, JSON-RPC, temporary SQLite/JSONL stores.

**Spec:** User-approved approach: whole-turn selection, original ID retained, native writer exclusion, backup, context/index reconstruction, rollback on failure.

## Constraints

- Prototype only; do not expose arbitrary history rewriting through HTTP yet.
- Never use real user conversations or credentials in the probe.
- Keep production rejection of compacted histories in place.
- Native reads alone do not prove model context was rebuilt.
- Retained later messages can still contain information from deleted turns.
- History management does not change model safety rules.

## Tasks

- [x] Build an opt-in synthetic probe with multiple compaction snapshots.
- [x] Confirm baseline native paging and outbound input reflect the fixture.
- [x] Rebuild without the selected turn and stale summaries; verify same ID, surviving turns, outbound input, and archive/unarchive.
- [x] Report failures and compatibility limits before implementing production UI.

## Evidence (2026-11-20, Windows)

Run `python tests/probes/history_rebuild_native.py` from the repository root.
Three synthetic turns and two synthetic compaction records are written only to a newly created temporary CODEX_HOME. The baseline outbound input contains the final compaction marker. After reconstruction, the same native thread ID exposes the two retained turns; the next request contains both retained user/assistant messages and neither the removed turn nor the stale summaries. The mock provider completes that turn. Native archive/unarchive succeeds.

A second app-server stays alive across reconstruction: its subsequent paginated read reflects the removal. This checks the API projection, not the desktop UI's own cache. A Windows edit lock also causes native resume to reject writer acquisition.

Latest report: `C:/Users/Administrator/AppData/Local/Temp/codex-history-rebuild-probe-fwdyc4nd/report.json` (temporary artifact).

This proves feasibility only for the short synthetic history. No model-based re-compaction was performed, and no claim is made that an arbitrarily long real rollout can be replayed unchanged. The production planner still rejects compacted histories. No user session has been changed and no release was produced.

## Remaining production gates

Native writer locking in both directions; live cache invalidation; native summary recomputation for histories exceeding context limits; tool pairing and aborted-turn boundaries; consistent index rollback; concurrency and platform verification. Passing the short synthetic probe does not satisfy these gates.

## Fast multi-select interaction (user requested)

- Enter selection mode from the current conversation; select complete turns with checkboxes, Shift range selection, and select/clear visible results.
- Fetch paged turn summaries, not full tool output or attachments. Keep selections by stable turn ID while navigating pages.
- A sticky action bar shows the selected count. One destructive confirmation describes the affected native session and backup.
- Submit all IDs in one operation, with a history revision token. Reject stale selections rather than deleting changed content.
- A background job reports backup, reconstruction, native verification, and completion. Never mark deletion successful before verification; freeze writes only for the affected session.
- Aim for seconds on ordinary histories; do not promise that latency for compaction-heavy sessions. Never reuse a stale summary solely to make deletion faster.
- Planner duplicate detection now uses a set (linear scan rather than scanning prior turns for each new turn). This optimization alone does not establish end-to-end deletion latency.

## Current integration

Inline selection refinement: each user message remains independently selectable. The Codex process and final reply within the same native turn now share one visible checkbox and one `__response__` selection key. Clicking either response body toggles that group; select-visible deduplicates it. Native deletion removes that turn's process and assistant replies together, retaining user messages and lifecycle boundaries. The authenticated server derives the expected native items itself and verifies them before reporting success. Existing compaction and rollback restrictions still apply.

The sidebar now opens a native-history manager with 50-turn pages, selection across pages, Shift range selection, a destructive confirmation, and background status polling. Authenticated GET manage/status and CSRF-protected POST delete routes are wired through the hub. Each job checks shared membership, revision, queue/active state, and native writer exclusion. It backs up the JSONL, atomically replaces it, verifies native turn IDs, and restores the original on verification failure. Success leaves the session released; reconnect explicitly before continuing.

This is a limited integration: Windows only, completed unambiguous histories only. Histories containing compaction or rollback are listed with deletion disabled. The user's existing long session is therefore NOT supported yet. Arbitrary compressed-history editing, desktop UI cache refresh, and model-based re-compaction have not been shipped. No claim of full completion is made.
