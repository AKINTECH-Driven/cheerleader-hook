"""HORME's single entry point. One hook script, dispatching on hook_event_name.

Contract, in order of importance:
  1. ALWAYS exit 0. This runs on every tool batch; a crash here breaks the session.
  2. ALWAYS write valid JSON to stdout. `{}` means silence, which is the normal case.
  3. NEVER exit 2 and never return decision:block. Advisory only, decided at intake. Context
     returned on Stop is not a block, but per the hooks reference the conversation then
     continues so that Claude can act on it.
"""
import json
import os
import sys

from . import brand, classify, compose, payload as payload_mod, rulebook, signals, state, transcript

DISABLE_FILE = brand.DISABLE_FILE
HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    'hooks', brand.HOOK_FILENAME)

#: Hook events whose `hookSpecificOutput.additionalContext` reaches Claude, as listed
#: in the public hooks reference on 2026-11-13. An event outside this list that the
#: rulebook sets to detect would be wired and never heard.
CONTEXT_EVENTS = ('SessionStart', 'SubagentStart', 'UserPromptSubmit', 'UserPromptExpansion',
                  'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'PostToolBatch',
                  'Stop', 'SubagentStop', 'PostModelSwitch')


def _events():
    cfg = rulebook.load('hooks').get('events') or {}
    return cfg if isinstance(cfg, dict) else {}


def _emit(event, iv):
    """The hook's JSON. `systemMessage` is a universal, top-level field in the hooks
    reference (beside `continue` and `stopReason`); nested under hookSpecificOutput it
    is ignored, and the human never learns that HORME spoke to the model."""
    return json.dumps({
        'systemMessage': iv.system_line,
        'hookSpecificOutput': {'hookEventName': event or 'Stop',
                               'additionalContext': iv.text},
    })


SELFTEST_ERROR = 'AssertionError: expected 4 cells, got 1, in importer.py'


def _synthetic_stuck_session(repeats=None):
    """Transcript rows for one command failing the same way for a whole window: as
    stuck as a session gets. Written in the transcript's own row format, so the
    self-test goes through the real reader instead of around it."""
    rows = []
    for i in range(repeats or signals.DEFAULT_WINDOW):
        tid = 'selftest-%d' % i
        rows.append({'type': 'assistant', 'isSidechain': False, 'message': {
            'role': 'assistant', 'content': [{'type': 'tool_use', 'id': tid, 'name': 'Bash',
                                              'input': {'command': 'run the tests'}}]}})
        rows.append({'type': 'user', 'isSidechain': False, 'message': {
            'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': tid,
                                         'content': SELFTEST_ERROR, 'is_error': True}]}})
    return rows


def _check_hook_answer(code, stdout, explain, event):
    """Raise unless one hook run answered a stuck session the way the reference says."""
    if code != 0:
        raise RuntimeError('the hook returned exit status %r' % (code,))
    try:
        answer = json.loads(stdout)
    except ValueError:
        raise RuntimeError('the hook printed something that is not JSON: %r' % stdout[:120])
    if answer == {}:
        why = [l.strip() for l in explain if 'SILENT' in l or 'internal error' in l]
        raise RuntimeError('the hook stayed silent on a fully stuck session%s'
                           % (' (%s)' % why[-1] if why else ''))
    spec = answer.get('hookSpecificOutput') if isinstance(answer, dict) else None
    if (not isinstance(spec, dict) or sorted(answer) != ['hookSpecificOutput', 'systemMessage']
            or sorted(spec) != ['additionalContext', 'hookEventName']):
        raise RuntimeError('the hook output has the wrong shape: %s' % stdout[:160])
    if (spec['hookEventName'] != event or brand.MARKER not in str(spec['additionalContext'])
            or not str(answer['systemMessage']).startswith(brand.LABEL)):
        raise RuntimeError('the hook output has the wrong content: %s' % stdout[:160])


