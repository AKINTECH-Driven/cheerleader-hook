# Cheerleader (HORME engine)

A Claude Code skill and hook set that detects, from the session transcript alone, when Claude looks stuck, and may then return one intervention that names a next step.

There is no model call anywhere inside it. The signal patterns, the diagnosis rules, the thresholds and the phrase templates are fixed, so with the same code and rulebook the same transcript always gets the same diagnosis and, when it speaks, the same words. That is deliberate: an encouragement layer that improvises is one that can be talked into saying whatever a stuck model wants to hear. Whether it speaks also depends on what it has already said, and when, so a second run on the same transcript can stay silent.

The skill is named `cheerleader`. The engine and its Python package are named `horme` (Ὁρμή, the daimon of impulse and effort: the setting-into-motion of an action).

## Status

Experimental. Read this section and "Known limitations" before you install it.

- **No efficacy claim.** Nothing here measures whether the intervention helps a model get unstuck. That needs a controlled trial against a no-hook baseline, and none has been run.
- **No session on record shows the hook running live.** The record is the author's own Claude Code session transcripts, and it cannot show a run that left no transcript. It does show the engine run by hand on live sessions: through the skill, four times, each on the transcript of the session that asked for it, in three working sessions on [theorem-b](https://github.com/AKINTECH-Driven/theorem-b), a Lean 4 proof project, between 26 August and 12 September 2026 (UTC). Each time it measured the session, found it not stuck and said nothing, so no session on record has received an intervention. Those runs used the build of August 2026, not this release. As a hook wired into Claude Code, every run on record was a process-level run on fixtures and recorded transcripts. The hook input field names and the output shape come from the public hooks documentation, not from observation. `hooks/horme_probe.py` exists to capture real payloads and settle the input side.
- **Thresholds come from one person's sessions.** See "How it decides".
- **One machine.** It has only been run on macOS with Python 3.9.

## Quick start

Requires Python 3.9 or later. Standard library only, offline.

```bash
python3 install.py --dry-run     # show what would be added to ~/.claude/settings.json
python3 install.py               # apply (writes a timestamped backup first, refuses a file it cannot parse)
python3 install.py --doctor      # is it wired in, does the self-test pass, does the stored command run
python3 uninstall.py             # removes only its own entries
```

The hooks reference says that edits to hooks in settings files are normally picked up automatically. If the hook does not show up in a running session, restart Claude Code.

Kill switch, with no uninstall needed: `export CHEERLEADER_DISABLE=1`, or `mkdir -p ~/.claude/cheerleader && touch ~/.claude/cheerleader/DISABLED`. Any non-empty value of the variable disables it, `0` included, and the older name `HORME_DISABLE` works too.

### Use it as a skill

The hooks work from this folder as it is. To have the manual flow in `SKILL.md` available as a Claude Code skill as well, build the skill folder and copy it:

```bash
python3 tools/export_skill.py     # runs the tests, then builds dist/cheerleader
mkdir -p ~/.claude/skills && cp -R dist/cheerleader ~/.claude/skills/
```

A default export is already that folder: it has no `tools/` and nothing to build, so copy it as it is. An export built with `--with-tests` keeps `tests/` and `tools/` and can build the default one again. The exported folder has its own `install.py`. The hook command stores the absolute path of the folder it was installed from, so install the hooks from the copy you mean to keep. The default export leaves out `tests/` and `tools/`; `--with-tests` keeps them. The export smoke-tests the hook as a process under your real home folder: it writes one state file under `~/.claude/cheerleader/state` and deletes it again, leaving the empty folder.

### What gets installed

