# Build log

> **Note for this release.** This log was written by Claude during the build, checkpoint by checkpoint, as the record of the builder and verifier passes. It is published as written, apart from the name of one desktop app removed in two places. "Intake" and "plan gate" are the author's approval checkpoints. `CLAUDE.md` and `PROGRESS.md` were working files: this log is the second, and parts of the first are in `NOTES.md`. File names reflect the time of writing: `hooks/horme_hook.py` is now `hooks/cheerleader_hook.py`, and runtime state now lives under `~/.claude/cheerleader`. Test counts are those of the build at each checkpoint. This release adds 4 tests in `tests/test_calibrate_provenance.py`, so its suite is that much larger than the last count in the log.

<!-- Features in dependency order. One feature in flight at a time. -->

## Features
- [x] 1. Signal reader — tail-read transcript JSONL + tolerant hook-stdin parser → `SignalSet`; payload probe
- [x] 2. Block classifier — SignalSet → BlockReport (cognitive/motivational/emotional-analogue/infeasible), rulebook-driven
- [x] 3. Intervention composer — BlockReport → intervention text, fail-closed denylist  [PLAN GATE: anti-sycophancy]
- [x] 4. Hook layer — event wiring, session state, rate limiting, kill switch, always-exit-0
- [x] 5. SKILL.md + installer — orchestrated flow, install/uninstall with settings.json backup + exact restore

## Checkpoint log
<!-- One line per checkpoint: type(scope): summary · tests N/N · PASS|FAIL -->
- C13 · docs(review): review before publication, nothing private found, the live-use statement supported by the records and reworded to say so, wordings corrected · tests 294/294 · PASS (six seats, each finding read a second time) · mutants not run again
- C12 · docs(readme): the status line on live use corrected from the session records, no code change · tests 294/294 · PASS · mutants not run again
- C11 · docs(release): the origin of the research brief stated, two attributions marked as unconfirmed · tests 294/294 · PASS · mutants 151/151
- C10 · feat(signals): any lower-case name ending in -guard is a gate, found in linear time; citations and hook notes corrected in the rulebooks · tests 294/294 · PASS WITH NOTES (one verifier round, two seats) · mutants 151/151
- C9 · docs(skill): the source README and SKILL carry the reviewed wording, a test holds both to what is measured, dist rebuilt · tests 288/288 · PASS WITH NOTES (one review round, two seats) · mutants 140/140
- C8 · fix(signals): the verdict check reads whole tool results (60,000 characters, both ends past that), linear test-file check, lighter hook start-up · tests 280/280 · PASS WITH NOTES at the third verifier round, test additions after it not independently re-verified · mutants 140/140
- C7 · fix(review): top-level notice, non-blocking installed command, runner output is not a verdict, fail-closed denylist, doctor self-test · tests 231/231 · PASS by suite and mutants, last pass not independently re-verified · mutants 103/103
- C6 · feat(export): skill renamed `cheerleader`, brand constants centralised, generated self-verifying export · tests 151/151 · PASS · mutants 33/33
- C5 · feat(skill): SKILL.md, install/uninstall/doctor, README · tests 149/149 · PASS · mutants 31/31
- C4 · feat(hooks): CLI entry, session state, rate limits, kill switch, always-exit-0 · tests 132/132 · PASS · mutants 27/27
- C3 · feat(compose): rulebook phrases + fail-closed denylist + specificity/repetition guards · tests 99/99 · PASS · mutants 20/20
- C2 · feat(classify): rulebook-driven diagnosis + suppression + episode identity · tests 70/70 · PASS · mutants 13/13
- C1 · feat(signals): transcript reader + windowed SignalSet + tolerant payload parser · tests 47/47 · PASS
- C0 · chore(skeleton): scaffold + CLAUDE.md + PROGRESS.md, transcript schema verified against 438 real sessions · tests 0/0 · PASS

## Verifier notes
<!-- Only FAILs and their resolutions need detail. -->

### C1 · Feature 1 — verdict FAIL, then PASS after fix
Builder and verifier are the same model here, so "the suite is green" is weak evidence.
`tools/mutate.py` breaks the code on purpose and requires the suite to notice. First run:
**6/7 caught, 1 SURVIVED** — deleting the `isSidechain` exclusion changed nothing, because
neither the fixtures nor the sampled real transcript contained subagent lines. That is a real
coverage hole, not a nit: without it, one flailing Explore subagent would make the parent
session read as stuck and HORME would fire on the wrong thing. Fixed by adding
`with_sidechain.jsonl` plus three tests. Second run: **7/7 caught**. Verdict PASS.