def _check_limits():
    """Raise unless the caps in rulebook/hooks.json hold. The two hook runs below never
    reach them: the second run is silenced earlier, by the per-block memory."""
    lim = state.limits()
    session, per, gap = int(lim['max_per_session']), int(lim['max_per_episode']), float(lim['min_seconds_between'])
    if session < 1 or per < 1:
        raise RuntimeError('rulebook/hooks.json allows no intervention at all '
                           '(max_per_session %d, max_per_episode %d)' % (session, per))
    t0 = 1000000.0
    if state.rate_limit(state.blank(), 'a', now=t0) != (True, ''):
        raise RuntimeError('a session that has heard nothing is not allowed one intervention')
    once = state.record_fire(state.blank(), 'a', now=t0)
    if once.get('fired_total') != 1 or once.get('last_fired_at') != t0:
        raise RuntimeError('a firing is not written into the session state')
    same = state.blank()
    for _ in range(per):
        state.record_fire(same, 'a', now=t0)
    if state.rate_limit(same, 'a', now=t0 + gap + 1)[0]:
        raise RuntimeError('the per-block cap does not hold')
    if gap > 0 and session > 1 and state.rate_limit(once, 'b', now=t0 + gap / 2.0)[0]:
        raise RuntimeError('the cooldown between interventions does not hold')
    full = state.blank()
    for i in range(session):
        state.record_fire(full, 'block-%d' % i, now=t0 + i * (gap + 1))
    if state.rate_limit(full, 'one-more', now=t0 + (session + 1) * (gap + 1))[0]:
        raise RuntimeError('the per-session cap does not hold')


