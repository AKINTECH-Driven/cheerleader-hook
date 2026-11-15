import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from _ctx import fx
import _samples as S
from horme import cli, state


def payload(event='PostToolBatch', fixture='stuck_repeat_error.jsonl', session='s1'):
    return json.dumps({'hook_event_name': event, 'session_id': session,
                       'transcript_path': fx(fixture), 'cwd': '/tmp/proj'})


class CliCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='horme-cli-')
        self._orig = state.STATE_DIR
        state.STATE_DIR = self.dir
        os.environ.pop('CHEERLEADER_DISABLE', None)

    def tearDown(self):
        state.STATE_DIR = self._orig
        shutil.rmtree(self.dir, ignore_errors=True)
        os.environ.pop('CHEERLEADER_DISABLE', None)

    def run_cli(self, raw, argv=None, now=1000.0):
        return cli.run(raw, argv or [], now=now)


class TestHookContract(CliCase):

    def test_it_fires_on_a_stuck_session(self):
        code, out, _ = self.run_cli(payload())
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d['hookSpecificOutput']['hookEventName'], 'PostToolBatch')
        self.assertIn(cli.compose.MARKER, d['hookSpecificOutput']['additionalContext'])
        self.assertTrue(d['systemMessage'])

    def test_the_human_notice_is_a_top_level_field(self):
        """The hooks reference lists systemMessage beside `continue` and `stopReason`,
        not inside hookSpecificOutput. Nested there, the one line that tells the human
        HORME fired is never shown, and the tool speaks to the model unannounced."""
        _c, out, _ = self.run_cli(payload())
        d = json.loads(out)
        self.assertTrue(d['systemMessage'].startswith(cli.brand.LABEL))
        self.assertEqual(sorted(d['hookSpecificOutput']), ['additionalContext', 'hookEventName'])

    def test_it_fires_on_a_red_run_in_the_common_runners(self):
        """End to end: a session stuck on a red unittest, jest, vitest or go test run
        must get its intervention. It used to be silenced as `adjudication`."""
        for runner, output in S.RED_RUNS.items():
            path = os.path.join(self.dir, 'stuck-%s.jsonl' % runner.replace(' ', '-'))
            with open(path, 'w', encoding='utf-8') as fh:
                for row in S.stuck_on(output):
                    fh.write(json.dumps(row) + '\n')
            raw = json.dumps({'hook_event_name': 'Stop', 'session_id': 's-' + runner,
                              'transcript_path': path})
            _c, out, explain = self.run_cli(raw, argv=['--explain'])
            self.assertTrue(json.loads(out), 'silent on a red %s run: %s' % (runner, explain[-3:]))

    def test_a_verdict_after_a_red_run_still_silences_it(self):
        path = os.path.join(self.dir, 'stuck-then-verdict.jsonl')
        with open(path, 'w', encoding='utf-8') as fh:
            for row in S.stuck_on(S.UNITTEST_RED + '\n\nVERIFIER VERDICT: FAIL'):
                fh.write(json.dumps(row) + '\n')
        raw = json.dumps({'hook_event_name': 'Stop', 'session_id': 's-verdict',
                          'transcript_path': path})
        _c, out, explain = self.run_cli(raw, argv=['--explain'])
        self.assertEqual(json.loads(out), {})
        self.assertIn('adjudication', '\n'.join(explain))

    def stuck_then(self, name, *last):
        """A transcript of a stuck session followed by the tool results in `last`."""
        path = os.path.join(self.dir, name + '.jsonl')
        with open(path, 'w', encoding='utf-8') as fh:
            for row in S.stuck_on(S.UNITTEST_RED) + S.calls(*last):
                fh.write(json.dumps(row) + '\n')
        return json.dumps({'hook_event_name': 'Stop', 'session_id': 's-' + name, 'transcript_path': path})

    def test_a_verdict_at_the_end_of_a_long_report_silences_it(self):
        """The usual shape of a verifier's answer: findings first, verdict last, and not
        an error. The hook used to read only the first 4,000 characters of it and spoke
        next to the verdict."""
        _c, out, _e = self.run_cli(self.stuck_then('no-report'))
        self.assertTrue(json.loads(out), 'the sample is wrong: without the report the hook must speak')
        for n in (100, 6000, 30000):
            report = (S.filler(n) + '\nVERIFIER VERDICT: FAIL\n', False)
            for name, last in (('newest-%d' % n, (report,)), ('middle-%d' % n, (report, 'ok')),
                               ('oldest-%d' % n, (report, 'ok', 'ok'))):
                _c, out, explain = self.run_cli(self.stuck_then(name, *last), argv=['--explain'])
                self.assertEqual(json.loads(out), {}, 'spoke next to a verdict: %s' % name)
                self.assertIn('adjudication', '\n'.join(explain))

    def test_a_verdict_at_the_end_of_a_very_long_report_silences_it(self):
        for n in (150000, 1000000):
            report = (S.filler(n) + '\nVERIFIER VERDICT: FAIL\n', False)
            _c, out, explain = self.run_cli(self.stuck_then('very-long-%d' % n, report), argv=['--explain'])
            self.assertEqual(json.loads(out), {}, 'spoke next to a verdict after %d characters' % n)
            self.assertIn('adjudication', '\n'.join(explain))
            quiet = (S.filler(n), False)
            _c, out, _e = self.run_cli(self.stuck_then('very-long-quiet-%d' % n, quiet))
            self.assertTrue(json.loads(out), 'silent after %d characters that hold no verdict' % n)

    def test_a_pathological_line_does_not_stall_the_hook(self):
        """One 59,000-character token on a jest-shaped line took the hook 16 seconds."""
        import time
        line = ' FAIL  ' + 'a' * 59000 + '\nTests:       1 failed, 3 passed, 4 total\n'
        raw = self.stuck_then('long-token', (line, False))
        t0 = time.perf_counter()
        code, out, _e = self.run_cli(raw)
        took = time.perf_counter() - t0
        self.assertEqual((code, json.loads(out)), (0, {}))
        self.assertLess(took, 2.0, 'the hook took %.1f s' % took)

    def test_long_output_with_no_verdict_still_gets_its_intervention(self):
        path = os.path.join(self.dir, 'long-red.jsonl')
        with open(path, 'w', encoding='utf-8') as fh:
            for row in S.stuck_on(S.filler(6000) + '\n' + S.UNITTEST_RED):
                fh.write(json.dumps(row) + '\n')
        raw = json.dumps({'hook_event_name': 'Stop', 'session_id': 's-long-red', 'transcript_path': path})
        _c, out, explain = self.run_cli(raw, argv=['--explain'])
        self.assertTrue(json.loads(out), 'silent on a long red run: %s' % explain[-3:])

    def test_a_suppressed_message_says_why_on_stderr(self):
        """Silence with no reason is how a broken guard goes unnoticed for months."""
        def run_with(check):
            orig = cli.compose.denylist.check
            cli.compose.denylist.check = check
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    _c, out, _e = self.run_cli(payload(session='s-%d' % id(check)))
            finally:
                cli.compose.denylist.check = orig
            self.assertEqual(json.loads(out), {})
            return err.getvalue()

        gone = run_with(lambda _t: [{'group': cli.compose.denylist.UNAVAILABLE, 'pattern': '',
                                     'why': 'rulebook/denylist.json is missing'}])
        self.assertIn('denylist unavailable', gone)
        self.assertIn('rulebook/denylist.json is missing', gone)
        trip = run_with(lambda _t: [{'group': 'group_b_correctness_claims',
                                     'pattern': 'looks right', 'why': 'x'}])
        self.assertIn('denylist trip', trip)
        self.assertIn('looks right', trip)

    def test_an_unusable_denylist_silences_it(self):
        """Fail closed means the check that cannot run stops the message. It used to
        wave every message through when denylist.json was missing or unreadable."""
        saved = cli.rulebook._CACHE.get('denylist')
        try:
            cli.rulebook._CACHE['denylist'] = {}
            cli.compose.denylist.reset()
            _c, out, explain = self.run_cli(payload(), argv=['--explain'])
            self.assertEqual(json.loads(out), {})
            self.assertIn('denylist_unavailable', '\n'.join(explain))
        finally:
            cli.rulebook._CACHE['denylist'] = saved
            cli.rulebook.load('denylist', refresh=True)
            cli.compose.denylist.reset()

    def test_it_stays_silent_on_a_clean_session(self):
        _c, out, _ = self.run_cli(payload(fixture='clean_control.jsonl'))
        self.assertEqual(json.loads(out), {})

    def test_it_stays_silent_while_a_verdict_is_being_decided(self):
        _c, out, _ = self.run_cli(payload(fixture='verdict_adjacent.jsonl'))
        self.assertEqual(json.loads(out), {})

    def test_it_stands_down_rather_than_cheering_an_impossible_task(self):
        _c, out, _ = self.run_cli(payload(fixture='infeasible.jsonl'))
        ctx = json.loads(out)['hookSpecificOutput']['additionalContext']
        self.assertIn('environment is blocking', ctx.lower())

    # --- the non-negotiables ---

    def test_exit_is_always_zero(self):
        for raw in (payload(), payload(fixture='garbage.jsonl'), 'not json', '', '[1,2,3]',
                    json.dumps({'hook_event_name': 'Stop'}),
                    json.dumps({'transcript_path': '/nope/missing.jsonl'})):
            code, _o, _e = self.run_cli(raw)
            self.assertEqual(code, 0, 'non-zero exit on %r' % raw[:40])

    def test_it_never_blocks(self):
        """Advisory only, decided at intake. Exit 2 is what blocks; HORME must never use it.
        (Context returned on Stop still continues the conversation: that is the hooks
        contract for feedback, and it is not what this test is about.)"""
        for raw in (payload(), payload(event='Stop'), payload(event='SubagentStop')):
            code, _o, _e = self.run_cli(raw)
            self.assertNotEqual(code, 2)

    def test_an_internal_failure_is_swallowed_not_propagated(self):
        """Fault injection, because none of the ordinary inputs actually raise. A hook
        that lets an exception escape breaks the very session it exists to help."""
        for target in ('signals', 'classify', 'compose', 'transcript'):
            mod = getattr(cli, target)
            fn = {'signals': 'extract', 'classify': 'classify',
                  'compose': 'compose', 'transcript': 'read_tail'}[target]
            orig = getattr(mod, fn)

            def boom(*_a, **_k):
                raise RuntimeError('injected failure in %s' % target)

            setattr(mod, fn, boom)
            try:
                code, out, _e = self.run_cli(payload())
                self.assertEqual(code, 0, 'non-zero exit when %s raised' % target)
                self.assertEqual(json.loads(out), {})
            finally:
                setattr(mod, fn, orig)

    def test_stdout_is_always_valid_json(self):
        for raw in ('not json', '', payload(), payload(fixture='truncated.jsonl'),
                    payload(fixture='empty.jsonl')):
            _c, out, _e = self.run_cli(raw)
            json.loads(out)

    def test_a_missing_transcript_is_silent_not_fatal(self):
        _c, out, _e = self.run_cli(json.dumps({
            'hook_event_name': 'Stop', 'session_id': 's', 'transcript_path': '/nope.jsonl'}))
        self.assertEqual(json.loads(out), {})