Two assertions changed during the feature; both were corrected *upward*, neither was relaxed
to make a verdict come out right:
- `consecutive_tool_errors == 0` on the clean fixture was simply wrong — that session hits one
  error and recovers, so max-run is truthfully 1. The real need was a distinct signal, so
  `current_error_run` was **added** (erroring now vs erred once) and both are asserted.
- `tool_calls == []` became `== ()` after the code was made consistently immutable; a new test
  proves the `EMPTY` singleton cannot be poisoned by a caller. Net: one more test, not one fewer.

### Design correction found by testing, not by planning
The SPEC said HORME suppresses when the transcript is "verdict-adjacent (test results, review
verdicts, gate output)". Writing the fixtures showed that would make the skill inert: a red test
suite is the single most common stuck state, so suppressing on `FAILED (failures=1)` silences
HORME exactly when it is needed. The distinction that actually carries the anti-sycophancy risk
is **adjudication** — a verifier/review/gate verdict being decided — not failure output.
`ADJUDICATION` now matches VERDICT/VERIFIER/standalone-uppercase PASS|FAIL/`*-guard`/code-review,
and deliberately does not match `FAILED`. Locked by
`test_a_plain_failing_test_run_is_NOT_adjudication` and by a mutant.

### C2 · Feature 2 — verdict FAIL, then PASS after fix
Mutation run 1: **12/13 caught, 1 SURVIVED** — deleting the `overrides` branch changed nothing,
because `infeasible` is already first in the diagnosis order so it wins the label regardless.
But `overrides` does a second job: it *narrows the evidence*. `docker: command not found`
repeated five times also crosses the cognitive threshold, so without the override those
crossings leak into an infeasible report and the composer would be handed material to build
decomposition advice for a task that cannot be done — precisely the move the brief rules out.
Closed by asserting the consequence (`crossed` must contain only `env_blocked_errors`), not the
mechanism. Run 2: **13/13**. Verdict PASS.

### Second design correction found by testing
The first classifier read `stuck_repeat_error` as `emotional_analogue`, because the fixture
crosses both capitulation and repeated-error thresholds and self-report was ordered first.
That is wrong: a model saying "I'm not sure why" *while one assertion keeps failing* has a
cognitive block whose symptom is capitulation. Comforting it and stopping there would be the
"false growth mindset" failure the brief warns about — praising effort while the strategy is
still wrong. Resolved the way the brief itself resolves it: Stage 1 picks the corrective move
(so concrete evidence now outranks self-report, and `emotional_analogue` became the fallback
for capitulation with no driver behind it), while Stage 2's "always open with validation"
became a `validate_first` modifier that rides on every block type. Both branches are tested.

### C3 · Feature 3 — the green suite was not enough
All 94 tests passed on the first implementation. Then verifier step 4 — *actually run the
thing* — was applied, and rendering one real intervention per block type exposed four defects
no assertion had covered:
1. The specific phrase (`AssertionError: expected 4 cells, got 1, in importer.py`) was emitted
   **verbatim three times** in one intervention. Specific is the brief's strongest style finding;
   specific-and-repeated reads as generated text and burns the sincerity the effect depends on.
2. `autonomy` restated `decompose` word for word — "Smallest next move: X. You could X, or Y."
   Twice the context cost for no added information.
3. `if_then` rendered "...instead of reading it again **instead of editing further**" — the
   contrast clause was hardcoded into a template that already contained one.
4. `n_fail` reported "docker: command not found, **10** times" while counting docker *and*
   pandoc failures. A false statement about the very thing the sentence points at.

Fixed by: emitting the full specific phrase once and referring back to it afterwards; allocating
a **distinct** move to each of decompose/autonomy/if_then from a ranked pool with generic
fallbacks; removing the hardcoded contrast; and counting only the named failure's own signature.
Five new tests lock each property, and six new mutants prove they bite. Final: 99/99, **20/20
mutants caught**. Verdict PASS.

The lesson is worth keeping: for a component whose output is prose, a green suite proves the
guardrails hold, not that the writing is any good. Reading it is a required step, not a courtesy.

