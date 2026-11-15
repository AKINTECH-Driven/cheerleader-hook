import json
import os
import shutil
import tempfile
import shlex
import stat
import subprocess
import sys
import unittest
from _ctx import fx  # noqa: F401
from horme import brand, install

REAL_LOOKING = ('{\n  "hooks": {\n    "SessionStart": [\n      {\n        "hooks": [\n'
                '          {\n            "type": "command",\n'
                '            "command": "open -gb com.example.Widget 2>/dev/null || true"\n'
                '          }\n        ]\n      }\n    ]\n  },\n'
                '  "statusLine": {\n    "type": "command",\n    "command": "statusline.py"\n  },\n'
                '  "theme": "dark"\n}')


class InstallCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='horme-install-')
        self.settings = os.path.join(self.dir, 'settings.json')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, text):
        with open(self.settings, 'w', encoding='utf-8') as fh:
            fh.write(text)

    def read(self):
        with open(self.settings, encoding='utf-8') as fh:
            return fh.read()


class TestInstall(InstallCase):

    def test_it_adds_hooks_for_every_detecting_event(self):
        self.write(REAL_LOOKING)
        res = install.install(self.settings)
        self.assertTrue(res['ok'], res.get('error'))
        cfg = json.loads(self.read())
        for ev in ('PostToolBatch', 'Stop', 'SubagentStop', 'SessionStart'):
            joined = json.dumps(cfg['hooks'].get(ev, []))
            self.assertIn(install.MARKER, joined, 'no HORME hook on %s' % ev)

    def test_it_preserves_an_existing_hook_on_the_same_event(self):
        """A settings.json often already has a SessionStart hook. Clobbering
        someone's own widget launcher would be an unforgivable way to install a morale tool."""
        self.write(REAL_LOOKING)
        install.install(self.settings)
        cfg = json.loads(self.read())
        self.assertIn('example.Widget', json.dumps(cfg['hooks']['SessionStart']))

    def test_it_preserves_unrelated_top_level_settings(self):
        self.write(REAL_LOOKING)
        install.install(self.settings)
        cfg = json.loads(self.read())
        self.assertEqual(cfg['theme'], 'dark')
        self.assertEqual(cfg['statusLine']['command'], 'statusline.py')

    def test_it_takes_a_backup_before_touching_anything(self):
        self.write(REAL_LOOKING)
        res = install.install(self.settings)
        self.assertTrue(os.path.exists(res['backup']))
        with open(res['backup'], encoding='utf-8') as fh:
            self.assertEqual(fh.read(), REAL_LOOKING)

    def test_it_is_idempotent(self):
        self.write(REAL_LOOKING)
        install.install(self.settings)
        once = self.read()
        install.install(self.settings)
        self.assertEqual(json.loads(self.read()), json.loads(once))
        self.assertEqual(json.dumps(json.loads(self.read())).count(install.MARKER), 4)

    def test_it_creates_a_valid_file_when_none_exists(self):
        res = install.install(self.settings)
        self.assertTrue(res['ok'])
        self.assertIn(install.MARKER, json.dumps(json.loads(self.read())))

    # --- deliberate failure cases ---

    def test_it_refuses_to_clobber_a_corrupt_settings_file(self):
        """Better to fail loudly than to overwrite a config we could not understand."""
        self.write('{ this is not json')
        res = install.install(self.settings)
        self.assertFalse(res['ok'])
        self.assertIn('parse', res['error'].lower())
        self.assertEqual(self.read(), '{ this is not json', 'corrupt file was modified')

    def test_it_refuses_when_settings_is_not_an_object(self):
        self.write('[1, 2, 3]')
        self.assertFalse(install.install(self.settings)['ok'])