class TestTheHookStartsLight(CliCase):
    """The hook runs on every tool batch, so what it loads is paid for every time. The
    self-test needs subprocess, shutil and tempfile; when those sat at the top of the
    module, every ordinary run loaded them too, which cost more than the diagnosis."""

    def test_an_ordinary_run_does_not_load_what_only_the_self_test_needs(self):
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
        code = (
            'import sys\n'
            'before = set(sys.modules)\n'
            'sys.path.insert(0, %r)\n'
            'import horme.cli as cli\n'
            'code, out, _ = cli.run(%r, [], now=1000.0)\n'
            'assert code == 0 and "systemMessage" in out, out\n'
            'print(sorted(m for m in ("subprocess", "shutil", "tempfile") if m in set(sys.modules) - before))\n'
        ) % (src, payload(session='light'))
        env = dict(os.environ, HOME=self.dir, PYTHONDONTWRITEBYTECODE='1')
        proc = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                              env=env, stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        self.assertEqual(proc.stdout.strip(), '[]', 'an ordinary hook run loaded: %s' % proc.stdout.strip())

    def test_the_hook_script_itself_starts_light(self):
        """The same, for the real entry point: the script Claude Code runs."""
        hook = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'hooks', cli.brand.HOOK_FILENAME)
        env = dict(os.environ, HOME=self.dir, PYTHONDONTWRITEBYTECODE='1')

        def loaded(args, raw):
            proc = subprocess.run([sys.executable, '-X', 'importtime'] + args, input=raw, capture_output=True,
                                  text=True, env=env, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
            names = set(line.rsplit('|', 1)[-1].strip() for line in proc.stderr.splitlines()
                        if line.startswith('import time:'))
            return names, proc.stdout
        at_start, _ = loaded(['-c', 'pass'], '')
        with_hook, out = loaded([hook], payload(event='Stop', session='light-script'))
        self.assertIn('systemMessage', out, 'the sample is wrong: the hook must speak on this session')
        self.assertIn('horme.signals', with_hook, 'the import trace was not read')
        heavy = sorted(n for n in ('subprocess', 'shutil', 'tempfile') if n in with_hook - at_start)
        self.assertEqual(heavy, [], 'an ordinary run of the hook script loaded: %s' % heavy)

    def test_the_self_test_still_has_what_it_needs(self):
        res = cli.selftest()
        self.assertTrue(res['ok'], res)


class TestEventRouting(CliCase):

    def test_it_listens_on_the_events_that_can_inject_context(self):
        for ev in ('PostToolBatch', 'Stop', 'SubagentStop'):
            _c, out, _e = self.run_cli(payload(event=ev, session='s-' + ev))
            self.assertTrue(json.loads(out), 'no output on %s' % ev)

    def test_it_does_not_fire_on_events_configured_off(self):
        for ev in ('SessionStart', 'UserPromptSubmit', 'PostToolUse'):
            _c, out, _e = self.run_cli(payload(event=ev, session='s-' + ev))
            self.assertEqual(json.loads(out), {}, '%s should not fire' % ev)

    def test_the_event_name_is_echoed_back_correctly(self):
        for ev in ('PostToolBatch', 'Stop'):
            _c, out, _e = self.run_cli(payload(event=ev, session='s-' + ev))
            self.assertEqual(json.loads(out)['hookSpecificOutput']['hookEventName'], ev)


class TestRateLimiting(CliCase):

    def test_the_same_block_only_speaks_once(self):
        _c, first, _e = self.run_cli(payload())
        self.assertTrue(json.loads(first))
        _c, second, _e = self.run_cli(payload(), now=10 ** 9)
        self.assertEqual(json.loads(second), {}, 'HORME repeated itself on the same block')

    def test_the_cooldown_holds_between_different_blocks(self):
        self.run_cli(payload(), now=1000.0)
        _c, out, _e = self.run_cli(payload(fixture='infeasible.jsonl'), now=1001.0)
        self.assertEqual(json.loads(out), {})

    def test_firing_is_persisted_to_session_state(self):
        self.run_cli(payload(session='s-persist'))
        self.assertEqual(state.load('s-persist')['fired_total'], 1)

    def test_state_is_not_written_when_it_stays_silent(self):
        self.run_cli(payload(fixture='clean_control.jsonl', session='s-quiet'))
        self.assertEqual(state.load('s-quiet')['fired_total'], 0)


class TestSilenceWhenTheFiringCannotBeRecorded(CliCase):
    """Found on 2026-11-15: with a state folder that could not be written, every limit was
    gone and the same block could get an intervention again on the next event. A firing
    that cannot be recorded is now not given at all."""

    def block_the_state(self):
        blocked = os.path.join(self.dir, 'in-the-way')
        with open(blocked, 'w') as fh:
            fh.write('a file where the state folder should be')
        state.STATE_DIR = blocked            # tearDown puts the original back

    def test_it_says_nothing_when_the_state_cannot_be_saved(self):
        self.block_the_state()
        for i in range(3):
            with contextlib.redirect_stderr(io.StringIO()):
                code, out, _e = self.run_cli(payload(session='s-blocked'), now=1000.0 + i * 10 ** 6)
            self.assertEqual((code, json.loads(out)), (0, {}),
                             'run %d spoke with no way to remember it' % (i + 1))

    def test_the_same_session_speaks_once_the_state_can_be_saved(self):
        """The control for the test above: same sample, same session, a usable folder."""
        _c, out, _e = self.run_cli(payload(session='s-blocked'))
        self.assertIn('systemMessage', json.loads(out))

    def test_explain_names_the_reason(self):
        self.block_the_state()
        with contextlib.redirect_stderr(io.StringIO()):
            _c, _o, explain = self.run_cli(payload(session='s-blocked'), argv=['--explain'])
        text = '\n'.join(explain)
        self.assertIn('SILENT: state_unwritable', text)
        self.assertNotIn('slot ', text, 'it listed the slots of a message it withheld')

    def test_it_says_so_on_standard_error(self):
        self.block_the_state()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.run_cli(payload(session='s-blocked'))
        self.assertIn(cli.brand.LABEL, err.getvalue())
        self.assertIn('state could not be saved', err.getvalue())
        self.assertIn(state.STATE_DIR, err.getvalue())

    def test_the_reason_is_named_even_when_there_is_no_standard_error(self):
        """A hook can be started with standard error closed. The line then has nowhere to
        go, and that must not turn the named reason into an internal error."""
        self.block_the_state()
        kept = sys.stderr
        sys.stderr = None
        try:
            code, out, explain = self.run_cli(payload(session='s-blocked'), argv=['--explain'])
            swapped = sys.stderr
        finally:
            sys.stderr = kept
        if swapped is not None:
            swapped.close()
        self.assertEqual((code, out), (0, '{}'))
        self.assertIn('SILENT: state_unwritable', '\n'.join(explain))

    def test_a_save_that_does_not_answer_true_keeps_it_silent(self):
        """None is what `save` answered before it reported anything. An answer that is not
        exactly True is not a recorded firing."""
        orig = cli.state.save
        try:
            for n, answer in enumerate((None, False, 0, 1, 'saved')):
                cli.state.save = lambda *_a, _answer=answer, **_k: _answer
                with contextlib.redirect_stderr(io.StringIO()):
                    _c, out, _e = self.run_cli(payload(session='s-answer-%d' % n))
                self.assertEqual(json.loads(out), {}, 'spoke on a save that answered %r' % (answer,))
        finally:
            cli.state.save = orig

    def test_the_hook_script_says_nothing_under_a_home_where_state_cannot_be_kept(self):
        """The same through the real entry point, started the way Claude Code starts it:
        three times under a home where the state cannot be kept, and then twice under one
        where it can. There the first run speaks and the second is silent."""
        hook = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'hooks', cli.brand.HOOK_FILENAME)
        under_home = os.path.relpath(cli.brand.STATE_DIR, os.path.expanduser('~'))
        self.assertFalse(under_home.startswith('..'), 'the state folder is not under the home folder')
        blocked_home, good_home = os.path.join(self.dir, 'home-blocked'), os.path.join(self.dir, 'home-good')
        os.makedirs(os.path.dirname(os.path.join(blocked_home, under_home)))
        os.makedirs(good_home)
        with open(os.path.join(blocked_home, under_home), 'w') as fh:
            fh.write('a file where the state folder should be')
        env = dict((k, v) for k, v in os.environ.items() if k not in cli.brand.ENV_DISABLE)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        raw = payload(event='Stop', session='s-process')

        def start(home):
            return subprocess.run([sys.executable, hook], input=raw, capture_output=True, text=True,
                                  env=dict(env, HOME=home), timeout=60)
        for i in range(3):
            proc = start(blocked_home)
            self.assertEqual((proc.returncode, proc.stdout), (0, '{}'), 'run %d: %s' % (i + 1, proc.stderr[-300:]))
            self.assertIn('state could not be saved', proc.stderr)
        proc = start(good_home)
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        self.assertIn('systemMessage', proc.stdout, 'the sample is wrong: the hook must speak on this session')
        self.assertEqual(start(good_home).stdout, '{}', 'the same block spoke twice')

    def test_the_line_on_standard_error_cannot_change_the_exit_status(self):
        """Standard error is a pipe nobody reads any more. The line cannot be written; the
        hook must still print {} and exit 0. Left in the buffer, the line fails again when
        the interpreter exits and the status becomes 120."""
        hook = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'hooks', cli.brand.HOOK_FILENAME)
        under_home = os.path.relpath(cli.brand.STATE_DIR, os.path.expanduser('~'))
        home = os.path.join(self.dir, 'home-blocked')
        os.makedirs(os.path.dirname(os.path.join(home, under_home)))
        with open(os.path.join(home, under_home), 'w') as fh:
            fh.write('a file where the state folder should be')
        env = dict((k, v) for k, v in os.environ.items() if k not in cli.brand.ENV_DISABLE)
        env.update(HOME=home, PYTHONDONTWRITEBYTECODE='1')
        read_end, write_end = os.pipe()
        os.close(read_end)
        try:
            proc = subprocess.run([sys.executable, hook], input=payload(event='Stop', session='s-pipe'),
                                  stdout=subprocess.PIPE, stderr=write_end, text=True, env=env, timeout=60)
        finally:
            os.close(write_end)
        self.assertEqual((proc.returncode, proc.stdout), (0, '{}'))