- One hook command on four events: `PostToolBatch`, `Stop` and `SubagentStop` (where it diagnoses) and `SessionStart` (where it only prunes old state). Existing hooks are kept. Each entry carries the status text `CHEERLEADER`.
- The command stores the absolute path of this folder and of your Python interpreter as Python itself reports it, which can differ from the path you typed. If the folder is moved or deleted, the hook goes silent instead of failing: the command checks that the script exists, holds its output until it has exited cleanly, and always exits 0. If only the interpreter is gone it still exits 0, but the shell writes an error line to standard error at every event. `install.py --doctor` reports either case. Run `python3 uninstall.py` before you remove the folder for good. If it is already gone, delete by hand the entries in `~/.claude/settings.json` whose command contains `cheerleader_hook.py`.
- At most 4 interventions per session, at least 90 seconds apart, and one per block. All three are data in `rulebook/hooks.json`.
- `uninstall.py` restores the pre-install bytes of `settings.json` when nothing else changed in the meantime. If you edited your settings after installing, it removes only its own entries and keeps your edits. In that case the file is written back in a normalised JSON layout. Uninstalling leaves the backup files next to `settings.json` in place and, once the hook has run, the folder `~/.claude/cheerleader`. If there was no `settings.json` before the install, it leaves one that holds `{}`. Delete them by hand if you want no trace.

### Diagnose a transcript by hand

```bash
PYTHONPATH=src python3 -m horme.cli --force --event Stop --explain \
  --transcript tests/fixtures/stuck_repeat_error.jsonl --session demo < /dev/null
```

The CLI is a hook entry point and always reads standard input, so a manual run closes it with `< /dev/null`.
It prints the hook JSON on standard output and the diagnosis on standard error. A second run with the same `--session` prints `{}`, because one block gets one intervention. Use a new session name to see it again. The fixture is in the repository and in an export built with `--with-tests`; with a default export, point `--transcript` at a session file of your own. A path that cannot be read gives `not_stuck` and `{}`, not an error.

## What it says

These are the two text fields of the JSON that the command above prints for the shipped fixture. The first line is the one-line notice meant for the human (`systemMessage`, a top-level field of the hook output). The rest is what lands in Claude's context (`additionalContext`).

```
CHEERLEADER: cognitive block, severity 2 — AssertionError: expected 4 cells, got 1, in importer.py

[CHEERLEADER] Being stuck here is a reasonable place to be — AssertionError: expected 4 cells, got 1, in importer.py is behaving in a way the obvious reading does not predict. The block is importer.py — narrow, and not yet solved. That is a fact about the attempts so far, not about the ceiling. For context: 6 of the last 12 steps in this window landed cleanly, so the failure is isolated to importer.py. Smallest next move: print the actual value the assertion is comparing before the next edit, so the next change is driven by data rather than a guess. You could reproduce the failure in isolation, outside the full run, or state the smallest assertion that should pass and target only that — either is a reasonable route. If the next run shows the same failure again, then re-read the failure output end to end before making another change, rather than repeating the last change.
```

## The four things it refuses to do

1. **Assert that anything is correct.** Every composed message is checked against a denylist (`rulebook/denylist.json`) before release. A match suppresses the whole message instead of editing it, so "that looks right", "it works" and "ship it" do not get out. When the denylist itself cannot be trusted (the file is missing or unreadable, a rule does not compile, or a group no longer catches the phrase it exists for), every message is suppressed and the reason goes to standard error. The failure mode of an encouragement layer is not bad morale advice, it is sycophancy: speaking near a verdict is what turns a FAIL into a PASS.
2. **Speak while a verdict is being decided.** This is a keyword match on the last three tool results of any kind, each read whole up to 60,000 characters: `VERDICT`, `VERIFIER`, and `PASS` or `FAIL` in capitals wherever no letter adjoins it (so `PASS:`, `FAIL_FAST` and `PASS2` count too), and in lower case a name ending in `-guard`, `code-review`, and `sign-off` or `signed off` (with a space or a hyphen). A match suppresses it completely. The lines that unittest, jest, vitest and go test print for a test result are set aside first, so a red run in those runners does not match: that is when it helps. The match is narrower than this heading. Limitations 1, 2, 11, 12 and 13 say where.
3. **Return an error or a blocking decision.** The engine and the hook entry point exit 0 on every path, including internal errors, and the installed command exits 0 even when the script or the interpreter is missing. It never exits 2 and never returns `decision: block`. That does not make it without effect on the turn. According to the hooks reference, context returned on `Stop` or `SubagentStop` is non-error feedback, and the conversation continues so that Claude can act on it. An intervention at `Stop` therefore gives Claude another turn instead of letting it stop there, at most once per block and 4 times per session. The hook does not read the `stop_hook_active` field of its input.
4. **Cheer an impossible task.** Missing `docker`, missing `pandoc`, a permission you do not have: it names the blocker, says that more attempts will not change it, and asks for what is needed or for a route that does not need it.

