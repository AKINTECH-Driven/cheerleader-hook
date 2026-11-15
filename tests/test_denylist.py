import copy
import json
import os
import shutil
import tempfile
import unittest
from _ctx import fx  # noqa: F401
from horme import denylist, rulebook


class TestDenylist(unittest.TestCase):

    def test_it_loads_both_groups(self):
        self.assertGreaterEqual(len(denylist.patterns()), 12)

    def test_every_entry_explains_itself(self):
        for e in denylist.entries():
            self.assertTrue(e.get('why'), 'a denylist entry with no rationale cannot be audited')

    def test_group_a_catches_the_briefs_backfiring_phrases(self):
        for bad in ("You're so smart, you'll get this",
                    "Just relax and it'll come",
                    "Don't worry, it's not that bad",
                    "You have to push through this",
                    "Come on, you've totally got this",
                    "Good job so far!",
                    "It's easy once you see it",
                    "You're better than the others at this"):
            self.assertTrue(denylist.check(bad), 'missed backfiring phrase: %r' % bad)

    def test_group_b_catches_correctness_claims(self):
        """HORME's own failure mode. These must be structurally unsayable."""
        for bad in ("That looks right to me",
                    "This is fine, move on",
                    "It works now",
                    "You're done here",
                    "Close enough, ship it",
                    "The tests are passing"):
            self.assertTrue(denylist.check(bad), 'missed correctness claim: %r' % bad)

    def test_it_reports_which_pattern_tripped(self):
        hits = denylist.check("You're so smart")
        self.assertTrue(hits[0].get('source') or hits[0].get('why'))

    def test_legitimate_encouragement_passes(self):
        for ok in ("This one is genuinely hard. Smallest next move: print the actual value.",
                   "What is stuck is specific: the merge span in importer.py, and it has not been cracked yet.",
                   "You could reproduce it in isolation, or change the command rather than the code."):
            self.assertEqual(denylist.check(ok), [], 'false positive on: %r' % ok)

    def test_it_is_case_insensitive(self):
        self.assertTrue(denylist.check("YOU HAVE TO PUSH THROUGH"))

    def test_empty_and_hostile_input_do_not_raise(self):
        self.assertEqual(denylist.check(''), [])
        self.assertEqual(denylist.check(None), [])
        self.assertEqual(denylist.check(12345), [])