class TestKillSwitch(CliCase):

    def test_the_env_var_silences_it(self):
        os.environ['CHEERLEADER_DISABLE'] = '1'
        _c, out, _e = self.run_cli(payload())
        self.assertEqual(json.loads(out), {})

    def test_the_disable_file_silences_it(self):
        flag = os.path.join(self.dir, 'DISABLED')
        open(flag, 'w').close()
        _c, out, _e = self.run_cli(payload(), argv=['--disable-file', flag])
        self.assertEqual(json.loads(out), {})


class TestExplain(CliCase):

    def test_explain_writes_to_the_side_channel_not_stdout(self):
        _c, out, explain = self.run_cli(payload(), argv=['--explain'])
        json.loads(out)                       # stdout stays machine-readable
        text = '\n'.join(explain)
        self.assertIn('cognitive', text)
        self.assertIn('repeated_error_count', text)

    def test_explain_says_why_it_stayed_silent(self):
        _c, _o, explain = self.run_cli(payload(fixture='clean_control.jsonl'), argv=['--explain'])
        self.assertIn('not_stuck', '\n'.join(explain))

    def test_explain_cites_the_research_behind_each_slot(self):
        _c, _o, explain = self.run_cli(payload(), argv=['--explain'])
        self.assertIn('Bandura', '\n'.join(explain))