It also speaks once per block: one episode, one intervention, then silence until the failure changes shape. The session cap and the cooldown still apply. It also stays silent while one of its own `Stop` messages, as recorded in the transcript, is still inside the window.

Other properties that have their own tests:

- Subagent lines are excluded, so a flailing subagent cannot make the parent session look stuck.
- When the environment is the blocker, the evidence is narrowed to that, so no decomposition advice is built for a task that cannot be done.
- Session names from hook input are sanitised against path traversal, and the test asserts on the computed path.
- The exit-0 contract is tested by making each of four pipeline stages raise in turn.

## How it decides

Signals are windowed over the last 40 tool calls, and every threshold is measured, not typed. `tools/calibrate.py` replays real sessions, samples the windowed signals at every third tool result, records the worst value each session reached, and sets each threshold one above the 99th percentile of those values, with a floor of 2.

The shipped `rulebook/thresholds.json` was calibrated on the author's own Claude Code sessions. 438 transcript files were scanned and 59 of them had at least 20 tool results, so 59 were used. With 59 sessions the 99th percentile is the second-highest value, so one session in that corpus can sit above a threshold. The corpus is unlabelled and is treated as healthy, which biases every threshold upward: the tool errs toward silence. Sampling every third result can miss a peak, which pulls the other way. The corpus is not part of this repository. Calibrate on your own sessions:

```bash
python3 tools/calibrate.py            # dry run, prints the distribution
python3 tools/calibrate.py --write    # regenerate rulebook/thresholds.json
```

`tools/` is in the repository and in an export built with `--with-tests`.

Calibration is also what killed the first design. The first calibration run found the same file edited a median of 12 times per session, so whole-session counts are worthless as evidence of thrash. That is why every signal is windowed. The figure comes from the output of that run, in the build session of 26 August 2026: the median, over the sessions it used, of how often the most-edited file of a session was edited. It is not recorded in the build log and cannot be reproduced from this repository, since the corpus is not part of it.

## What it reads and writes

- It reads the tail of the session transcript that Claude Code names in the hook input. Nothing leaves your machine and there is no network call.
- It keeps per-session state under `~/.claude/cheerleader/state`, pruned after 7 days.
- `install.py` edits `~/.claude/settings.json` as described above.
- `hooks/horme_probe.py` is a separate diagnostic hook that is not installed by default. If you wire it in yourself, it saves full hook payloads, which can include your prompts and tool output, under `~/.claude/horme/probe`. Delete them when you are done.

## Known limitations

Reviewers that had not seen the build went over this release several times. What they found, and what was fixed, is in `docs/BUILD-LOG.md` (checkpoints C7 and C8). These remain.

