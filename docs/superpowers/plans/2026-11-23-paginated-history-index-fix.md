# Paginated native history deletion verification

The failed November 23 deletion was reproduced from the automatic backup in a temporary CODEX_HOME. The original rollout was not modified. No inference or user service restart was performed.

## Confirmed cause

Modern paginated Codex histories contain top-level ordinals and an independent `thread_history_1.sqlite` projection. Replacing the rollout alone leaves the paginated reader returning the old selected items, even in a fresh native process. Clearing the index is insufficient: the reader returns an empty history. A replacement compacted record without an ordinal also makes native resume fail.

## Implementation

- Preserve original ordinals and append the replacement context with the next ordinal.
- Back up only the selected thread's four history projection tables alongside the complete rollout backup, inside the native writer guard.
- Synchronize retained items, turn boundaries, byte offsets, first/final pointers, and projection continuation position with the rewritten rollout. Preserve incomplete legacy tool projections by their retained source ordinal.
- Keep other threads untouched. On verification failure restore both the rollout and selected thread index rows.
- Keep native semantic verification enabled. Legacy histories without the paginated index continue using the existing path.

## Verification

- Real failed-backup copy: 216 turns, 91 old compactions, about 689 MiB; selected user message and its grouped response deleted. Native paginated signatures for every retained item matched. Same-ID native resume passed afterward. Latest passing isolated directory: `C:/Users/Administrator/AppData/Local/Temp/history-backup-diagnostic-92s1o82p`.
- Existing isolated mock-provider compatibility probe passed with 120 compactions and bounded next-request context.
- Added transaction tests exercise native index synchronization, other-thread isolation, sequence/offset continuation, and complete file/index rollback on verification failure.

Run an opt-in failed-backup reproduction with `python tests/probes/history_backup_diagnostic.py BACKUP_PATH TURN_ID`. It edits only a temporary copy and points its provider at an unreachable loopback endpoint.