class TestSelfTest(CliCase):
    """What `install.py --doctor` asks the hook process. The hook swallows every failure
    by design, so a health check that only looks at its exit status reports health for
    an engine that is not there. The self-test runs every stage and says which broke."""

    def test_it_passes_on_a_healthy_engine(self):
        res = cli.selftest()
        self.assertTrue(res['ok'], res)
        self.assertEqual(res['error'], '')

    def test_it_names_the_stage_that_broke(self):
        for target, fn in (('transcript', 'read_tail'), ('signals', 'extract'),
                           ('classify', 'classify'), ('compose', 'compose')):
            mod = getattr(cli, target)
            orig = getattr(mod, fn)

            def boom(*_a, **_k):
                raise RuntimeError('injected failure')

            setattr(mod, fn, boom)
            try:
                res = cli.selftest()
            finally:
                setattr(mod, fn, orig)
            self.assertFalse(res['ok'], 'self-test passed with %s broken' % target)
            self.assertEqual(res['stage'], target)
            self.assertIn('injected failure', res['error'])

    def test_it_fails_when_the_denylist_is_unusable(self):
        saved = cli.rulebook._CACHE.get('denylist')
        try:
            cli.rulebook._CACHE['denylist'] = {}
            cli.compose.denylist.reset()
            res = cli.selftest()
        finally:
            cli.rulebook._CACHE['denylist'] = saved
            cli.rulebook.load('denylist', refresh=True)
            cli.compose.denylist.reset()
        self.assertFalse(res['ok'])
        self.assertEqual(res['stage'], 'denylist')

    def test_it_fails_when_any_rulebook_is_missing(self):
        for name in ('thresholds', 'diagnosis', 'phrases', 'hooks'):
            saved = cli.rulebook._CACHE.get(name)
            try:
                cli.rulebook._CACHE[name] = {}
                res = cli.selftest()
            finally:
                cli.rulebook._CACHE[name] = saved
                cli.rulebook.load(name, refresh=True)
            self.assertFalse(res['ok'], 'passed without %s.json' % name)
            self.assertEqual(res['stage'], 'rulebooks')
            self.assertIn(name, res['error'])

    def test_it_drives_the_whole_hook_not_just_the_engine(self):
        """Stage by stage is how it names a fault. But a hook run also parses its
        input, checks which events are watched, keeps session state and shapes its
        output, and a break in any of those leaves the real hook silent or malformed.
        So the last stage is the hook itself, on the synthetic session."""
        breaks = (
            ('payload parsing', cli.payload_mod, 'parse', lambda *_a, **_k: cli.payload_mod.EMPTY),
            ('the event name', cli, '_emit',
             lambda event, iv, real=cli._emit: real('PostToolBatch', iv)),
            ('the output shape', cli, '_emit', lambda *_a, **_k: json.dumps({'oops': True})),
            ('the notice field', cli, '_emit', lambda event, iv: json.dumps({'hookSpecificOutput': {
                'hookEventName': event, 'additionalContext': iv.text, 'systemMessage': iv.system_line}})),
        )
        for what, mod, name, wrong in breaks:
            orig = getattr(mod, name)
            setattr(mod, name, wrong)
            try:
                res = cli.selftest()
            finally:
                setattr(mod, name, orig)
            self.assertFalse(res['ok'], 'self-test passed with %s broken' % what)
            self.assertEqual(res['stage'], 'hook', what)

    def test_it_checks_the_caps_themselves(self):
        """The hook runs never reach them: a repeat is silenced earlier, by the memory
        of the block. A hook with no cap or no cooldown would pass on those alone."""
        limit, fire = cli.state.rate_limit, cli.state.record_fire

        def forgetful(data, episode_id, now=None):
            out = fire(data, episode_id, now=now)
            out['last_fired_at'] = 0.0
            return out

        breaks = (
            # what is broken, where, how, and the check that has to be the one to notice
            ('allows everything', 'rate_limit', lambda *_a, **_k: (True, ''), 'per-block cap'),
            ('denies everything', 'rate_limit', lambda *_a, **_k: (False, 'broken'), 'heard nothing'),
            ('no cooldown', 'rate_limit',
             lambda d, e, now=None, lim=None: limit(d, e, now=(now or 0) + 10 ** 6, lim=lim), 'cooldown'),
            ('no per-block cap', 'rate_limit',
             lambda d, e, now=None, lim=None: limit(d, 'unseen-%s' % e, now=now, lim=lim), 'per-block cap'),
            ('no per-session cap', 'rate_limit',
             lambda d, e, now=None, lim=None: limit(dict(d, fired_total=0), e, now=now, lim=lim),
             'per-session cap'),
            ('firing time not kept', 'record_fire', forgetful, 'not written'),
        )
        for what, name, wrong, noticed_by in breaks:
            orig = getattr(cli.state, name)
            setattr(cli.state, name, wrong)
            try:
                res = cli.selftest()
            finally:
                setattr(cli.state, name, orig)
            self.assertFalse(res['ok'], 'self-test passed with a limiter that %s' % what)
            self.assertEqual(res['stage'], 'limits', what)
            self.assertIn(noticed_by, res['error'], what)

    def test_it_refuses_an_event_name_that_cannot_add_context(self):
        """A misspelt event in the rulebook is wired by the installer and never fires."""
        saved = cli.rulebook._CACHE.get('hooks')
        try:
            odd = json.loads(json.dumps(saved))
            odd['events']['Stopp'] = odd['events'].pop('Stop')
            cli.rulebook._CACHE['hooks'] = odd
            res = cli.selftest()
        finally:
            cli.rulebook._CACHE['hooks'] = saved
            cli.rulebook.load('hooks', refresh=True)
        self.assertFalse(res['ok'])
        self.assertEqual(res['stage'], 'hook')
        self.assertIn('Stopp', res['error'])

    def test_it_reports_every_event_it_exercised(self):
        res = cli.selftest()
        for event in ('PostToolBatch', 'Stop', 'SubagentStop'):
            self.assertIn(event, res['detail'])

    def test_the_answer_check_wants_the_shape_the_event_and_the_label(self):
        good = {'systemMessage': '%s: cognitive block' % cli.brand.LABEL,
                'hookSpecificOutput': {'hookEventName': 'Stop',
                                       'additionalContext': '%s text' % cli.brand.MARKER}}
        cli._check_hook_answer(0, json.dumps(good), [], 'Stop')
        wrong = (
            (2, good, 'a non-zero exit status'),
            (0, dict(good, systemMessage='something happened'), 'a notice without the label'),
            (0, dict(good, hookSpecificOutput=dict(good['hookSpecificOutput'], hookEventName='Other')), 'the wrong event'),
            (0, dict(good, hookSpecificOutput=dict(good['hookSpecificOutput'], additionalContext='no marker')), 'no marker'),
            (0, dict(good, extra=1), 'an extra top-level field'),
            (0, {}, 'silence'),
        )
        for code, answer, what in wrong:
            with self.assertRaises(RuntimeError, msg='accepted %s' % what):
                cli._check_hook_answer(code, json.dumps(answer), [], 'Stop')

    def test_it_runs_the_hook_script_itself_as_a_process(self):
        """`run()` can be perfect while the script that wraps it reads no stdin,
        prints nothing or never calls it. Only starting the script shows that."""
        broken = {
            'prints an empty answer': 'import sys\nsys.stdin.read()\nsys.stdout.write("{}")\n',
            'prints nothing': 'import sys\nsys.stdin.read()\n',
            'exits non-zero': 'import sys\nsys.exit(1)\n',
            'prints junk': 'print("not json")\n',
            # a correct answer and then the one exit status a hook must never return
            'answers and exits 2': (
                'import json, sys\nsys.stdin.read()\n'
                'print(json.dumps({"systemMessage": %r, "hookSpecificOutput": '
                '{"hookEventName": "Stop", "additionalContext": %r}}))\nsys.exit(2)\n'
                % ('%s: cognitive block' % cli.brand.LABEL, '%s text' % cli.brand.MARKER)),
        }
        for what, body in broken.items():
            script = os.path.join(self.dir, 'hook-%d.py' % len(what))
            with open(script, 'w', encoding='utf-8') as fh:
                fh.write(body)
            try:
                res = cli.selftest(hook_path=script)
            finally:
                os.remove(script)
            self.assertFalse(res['ok'], 'passed with a hook script that %s' % what)
            self.assertEqual(res['stage'], 'process', what)

    def test_it_fails_when_a_firing_is_not_remembered(self):
        orig = cli.state.save
        # Answers True and writes nothing. Until 2026-11-15 this stub answered None, as
        # `save` then did; a save that does not answer True now silences the first run,
        # so a firing can only go unremembered behind a save that claims it worked.
        cli.state.save = lambda *_a, **_k: True
        try:
            res = cli.selftest()
        finally:
            cli.state.save = orig
        self.assertFalse(res['ok'])
        self.assertEqual(res['stage'], 'hook')
        self.assertIn('twice', res['error'])

    def test_it_fails_when_no_event_is_set_to_detect(self):
        saved = cli.rulebook._CACHE.get('hooks')
        try:
            off = json.loads(json.dumps(saved))
            for spec in off['events'].values():
                spec['detect'] = False
            cli.rulebook._CACHE['hooks'] = off
            res = cli.selftest()
        finally:
            cli.rulebook._CACHE['hooks'] = saved
            cli.rulebook.load('hooks', refresh=True)
        self.assertFalse(res['ok'])
        self.assertEqual(res['stage'], 'hook')
        self.assertIn('detect', res['error'])

    def test_it_leaves_the_state_directory_setting_as_it_found_it(self):
        before = cli.state.STATE_DIR
        cli.selftest()
        self.assertEqual(cli.state.STATE_DIR, before)

    def test_it_fails_when_no_session_could_ever_cross_the_thresholds(self):
        """A thresholds.json calibrated on too little data can sit above anything a
        40-call window can hold. Then HORME never speaks, and the self-test says so."""
        saved = cli.rulebook._CACHE.get('thresholds')
        try:
            cli.rulebook._CACHE['thresholds'] = {
                'thresholds': dict((k, 10 ** 6) for k in (saved or {}).get('thresholds', {}))}
            res = cli.selftest()
        finally:
            cli.rulebook._CACHE['thresholds'] = saved
            cli.rulebook.load('thresholds', refresh=True)
        self.assertFalse(res['ok'])
        self.assertEqual(res['stage'], 'classify')
        self.assertIn('thresholds.json', res['error'])

    def test_it_writes_no_session_state(self):
        home = os.path.expanduser('~')
        before = sorted(os.listdir(os.path.join(home, '.claude', 'cheerleader', 'state'))) \
            if os.path.isdir(os.path.join(home, '.claude', 'cheerleader', 'state')) else None
        cli.selftest()
        self.assertEqual(os.listdir(self.dir), [])
        after = sorted(os.listdir(os.path.join(home, '.claude', 'cheerleader', 'state'))) \
            if os.path.isdir(os.path.join(home, '.claude', 'cheerleader', 'state')) else None
        self.assertEqual(before, after, 'the hook process wrote into the real home')

    def test_it_goes_through_the_real_transcript_reader_and_cleans_up(self):
        """A self-test that builds its events in memory would pass with a broken
        reader, which is the first stage every real hook call depends on."""
        seen = []
        orig = cli.transcript.read_tail

        def spy(path, *a, **k):
            seen.append(path)
            self.assertTrue(os.path.isfile(path))
            return orig(path, *a, **k)

        cli.transcript.read_tail = spy
        try:
            self.assertTrue(cli.selftest()['ok'])
        finally:
            cli.transcript.read_tail = orig
        self.assertTrue(seen)
        for path in seen:
            self.assertFalse(os.path.exists(path), 'the temporary transcript was left behind')
            self.assertFalse(os.path.exists(os.path.dirname(path)), 'its folder was left behind')

    def test_it_reports_an_engaged_kill_switch_without_failing(self):
        """A disabled install must still be diagnosable, and the user must be told
        that the silence they see is the switch, not a fault."""
        self.assertFalse(cli.selftest(disable_file=os.path.join(self.dir, 'absent'))['kill_switch'])
        os.environ['CHEERLEADER_DISABLE'] = '1'
        res = cli.selftest(disable_file=os.path.join(self.dir, 'absent'))
        self.assertTrue(res['ok'], res)
        self.assertTrue(res['kill_switch'])
        self.assertEqual(os.environ.get('CHEERLEADER_DISABLE'), '1', 'the switch was not put back')

    def test_it_never_raises(self):
        orig = cli.rulebook.load

        def boom(*_a, **_k):
            raise RuntimeError('rulebook loader exploded')

        cli.rulebook.load = boom
        try:
            res = cli.selftest()
        finally:
            cli.rulebook.load = orig
        self.assertFalse(res['ok'])


if __name__ == '__main__':
    unittest.main()