1. **The verdict check knows four runners.** It sets aside the result lines of unittest, jest, vitest and go test. Output from other tools that prints a standalone `PASS` or `FAIL` still silences it: perl's `prove`, TAP in upper case, jest with a project label, a test path with a space, a go benchmark, and unittest `-v` when the failing test prints something of its own. That is the safe side of the trade. The unittest formats were checked against real output from Python 3.9 and 3.12. The jest, vitest and go formats follow those tools' documented output and were not run for this release.
2. **Output in exactly a runner's format is taken for the runner.** A gate that prints `FAIL` in go test's tab-separated format, a jest line together with jest's summary line anywhere in the same result, unittest's failure header between its two rules, or any line ending in ` ... FAIL` directly under a unittest test id line (the form `-v` prints for a test with a docstring) is not read as a verdict. Nothing in the text separates the two.
3. **Tool text is quoted.** The intervention includes up to 90 characters of an error line, a file name, and up to 60 characters of a repeated command. That text is not fixed data. Treat it like any other tool output that reaches the model. The quoted error is the first error in the window, which is not always the failure that crossed the threshold. When the window holds give-up language and no failing command, the text can still say `0 attempts against the same failure` and name a command that succeeded.
4. **A manual `--explain` uses up the episode.** It writes the same per-session state as the live hook, so diagnosing a live session by hand spends that block's one intervention and one of the session's 4, and starts the cooldown.
5. **Stand-down can trigger on ordinary errors.** Messages such as "no such file or directory", "permission denied", "command not found" and "cannot find module" count as environment blocks. Three anywhere in the window produce a stand-down, which overrides every other diagnosis, even when the cause is a mistyped path or one missing package.
6. **Calibration has no minimum corpus size.** `--write` on a handful of sessions produces thresholds that mean little.
7. **The installer rewrites `settings.json` in place**, and so does the uninstaller when it cannot restore a backup. The write is not atomic, non-ASCII text in your settings is rewritten as escape sequences, and a failed backup does not stop the install. Backup names have a resolution of one second, so a second install within the same second overwrites the first backup and the pre-install bytes are lost. `--dry-run` prints a backup line even when there is no settings file to back up. A settings file whose `hooks` value is not an object stops the installer with a traceback after the backup is written; the settings file itself is left as it was.
8. **On `SubagentStop` it does not read the subagent.** It reads `transcript_path` and drops subagent lines. According to the hooks reference that path is the main session's transcript at this event, the subagent's own is `agent_transcript_path`, which the hook does not read, and context returned here keeps the subagent running. So an intervention at `SubagentStop` is about the parent session and is delivered to the subagent. None of this has been observed in a live session.
9. **The self-test works on a session it wrote itself.** `install.py --doctor` runs every stage, the caps, each watched event and then the hook script as a process, all on a synthetic session in a temporary folder. A fault that only shows on your real session files is outside what it can see.
10. **The denylist is a list.** It catches the phrases it lists, written with straight apostrophes. A rulebook cut down to one rule per group that still catches that group's test phrase would pass its own check. A rule runs with no time limit, so one that backtracks badly on some text hangs the hook.
11. **Very long results are read at both ends, and the transcript only so far back.** Past 60,000 characters the verdict check reads the first and the last 30,000 of a tool result, so a verdict in the middle of such a result is not seen. Where that cut goes through a red test run, the run can read as a verdict, and the hook then stays quiet. The reader takes the last 2 MB and at most 400 lines of the transcript: a tool result further back than that is not seen at all. Tool results whose content is nested rather than plain text are read with their line breaks escaped, so a bare `PASS` or `FAIL` on a line of its own inside them is missed. Every check other than the verdict check reads only the first 4,000 characters of a result.
12. **Verdict words are a short list, matched in one case.** `VERDICT`, `VERIFIER`, `PASS` and `FAIL` count in capitals, and names ending in `-guard`, `code-review` and the sign-off forms in lower case. `Verdict: pass` does not silence it, and neither does a verdict in other words, such as `APPROVED`, `GREEN` or `RED`.
13. **A transcript it cannot read looks like a healthy session.** A wrong path or a file it cannot open gives `not_stuck` and `{}` with no error, in the hook and in a manual run.

## Layout

This is the repository. A skill export is a subset of it: the documents, the installers, `src/`, `rulebook/` and `hooks/`, and with `--with-tests` also `tests/` and `tools/`. Whatever else is named below, and the build log that later sections cite, is in the repository only.

| Path | What |
|---|---|
| `SKILL.md` | The skill (`name: cheerleader`): manual flow, install, tuning |
| `install.py`, `uninstall.py` | Thin entry points for `src/horme/install.py` |
| `src/horme/` | `transcript`, `payload`, `signals`, `classify`, `compose`, `denylist`, plus `state`, `rulebook`, `cli`, `install` and `brand` |
| `rulebook/` | All knowledge as data: thresholds, diagnosis, phrases, denylist, hooks |
| `hooks/` | `cheerleader_hook.py` (single entry point, dispatches on `hook_event_name`) and `horme_probe.py` (optional payload capture) |
| `tools/` | `calibrate.py` (thresholds), `mutate.py` (mutation check), `make_fixtures.py`, `export_skill.py` (builds an installable skill folder) |
| `tests/` | 298 tests, offline |
| `docs/` | `SPEC.md` (the spec as approved), `BUILD-LOG.md` (checkpoints and verifier notes), `NOTES.md` (transcript schema and hook facts) |