### C4 · Feature 4 — verdict FAIL, then PASS after fix
Mutation run: **25/27 caught, 2 SURVIVED**, and both survivors were weaknesses in the *tests*:
- The path-traversal test asserted that no file appeared outside the state directory. Under a
  `/tmp` state dir an escaping write simply fails on permissions, so a deleted sanitiser hides.
  Under the real `~/.claude/horme/state` the parent directories exist and it would not.
  Rewritten to assert the **computed path** is contained, across eight hostile session ids.
- `test_exit_is_always_zero` never actually raised anything, so the safety net was untested.
  Added fault injection: each of `signals.extract`, `classify.classify`, `compose.compose` and
  `transcript.read_tail` is made to raise in turn, and the hook must still exit 0 with `{}`.
Run 2: **27/27**. Verdict PASS.

Live end-to-end run of `hooks/horme_hook.py` as a real process: fires once on the stuck fixture,
silent on the repeat, silent on garbage stdin, exit 0 throughout. **p95 22.5 ms including full
Python interpreter startup**, against the 50 ms SPEC budget.

### C5 · Feature 5 — verdict PASS
149/149 green, **31/31 mutants caught** across all five features. Installer verified against a
settings fixture shaped like the real one, including a pre-existing `SessionStart`
hook: install appends rather than replaces, refuses outright on a settings file it cannot parse,
and uninstall removes surgically then restores the pre-install bytes exactly — while a separate
test proves a blind copy-back would have discarded edits made after install, which is why it is
not one.

`install.py --dry-run` was run against the real `~/.claude/settings.json` (read-only) and
correctly reported the existing hook as preserved. **HORME was deliberately NOT
installed**: it edits global config, so that is the user's call, not the builder's.

### C6 · Export as `cheerleader` — verdict PASS
Renaming exposed a latent drift hazard: the marker `[HORME]` was an independent string literal in
`compose.py` (which writes it) and `signals.py` (which reads it back to dedupe). Changing one and
not the other would leave the tool unable to recognise its own past interventions — repeating
itself forever, silently, with every test still green. Now one constant in `src/horme/brand.py`,
locked by a **round-trip** test (compose the text, feed it back through the detector) rather than
a constant comparison, plus a mutant. The frozen fixture is the independent anchor that catches it.

Reading the dry-run output caught a second one: the message promised a `.horme-backup-` file while
the writer had been changed to produce `.cheerleader-backup-`. A dry run that misstates what it
will do is worse than no dry run. Both strings now derive from `brand.NAME`, with a test.

`tools/export_skill.py` builds `dist/cheerleader/` from the repo and **runs the suite inside the
export** before declaring success — the shipped skill cannot drift from the tested one. Verified
relocatable: copied to a random temp path, the suite, the live hook, the installer's self-path
resolution and the rulebook all resolve correctly from there. 151/151, 33/33 mutants.

### C7 · Review fixes of 2026-11-13: three verifier rounds, last pass not re-verified
Before publication, reviewers that had not seen the build read the code rather than its summary.
They found five defects that 151 tests and 33 mutants had passed over. All five were of one kind:
the code did what its tests said, and the tests did not say what the contract required.

1. **The one-line notice never reached the user.** `systemMessage` was nested inside
   `hookSpecificOutput`; Claude Code reads it at the top level of the hook's answer. The test
   asserted the nested position, so it was green. Fixed in `cli._emit`, the Out contract in
   `SPEC.md` corrected, and the tests now assert the top-level field.
2. **The installed command could exit 2 on every event.** It was `python3 "<hook>"`. When the
   folder moves, python cannot open the script and exits 2, the one status a hook must not
   return. The first review said this keeps the session from stopping on `Stop`. The hooks
   reference, read again on 2026-11-13, is narrower: on `Stop` and `SubagentStop` exactly this
   case (exit 2, empty stdout, a missing-file message) counts as a non-blocking error, while on
   `PostToolBatch` exit 2 stops the agentic loop before the next model call. Neither was
   observed in a live session. The command now runs the script only if it exists, holds the
   output back until the script has exited 0, and ends in `true`, so it no longer depends on
   how an exit status is read; both paths are shell-quoted.
   `doctor` runs a stored command only if it parses back into exactly what the installer writes.
   An entry in the older format, or anything else that merely names the hook file, is reported
   and not run.
