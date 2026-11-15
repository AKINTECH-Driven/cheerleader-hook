---
name: cheerleader
description: Diagnose a stuck coding session and produce one calibrated, research-grounded intervention that ends in a concrete next step. Use when work has stalled (the same test failing repeatedly, the same file edited over and over without the error changing, a command re-run with identical results) or when you notice yourself saying "I'm not sure why" or "let me try a completely different approach" for the second or third time. Also use when the user asks why the cheerleader fired, asks to check, explain or diagnose a stuck session, asks whether they or Claude are stuck, or asks to install, uninstall, disable, tune or calibrate the encouragement hooks. Triggers on "am I stuck", "unstick me", "run the cheerleader", "cheerleader doctor", "why did that fire". Not for ordinary failing tests you already know how to fix, and never for judging whether work is correct, because it does not adjudicate.
---

# Cheerleader

The engine is called **HORME** (Ὁρμή, the daimon of impulse and effort, the *setting-into-motion*
of an action), which is the job. The human-subject work behind this skill treats verbal encouragement
as a weaker lever than a small success of one's own, so the useful thing to do for someone stuck is to shrink
the task until they succeed at something. So this ends in a next step, not a pep talk.

## What it is

A deterministic pipeline: session transcript in, at most one intervention out. **No model call
anywhere inside it**: the diagnosis, the thresholds and every phrase are fixed data, so the same
session always produces the same intervention. That is the point. An encouragement layer that
improvises is one that can be talked into saying whatever a stuck model wants to hear.

Normally it runs by itself, from hooks. This file is the manual path.

## The flow

**1 · Diagnose.** Run the commands in this file from the skill's own folder, the one that holds this file.
Point the engine at the session transcript. `$TRANSCRIPT` is the path of the session's `.jsonl` file under
`~/.claude/projects`, and `$SESSION` is a name you choose. A manual run records that it fired, exactly as the
hook does, so use a throwaway name unless you mean to spend that session's one intervention for this block:

```bash
PYTHONPATH=src /usr/bin/python3 -m horme.cli --force --event Stop --explain \
  --transcript "$TRANSCRIPT" --session "$SESSION" < /dev/null
```

`--explain` writes the diagnosis to stderr and the hook JSON to stdout. It reports which signals
crossed which measured thresholds, the block type, the severity, and the research behind each slot.

**2 · Read the diagnosis, not just the text.** Four block types, wanting different things:

| Block | What it means | The move |
|---|---|---|
| `cognitive` | The next step is not known: one failure repeating, edits not changing the error | Decompose. Get one smaller thing passing. |
| `motivational` | Motion without progress: same command, same files, no new information | Change the route; from severity 2 up, first mark what has landed. |
| `emotional_analogue` | Capitulation language with no concrete driver behind it | Validate, then decompose anyway. |
| `infeasible` | The environment is blocking: missing binary, missing permission | **Stand down.** Say what is needed. Do not persist. |

**3 · Act on the next step.** For a cognitive or emotional-analogue block that is the `Smallest next
move:` clause, and everything before it exists to make it land. A motivational block offers routes to
choose between, and an infeasible one ends in a stand-down: say what is needed, or take the route that does
not need it.

## What it will not do

- **Never says anything is correct.** Not "that looks right", not "it works", not "ship it". A
  denylist over its own output suppresses any message that matches, and every message when the denylist
  itself cannot be trusted. Its failure mode is not bad morale
  advice, it is sycophancy: an encouragement layer speaking near a verdict is exactly what could turn
  a FAIL into a PASS.
- **Goes silent while a verdict is being decided.** This is a keyword match on the last three tool
  results: `VERDICT`, `VERIFIER`, a standalone `PASS` or `FAIL`, a name ending in `-guard`, `code-review` or
  sign-off. The result lines of unittest, jest, vitest and go test are set aside first, so a red run in
  those does not silence it (see `README.md`, Known limitations, for the runners it does not know).
- **Never returns an error or a blocking decision.** It exits 0 on every path and never returns exit 2 or
  `decision: block`. An intervention at `Stop` still has an effect on the turn: according to the hooks reference,
  context returned there continues the conversation so that Claude can act on it.
- **Speaks once per block.** One episode, one intervention, then silence until the failure changes shape.
- **Will not cheer an impossible task.** Missing `docker`, missing `pandoc`, a permission you do not
  have: it names the blocker and says that more attempts will not change it.

## Install

```bash
/usr/bin/python3 install.py --dry-run     # show the events and the command that would be added to ~/.claude/settings.json
/usr/bin/python3 install.py               # apply
/usr/bin/python3 install.py --doctor      # is it wired in, does the self-test pass, does the stored command run
/usr/bin/python3 uninstall.py             # surgical removal; restores the pre-install bytes if nothing else changed
```

It backs the settings file up timestamped first, refuses outright on one it cannot parse, and
appends to existing hooks rather than replacing them. The hooks reference says that edits to
settings files are normally picked up automatically. If the hook does not show up in a running session,
**restart Claude Code**.

Turn it off without uninstalling: `export CHEERLEADER_DISABLE=1` (any non-empty value disables it), or
`mkdir -p ~/.claude/cheerleader && touch ~/.claude/cheerleader/DISABLED`.

## Tuning

Everything tunable is data in `rulebook/`, and every slot has a `source` field: an author, a theory, a study,
or the section of the research brief it follows.

- `thresholds.json`: **measured**, never hand-typed. Regenerate with
  `/usr/bin/python3 tools/calibrate.py --write`, which replays real sessions and sets each threshold
  one above the 99th percentile of the worst value those sessions reached.
- `diagnosis.json`: signals to block types · `phrases.json`: slots and their sources
- `denylist.json`: what it may never say · `hooks.json`: events and rate limits. Its `kill_switch` entry
  only describes the switch: the variable and the file name are fixed in `src/horme/brand.py`.

Verify it end to end: `/usr/bin/python3 -m unittest discover -s tests -t tests` (298 tests; with no transcripts of your own the runner reports 295 and one skip) and
`/usr/bin/python3 tools/mutate.py` (151 mutants, all must be caught).
These two commands and `tools/calibrate.py` need `tests/` and `tools/`, which the default skill export leaves out
(`tools/export_skill.py --with-tests` keeps them).

## Honesty

The research behind this is entirely human-subject. Nothing in it was measured on a language model,
and the effect sizes are modest even in humans: a large national trial of a growth-mindset intervention
(Yeager et al. 2019) raised grades by 0.10 grade points among lower-achieving students (standardised effect
0.11), and Bandura treats verbal persuasion as a weaker source of efficacy than mastery experience. What plausibly
transfers is structural: decomposition to a proximal subgoal, relabelling a cause as specific and
temporary, an if-then plan. Not the affective mechanism. **This ships no efficacy claim it has not
measured, and it has not measured any.** Thresholds come from an unlabelled corpus treated as
healthy, which biases them upward, toward silence. Sampling every third tool result can miss a peak, which pulls the other way.

*(The Python package stays `horme`; only the skill is named `cheerleader`.)*

Known limitations of this release are listed in `README.md`. Read them before relying on the hook.
