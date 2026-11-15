"""The calibration record is meant to be committed, so it must not carry an account name."""
import importlib.util
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIBRATE = os.path.join(ROOT, 'tools', 'calibrate.py')
THRESHOLDS = os.path.join(ROOT, 'rulebook', 'thresholds.json')


def _load():
    spec = importlib.util.spec_from_file_location('calibrate_under_test', CALIBRATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(os.path.isfile(CALIBRATE), 'tools/ is not shipped in the lean export')
class TestCorpusPathIsRecordedWithoutTheHomeFolder(unittest.TestCase):

    def test_a_path_under_home_is_written_with_a_tilde(self):
        full = os.path.join(os.path.expanduser('~'), '.claude', 'projects')
        self.assertEqual(_load().display_path(full), '~/.claude/projects')

    def test_the_default_spelling_survives_unchanged(self):
        self.assertEqual(_load().display_path('~/.claude/projects'), '~/.claude/projects')

    def test_a_path_outside_home_is_kept_as_given(self):
        self.assertEqual(_load().display_path('/srv/corpus'), '/srv/corpus')


class TestShippedThresholdsFile(unittest.TestCase):

    def test_the_committed_record_names_no_absolute_home(self):
        with open(THRESHOLDS, encoding='utf-8') as fh:
            origin = json.load(fh)['_provenance']['derived_from']
        self.assertFalse(origin.startswith(('/Users/', '/home/')), origin)


if __name__ == '__main__':
    unittest.main()