class TestUninstall(InstallCase):

    def test_uninstall_restores_the_file_byte_identically(self):
        """The SPEC's done-when. Surgical removal, then a byte-exact check against the
        pre-install backup — not a blind copy-back, which would discard later edits."""
        self.write(REAL_LOOKING)
        install.install(self.settings)
        self.assertNotEqual(self.read(), REAL_LOOKING)
        res = install.uninstall(self.settings)
        self.assertTrue(res['ok'], res.get('error'))
        self.assertEqual(self.read(), REAL_LOOKING, 'settings.json was not restored exactly')

    def test_uninstall_keeps_the_users_own_hooks(self):
        self.write(REAL_LOOKING)
        install.install(self.settings)
        install.uninstall(self.settings)
        self.assertIn('example.Widget', self.read())

    def test_uninstall_does_not_discard_edits_made_after_install(self):
        """A blind restore-from-backup would silently throw these away."""
        self.write(REAL_LOOKING)
        install.install(self.settings)
        cfg = json.loads(self.read())
        cfg['theme'] = 'light'
        cfg['newSetting'] = 42
        self.write(json.dumps(cfg, indent=2))
        install.uninstall(self.settings)
        after = json.loads(self.read())
        self.assertEqual(after['theme'], 'light')
        self.assertEqual(after['newSetting'], 42)
        self.assertNotIn(install.MARKER, json.dumps(after))

    def test_uninstall_on_a_clean_file_is_a_no_op(self):
        self.write(REAL_LOOKING)
        res = install.uninstall(self.settings)
        self.assertTrue(res['ok'])
        self.assertEqual(self.read(), REAL_LOOKING)

    def test_uninstall_removes_every_trace(self):
        self.write(REAL_LOOKING)
        install.install(self.settings)
        install.uninstall(self.settings)
        self.assertNotIn('horme', self.read().lower())

    def test_uninstall_refuses_on_a_corrupt_file(self):
        self.write('{ broken')
        self.assertFalse(install.uninstall(self.settings)['ok'])
        self.assertEqual(self.read(), '{ broken')


class TestBackupNaming(InstallCase):

    def test_the_dry_run_names_the_backup_file_it_will_actually_create(self):
        """The dry-run message and the backup writer were two independent strings; the
        message said `.horme-backup-` while the writer produced `.cheerleader-backup-`.
        A dry run that misstates what it will do is worse than no dry run."""
        self.write(REAL_LOOKING)
        res = install.install(self.settings)
        self.assertIn('.%s-backup-' % brand.NAME, os.path.basename(res['backup']))