3. **The verdict scan went quiet on ordinary red runs.** `ADJUDICATION` matched any standalone
   `FAIL` or `PASS`, and unittest's failure header, the file line of jest and vitest and go
   test's result lines all carry one. The C1 design correction promised that test output stays
   out of it. That held for `FAILED (failures=1)` and for nothing else. The scan now sets aside
   lines in exactly those runners' formats before it looks for a verdict word. The unittest
   shapes are pinned to captured output of Python 3.9 and 3.12 (plain, `-v`, a docstring, a
   subtest). The jest, vitest and go shapes are written from the documented formats; none of
   those runners was run here.
4. **The denylist failed open.** A missing, unreadable or emptied `denylist.json`, or one rule
   that did not compile, made `check` answer "clean". It now answers with a trip in group
   `unavailable` and the composer suppresses the message. Each group also has to catch a test
   phrase of its own, so a rulebook that loads and matches nothing is refused as well.
5. **`--doctor` passed with a dead engine.** The hook hides every failure behind `{}` and exit 0,
   and doctor looked at the exit status. The hook now has `--selftest`: rulebooks, denylist,
   transcript, signals, classify, compose, the rate limits, every watched event, then the hook
   script as a real process, all on a synthetic stuck session under a throwaway home. Doctor
   reads that answer, runs the stored command as Claude Code would, and exits non-zero on a fault.

PLAN gate: the plan was shown in the session and approved under the standing rule for plans
with no open decision. Each fix began with tests that failed against the old code.