def selftest(disable_file=None, hook_path=None):
    """Prove the hook works, stage by stage and then end to end, on a synthetic stuck
    session.

    The hook hides every failure from the session it runs in: it prints `{}` and exits
    0 whether the engine ran or could not even be imported. That is right for a hook
    and useless for a health check, so `install.py --doctor` asks this instead.

    The stages (rulebooks, denylist, transcript, signals, classify, compose, limits)
    name the part that broke. Then `hook`: for every event the rulebook watches, two
    real runs of `run()` on the same transcript. The first must answer in the
    documented shape and echo that event; the second must stay silent because the
    first was remembered. That covers what the stages go around: input parsing, which
    events are watched, session state and the output.

    Then `process`: the hook script itself, started the way Claude Code starts it,
    with the payload on stdin and a temporary home. `run()` can be perfect while the
    script that wraps it reads no stdin, writes nothing or never calls it.

    What it cannot see: it reads a transcript it wrote itself, so a reader that fails
    only on your real session files stays invisible to it.

    Uses a temporary folder for the transcript, the state and the home, sets the kill
    switch aside for the runs and reports whether it was on, never raises. Returns
    {'ok', 'stage', 'error', 'detail', 'kill_switch'}.
    """
    # Loaded here, not at the top: the hook runs on every tool batch and only this
    # function needs them. At module level they cost more than the diagnosis itself.
    import shutil
    import subprocess
    import tempfile

    out = {'ok': False, 'stage': 'rulebooks', 'error': '', 'detail': '', 'kill_switch': False}
    work = None
    set_aside = {}
    state_dir = state.STATE_DIR
    try:
        out['kill_switch'] = bool(brand.disabled(disable_file or DISABLE_FILE))
        for name in ('thresholds', 'diagnosis', 'phrases', 'hooks'):
            if not rulebook.load(name):
                raise RuntimeError('rulebook/%s.json is missing, unreadable or empty' % name)

        out['stage'] = 'denylist'
        found = compose.denylist.problems()
        if found:
            raise RuntimeError('; '.join(found))

        out['stage'] = 'transcript'
        work = tempfile.mkdtemp(prefix='%s-selftest-' % brand.NAME)
        path = os.path.join(work, 'session.jsonl')
        rows = _synthetic_stuck_session()
        with open(path, 'w', encoding='utf-8') as fh:
            for row in rows:
                fh.write(json.dumps(row) + '\n')
        events = transcript.read_tail(path)
        if len(events) != len(rows):
            raise RuntimeError('read %d events back from a transcript of %d rows'
                               % (len(events), len(rows)))

        out['stage'] = 'signals'
        sig = signals.extract(events)
        if sig.repeated_error_count != len(rows) // 2:
            raise RuntimeError('measured %d repeated errors in a session that has %d'
                               % (sig.repeated_error_count, len(rows) // 2))

        out['stage'] = 'classify'
        report = classify.classify(sig, session_id='selftest', event='Stop', state=state.blank())
        if not report.should_speak:
            raise RuntimeError('a fully stuck session was not diagnosed (%s); check '
                               'rulebook/thresholds.json'
                               % (report.suppression_reason or 'not_stuck'))

        out['stage'] = 'compose'
        iv = compose.compose(report)
        if iv.suppressed or brand.MARKER not in iv.text:
            raise RuntimeError('no intervention was composed (%s)' % (iv.reason or 'no text'))

        out['stage'] = 'limits'
        _check_limits()

        out['stage'] = 'hook'
        watched = sorted(name for name, spec in _events().items()
                         if isinstance(spec, dict) and spec.get('detect'))
        if not watched:
            raise RuntimeError('no event in rulebook/hooks.json is set to detect, so the '
                               'hook can never speak')
        unknown = [name for name in watched if name not in CONTEXT_EVENTS]
        if unknown:
            raise RuntimeError('rulebook/hooks.json sets %s to detect, which is not a hook '
                               'event that can add context' % ', '.join(unknown))
        for name in brand.ENV_DISABLE:
            if name in os.environ:
                set_aside[name] = os.environ.pop(name)
        state.STATE_DIR = os.path.join(work, 'state')
        argv = ['--explain', '--disable-file', os.path.join(work, 'DISABLED')]

        def payload_for(name):
            return json.dumps({'hook_event_name': name, 'session_id': 'selftest-' + name,
                               'transcript_path': path})

        for event in watched:
            code, stdout, explain = run(payload_for(event), argv)
            _check_hook_answer(code, stdout, explain, event)
            code, again, _explain = run(payload_for(event), argv)
            if code != 0 or again != '{}':
                raise RuntimeError('the same block spoke twice on %s, so a firing is not '
                                   'being remembered' % event)
        event = 'Stop' if 'Stop' in watched else watched[0]
        raw = json.dumps({'hook_event_name': event, 'session_id': 'selftest-process',
                          'transcript_path': path})

        out['stage'] = 'process'
        env = dict((k, v) for k, v in os.environ.items() if k not in brand.ENV_DISABLE)
        env['HOME'] = os.path.join(work, 'home')
        os.makedirs(env['HOME'])
        proc = subprocess.run([sys.executable, hook_path or HOOK], input=raw, env=env,
                              capture_output=True, text=True, timeout=30)
        _check_hook_answer(proc.returncode, proc.stdout, [], event)

        out.update(ok=True, stage='',
                   detail='%s block, severity %d, %d characters, on %s'
                          % (report.block_type, report.severity, len(iv.text), ', '.join(watched)))
    except Exception as exc:
        out['error'] = ('%s' % (exc,)) or repr(exc)
    finally:
        state.STATE_DIR = state_dir
        os.environ.update(set_aside)
        if work:
            shutil.rmtree(work, ignore_errors=True)
    return out


def _explain_lines(pay, sig, report, iv, reason):
    out = ['%s --explain' % brand.LABEL, '  event: %s' % (pay.event or '(none)'),
           '  transcript: %s' % (pay.transcript_path or '(none)')]
    if sig is not None:
        out.append('  signals: ' + ', '.join(
            '%s=%s' % (k, v) for k, v in sorted(sig.as_dict().items())
            if isinstance(v, int) and v))
    if report is not None:
        out.append('  diagnosis: block=%s move=%s severity=%s validate_first=%s episode=%s'
                   % (report.block_type, report.primary_move, report.severity,
                      report.validate_first, report.episode_id))
        for c in report.crossed:
            out.append('    crossed: %s = %s (threshold %s)'
                       % (c['signal'], c['value'], c['threshold']))
    if reason:
        out.append('  SILENT: %s' % reason)
    if iv is not None and not iv.suppressed:
        for p in iv.parts:
            out.append('    slot %-11s <- %s' % (p['slot'], p.get('source', '')[:90]))
    return out


def run(raw_stdin, argv=None, now=None):
    """Return (exit_code, stdout_text, explain_lines). Never raises."""
    argv = list(argv or [])
    explain = '--explain' in argv
    disable_file = DISABLE_FILE
    if '--disable-file' in argv:
        try:
            disable_file = argv[argv.index('--disable-file') + 1]
        except Exception:
            pass

    pay = sig = report = iv = None
    reason = ''
    try:
        pay = payload_mod.parse(raw_stdin)
        # Manual invocation (the SKILL.md path) has no hook stdin: allow the same
        # engine to be pointed at a transcript directly.
        for flag, field in (('--event', 'event'), ('--transcript', 'transcript_path'),
                            ('--session', 'session_id')):
            if flag in argv:
                try:
                    pay = pay._replace(**{field: argv[argv.index(flag) + 1]})
                except Exception:
                    pass
        if '--force' in argv and pay.event:
            # Diagnose regardless of the event's detect flag; still never blocks.
            _events().setdefault(pay.event, {})

        if brand.disabled(disable_file):
            reason = 'disabled'
            return 0, '{}', (_explain_lines(pay, None, None, None, reason) if explain else [])

        cfg = _events().get(pay.event) or {}
        if '--force' in argv:
            cfg = dict(cfg, detect=True)
        if pay.event == 'SessionStart':
            state.prune()
        if not cfg.get('detect'):
            reason = 'event_not_watched:%s' % (pay.event or '?')
            return 0, '{}', (_explain_lines(pay, None, None, None, reason) if explain else [])

        events = transcript.read_tail(pay.transcript_path)
        sig = signals.extract(events)
        st = state.load(pay.session_id)
        report = classify.classify(sig, session_id=pay.session_id, event=pay.event, state=st)

        if not report.should_speak:
            reason = report.suppression_reason or 'not_stuck'
            return 0, '{}', (_explain_lines(pay, sig, report, None, reason) if explain else [])

        allowed, why = state.rate_limit(st, report.episode_id, now=now)
        if not allowed:
            reason = why
            return 0, '{}', (_explain_lines(pay, sig, report, None, reason) if explain else [])

        iv = compose.compose(report)
        if iv.suppressed:
            reason = iv.reason
            if iv.reason == 'denylist_unavailable':
                # Louder still: the guard itself is gone, so nothing may be said.
                sys.stderr.write('%s denylist unavailable, intervention suppressed: %s\n'
                                 % (brand.LABEL, '; '.join(str(v.get('why', ''))
                                                           for v in iv.violations)))
            elif iv.violations:
                # Loud by design: every template is ours, so a trip is a template bug.
                sys.stderr.write('%s denylist trip, intervention suppressed: %%s\n' % brand.LABEL
                                 % json.dumps([v.get('pattern') for v in iv.violations]))
            return 0, '{}', (_explain_lines(pay, sig, report, iv, reason) if explain else [])

        state.record_fire(st, report.episode_id, now=now)
        state.save(pay.session_id, st)
        return 0, _emit(pay.event, iv), (_explain_lines(pay, sig, report, iv, '') if explain else [])

    except Exception as exc:                 # never take the session down with us
        if explain:
            return 0, '{}', ['%s internal error (silenced): %r' % (brand.LABEL, exc)]
        return 0, '{}', []


def main(argv=None):
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ''
    code, out, explain = run(raw, argv if argv is not None else sys.argv[1:])
    sys.stdout.write(out)
    for line in explain:
        sys.stderr.write(line + '\n')
    return code


if __name__ == '__main__':
    sys.exit(main())