class TestDoctor(InstallCase):

    def test_doctor_reports_not_installed(self):
        self.write(REAL_LOOKING)
        d = install.doctor(self.settings)
        self.assertFalse(d['installed'])

    def test_doctor_reports_installed_and_lists_the_events(self):
        self.write(REAL_LOOKING)
        install.install(self.settings)
        d = install.doctor(self.settings)
        self.assertTrue(d['installed'])
        self.assertIn('PostToolBatch', d['events'])

    def test_doctor_checks_the_engine_actually_runs(self):
        d = install.doctor(self.settings)
        self.assertTrue(d['engine_ok'], d.get('engine_error'))
        self.assertTrue(d['selftest']['ok'])

    def copy_of_the_hook(self):
        """The real hook script in a folder with no engine beside it."""
        d = os.path.join(self.dir, 'moved', 'hooks')
        os.makedirs(d)
        dst = os.path.join(d, brand.HOOK_FILENAME)
        shutil.copy2(install.HOOK, dst)
        return dst

    def test_doctor_fails_when_the_engine_cannot_be_imported(self):
        """The hook swallows an import error and prints `{}` with exit 0, which is
        right for a hook and useless for a health check. Doctor used to call that ok."""
        d = install.doctor(self.settings, hook_path=self.copy_of_the_hook())
        self.assertFalse(d['engine_ok'])
        self.assertIn('import', d['engine_error'].lower())

    def test_doctor_runs_the_command_stored_in_settings(self):
        install.install(self.settings, hook_path=self.copy_of_the_hook())
        d = install.doctor(self.settings)
        self.assertIs(d['command_ok'], True, d.get('command_error'))

    def test_doctor_notices_a_stored_command_whose_script_is_gone(self):
        """The guard keeps a missing script from blocking the session. Doctor is where
        the user finds out that the hook has silently stopped running."""
        hook = self.copy_of_the_hook()
        install.install(self.settings, hook_path=hook)
        os.remove(hook)
        d = install.doctor(self.settings)
        self.assertIs(d['command_ok'], False)
        self.assertIn('script is gone', d['command_error'])

    def test_doctor_names_a_missing_interpreter(self):
        install.install(self.settings, python=os.path.join(self.dir, 'no-such-python'),
                        hook_path=self.copy_of_the_hook())
        d = install.doctor(self.settings)
        self.assertIs(d['command_ok'], False)
        self.assertIn('interpreter is gone', d['command_error'])

    def test_doctor_names_an_interpreter_that_cannot_be_executed(self):
        python = os.path.join(self.dir, 'python-not-executable')
        with open(python, 'w', encoding='utf-8') as fh:
            fh.write('#!/bin/sh\n')
        os.chmod(python, 0o644)
        install.install(self.settings, python=python, hook_path=self.copy_of_the_hook())
        d = install.doctor(self.settings)
        self.assertIs(d['command_ok'], False)
        self.assertIn('interpreter is gone', d['command_error'])

    def test_the_installer_script_exits_non_zero_for_a_broken_engine_with_nothing_installed(self):
        """The engine fault alone has to fail the check, not only a bad stored command."""
        copy = os.path.join(self.dir, 'broken-copy')
        os.makedirs(copy)
        for name in ('src', 'hooks', 'rulebook'):
            shutil.copytree(os.path.join(install.ROOT, name), os.path.join(copy, name),
                            ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(os.path.join(install.ROOT, 'install.py'), copy)
        os.remove(os.path.join(copy, 'rulebook', 'phrases.json'))
        proc = subprocess.run([sys.executable, os.path.join(copy, 'install.py'), '--doctor',
                               '--settings', self.settings],
                              input='', capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn('engine   : FAILED', proc.stdout)
        self.assertIn('phrases', proc.stdout)

    def test_doctor_notices_a_stored_command_that_prints_nothing(self):
        hook = os.path.join(self.dir, 'mute', brand.HOOK_FILENAME)
        os.makedirs(os.path.dirname(hook))
        open(hook, 'w').close()
        install.install(self.settings, hook_path=hook)
        d = install.doctor(self.settings)
        self.assertIs(d['command_ok'], False)
        self.assertIn('no output', d['command_error'])

    def test_doctor_does_not_run_a_script_that_only_sits_in_a_folder_named_like_the_hook(self):
        marker = os.path.join(self.dir, 'OTHER_RAN')
        other = os.path.join(self.dir, brand.HOOK_FILENAME, 'other.py')
        os.makedirs(os.path.dirname(other))
        with open(other, 'w', encoding='utf-8') as fh:
            fh.write('open(%r, "w").close()\nprint("{}")\n' % marker)
        self.write(self.entry(install.hook_command(hook_path=other)))
        d = install.doctor(self.settings)
        self.assertFalse(os.path.exists(marker))
        self.assertIs(d['command_ok'], False)

    def test_doctor_has_no_command_verdict_when_nothing_is_installed(self):
        self.write(REAL_LOOKING)
        self.assertIsNone(install.doctor(self.settings)['command_ok'])

    def entry(self, command):
        return json.dumps({'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': command}]}]}})

    def test_doctor_does_not_run_a_command_it_did_not_write(self):
        """A health check that runs every settings entry mentioning the hook's file
        name runs other people's commands. Only the exact shape install writes is run."""
        marker = os.path.join(self.dir, 'FOREIGN_RAN')
        self.write(self.entry('touch %s # %s' % (marker, brand.HOOK_FILENAME)))
        d = install.doctor(self.settings)
        self.assertFalse(os.path.exists(marker), 'doctor executed a foreign command')
        self.assertIs(d['command_ok'], False)
        self.assertIn('not run', d['command_error'])

    def test_doctor_does_not_run_a_lookalike_of_its_own_command(self):
        marker = os.path.join(self.dir, 'LOOKALIKE_RAN')
        real = install.hook_command(hook_path=self.copy_of_the_hook())
        quoted = real.split(';', 1)[0].split('=', 1)[1]            # the shell-quoted hook path
        hook = install._parse_command(real)[1]
        tampered = (real + '; touch %s' % marker,
                    # same shape, but the path is in double quotes, where $(...) runs
                    real.replace(quoted, '"$(touch %s)%s"' % (marker, hook), 1))
        # the same trick against a script that really exists under that odd name, so
        # that only the exact-match rule stands between doctor and running it
        literal = os.path.join(self.dir, 'lookalike', '$(touch %s)' % marker, brand.HOOK_FILENAME)
        os.makedirs(os.path.dirname(literal))
        with open(literal, 'w', encoding='utf-8') as fh:
            fh.write('print("{}")\n')
        genuine = install.hook_command(hook_path=literal)
        tampered += (genuine.replace(shlex.quote(literal), '"%s"' % literal, 1),)
        for cmd in tampered:
            self.assertNotIn(cmd, (real, genuine))
            self.write(self.entry(cmd))
            d = install.doctor(self.settings)
            self.assertFalse(os.path.exists(marker), 'doctor executed a tampered command: %s' % cmd)
            self.assertIs(d['command_ok'], False)

    def test_doctor_flags_an_entry_written_by_an_older_version_without_running_it(self):
        marker = os.path.join(self.dir, 'OLD_RAN')
        hook = os.path.join(self.dir, 'old', brand.HOOK_FILENAME)
        os.makedirs(os.path.dirname(hook))
        with open(hook, 'w', encoding='utf-8') as fh:
            fh.write('open(%r, "w").close()\nprint("{}")\n' % marker)
        self.write(self.entry('%s "%s"' % (sys.executable, hook)))
        d = install.doctor(self.settings)
        self.assertFalse(os.path.exists(marker))
        self.assertIs(d['command_ok'], False)
        self.assertIn('older version', d['command_error'])

    def test_doctor_notices_a_stored_command_that_prints_garbage(self):
        """Proves doctor really runs the command: a check that only looked for the
        script on disk would call this healthy."""
        hook = os.path.join(self.dir, 'garbage', brand.HOOK_FILENAME)
        os.makedirs(os.path.dirname(hook))
        with open(hook, 'w', encoding='utf-8') as fh:
            fh.write('print("this is not json")\n')
        install.install(self.settings, hook_path=hook)
        d = install.doctor(self.settings)
        self.assertIs(d['command_ok'], False)

    def test_doctor_reports_an_engaged_kill_switch(self):
        os.environ['CHEERLEADER_DISABLE'] = '1'
        try:
            d = install.doctor(self.settings)
        finally:
            os.environ.pop('CHEERLEADER_DISABLE', None)
        self.assertTrue(d['engine_ok'], d.get('engine_error'))
        self.assertTrue(d['kill_switch'])

    def test_the_installer_script_exits_non_zero_when_doctor_finds_a_fault(self):
        script = os.path.join(install.ROOT, 'install.py')

        def run():
            return subprocess.run([sys.executable, script, '--doctor', '--settings', self.settings],
                                  input='', capture_output=True, text=True, timeout=120)

        hook = self.copy_of_the_hook()
        install.install(self.settings, hook_path=hook)
        healthy = run()
        self.assertEqual(healthy.returncode, 0, healthy.stdout + healthy.stderr)
        self.assertIn('command  : ok', healthy.stdout)
        os.remove(hook)
        broken = run()
        self.assertEqual(broken.returncode, 1, broken.stdout)
        self.assertIn('command  : FAILED', broken.stdout)