class TestFailClosedOnLoad(unittest.TestCase):
    """The module calls itself fail-closed, and for a match it was. For everything that
    stops the check from running it failed open: a missing or unreadable denylist.json
    gave no patterns, so every message passed; a pattern that did not compile was
    dropped in silence; an exception inside the check came back as `clean`. A guard
    that cannot run must stop the message, not wave it through."""

    OK_TEXT = 'This one is genuinely hard. Smallest next move: print the actual value.'
    GROUPS = ('group_a_backfires', 'group_b_correctness_claims')

    def setUp(self):
        self.good = copy.deepcopy(rulebook.load('denylist', refresh=True))
        denylist.reset()

    def tearDown(self):
        rulebook.load('denylist', refresh=True)
        denylist.reset()

    def use(self, data):
        rulebook._CACHE['denylist'] = data
        denylist.reset()

    def assertUnavailable(self, hits, msg=''):
        self.assertTrue(hits, msg or 'an unusable denylist let the text through')
        self.assertEqual(hits[0]['group'], denylist.UNAVAILABLE, msg)
        self.assertTrue(hits[0].get('why'), 'the reason must be reported')

    def test_the_shipped_rulebook_has_no_problems(self):
        self.assertEqual(denylist.problems(), [])
        self.assertEqual(denylist.check(self.OK_TEXT), [])

    def test_an_unreadable_rulebook_trips_on_everything(self):
        self.use({})
        self.assertTrue(denylist.problems())
        self.assertUnavailable(denylist.check(self.OK_TEXT))

    def test_an_unusable_rulebook_outranks_an_empty_or_odd_text(self):
        """`nothing to check` is only an answer from a guard that works."""
        self.use({})
        for text in ('', None, 12345):
            self.assertUnavailable(denylist.check(text), 'answered clean for %r' % (text,))

    def test_a_missing_or_empty_group_trips_on_everything(self):
        for group in self.GROUPS:
            gone = copy.deepcopy(self.good)
            del gone[group]
            self.use(gone)
            self.assertUnavailable(denylist.check(self.OK_TEXT), 'missing %s' % group)
            empty = copy.deepcopy(self.good)
            empty[group] = []
            self.use(empty)
            self.assertUnavailable(denylist.check(self.OK_TEXT), 'empty %s' % group)

    def test_a_pattern_that_does_not_compile_trips_on_everything(self):
        """One dropped rule is one phrase that can now be said. Nobody would know."""
        bad = copy.deepcopy(self.good)
        bad[self.GROUPS[1]].append({'pattern': '(unclosed', 'why': 'typo in the rulebook'})
        self.use(bad)
        self.assertUnavailable(denylist.check(self.OK_TEXT))
        self.assertIn('(unclosed', denylist.check(self.OK_TEXT)[0]['why'])

    def test_an_entry_without_a_pattern_trips_on_everything(self):
        for junk in ({'why': 'no pattern here'}, 'not even an object', {'pattern': ''}):
            bad = copy.deepcopy(self.good)
            bad[self.GROUPS[0]].append(junk)
            self.use(bad)
            self.assertUnavailable(denylist.check(self.OK_TEXT), 'accepted %r' % (junk,))

    def test_a_failure_inside_the_check_is_a_trip_not_a_pass(self):
        orig = denylist.patterns

        def boom(*_a, **_k):
            raise RuntimeError('injected failure')

        denylist.patterns = boom
        try:
            hits = denylist.check(self.OK_TEXT)
        finally:
            denylist.patterns = orig
        self.assertUnavailable(hits)

    def test_a_rulebook_that_can_match_nothing_trips_on_everything(self):
        """It loads, it compiles, and it vouches for every message. Each group has to
        prove it still catches the phrase it exists for."""
        for dead in ('(?!)', 'zzzqqq'):
            gutted = copy.deepcopy(self.good)
            for group in self.GROUPS:
                for e in gutted[group]:
                    e['pattern'] = dead
            self.use(gutted)
            self.assertUnavailable(denylist.check(self.OK_TEXT), 'gutted with %r' % dead)

    def test_one_gutted_group_is_enough_to_trip(self):
        for group in self.GROUPS:
            gutted = copy.deepcopy(self.good)
            for e in gutted[group]:
                e['pattern'] = '(?!)'
            self.use(gutted)
            self.assertUnavailable(denylist.check(self.OK_TEXT), 'gutted %s' % group)

    def test_groups_swapped_for_each_other_trip_on_everything(self):
        a, b = self.GROUPS
        swapped = copy.deepcopy(self.good)
        swapped[a], swapped[b] = swapped[b], swapped[a]
        self.use(swapped)
        self.assertUnavailable(denylist.check(self.OK_TEXT))

    def test_a_group_must_catch_its_own_canary(self):
        """Correctness claims filed under the other group, and their own group left
        with nothing that can match: the rulebook is no longer the one that was
        reviewed, even though every pattern is still in it somewhere."""
        a, b = self.GROUPS
        moved = copy.deepcopy(self.good)
        moved[a] = moved[a] + moved[b]
        moved[b] = [{'pattern': '(?!)', 'why': 'emptied'}]
        self.use(moved)
        self.assertUnavailable(denylist.check(self.OK_TEXT))

    def test_a_banned_phrase_is_caught_inside_a_long_message(self):
        """A real intervention runs to 800 characters and more. A check that is only
        ever tried on one-liners proves nothing about the text that ships."""
        body = ' '.join([self.OK_TEXT] * 14)
        self.assertGreater(len(body), 900)
        self.assertEqual(denylist.check(body), [])
        for bad in ('That looks right to me.', 'Good job so far!'):
            hits = denylist.check(body + ' ' + bad + ' ' + body)
            self.assertTrue(hits, 'missed %r inside a long message' % bad)
            self.assertNotEqual(hits[0]['group'], denylist.UNAVAILABLE)

    def test_a_banned_phrase_is_caught_anywhere_in_a_very_long_message(self):
        lines = [self.OK_TEXT] * 300                       # about twenty thousand characters
        self.assertEqual(denylist.check('\n'.join(lines)), [])
        for position in (2, 150, 299):
            poisoned = list(lines)
            poisoned[position] = 'It works now.'
            hits = denylist.check('\n'.join(poisoned))
            self.assertTrue(hits, 'missed a banned phrase on line %d of %d' % (position, len(lines)))
            self.assertNotEqual(hits[0]['group'], denylist.UNAVAILABLE)

    def test_refresh_reads_the_file_again(self):
        """The rulebook loader keeps its own cache. A refresh that only forgets the
        compiled patterns would never notice a denylist deleted after first use."""
        tmp = tempfile.mkdtemp(prefix='horme-denylist-')
        orig = rulebook._DIR
        try:
            shutil.copy2(rulebook.path_for('denylist'), os.path.join(tmp, 'denylist.json'))
            rulebook._DIR = tmp
            self.assertEqual(denylist.problems(refresh=True), [])
            os.remove(os.path.join(tmp, 'denylist.json'))
            self.assertTrue(denylist.problems(refresh=True))
            self.assertUnavailable(denylist.check(self.OK_TEXT))
            with open(os.path.join(tmp, 'denylist.json'), 'w', encoding='utf-8') as fh:
                json.dump(self.good, fh)
            self.assertEqual(denylist.problems(refresh=True), [])
        finally:
            rulebook._DIR = orig
            shutil.rmtree(tmp, ignore_errors=True)

    def test_it_recovers_once_the_rulebook_is_whole_again(self):
        self.use({})
        self.assertUnavailable(denylist.check(self.OK_TEXT))
        self.use(copy.deepcopy(self.good))
        self.assertEqual(denylist.check(self.OK_TEXT), [])
        self.assertTrue(denylist.check('That looks right to me'))


if __name__ == '__main__':
    unittest.main()
