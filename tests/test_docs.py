"""The numbers README.md and SKILL.md state, checked against what they describe.

Both said 150 tests and 33 mutants for weeks after both figures had changed, and went
on describing limits the code no longer had. A number in a document is a claim like
any other: here each one is measured, so a change to the code or to the documents
that makes them disagree fails the suite.
"""
import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
from horme import signals, transcript  # noqa: E402


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


def methods_in(name):
    """How many test methods the file defines, counted from its syntax tree."""
    tree = ast.parse(read('tests', name))
    return sum(1 for node in tree.body if isinstance(node, ast.ClassDef)
               for item in node.body
               if isinstance(item, ast.FunctionDef) and item.name.startswith('test_'))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HAVE_ALL = all(os.path.exists(os.path.join(ROOT, *p)) for p in (
    ('README.md',), ('SKILL.md',), ('tools', 'mutate.py'), ('tools', 'calibrate.py')))


@unittest.skipUnless(HAVE_ALL, 'the documents or the tools are not part of this copy')
class TestTheDocumentsStateWhatIsMeasured(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.readme, cls.skill = read('README.md'), read('SKILL.md')
        files = sorted(n for n in os.listdir(os.path.join(ROOT, 'tests'))
                       if n.startswith('test_') and n.endswith('.py'))
        cls.tests = sum(methods_in(n) for n in files)
        cls.corpus = methods_in('test_real_corpus.py')
        dont_write = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            cls.mutants = len(load(os.path.join(ROOT, 'tools', 'mutate.py'), 'docs_mutate').MUTANTS)
            cls.min_tools = load(os.path.join(ROOT, 'tools', 'calibrate.py'), 'docs_calibrate').MIN_TOOLS
        finally:
            sys.dont_write_bytecode = dont_write
        cls.limits = json.loads(read('rulebook', 'hooks.json'))['limits']
        cls.measured = json.loads(read('rulebook', 'thresholds.json'))['_provenance']

    def numbers(self, pattern, text):
        found = re.findall(pattern, text)
        self.assertTrue(found, 'the documents no longer say this: %s' % pattern)
        return [tuple(int(x.replace(',', '')) for x in (m if isinstance(m, tuple) else (m,))) for m in found]

    def test_the_corpus_tests_exist(self):
        self.assertGreater(self.corpus, 0)

    def test_the_number_of_tests(self):
        without = self.tests - self.corpus
        for count in self.numbers(r'\b(\d+) tests\b', self.readme):
            self.assertIn(count[0], (self.tests, without), 'README.md says %d tests' % count[0])
        self.assertIn((self.tests,), self.numbers(r'\| (\d+) tests, offline \|', self.readme))
        self.assertEqual(self.numbers(r'# (\d+) tests\b', self.readme), [(self.tests,)])
        self.assertEqual(self.numbers(r'Three of the (\d+) tests read .* reports (\d+) tests and one skip', self.readme),
                         [(self.tests, without)])
        self.assertEqual(self.corpus, 3, 'README.md says three of the tests read your own transcripts')
        self.assertEqual(self.numbers(r'\((\d+) tests; with no transcripts of your own the runner reports (\d+) and one skip\)',
                                      self.skill), [(self.tests, without)])

    def test_the_number_of_mutants(self):
        for doc in (self.readme, self.skill):
            self.assertEqual(self.numbers(r'\b(\d+) mutants\b', doc), [(self.mutants,)])

    def test_the_caps_on_how_often_it_speaks(self):
        cap, gap = self.limits['max_per_session'], self.limits['min_seconds_between']
        self.assertEqual(self.numbers(r'At most (\d+) interventions per session, at least (\d+) seconds apart', self.readme),
                         [(cap, gap)])
        self.assertEqual(self.numbers(r'at most once per block and (\d+) times per session', self.readme), [(cap,)])
        self.assertEqual(self.numbers(r"one of the session's (\d+)", self.readme), [(cap,)])
        self.assertEqual(self.limits['max_per_episode'], 1, 'the documents say one intervention per block')
        self.assertEqual(self.numbers(r'pruned after (\d+) days', self.readme), [(self.limits['state_ttl_days'],)])

    def test_how_the_thresholds_were_measured(self):
        m = self.measured
        self.assertEqual(self.numbers(r'windowed over the last (\d+) tool calls', self.readme), [(m['window_tool_calls'],)])
        self.assertEqual(m['window_tool_calls'], signals.DEFAULT_WINDOW)
        self.assertEqual(self.numbers(r'(\d+) transcript files were scanned and (\d+) of them had at least (\d+) tool '
                                      r'results, so (\d+) were used\. With (\d+) sessions', self.readme),
                         [(m['sessions_scanned'], m['sessions_used'], self.min_tools, m['sessions_used'], m['sessions_used'])])

    def test_how_far_the_verdict_check_reads(self):
        half = transcript.SCAN_CAP // 2
        self.assertEqual(self.numbers(r'the last three tool results of any kind, each read whole up to ([\d,]+) characters',
                                      self.readme), [(transcript.SCAN_CAP,)])
        self.assertEqual(signals.VERDICT_TAIL, 3, 'the documents say the last three tool results')
        self.assertIn('the last three tool', self.skill)
        self.assertEqual(self.numbers(r'Past ([\d,]+) characters the verdict check reads the first and the last ([\d,]+) of a tool result',
                                      self.readme), [(transcript.SCAN_CAP, half)])
        self.assertEqual(self.numbers(r'reads only the first ([\d,]+) characters of a result', self.readme),
                         [(transcript.TEXT_CAP,)])
        self.assertEqual(self.numbers(r'takes the last (\d+) MB and at most (\d+) lines of the transcript', self.readme),
                         [(transcript.DEFAULT_MAX_BYTES // (1024 * 1024), transcript.DEFAULT_MAX_LINES)])
        self.assertEqual(transcript.DEFAULT_MAX_BYTES % (1024 * 1024), 0)

    def test_the_example_is_what_the_command_prints(self):
        """`What it says` shows the two text fields of the hook's answer for the shipped
        fixture. Run the command the README gives, under a throwaway home."""
        home = tempfile.mkdtemp(prefix='horme-docs-')
        try:
            env = dict((k, v) for k, v in os.environ.items() if not k.endswith('_DISABLE'))
            env.update(HOME=home, PYTHONPATH=os.path.join(ROOT, 'src'), PYTHONDONTWRITEBYTECODE='1')
            proc = subprocess.run(
                [sys.executable, '-m', 'horme.cli', '--force', '--event', 'Stop', '--explain', '--transcript',
                 os.path.join('tests', 'fixtures', 'stuck_repeat_error.jsonl'), '--session', 'demo'],
                cwd=ROOT, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        finally:
            shutil.rmtree(home, ignore_errors=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        answer = json.loads(proc.stdout)
        printed = answer['systemMessage'] + '\n\n' + answer['hookSpecificOutput']['additionalContext']
        self.assertIn('--transcript tests/fixtures/stuck_repeat_error.jsonl --session demo', self.readme)
        shown = self.readme.split('## What it says', 1)[1].split('```')[1].strip('\n')
        self.assertEqual(shown, printed)

    def test_which_gate_names_silence_it(self):
        """Either any name ending in -guard counts, or only the names the documents list.
        The documents say which, and the code decides whether they are right."""
        any_name = signals.adjudicated('some-other-guard exit 2')
        for doc, name in ((self.readme, 'README.md'), (self.skill, 'SKILL.md')):
            says_any = 'a name ending in `-guard`' in doc
            listed = re.findall(r'`([a-z][a-z0-9-]*-guard)`', doc)
            self.assertEqual(says_any, any_name, '%s is wrong about which -guard names count' % name)
            if not any_name:
                self.assertTrue(listed, '%s names no gate tool although only named ones count' % name)
                for gate in listed:
                    self.assertTrue(signals.adjudicated(gate + ' exit 2'), '%s lists %s, which does not count' % (name, gate))
                pattern = [p.pattern for p in signals.ADJUDICATION if p.pattern.endswith(r'-guard\b')]
                self.assertEqual(len(pattern), 1)
                in_code = re.search(r'\(\?:([^)]*)\)-guard', pattern[0]).group(1).split('|')
                self.assertEqual(sorted(listed), sorted(g + '-guard' for g in in_code),
                                 '%s does not list exactly the gate names the code matches' % name)


if __name__ == '__main__':
    unittest.main()
