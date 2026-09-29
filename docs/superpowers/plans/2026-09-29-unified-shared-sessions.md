# Unified Shared Sessions Implementation Plan

> **For agentic workers:** Use executing-plans, current branch per user instruction.

**Goal:** One TOML shared-session list; removing a shared task also releases ownership.
**Architecture:** Shared atomic config writer coordinates desktop and server changes. SessionTasks owns serialized membership mutations; Hub handles membership and release. Existing creation journal remains non-authoritative runtime data.
**Tech Stack:** Python, TOML/tomlkit, Qt desktop, vanilla JavaScript.
**Spec:** docs/superpowers/specs/2026-09-29-unified-shared-sessions-design.md

## Constraints
Temporary config and fake sessions only; no live service changes, no push or release. Preserve comments, secrets, history and drafts. Existing release API remains release-only.

## Task 1: Configuration
- [x] Add tests for explicit modes: `session_mode="selected"; session_ids=[]` must yield neither auto nor discovery.
- [x] Add `session_mode` and config path to LanConfig; legacy inference unchanged.
- [x] Add shared file-lock and atomic version-checked writer, then use it in desktop ConfigDocument and server membership persistence. TOML edits preserve other fields/comments.
- [x] Verify invalid mode, empty selected, existing comments, concurrent edits and write failures using temporary files.

## Task 2: Membership
- [x] SessionTasks gets optional config store; configured mode restore never re-adds runtime IDs. `management()` reports mode/migration; explicit confirmation permits fixed selected list and one-time import or skip.
- [x] Add mutation transaction under task lock: validate config before external create; persist config before register; retain creation journal for retries.
- [x] Add Hub removal under shared operation lock: reject busy/queued; release loaded service, persist, remove maps, broadcast. Failure to persist leaves released service visible. No startup for unloaded removals.
- [x] Allow empty Hub and snapshots; catalog fixed-list conversion prevents resurrection. Test removed current selection falls back for snapshot only, mutations remain strict.

## Task 3: UI and integration
- [x] Add authenticated management/migration/remove routes; startup passes actual config path.
- [x] New-task confirmation handles auto/all conversion and migration; removal UI says releases and retains history. Keep drafts keyed by previous session when selection changes remotely.
- [x] Desktop mode editor reads/writes explicit mode. Shared writer rejects stale desktop saves.
- [x] Update README/example; run targeted then full tests and isolated UI checks; record results before local commit.

## Verification (2026-09-29)

- Full Python suite: 820 passed in 76.35 seconds.
- JavaScript suite: 57 passed.
- Isolated two-tab browser check: removing tasks updates both tabs, the last removal leaves an empty list with new-task entry available, and re-adding restores each tab's independent unsent draft.
- Temporary configuration and fake sessions only; no live configuration, service or real session changed. No push, package or release.