**Verifier rounds** (three seats in rounds 1 and 2, two in round 3; each was given the diff and
the contract, not the builder's summary):
- Round 1: verdict scan **FAIL**, installer and denylist pass with notes. The runner patterns
  were too loose (a gate line such as `FAIL app.js` was let through), `unittest -v` was missed,
  a rulebook with every rule gutted still passed, doctor executed any command that mentioned
  the hook's file name, and the self-test was shallow.
- Round 2: all three seats pass with notes. Tightened further: a unittest id needs the `test`
  prefix and a dotted class, go's package line needs its tabs, a jest line counts only beside
  jest's own summary, and the self-test gained the process stage.
- Round 3: verdict scan pass with notes; self-test and installer **FAIL** on completeness, with
  no blocking defect: the self-test never reached the caps, ran one event only, and accepted
  event names Claude Code does not fire. All three were fixed, and the widths of the runner
  patterns were pinned from both sides in `tests/_samples.py`.

Three rounds is the cap, so **the pass after round 3 has not been seen by an independent
verifier.** What stands behind it is the suite, the mutants below, and a comparison of the old
and the new scan over 400,000 texts generated from a vocabulary of 180 lines: none where the
new scan is quieter than the old one, which follows from how it is built (it only sets lines
aside), and 16,359 where the old scan went quiet and the new one does not. In those, the lines
set aside fall into 39 shapes. Most are runner formats. Some are lines a gate could print
identically, set aside only where a runner would print them: under a unittest id line, beside
jest's summary line, or in go test's or unittest's own layout. That is the accepted trade
below, and the comparison cannot tell those apart either.

**What the mutants taught, again.** The list grew from 33 to 103. Three runs had survivors
(70 of 72, 81 of 84, 102 of 103) and every one was a weak test, not dead code. The last: the
self-test's check that a firing is recorded could be deleted unnoticed, because the cooldown
check at the same stage caught the same break. The test now names the check that has to notice.

One mutant pointed the self-test at the live state directory, and running it wrote a file into
the real home folder. The file was removed, and `tools/mutate.py` now runs every suite under a
throwaway home with stdin closed. A tool that breaks code on purpose must not be able to reach
outside its copy.

**Accepted cost, pinned in `tests/_samples.py`.** Output in exactly a runner's own format is
taken for the runner (`INDISTINGUISHABLE`), and runner formats the scan does not know still read
as verdicts (`STILL_QUIET`), which is the safe side. If the first trade is not wanted, the
narrower alternative is to keep the unittest exemptions only, the one format checked against
real output. `INDISTINGUISHABLE` has four entries: go test's package line, a jest file line with
its summary, unittest's failure header between its two rules, and any `<text> ... FAIL` line
directly under a unittest id line (the `-v` docstring form).

Still open after this round:
- typographic variants of a denied phrase, and one test phrase per group rather than per rule;
- no time limit on a denylist rule: a rule that backtracks badly hangs the hook (a round 2
  verifier stopped one after 120 s);
- no runner other than unittest checked against a real run;
- the mutants are the builder's own list, and the width of each runner exemption is pinned by
  examples, not proved (round 3);
- the self-test reads a session it wrote itself, in process and through the hook script, never
  a real transcript (round 2).

A later review of the release documents (13 Nov, three seats) found two more gaps in the verdict
scan that this round did not touch. Only the first 4,000 characters of each tool result are
kept, so a verdict printed at the end of longer output is not seen. And the verdict words are
matched in one case only (`VERDICT`, `PASS`, `FAIL` in capitals; `code-review` and the sign-off
forms in lower case). Both went into the README's limitations. The first was fixed afterwards
(C8 below); the second stands.

Final: 231/231 tests, **103/103 mutants caught**, nothing written outside the throwaway home.

### C8 · The verdict check reads the whole result: three attempts, three verifier rounds
The defect: the transcript reader kept the first 4,000 characters of each tool result and
the verdict check read that. A verifier prints its findings and then its verdict, so the
verdict of any long report was out of sight and the hook spoke next to it. This is the one
gap C7 left that contradicted a headline promise.

**Measured before choosing.** On 164 real sessions (11,274 positions, every third tool
result), the old reading silenced the hook at 15.3% of positions, the first and last 4,000
characters at 16.6%, whole results at 17.3%. Whole results cost little extra silence and
leave no unread middle, so that was chosen, with a cap of 60,000 characters per result.
Every other signal still reads the first 4,000 characters: the thresholds were calibrated
on that, and a test pins it.

**Attempt 1: FAIL at all three seats.** Each long result was kept whole for the verdict
check, and past the cap as its two halves joined by a note line. The verifiers found:
- a blocker. One pattern (`[^/\s]+\.(?:test|spec)...`, searched) is quadratic in the length
  of a token. At 4,000 characters that was 38 ms and nobody had seen it. At 60,000 it was
  16 seconds for one line, and the hook has no timeout of its own. Raising a cap changes
  what every pattern behind it can cost;
- the note line did not keep the halves apart: unittest's rule of dashes is looked for two
  lines down, so a rule beyond the cut vouched for a header before it;
- what the cut left of a line could pass for a runner's line;
- the tests would have accepted a version that kept long results only when they were
  errors (a verifier's answer is not an error), a lower cap, and a version that read only
  one of the last three results whole.

**Attempt 2: speed seat pass with notes, the other two FAIL.** The test-file check became
three linear searches (equal to the old pattern on 1.65 million generated paths), only lines
that carry a PASS or FAIL are examined, the halves became separate texts with a mark on
each cut edge, and the tests were rewritten with the sizes written out. The verifiers found:
- a blocker again, at the same place. A mark is not a rule. A vitest line cut right after
  its `>` read as the start of a trail, because the space before the mark completed the
  pattern; a jest summary cut after `1 failed` read as a summary and vouched for a gate's
  line above it;
- no test above about 100,000 characters, and four loosenings of the test-file rule that
  the suite accepted.

**Attempt 3: pass with notes at all three seats, no blocker.** The line the cut goes
through is now kept apart from the whole lines of its half and read as it stands: any
verdict word in it counts, no runner rule applies to it, and it takes no part in what the
whole lines are. The whole lines of the first half end in a mark line, because go test's
closing FAIL is excused only as the last line of the output. Neighbours are found by
bisection. A sweep test tries every alignment of the cut for nineteen line groups (the
same code with halves of 300 characters: 5,276 alignments, 2,506 of them with the verdict
word in view). What the verifiers ran:
- the scan seat built its own oracle and ran 5.42 million cases at the real size, the cut
  at every character of every line of 130 groups and 2,721 one-feature variants, four kinds
  of line break, four result sizes: 0 violations (the same harness finds 184 on attempt 2).
  `adjudicated` answered as in attempt 2 on about 3 million texts, one set exhaustive;
- the speed seat found every cost linear. Its worst shape, tens of thousands of blank
  lines around a few result lines, costs 21 to 25 ms for one 60,000-character result on a
  loaded machine, so three such results in a row use about the whole 50 ms budget. Ordinary
  output costs 3 to 5 ms per result. Every other signal was identical on 3,000 generated
  sessions and the calibration table came out the same;
- the tests seat re-applied 21 wrong versions from round 2 (all caught), wrote 91 new ones
  (84 caught; of the 7 accepted, 5 change no behaviour) and applied 66 mutants by hand (all
  caught). Its open points were a slow version that looks up the failed-package flag for
  every line, a walking neighbour search, and two wrong ideas of what a blank line is.

That was the third round, which is the cap. **After it, and not seen by an independent
verifier:** three timing shapes, a test for lines of spaces and indented lines, four mutants
for the tests seat's open points, a test that counts what the neighbour search reads, and the
corrected timing figures. Tests and comments only; no behaviour changed.

**On real transcripts, final code.** 164 sessions, 11,345 positions: silenced at 15.4%
before and 17.4% now. 221 positions are newly silenced (the verdict word sits in a Bash
result at 161 of them, a file read at 64) and none is silenced no longer. 8 of 34,197
results are longer than the cap.

**Also fixed here: the hook's start-up.** Timing this fix showed that C7 had made every
run slower. The self-test needs subprocess, shutil and tempfile, and they sat at the top of
the entry module, so every tool batch paid for them: importing it took 58 ms against 34 ms
at the last commit, measured under load. They are loaded inside the self-test now, and one
test checks the entry module and another the hook script itself.

**Accepted and pinned in the tests.** Past 60,000 characters the middle of a result is not
read. A red run that the cut splits can read as a verdict, and so can a word cut in two
(`FAIL` out of `FAILED`): both toward silence. Within one result a jest or vitest summary
vouches for a file line at any distance, since jest prints it last however long the run;
`INDISTINGUISHABLE` has a fifth entry for that.

**Still open after C8.**
- The reader takes the last 2 MB and at most 400 lines of the transcript. A tool result
  further back is not seen at all. Older than this fix, not touched by it.
- Tool-result content that is nested (a list inside a block, a dictionary) is turned into
  text with its line breaks escaped, so a bare PASS or FAIL on its own line inside it is
  missed. Also older than this fix.
- The texts for the verdict check are prepared for every long result in the tail, though
  only the last three are read: about 0.5 ms for each result over the cap.
- The timing tests catch a wrong order of growth, not a slowdown by a constant factor.
- Verdict words are still matched in one case only.

**What went wrong on the way, besides the code.** A verifier ran the hook once without its
stand-in home and left a state file in the real one; it was removed, and the third round
was told to check its own commands. A mutation run stopped halfway left two temporary
folders behind; removed. The test helper that builds filler text was quadratic and made the
suite take 109 seconds until it was fixed.

The mutants had one more thing to teach. The first full run of the 140 on a quiet machine
ended 139 of 140. A neighbour search that walks the lines is only some forty times slower
inside 60,000 characters, and the timing test told that apart while five runs shared the
machine and not when one had it alone. That check now counts what the search reads, which
does not depend on the machine. A clock is a fair test for a wrong order of growth that
reaches seconds, and for nothing smaller.

Final: 280/280 tests, **140/140 mutants caught** (the list grew from 103; two runs on the
way had a survivor: 125 of 126, a missing sample for the `__tests__` rule, and the 139 of 140
above), nothing written outside the throwaway home.

### C9 · The source's own README and SKILL, and a test for what they state
Since C7 the corrected wording existed only in the copy prepared for release. The README and
the SKILL file of this repository still said 150 tests and 33 mutants, "never blocks", hooks
"snapshotted at session start", a restore "byte for byte", and they described none of the
limits found since. `dist/` shipped exactly those two files.

**Ported, not retyped.** A script in the release tooling derives both documents from the
reviewed ones by exact replacements that stop when either side has changed shape, with every
number measured from this tree. The SKILL frontmatter, which is the installed skill's trigger
text, is byte for byte what it was. Each document describes its own tree: this repository's
file names and test counts, and the citations as its rulebook files really have them.

**The port found a false sentence of its own.** The reviewed text says a name ending in
`-guard` silences the hook. That is true of the release copy, whose pattern was generalised.
At C9 the pattern here matched four gate tools by name and nothing else, so the ported
sentence was wrong for this code, and the documents listed what the code matched. C10 below
brought the rule itself over.

**A test for the documents.** `tests/test_docs.py` (8 tests) holds README and SKILL to what
is measured: how many tests and mutants, the caps on how often it speaks, the calibration
figures, how far the verdict check reads, the reader's tail budget, which gate names count,
and the example under "What it says" against what the command prints. Written first: five of
its first six tests failed against the stale documents. Writing it also showed that the
release tool counted tests with a pattern that took a helper function for a test; it counts
from the syntax tree now.

**Review: both seats pass with notes.** One reviewer checked the two documents against this
code, the other unpacked both exports and followed the documents as a user would. No blocker.
Each note was reproduced before the wording was changed:
- the `kill_switch` entry in `rulebook/hooks.json` is read by nothing; the switch is fixed
  in `brand.py`, and the tuning section said otherwise;
- the `Smallest next move:` clause exists for two of the four block types only;
- the hand-diagnosis example needs a fixture that the default export does not ship, and a
  transcript that cannot be read answers `not_stuck` and `{}` like a healthy session;
- verdicts in other words (`APPROVED`, `GREEN`, `RED`) do not silence it, and `PASS` or `FAIL`
  counts wherever no letter adjoins it (`FAIL_FAST`, `PASS2`);
- which paths exist only in the repository, what an export contains, and that the default
  export is already the skill folder;
- left behind after uninstall: the backups, the state folder, and a `settings.json` holding
  `{}` when there was none before;
- at `SubagentStop` the hooks reference says the path it reads is the main session's and
  that the context is delivered to the subagent.

**Found by the reviewers in the code and not fixed, now in the README's limitations.** With
give-up language and no failing command in the window, the text says `0 attempts against the
same failure` and names a command that succeeded. A settings file whose `hooks` value is not
an object stops the installer with a traceback after the backup is written.

`dist/` is rebuilt from this state: the default folder (23 files), its zip, and the zip with
tests and tools (55 files). Both were unpacked and run under temporary homes: install,
doctor, the stored command, self-test, uninstall, and for the larger one the suite.

No second review round followed the corrections: each was checked by reproducing the
behaviour it describes, and the numbers by the new test. The installed copy of the skill was
not touched.

Final: 288/288 tests, **140/140 mutants caught**.

### C10 · The gate-name rule and the corrected citations, in this repository too
After C9 two things still existed only in the copy prepared for release: the rule that any
lower-case name ending in `-guard` is a gate, and the corrections to citations and hook notes
in three rulebook files. Both are here now, so the two trees differ only in private names
and paths.

**The rule was ported, not the pattern.** In the release copy the rule was one pattern,
`\b[a-z][a-z0-9]*(?:-[a-z0-9]+)*-guard\b`. Timed before porting, it turned out to have the
fault C8 was about: searched, it starts again at every word of a long hyphenated token and
reads to the end each time. 0.6 s on 16,000 characters, 8.3 s on the 60,000 the verdict check
can read. The release copy had carried that since its first build, and none of the C8
verifiers saw it, because they were given this repository's code, which matched four names.
`_GateName` in `signals.py` finds every `-guard` that ends a word and walks back through the
parts of the name. The pattern stays in the tests as the definition the code is held to.

The rule had no test at all before, in either tree, and no mutant. Now: samples checked
against the pattern itself, every letter and digit a name may hold, a comparison with the
pattern on 30,000 generated strings in the suite, and long hyphenated input among the
timing shapes.

**The citations.** Two test statistics given for Bandura and Schunk 1981 could not be
confirmed and are gone from `phrases.json` and `diagnosis.json`. That repetition makes
encouragement read as insincere is now marked as this project's inference from Henderlong
and Lepper 2002 and Hattie and Timperley 2007, in `diagnosis.json`, `hooks.json` and a note
in `phrases.json`. The notes in `hooks.json` about which hook events can add context, which
events the installer wires and what `SubagentStop` reads follow the public hooks reference
as read on 2026-11-13. None of these texts feeds behaviour except one `source` field, which
`--explain` prints.

**Verification: both seats pass with notes, no blocker.**
- The rule seat compared the code with the pattern on about 327 million strings (every
  prefix up to eight characters over the characters that matter, every code point placed
  around a name, 10.8 million random strings): no disagreement. Cost is linear: 11 ms at
  60,000 characters for its worst shape, against 8.3 s for the pattern. Against the tree
  before the change, 1.2 million texts: none lost its silence, and every text that gained it
  holds a lower-case name ending in `-guard`.
- It wrote 34 wrong versions of the code. The suite accepted four that change an answer: a
  name could not hold a `z`, a short name at the very start of the text with a part that
  begins with a digit, and a digit of another script in front of a name. Samples and four
  mutants for these were added afterwards.
- The texts seat walked the rulebook files key by key (only the changed texts differ), ran
  the three fixtures in both trees (same intervention, one changed line in `--explain`),
  set an unwired event to detect and installed again (it is then wired, as the note says),
  and unpacked both exports.

The working notes of this repository said that `PostToolUse` cannot add context, that hooks
are snapshotted at session start, and that a record in the transcript is how repeats are
recognised. They are an instruction file, which is not edited without the owner's word. That
word was given on 2026-11-14, and the three notes now carry the wording that the release
copy's notes had, already checked against the hooks reference. On the same word, a day
later, two more of its lines were corrected: that hooks "never block" (they never exit 2 or
return a blocking decision, but context returned on `Stop` continues the conversation), and
that every phrase names a study (every slot has a source, which may be an author, a theory or
a section of the brief, and the next-step phrases have none). A handoff document from
August still says an event is wired that is not; it is left as history.

After the verifier round, not seen by a further one: the samples and mutants above, a
sentence in the SKILL file, and the softened note in `phrases.json`.

`dist/` is rebuilt from this state.

Final: 294/294 tests, **151/151 mutants caught**.

### C11 · Two decisions before release, 2026-11-15
Both were the owner's to make, and both are his answers.

**Where the research brief comes from.** It is a report the owner commissioned from an AI
research tool. The README now says so, and says that its claims were not verified beyond
the spot check of 13 November. The brief itself stays out of the repository. The sentence
that one rulebook file quotes from it stays as it is.

**The two attributions the spot check questioned.** Fredrickson for the entry on forced
positivity, and the years given for Brummelman and colleagues. Both stay in
`rulebook/denylist.json`, each now marked there as not confirmed, so that a reader of the
file sees it without the README. Only the two `source` texts changed: no rule, and nothing
the code reads.

Final: 294/294 tests, **151/151 mutants caught**.

### C12 · What the session records say about live use, 2026-11-15
The README said the tool had not yet been exercised in a live session. The owner pointed
out that it had been used, so the session records were read to see how.

**What they show.** The session transcripts recorded on the author's machine were scanned
by script, the session doing this release left out.

- Through the skill the engine was run by hand four times, each time on the transcript of
  the session that asked for it: on 26 and 29 August and on 1 and 12 September 2026 (UTC),
  in three working sessions of a Lean 4 proof project. Each run measured the session,
  reported `SILENT: not_stuck` and returned an empty answer.
- No transcript records the hook script being executed by Claude Code, and it is not in the
  settings file today. The one file the probe wrote is a made-up payload from the build.

**What changed.** One line under Status in the README. It now says that the hook has not
run in a live session, that the engine has, by hand, four times, and that it stayed silent
each time, on the build of August 2026. No code, no test and no rulebook changed.

The scan scripts and their output are kept with the release tooling, outside this
repository.

Final: 294/294 tests. Nothing the mutants act on changed, so they were not run again.

### C13 · The review before publication, 2026-11-15
Six seats read the tree that was about to be published, none of them the builder. Three
read it for anything private: the code and rulebooks, the tests and fixtures, and a
scripted sweep of all 62 files and of the commit. One read the seven documents. Two checked
the new statement on live use against the session records, by different methods. Each
finding then went to a second reader whose job was to refute it. A last seat read only the
lines that changed after that.

**Private material.** None found. The fixtures are synthetic, the tree holds no address,
account name, home path, session id or credential, and the history held the single commit
of the first release.

**The statement on live use.** Both seats went through every recorded transcript, those of
subagents included, and supported every clause: four by-hand runs through the skill in
three sessions, each on its own transcript, each silent, on the August build, and no record
of Claude Code executing the hook script. What the records cannot show is a run that left
no transcript. The last seat pointed out that the README stated this as what happened, not
as what the record shows, so the status line now speaks of the record.

**Wordings corrected.**
- `uninstall.py` said in its docstring that it restores the backup byte for byte. It does
  that only when the settings, without its own entries, hold the same data as a backup.
  Otherwise it rewrites the file without those entries, and it writes nothing when it has
  no entry to remove. The docstring says that now.
- The README said that the figure from the first calibration run is recorded in this log.
  It is not. It comes from the output of that run in the build session of 26 August 2026,
  and the README says so now.
- One sentence of the C12 entry above was shortened: it gave the size and date range of the
  author's transcript store, which nothing here needs.

Set aside by the second readers, and left as they are: process words that the note at the
top of this log explains, a test comment that uses one, the default `~/.claude/projects`
named in the calibration provenance, and the `dist/` folder this log mentions, which is not
part of the published tree. A note on the address of the local git remote was checked by
hand: it is the plain repository address.

The wording changes made after the last seat's report were checked by the builder against
the code and the records, not read again by an independent seat.

Final: 294/294 tests. One docstring and two documents changed, nothing the mutants act on.