## Verifying

```bash
python3 -m unittest discover -s tests -t tests   # 298 tests
python3 tools/mutate.py                          # 151 mutants, all must be caught
```

Both commands need `tests/` and `tools/`: the repository, or an export built with `--with-tests`. Three of the 298 tests read your own transcripts under `~/.claude/projects`. When there are none they skip as one class, and the runner reports 295 tests and one skip. Run the suite with the kill switch not engaged. With `HORME_DISABLE` set or the `DISABLED` file in place, the tests that expect an intervention fail. The tests clear `CHEERLEADER_DISABLE` themselves.

`mutate.py` breaks the source on purpose and requires the suite to notice. Builder and verifier were the same model on this project, so "the tests pass" was not sufficient evidence by itself. During the build the mutation check found four gaps that a green suite had missed. In the review rounds five more runs ended with survivors (two, three, one, one and one), each a test too weak to notice the break. `docs/BUILD-LOG.md` records them and how they were closed. The tool runs every mutant under a temporary home folder.

## How it was built

The code and tests were written by Claude in Claude Code, to a spec the author approved and behind human approval gates. `docs/BUILD-LOG.md` is the checkpoint log, in the builder's own words. It includes two design corrections that came from testing, not from planning, and one case where a fully green suite still produced four defects that only reading the output revealed. After the build, reviewers that had not seen it found five defects in the first version. The human-visible notice was emitted in the wrong place, the installed command exited 2 on every event once the folder moved (which the hooks reference treats as blocking on `PostToolBatch`), the verdict check went silent on ordinary red test runs, the denylist let messages through when it could not be loaded, and the health check passed for an engine that could not be imported. Three rounds of independent verification followed the fixes. The code changes made after the third round were checked by the suite, the mutants and a comparison run, not by a further independent round. This README, `SKILL.md` and the build log were then reviewed against the code and corrected. Checkpoint C7 in the build log records the defects, the fixes, and what the verifiers still flagged at the end. That review of the documents found one more defect of the same weight: the verdict check read only the first 4,000 characters of a tool result, so a verdict at the end of a long report went unseen. Fixing it took three attempts and three more rounds of independent verification. The first two failed, once on a pattern that took 16 seconds on one long line and once on how a very long result is cut; the third passed with notes. Checkpoint C8 records all three, and what was added after the last round without a further independent check (tests only).

## Research basis, and its limits

The phrase templates follow a research brief on encouraging people who are stuck on a task. The brief is a report the author commissioned from an AI research tool. It is not part of this repository, and its claims were not verified beyond the spot check described below. Each slot in `rulebook/phrases.json` has a `source` field: the author, theory or study it draws on as cited in that brief, or the section of the brief it follows. Several entries give a name without a year or a title. The concrete next-step phrases (`moves` and `fallback_moves`) carry no source.

The research is entirely human-subject, and modest even there. A large national trial of a growth-mindset intervention (Yeager et al. 2019) raised grades by 0.10 grade points among lower-achieving students (standardised effect 0.11), and Bandura treats verbal persuasion as a weaker source of efficacy than mastery experience. What plausibly transfers to a language model is structural: decomposition to a proximal subgoal, relabelling a cause as specific and temporary, an if-then plan. The affective mechanism is not assumed to transfer.

A spot check against public sources on 13 November 2026 confirmed the Yeager et al. 2019 figures and most of the other cited works it reached, softened two attributions that went beyond their sources, and removed two statistics that could not be confirmed. It questioned two attributions in `rulebook/denylist.json`: Fredrickson for the entry on forced positivity, and the years given for Brummelman and colleagues. Both are kept, and each is marked in that file as not confirmed. Citations the check did not reach remain as cited in the brief.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`.

Copyright 2026 AKINTECH Driven Ltd

This is an independent project. It is not affiliated with or endorsed by Anthropic.