class TestHookCommand(InstallCase):
    """The string Claude Code will run on every tool batch, for as long as it stays in
    settings.json. python3 exits 2 when it cannot open its script, and exit 2 is the
    one status a hook must never return: per the hooks reference it stops the agentic
    loop on PostToolBatch, and on Stop only the missing-file case is excused. A moved
    or deleted folder must degrade to silence."""

    def sh(self, cmd):
        return subprocess.run(cmd, shell=True, input='{}', capture_output=True, text=True, timeout=60)

    def script(self, *parts):
        path = os.path.join(self.dir, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('import sys\nsys.stdout.write(\'{"ran": true}\')\n')
        return path

    def test_a_missing_script_exits_zero_and_says_nothing(self):
        gone = os.path.join(self.dir, 'deleted', brand.HOOK_FILENAME)
        proc = self.sh(install.hook_command(hook_path=gone))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(proc.stderr, '', 'a moved folder must not print on every tool batch')

    def test_output_from_a_script_that_then_fails_is_not_passed_on(self):
        """Half a message from a hook that died is worse than none: on SessionStart
        plain stdout is given to Claude as context."""
        for ending in ('raise RuntimeError("died")', 'sys.exit(2)', 'sys.exit(1)'):
            path = os.path.join(self.dir, 'dies', brand.HOOK_FILENAME)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write('import sys\nsys.stdout.write("partial")\nsys.stdout.flush()\n%s\n' % ending)
            proc = self.sh(install.hook_command(hook_path=path))
            self.assertEqual(proc.returncode, 0, ending)
            self.assertEqual(proc.stdout, '', ending)

    def test_no_path_can_make_the_command_run_anything_else(self):
        """The folder name is whatever the user's disk says it is. Quoting that only
        handles spaces is an injection the first time a path holds a `$(...)`."""
        hostile = ('$(touch %s)', 'a`touch %s`b', 'a"b', 'a;touch %s', 'a&touch %s',
                   'a|touch %s', 'a\ntouch %s', "a'; touch %s; '", '$HOME', '*', '~', 'a\\b', '-n')
        for i, name in enumerate(hostile):
            marker = os.path.join(self.dir, 'RAN-%d' % i)
            folder = name % marker if '%s' in name else name
            hook = self.script('hostile-%d' % i, folder, brand.HOOK_FILENAME)
            proc = self.sh(install.hook_command(hook_path=hook))
            self.assertEqual(proc.returncode, 0, name)
            self.assertEqual(json.loads(proc.stdout or 'null'), {'ran': True}, 'did not run from %r' % name)
            self.assertFalse(os.path.exists(marker), 'the folder name %r was executed' % name)

    def test_no_interpreter_path_can_make_the_command_run_anything_else(self):
        marker = os.path.join(self.dir, 'RAN-interpreter')
        wrapper = os.path.join(self.dir, 'tools $(touch %s)' % marker, 'python3')
        os.makedirs(os.path.dirname(wrapper))
        with open(wrapper, 'w', encoding='utf-8') as fh:
            fh.write('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable)
        os.chmod(wrapper, os.stat(wrapper).st_mode | stat.S_IXUSR)
        proc = self.sh(install.hook_command(python=wrapper,
                                            hook_path=self.script('hooks', brand.HOOK_FILENAME)))
        self.assertEqual(json.loads(proc.stdout or 'null'), {'ran': True})
        self.assertFalse(os.path.exists(marker))

    def test_a_missing_interpreter_exits_zero(self):
        proc = self.sh(install.hook_command(python=os.path.join(self.dir, 'no-such-python'),
                                            hook_path=self.script('hooks', brand.HOOK_FILENAME)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, '')

    def test_the_real_hook_still_runs_through_it(self):
        proc = self.sh(install.hook_command())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {})

    def test_a_script_path_with_spaces_and_non_ascii_survives_the_shell(self):
        hook = self.script('\u0394\u03bf\u03ba\u03b9\u03bc\u03ae folder', "it's here", brand.HOOK_FILENAME)
        proc = self.sh(install.hook_command(hook_path=hook))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {'ran': True})

    def test_an_interpreter_path_with_a_space_survives_the_shell(self):
        wrapper = os.path.join(self.dir, 'my tools', 'python3')
        os.makedirs(os.path.dirname(wrapper))
        with open(wrapper, 'w', encoding='utf-8') as fh:
            fh.write('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable)
        os.chmod(wrapper, os.stat(wrapper).st_mode | stat.S_IXUSR)
        proc = self.sh(install.hook_command(python=wrapper,
                                            hook_path=self.script('hooks', brand.HOOK_FILENAME)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {'ran': True})

    def test_a_relative_hook_path_is_made_absolute(self):
        """`-V` as a script name would reach python as an option."""
        cmd = install.hook_command(hook_path='-V')
        self.assertEqual(install._parse_command(cmd), None)        # not named like the hook
        cmd = install.hook_command(hook_path=os.path.join('.', brand.HOOK_FILENAME))
        python, hook = install._parse_command(cmd)
        self.assertTrue(os.path.isabs(hook))

    def test_the_command_names_the_hook_once(self):
        """Uninstall finds its own entries by this marker, and the idempotence test
        counts it, so the path must not be repeated inside the command."""
        self.assertEqual(install.hook_command().count(install.MARKER), 1)

    def test_an_entry_written_by_an_older_version_is_still_recognised(self):
        old = {'hooks': {'Stop': [{'hooks': [{'type': 'command',
               'command': '%s "%s"' % (sys.executable, install.HOOK)}]}]}}
        self.write(json.dumps(old))
        self.assertEqual(install.uninstall(self.settings)['removed'], 1)


if __name__ == '__main__':
    unittest.main()
