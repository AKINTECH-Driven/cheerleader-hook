# Notes for hook authors

Two sections of the project working notes, published as written apart from one edit: a line about the author's own settings file was generalised. Three of the notes were corrected in the working notes themselves on 2026-11-14: what `PostToolUse` can add and when hook edits take effect, both against the public hooks reference as read on 2026-11-13, and how the engine recognises its own earlier message. The transcript schema was measured on 2026-08-26 and may change with Claude Code releases.

## Verified transcript schema (measured 2026-08-26, not guessed)
Line `type`: `user` | `assistant` | `attachment` | `system` | `queue-operation` | `last-prompt` | `mode` | `custom-title`.
- `assistant.message.content[]` blocks: `thinking` | `text` | `tool_use` (`name`, `input`, `id`).
- `user.message.content` is `str` OR `list` of `tool_result` (`tool_use_id`, `content`, **`is_error`**).
  `is_error: true` is the primary failure signal; `content` is the error string ("Exit code 1\n...").
- top-level `toolUseResult`: dict with `stdout`/`stderr`/`interrupted` (Bash), `filePath`/`structuredPatch`/
  `oldString`/`newString` (Edit), `file` (Read). Can also be `str` or `list`.
- `system` + `subtype: "stop_hook_summary"` carries `hookAdditionalContext[]` and `preventedContinuation`
  → on `Stop`, this is how HORME recognises its own earlier message. The per-session state file is the main dedupe.
- `isSidechain: true` marks subagent lines; `timestamp` is ISO8601 Z; `uuid`/`parentUuid` thread the log.

## Gotchas
- **Plain stdout from `PostToolUse` does not reach Claude** (it goes to the debug log). A hook adds context by
  returning JSON `hookSpecificOutput.additionalContext`. The public hooks reference, as read on 2026-11-13, lists
  `SessionStart`, `SubagentStart`, `UserPromptSubmit`, `UserPromptExpansion`, `PreToolUse`, `PostToolUse`,
  `PostToolUseFailure`, `PostToolBatch`, `Stop`, `SubagentStop` and `PostModelSwitch` as events whose
  `additionalContext` is added. The original note said `PostToolUse` could not add context at all, which the
  reference does not support.
- Hook stdin field names come from public docs, NOT observation. `hooks/horme_probe.py` captures the real
  payloads; the parser must stay tolerant (accept `tool_response` OR `tool_output`, tolerate absent fields).
- Hook config was noted here as snapshotted at session start. The public hooks reference, as read on 2026-11-13,
  says direct edits to hooks in settings files are normally picked up automatically by the file watcher.
- Transcripts run to 1300+ lines. Tail-read backwards, bounded. Budget < 50 ms per hook invocation.
- `~/.claude/settings.json` is global and may already hold other hooks and a status line. Never overwrite it;
  patch it, back it up first, and prove the uninstall restores it byte-identical.
