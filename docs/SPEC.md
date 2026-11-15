# SPEC · HORME — the encouragement gate for Claude Code

> **Note for this release.** This is the spec as approved on 2026-08-26, published with four wordings generalised (target user, two project-convention remarks, a local folder path) and one template comment removed. Where the shipped code differs from it, among other things: runtime state lives under `~/.claude/cheerleader`, not `~/.claude/horme`; the skill installs as `cheerleader`, not `horme`; there is no `rulebook/signals.json` (signal definitions live in `src/horme/signals.py`); the self-check is `install.py --doctor`; `UserPromptSubmit` is not wired by default; the item on escalating warmth was not built; and suppression was narrowed during the build from "verdict-adjacent" output to adjudication only (see `BUILD-LOG.md`). "Never blocks" in this spec means that it never exits 2 and never returns `decision: block`: according to the public hooks reference, context returned on `Stop` still continues the conversation. A `source` field names an author, a theory, a study or a section of the research brief, and it sits on each slot: the `moves` and `fallback_moves` lists carry none.

## Idea
A Claude Code skill that detects, deterministically and from the session transcript alone, when Claude is
stuck on a task, and injects one calibrated, research-grounded encouragement that hands the model a concrete
next step instead of a pep talk.

## Target user
The author, as the operator of their own Claude Code sessions. The *reader* of the output is Claude itself:
the intervention lands in Claude's context via hook `additionalContext`, with a one-line `systemMessage`
so the human can see that HORME fired and why. Secondary user: any Claude Code user who installs the skill.

## Scenario
**Document automation** · It is a pipeline: transcript JSONL + hook stdin in, one intervention JSON out,
selected by a data rulebook, with fixtures as the law and zero LLM calls inside the product. The riskiest
part is the deterministic detect-and-select stage, so per the boundary rule that scenario governs. (It is
*not* an AI-powered app: the product never calls a model; the model is the consumer.)

## Features (MoSCoW)
**Must:**
1. **Signal reader** — tail-read `transcript_path` JSONL + parse hook stdin into a `SignalSet`; verify the real hook field names empirically before trusting the docs.
2. **Block classifier** — deterministic diagnosis into `cognitive` / `motivational` / `emotional-analogue` / `infeasible`, with severity and per-episode dedupe. Rules live in `rulebook/*.json`, never in code.
3. **Intervention composer** — rulebook-driven assembly in the brief's order: validate → relabel the cause as specific/temporary/controllable → proximal next step → autonomy/choice → if-then plan. Fail-closed denylist blocks every phrasing the brief marks as backfiring.
4. **Hook layer** — `SessionStart` / `PostToolBatch` / `Stop` / `SubagentStop` / `UserPromptSubmit` wiring, per-session state, rate limiting, kill switch. **Advisory only: never exit 2, never blocks.**
5. **SKILL.md + installer** — the orchestrated flow for manual invocation, plus `install.py` / `uninstall.py` that patch `~/.claude/settings.json` with a timestamped backup and restore it exactly.

**Should:** `--explain` mode printing which signals fired and which rule selected each phrase · escalating warmth across repeated firings within one episode · a `horme doctor` self-check.
**Could:** transcript replay CLI to dry-run HORME over any past session · per-project rulebook overrides.
**Won't (this version):** any LLM call · any GUI or port · veto power over `Stop` · efficacy measurement · non-English phrasing.

## Constraints
Stack: Python 3.9.6 **stdlib only**, offline, zero dependencies (hooks must not import anything that can be missing) · JSON rulebooks, not YAML (a project convention) · Platform/delivery: a skill folder under git, installed to `~/.claude/skills/horme` + hook entries in `~/.claude/settings.json` · **Performance budget: < 50 ms per hook invocation** — hooks fire on every tool batch, so the transcript is tail-read, never fully parsed · Verify bias: **both** — full unittest suite *and* a live end-to-end run against a real session transcript · Deadline: none stated.

## Data & interfaces
- **In (A)** hook stdin JSON. Documented fields: `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `permission_mode`; `tool_calls[]` on `PostToolBatch`; `last_assistant_message` on `Stop`/`SubagentStop`; `user_input` on `UserPromptSubmit`. Treated as **unverified** until Feature 1 dumps the real payloads.
- **In (B)** the session JSONL at `transcript_path`, read from the tail backwards, bounded by line count and bytes.
- **In (C)** `rulebook/signals.json`, `rulebook/diagnosis.json`, `rulebook/phrases.json`, `rulebook/denylist.json` — every phrase carries a `source` field naming the study behind it; no phrase without a source ships.
- **Internal contract** `BlockReport` = `{session_id, event, episode_id, signals[], block_type, severity 0-3, fired_count, verdict_adjacent: bool}`.
- **Out** stdout `{"systemMessage": "...", "hookSpecificOutput": {"hookEventName": "<event>", "additionalContext": "..."}}`, **always exit 0**. Silence (empty object) is the default and the most common output.
- **State** `~/.claude/horme/state/<session_id>.json`, pruned after 7 days. Honest: this is real on-disk persistence outside the project.

## Done when
On a real Claude Code transcript containing a genuine stuck episode, the installed hooks emit **exactly one**
intervention inside that episode and **zero** on a clean control transcript; the full unittest suite is green
including the denylist test, the `verdict_adjacent` suppression test and the infeasible-task fixture that must
produce a stand-down rather than encouragement; and `uninstall.py` restores `settings.json` byte-identical to
its pre-install backup.

## Risks & open questions
- **Sycophancy is the top risk.** An encouragement layer firing near a verifier verdict could help rationalise a FAIL into a PASS, which is the exact failure this design exists to prevent. Mitigation is structural and non-negotiable: HORME never comments on correctness, never asserts that work is fine, suppresses itself when the recent transcript is verdict-adjacent (test results, review verdicts, gate output), and runs a fail-closed denylist over its own output. This gets its own PLAN gate.
- **Hook field names are secondhand.** Taken from the public docs, not observed. `PostToolBatch` showing `tool_output` where `PostToolUse` uses `tool_response` looks wrong. Feature 1 is an echo-hook that dumps real stdin; the schema in this spec is provisional until it does.
- **The evidence base is human-subject.** Nothing in the brief was measured on a language model. Only the *structural* mechanisms plausibly transfer — decomposition to a proximal subgoal, relabelling the cause as specific/temporary/controllable, if-then plans, feed-forward. HORME will ship no efficacy claim it has not measured, and v1 measures none.
- **Context cost is real.** Every injection spends tokens in the session it is trying to help. Hard rate limit, aggressive default silence, and `--explain` so the cost is auditable.
- **The infeasible-task boundary.** The brief is explicit that encouraging sunk-cost persistence on an unachievable goal is the wrong move. HORME needs a stand-down path that says so plainly instead of cheering.
- **Editing global `settings.json`** is the one destructive-adjacent action in the build. Installer only, backup first, uninstall proven by test.
- Open: whether `PostToolBatch` fires often enough to be the primary detector, or whether `Stop` carries most of the value. Feature 1's telemetry decides; no guess here.
