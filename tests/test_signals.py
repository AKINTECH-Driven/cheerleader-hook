import json
import os
import random
import re
import shutil
import tempfile
import unittest
from _ctx import fx
import _samples as S
from horme import transcript, signals


def sig(name, **kw):
    return signals.extract(transcript.read_tail(fx(name)), **kw)


def tail_of(*results):
    """A window whose tool results are exactly `results`, oldest first."""
    events = []
    for i, text in enumerate(results):
        events.append(transcript._mk('tool_use', '', name='Bash',
                                     inp={'command': 'step %d' % i}, tool_use_id='t%d' % i))
        events.append(transcript._mk('tool_result', '', tool_use_id='t%d' % i,
                                     text=text, is_error=True))
    return signals.extract(events)


class TestSignalExtraction(unittest.TestCase):

    def test_clean_session_is_quiet(self):
        s = sig('clean_control.jsonl')
        self.assertLessEqual(s.repeated_error_count, 1)
        # It hit one error and recovered: max-run is truthfully 1, current-run is 0.
        self.assertLessEqual(s.consecutive_tool_errors, 1)
        self.assertEqual(s.current_error_run, 0)
        self.assertEqual(s.capitulation_hits, 0)
        self.assertLessEqual(s.calls_since_success, 6)

    def test_current_error_run_separates_erroring_now_from_erred_once(self):
        """A session that failed once and recovered must not read as a session
        that is failing right now. The classifier needs both numbers."""
        self.assertEqual(sig('clean_control.jsonl').current_error_run, 0)
        self.assertGreaterEqual(sig('stuck_repeat_error.jsonl').current_error_run, 1)

    def test_stuck_session_shows_a_repeated_error_signature(self):
        s = sig('stuck_repeat_error.jsonl')
        self.assertGreaterEqual(s.repeated_error_count, 5)
        self.assertIn('assertionerror', s.top_error_signature)

    def test_error_signature_normalises_away_paths_and_numbers(self):
        """The same failure with different line numbers must collapse to one signature."""
        a = signals.signature('AssertionError: expected 4 cells, got 1\n  File "/a/b.py", line 88')
        b = signals.signature('AssertionError: expected 4 cells, got 1\n  File "/c/d.py", line 91')
        self.assertEqual(a, b)

    def test_error_signature_keeps_genuinely_different_errors_apart(self):
        a = signals.signature('AssertionError: expected 4 cells, got 1')
        b = signals.signature('KeyError: research')
        self.assertNotEqual(a, b)

    def test_stuck_session_shows_edit_thrash_on_one_file(self):
        s = sig('stuck_repeat_error.jsonl')
        self.assertGreaterEqual(s.edit_thrash, 5)
        self.assertTrue(s.edit_thrash_file.endswith('importer.py'))

    def test_stuck_session_shows_command_repetition(self):
        s = sig('stuck_repeat_error.jsonl')
        self.assertGreaterEqual(s.command_repeat, 5)

    def test_capitulation_language_is_counted(self):
        s = sig('stuck_repeat_error.jsonl')
        self.assertGreaterEqual(s.capitulation_hits, 2)

    def test_error_samples_are_captured_for_downstream_specificity(self):
        s = sig('stuck_repeat_error.jsonl')
        self.assertTrue(s.error_samples)
        self.assertTrue(any('AssertionError' in t for t in s.error_samples))
        for t in s.error_samples:
            self.assertLessEqual(len(t), signals.SAMPLE_CHARS)

    def test_window_bounds_the_signals(self):
        """Whole-session counts are meaningless; a small window must see less."""
        wide = sig('stuck_repeat_error.jsonl', window=100)
        narrow = sig('stuck_repeat_error.jsonl', window=4)
        self.assertLess(narrow.repeated_error_count, wide.repeated_error_count)

    def test_environment_blocked_errors_are_flagged_separately(self):
        s = sig('infeasible.jsonl')
        self.assertGreaterEqual(s.env_blocked_errors, 5)

    def test_a_normal_failing_test_is_not_environment_blocked(self):
        s = sig('stuck_repeat_error.jsonl')
        self.assertEqual(s.env_blocked_errors, 0)

    # --- suppressors ---

    def test_verdict_adjacent_is_detected(self):
        self.assertTrue(sig('verdict_adjacent.jsonl').verdict_adjacent)

    def test_clean_session_is_not_verdict_adjacent_at_the_tail(self):
        self.assertFalse(sig('clean_control.jsonl').verdict_adjacent)

    def test_a_plain_failing_test_run_is_NOT_adjudication(self):
        """The load-bearing distinction. A red suite is precisely when HORME should
        help; suppressing on every `FAILED (failures=1)` would make the skill inert.
        Only an explicit *adjudication* — a verifier/review/gate verdict — suppresses."""
        self.assertFalse(sig('stuck_repeat_error.jsonl').verdict_adjacent)

    def test_prior_horme_injection_is_detected(self):
        self.assertTrue(sig('already_fired.jsonl').horme_recent)

    def test_no_prior_injection_in_a_plain_stuck_session(self):
        self.assertFalse(sig('stuck_repeat_error.jsonl').horme_recent)

    def test_a_flailing_subagent_does_not_make_the_parent_look_stuck(self):
        """The end-to-end version of the exclusion: signals must stay quiet."""
        s = sig('with_sidechain.jsonl')
        self.assertLessEqual(s.repeated_error_count, 1)
        self.assertEqual(s.current_error_run, 0)
        self.assertEqual(s.capitulation_hits, 0)

    # --- deliberate failure cases ---

    def test_empty_event_list_yields_an_empty_signalset(self):
        s = signals.extract([])
        self.assertEqual(s.tool_count, 0)
        self.assertEqual(s.repeated_error_count, 0)
        self.assertFalse(s.verdict_adjacent)

    def test_signalset_is_json_serialisable(self):
        import json
        json.dumps(sig('stuck_repeat_error.jsonl').as_dict())


class TestRunnerOutputIsNotAVerdict(unittest.TestCase):
    """The comment on ADJUDICATION promised that test output stays out of it. That held
    for `FAILED (failures=1)` and for nothing else: unittest's own per-failure header,
    jest's file line and go test's result lines all carry a standalone FAIL, so HORME
    went silent on a red run in three of the most common runners. A red run is when it
    is supposed to help."""

    def test_a_red_run_is_not_adjudication(self):
        for runner, output in S.RED_RUNS.items():
            self.assertFalse(tail_of(output).verdict_adjacent,
                             'a red %s run was read as a verdict' % runner)

    def test_a_green_run_is_not_adjudication_either(self):
        for runner, output in S.GREEN_RUNS.items():
            self.assertFalse(tail_of(output).verdict_adjacent,
                             'a green %s run was read as a verdict' % runner)

    def test_blank_lines_do_not_separate_a_bare_result_from_its_package_line(self):
        """Output that reached the transcript through a pipe or a wrapper often gains
        blank lines. go test's bare PASS or FAIL still belongs to the package line it
        sums up, and to the exit status line between them."""
        self.assertFalse(tail_of('PASS\n\nok  \tgithub.com/acme/p\t0.1s').verdict_adjacent)
        self.assertFalse(tail_of('--- FAIL: TestMerge (0.00s)\nFAIL\n\n\nexit status 1\n\n'
                                 'FAIL\tgithub.com/acme/p\t0.012s').verdict_adjacent)
        self.assertFalse(tail_of('FAIL\tgithub.com/acme/p\t0.012s\n\n\nFAIL\n\n').verdict_adjacent)
        self.assertTrue(tail_of('PASS\n\nreview complete\nok  \tgithub.com/acme/p\t0.1s').verdict_adjacent)

    def test_a_line_of_spaces_is_blank_and_an_indented_line_is_not(self):
        self.assertFalse(tail_of('FAIL\n   \nFAIL\tgithub.com/acme/p\t0.1s').verdict_adjacent)
        self.assertFalse(tail_of('PASS\n\t\nok  \tgithub.com/acme/p\t0.1s').verdict_adjacent)
        self.assertTrue(tail_of('review gate\nFAIL\n    see the report\nFAIL\tgithub.com/acme/p\t0.1s').verdict_adjacent)
        self.assertTrue(tail_of('PASS\n    with two warnings\nok  \tgithub.com/acme/p\t0.1s').verdict_adjacent)

    def test_red_runs_filling_the_whole_tail_are_not_adjudication(self):
        self.assertFalse(tail_of(S.UNITTEST_RED, S.JEST_RED, S.GO_RED).verdict_adjacent)


class TestGateNames(unittest.TestCase):
    """A tool whose name ends in -guard is a gate, and what a gate prints is a verdict
    being decided, whatever the gate is called. The rule is the pattern below. It is
    not run as a pattern: searched, it starts again at every word of a long hyphenated
    token and takes seconds on one line, so the name is found from its end backwards.
    The pattern stays here as the definition the code is held to."""

    RULE = re.compile(r'\b[a-z][a-z0-9]*(?:-[a-z0-9]+)*-guard\b')

    GATES = ('ran budget-guard: exit 2', 'release-2-guard exit 1', 'x-guard', 'a-b-c-guard.', '(budget-guard)',
             'budget-guard\n', 'see docs/budget-guard', 'abc-123-guard', '123-abc-guard', 'a1-guard',
             'a-guard-x', 'Foo-bar-guard', 'X1-guard-guard', 'budget-guard budget-guard', 'x-guard\tok',
             'z-guard', 'zeta-guard', 'ran jazz-guard', 'budget-zz-guard', 'a9z-guard', '9-z-guard',
             'a-1-guard', 'x-9-guard', 'a-1-2-guard', 'ab-1-guard exit 2')
    NOT_GATES = ('Budget-guard', 'BUDGET-GUARD', 'budget-guards', 'budget-guarded', 'budget_guard', 'safeguard',
                 'guard', '-guard', ' -guard', '1-guard', '123-456-guard', 'a--guard', 'budget -guard',
                 'budget- guard', 'X1-guard', '_a-guard', 'a-guard2', 'a-guard_', '\u00e9-guard', '\u00e9a-guard',
                 'a-Guard', 'a-GUARD', 'budget\n-guard', '\u0663a-guard', '\u0663x-guard', 'a\u0663-guard',
                 '1-2-guard', '-1-guard', 'A-1-guard')

    def test_the_samples_are_what_the_rule_says(self):
        for text in self.GATES:
            self.assertTrue(self.RULE.search(text), text)
        for text in self.NOT_GATES:
            self.assertFalse(self.RULE.search(text), text)

    def test_a_name_ending_in_guard_is_a_verdict(self):
        for text in self.GATES:
            self.assertTrue(signals.adjudicated(text), 'not read as a gate: %r' % text)
            self.assertTrue(tail_of('ok', text, 'ok').verdict_adjacent, text)

    def test_what_only_looks_like_one_is_not(self):
        for text in self.NOT_GATES:
            self.assertFalse(signals.adjudicated(text), 'read as a gate: %r' % text)

    def test_every_character_a_name_may_hold_is_known(self):
        """Each letter and digit, as the first character of a name, inside it, and as a
        part of its own. A name that could not hold a `z` would pass every other test here."""
        for c in 'abcdefghijklmnopqrstuvwxyz':
            for text in (c + '-guard', 'x' + c + '-guard', 'x-' + c + '-guard', c + '-1-guard'):
                self.assertTrue(signals.adjudicated(text), text)
        for d in '0123456789':
            for text in ('x' + d + '-guard', 'x-' + d + '-guard', 'x-' + d + d + '-guard'):
                self.assertTrue(signals.adjudicated(text), text)
            self.assertFalse(signals.adjudicated(d + '-guard'), d)

    def test_what_the_search_hands_back(self):
        """A match on the `-guard` that ends the name, not on the whole name. Callers
        ask only whether there is one."""
        gate = [p for p in signals.ADJUDICATION if isinstance(p, signals._GateName)][0]
        found = gate.search('ran budget-guard: exit 2')
        self.assertEqual((found.group(), found.span()), ('-guard', (10, 16)))
        self.assertIsNone(gate.search('ran Budget-guard: exit 2'))
        self.assertEqual(gate.pattern, self.RULE.pattern)

    def test_it_agrees_with_the_rule_on_generated_text(self):
        pieces = ('a', 'b1', '1', '9', 'A', '_', '-', '--', ' ', '\n', '.', 'guard', '-guard', 'x-guard', '\u00e9',
                  'Guard', '-guard-', 'guards', '0-', 'z', 'z9', '\u0663', 'a-1', '-9')
        rnd = random.Random(20261114)
        for _ in range(30000):
            text = ''.join(rnd.choice(pieces) for _ in range(rnd.randint(0, 12)))
            self.assertEqual(signals.adjudicated(text), bool(self.RULE.search(text)), repr(text))


class TestVerdictsStillSuppress(unittest.TestCase):
    """The other half, and the safety-critical one. Teaching the scan about runners must
    not teach it to ignore a verdict. Each exemption is as narrow as the runner's own
    format; anything else that says PASS or FAIL still silences HORME."""

    def test_every_verdict_shape_still_counts(self):
        for verdict in S.VERDICTS:
            self.assertTrue(tail_of(verdict).verdict_adjacent,
                            'no longer read as a verdict: %r' % verdict)

    def test_a_fail_header_only_stops_counting_under_the_unittest_rule_line(self):
        """`FAIL: <something>` is also how a gate reports. Only the header that sits
        directly under unittest's row of '=' is runner output."""
        self.assertTrue(tail_of('checking the draft\nFAIL: test_merge (gates.Budget)').verdict_adjacent)
        self.assertFalse(tail_of(S.UNITTEST_RED).verdict_adjacent)

    def test_a_bare_fail_line_only_stops_counting_inside_go_test_output(self):
        self.assertTrue(tail_of('building the report...\nFAIL\n').verdict_adjacent)
        self.assertFalse(tail_of(S.GO_RED).verdict_adjacent)

    def test_a_file_line_only_stops_counting_when_it_names_a_script_file(self):
        self.assertTrue(tail_of(' FAIL  budget table\n').verdict_adjacent)
        self.assertTrue(tail_of('PASS with two warnings').verdict_adjacent)
        self.assertFalse(tail_of(S.JEST_RED).verdict_adjacent)

    def test_a_verdict_next_to_runner_output_still_counts(self):
        for output in S.RED_RUNS.values():
            self.assertTrue(tail_of(output + '\n\nVERIFIER VERDICT: FAIL').verdict_adjacent)
            self.assertTrue(tail_of(output + '\nReviewer: FAIL, do not merge').verdict_adjacent)

    def test_a_verdict_in_an_earlier_result_of_the_tail_still_counts(self):
        self.assertTrue(tail_of('VERDICT: FAIL', S.UNITTEST_RED, S.GO_RED).verdict_adjacent)

    def test_only_the_tail_is_scanned(self):
        older = ['VERDICT: FAIL'] + ['ok'] * signals.VERDICT_TAIL
        self.assertFalse(tail_of(*older).verdict_adjacent)

    def test_known_quiet_cases_are_still_read_as_verdicts(self):
        """Runner formats the scan does not recognise. HORME stays silent on them,
        which is the safe side of the trade. Recorded so that widening an exemption
        to cover one of them is a decision somebody makes, not a side effect."""
        for output in S.STILL_QUIET:
            self.assertTrue(tail_of(output).verdict_adjacent, 'now exempt: %r' % output)

    def test_output_in_exactly_a_runners_format_is_let_through(self):
        """The cost of speaking on red runs: a gate that prints a runner's exact
        format is taken for the runner. Pinned here so that it stays a known cost."""
        for output in S.INDISTINGUISHABLE:
            self.assertFalse(tail_of(output).verdict_adjacent, output)

    def test_crlf_line_endings_change_nothing(self):
        for runner, output in S.RED_RUNS.items():
            self.assertFalse(tail_of(output.replace('\n', '\r\n')).verdict_adjacent, runner)
        for verdict in S.VERDICTS:
            self.assertTrue(tail_of(verdict.replace('\n', '\r\n')).verdict_adjacent, verdict)


class ScanCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='horme-scan-')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def session(self, *results):
        """Signals of a session read from a transcript file whose tool results are
        `results`, oldest first: each the output, or (output, is_error)."""
        path = os.path.join(self.dir, 'session.jsonl')
        with open(path, 'w', encoding='utf-8') as fh:
            for row in S.calls(*results):
                fh.write(json.dumps(row) + '\n')
        return signals.extract(transcript.read_tail(path))

    def seen(self, *results):
        return self.session(*results).verdict_adjacent


class TestTheWholeResultIsScanned(ScanCase):
    """A verifier prints its findings and then its verdict. With only the first 4,000
    characters of a result in view, the verdict of any long report was out of sight and
    HORME spoke right next to it. The check now reads the result as the transcript
    holds it."""

    VERDICTS = ('VERIFIER VERDICT: FAIL', 'gate: FAIL', 'FAIL', 'PASS',
                'signed off by the reviewer', 'code-review requested on the diff')

    def test_a_verdict_after_long_output_is_seen(self):
        for verdict in self.VERDICTS:
            for n in (100, 3900, 4100, 20000, 59000):
                for is_error in (True, False, None):   # a verifier's answer is not an error
                    self.assertTrue(self.seen((S.filler(n) + '\n' + verdict + '\n', is_error)),
                                    '%r after %d characters (is_error %r) was not seen' % (verdict, n, is_error))

    def test_a_verdict_in_the_middle_of_long_output_is_seen(self):
        for is_error in (True, False):
            report = S.filler(25000) + '\nVERDICT: FAIL\n' + S.filler(25000)
            self.assertTrue(self.seen((report, is_error)))

    def test_each_of_the_last_three_results_is_read_whole(self):
        """Not only the newest, not only the oldest: any of the three."""
        late = (S.filler(9000) + '\nVERDICT: FAIL\n', False)
        self.assertTrue(self.seen('ok', 'ok', late), 'newest of three')
        self.assertTrue(self.seen('ok', late, 'ok'), 'middle of three')
        self.assertTrue(self.seen(late, 'ok', 'ok'), 'oldest of three')
        self.assertFalse(self.seen(late, 'ok', 'ok', 'ok'), 'the fourth from the end is out of the tail')

    def test_a_short_verdict_counts_in_each_of_the_last_three_results(self):
        self.assertTrue(self.seen('ok', 'ok', 'VERDICT: FAIL'), 'newest of three')
        self.assertTrue(self.seen('ok', 'VERDICT: FAIL', 'ok'), 'middle of three')
        self.assertTrue(self.seen('VERDICT: FAIL', 'ok', 'ok'), 'oldest of three')

    def test_long_output_without_a_verdict_does_not_silence(self):
        for n in (4100, 20000, 60000, 60001, 100000):
            self.assertFalse(self.seen(S.filler(n)), n)

    def test_a_long_red_run_is_still_not_a_verdict(self):
        many_tests = ''.join('--- PASS: TestCase%03d (0.00s)\n' % i for i in range(400))
        for runner, output in (
                ('unittest after a long build log', S.filler(9000) + '\n' + S.UNITTEST_RED),
                ('unittest -v after a long build log', S.filler(9000) + '\n' + S.UNITTEST_VERBOSE_RED),
                ('go test with four hundred tests', many_tests + S.GO_RED),
                ('unittest, then a long tail of log', S.UNITTEST_RED + '\n' + S.filler(9000))):
            self.assertGreater(len(output), 4000)
            self.assertFalse(self.seen(output), runner)

    def test_a_jest_run_is_known_by_a_summary_far_below_its_file_line(self):
        """jest prints the file line first and `Tests:` last. With the summary cut off,
        a long red jest run looked like a gate's FAIL line and HORME went quiet on it."""
        file_line, rest = S.JEST_RED.split('\n', 1)
        self.assertFalse(self.seen(file_line + '\n' + S.filler(9000) + '\n' + rest))

    def test_known_cost_a_summary_anywhere_in_the_result_vouches_for_a_file_line(self):
        """The other side of the test above, recorded so that it stays a decision: a
        gate that prints a jest-shaped line is taken for jest when anything further
        down the same result looks like jest's summary. jest prints its summary last,
        however long the run, so the distance cannot be bounded."""
        gate = ' FAIL  src/budget.test.js\nbudget gate rejects the draft\n'
        self.assertFalse(self.seen(gate + S.filler(10000) + '\nTests:       3 passed, 3 total'))
        self.assertTrue(self.seen(gate + S.filler(10000)))

    def test_only_the_verdict_check_reads_past_the_text_cap(self):
        """The other signals were calibrated on the first 4,000 characters. An error
        phrase that sits further down must not start counting now. (The error signature
        and the quoted sample read only the first 800 and 400 characters in any case.)"""
        phrase = 'zsh: command not found: docker\n'
        inside = S.filler(3960) + '\n' + phrase            # ends at character 3,992
        outside = S.filler(4010) + '\n' + phrase           # starts at character 4,011
        self.assertEqual(self.session(inside, inside, inside).env_blocked_errors, 3)
        self.assertEqual(self.session(outside, outside, outside).env_blocked_errors, 0)


class TestPastTheScanCap(ScanCase):
    """Past 60,000 characters the check reads the first and the last 30,000 as two
    separate texts. Whatever the cut does, it must do it toward silence: nothing on one
    side may vouch for a line on the other, and a line the cut went through is read
    as it stands and can never pass for runner output."""

    def test_a_verdict_at_either_end_is_seen(self):
        for is_error in (True, False):
            self.assertTrue(self.seen(('VERDICT: FAIL\n' + S.filler(100000), is_error)))
            self.assertTrue(self.seen((S.filler(100000) + '\nVERDICT: FAIL', is_error)))
            self.assertTrue(self.seen((S.filler(29000) + '\nFAIL\n' + S.filler(71000), is_error)))
            self.assertTrue(self.seen((S.filler(71000) + '\nFAIL\n' + S.filler(29000), is_error)))

    def test_a_verdict_at_either_end_of_a_very_long_result_is_seen(self):
        """The last 30,000 characters of a result of any length, not of its first part."""
        for n in (150000, 1000000):
            self.assertTrue(self.seen((S.filler(n) + '\nVERIFIER VERDICT: FAIL\n', False)), n)
            self.assertTrue(self.seen(('VERIFIER VERDICT: FAIL\n' + S.filler(n), False)), n)
            self.assertTrue(self.seen((S.filler(n) + '\nFAIL', False)), n)
            self.assertFalse(self.seen((S.filler(n), False)), n)

    def test_a_single_long_line_is_read_at_both_ends(self):
        line = 'x' * 100000
        self.assertTrue(self.seen(line + ' VERDICT: FAIL'))
        self.assertTrue(self.seen('VERDICT: FAIL ' + line))

    def test_known_limit_the_middle_is_not_read(self):
        """Recorded so that it stays a decision. A result this long is rare, and the
        cap is what keeps the hook inside its time budget."""
        self.assertFalse(self.seen(S.filler(50000) + '\nVERDICT: FAIL\n' + S.filler(50000)))
        centred = S.filler(30243) + '\nVERDICT: FAIL\n' + S.filler(30242)      # 60,500 in all
        self.assertEqual(len(centred), 60500)
        self.assertFalse(self.seen(centred))

    def test_a_red_run_wholly_inside_either_half_is_still_not_a_verdict(self):
        self.assertFalse(self.seen(S.UNITTEST_RED + '\n' + S.filler(80000)))
        self.assertFalse(self.seen(S.filler(80000) + '\n' + S.GO_RED))

    def test_a_rule_beyond_the_cut_does_not_vouch_for_a_header(self):
        """unittest's failure header counts as runner output only between its two rules.
        Here the rule of dashes is the first line of the second half: it was never the
        neighbour of the header that ends the first half."""
        header = '\n' + '=' * 70 + '\nFAIL: test_budget (gates.Budget)'
        first = S.filler(30000 - len(header)) + header
        second = '-' * 70 + '\n' + S.filler(30000 - 71)
        self.assertEqual((len(first), len(second)), (30000, 30000))
        side_by_side = first + '\n' + second
        self.assertFalse(signals.adjudicated(side_by_side), 'the sample is wrong: adjacent, this is unittest output')
        self.assertTrue(self.seen(first + S.filler(40000) + second))

    def test_a_package_line_beyond_the_cut_does_not_vouch_for_a_bare_fail(self):
        first = S.filler(30000 - 6) + '\nFAIL\n'
        second = 'FAIL\tgithub.com/acme/p\t0.1s\n'
        second += S.filler(30000 - len(second))
        self.assertEqual((len(first), len(second)), (30000, 30000))
        self.assertFalse(signals.adjudicated(first + second), 'the sample is wrong: adjacent, this is go test output')
        self.assertTrue(self.seen(first + S.filler(40000) + second))

    def test_the_end_of_a_cut_line_cannot_pass_for_a_runner_line(self):
        """`release gate says FAIL<tab>...` is a verdict. Cut just before FAIL, what is
        left of the line is go test's package line to the letter."""
        tail_line = 'FAIL\tgithub.com/acme/p\t0.012s\n'
        second = tail_line + S.filler(30000 - len(tail_line))
        whole = S.filler(50000) + '\nrelease gate says ' + second
        self.assertEqual(len(second), 30000)
        self.assertFalse(signals.adjudicated(second), 'the sample is wrong: alone, this is go test output')
        self.assertTrue(signals.adjudicated(whole[:59000]), 'the sample is wrong: uncut, this is a verdict')
        self.assertTrue(self.seen(whole))

    def test_the_start_of_a_cut_line_cannot_pass_for_a_runner_line(self):
        head_line = 'FAIL\tgithub.com/acme/p\t0.012s'
        first = S.filler(30000 - len(head_line) - 1) + '\n' + head_line
        whole = first + ' is what the release gate printed\n' + S.filler(50000)
        self.assertEqual(len(first), 30000)
        self.assertFalse(signals.adjudicated(first), 'the sample is wrong: alone, this is go test output')
        self.assertTrue(self.seen(whole))

    def test_a_vitest_line_cut_after_its_trail_mark_stays_a_verdict(self):
        """` FAIL  src/a.test.ts >gate` is a verdict: vitest's trail is ` > suite`, with
        spaces. Cut right after the `>`, what is left looked like the start of a trail."""
        summary, last = ' Test Files  1 failed (1)\n', '\n FAIL  src/a.test.ts >'
        first = summary + S.filler(30000 - len(summary) - len(last)) + last
        self.assertEqual(len(first), 30000)
        whole = first + 'gate\n' + S.filler(50000)
        self.assertTrue(signals.adjudicated(whole[:59000]), 'the sample is wrong: uncut, this is a verdict')
        self.assertTrue(self.seen((whole, False)))

    def test_a_summary_cut_short_does_not_vouch_for_a_file_line(self):
        """`Tests:       1 failed_logins here` is not jest's summary. Cut after `failed`
        it read as one, and vouched for the gate's line above it."""
        gate, last = ' FAIL  src/budget.test.js\n', '\nTests:       1 failed'
        first = gate + S.filler(30000 - len(gate) - len(last)) + last
        self.assertEqual(len(first), 30000)
        self.assertFalse(signals.adjudicated(first), 'the sample is wrong: cut here, this reads as a jest run')
        whole = first + '_logins here\n' + S.filler(50000)
        self.assertTrue(signals.adjudicated(whole[:59000]), 'the sample is wrong: uncut, this is a verdict')
        self.assertTrue(self.seen((whole, False)))

    def test_the_end_of_the_first_half_is_not_the_end_of_the_output(self):
        """go test's closing FAIL is excused only as the last line of the output. The
        last whole line of the first half is not that."""
        last = 'FAIL\tgithub.com/acme/p\t0.1s\nFAIL\n'
        first = S.filler(30000 - len(last) - 1) + '\n' + last
        self.assertEqual(len(first), 30000)
        self.assertFalse(signals.adjudicated(first), 'the sample is wrong: alone, this is go test output')
        for rest in ('release blocked by the gate\n', 'release blocked\nby the gate\n'):
            whole = first + rest + S.filler(50000)
            self.assertTrue(signals.adjudicated(whole[:59000]), 'the sample is wrong: uncut, this is a verdict')
            self.assertTrue(self.seen((whole, False)), rest)
        shifted = first[1:] + 'r' + 'elease blocked by the gate\n' + S.filler(50000)
        self.assertTrue(self.seen((shifted, False)), 'the cut one character into the next line')

    def test_a_rule_on_the_second_line_of_the_second_half_does_not_vouch_either(self):
        header = '\n' + '=' * 70 + '\nFAIL: test_budget (gates.Budget)\nand the gate '
        first = S.filler(30000 - len(header)) + header
        second = 'closed\n' + '-' * 70 + '\n'
        second += S.filler(30000 - len(second))
        self.assertEqual((len(first), len(second)), (30000, 30000))
        self.assertTrue(self.seen((first + 'x' * 40000 + second, False)))

    def test_known_limit_a_red_run_split_by_the_cut_can_read_as_a_verdict(self):
        """The cost of the two rules above, and the safe side of it: a failure header
        whose rule of dashes fell into the unread middle is not vouched for either."""
        header = '\n' + '=' * 70 + '\nFAIL: test_budget (gates.Budget)'
        first = S.filler(30000 - len(header)) + header
        whole = first + '\n' + '-' * 70 + '\nTraceback (most recent call last):\n' + S.filler(60000)
        self.assertFalse(signals.adjudicated(whole[:59000]), 'the sample is wrong: uncut, this is unittest output')
        self.assertEqual(len(first), 30000)
        self.assertTrue(self.seen(whole))

    def test_known_limit_a_word_cut_in_two_can_read_as_a_verdict(self):
        whole = S.filler(29995) + '\nFAILED tests/test_x.py::test_a - assert 1 == 4\n' + S.filler(40000)
        self.assertEqual(whole[29996:30000], 'FAIL')
        self.assertFalse(signals.adjudicated(whole[:59000]))
        self.assertTrue(self.seen(whole))


class TestEveryAlignmentOfTheCut(unittest.TestCase):
    """The rule past the cap, tried at every position instead of at chosen ones: if a
    verdict word of a line that the whole result does not excuse lies wholly inside what
    is read, the hook is silent. The halves are 300 characters here instead of 30,000,
    which is the same code at a size where each of some 5,000 alignments is cheap."""

    HALF = 300
    LENGTH = 900

    #: (lines, index of the line whose PASS, FAIL or verdict word must count). Each
    #: group is a verdict when read whole, and tempting to excuse when cut.
    GROUPS = (
        ([' Test Files  1 failed (1)', ' FAIL  src/a.test.ts >gate'], 1),
        ([' Test Files  1 failed (1)', ' FAIL  src/a.test.js  >x'], 1),
        ([' FAIL  src/budget.test.js', 'Tests:       1 failed_logins here'], 0),
        (['Tests:       1 failed, 1 total', ' FAIL  src/a.test.js.bak'], 1),
        (['Tests:       1 failed, 1 total', ' FAIL  src/a.test.js 3 violations found'], 1),
        (['release gate says FAIL\tgithub.com/acme/p\t0.012s'], 0),
        (['FAIL\tgithub.com/acme/p\t0.012s is what the gate printed'], 0),
        (['FAIL\tgithub.com/acme/p\t0.1s', 'FAIL', 'release blocked by the gate'], 1),
        (['gate result', 'FAIL', 'FAIL\tgithub.com/acme/p\t0.1s was the reason'], 1),
        (['PASS', 'FAIL\tgithub.com/acme/p\t0.1s'], 0),
        (['=' * 70, 'FAIL: test_budget (gates.Budget)', 'no rule of dashes follows'], 1),
        (['=' * 70, 'FAIL: test_budget (gates.Budget) and the gate closed', '-' * 70], 1),
        (['test_budget (gates.Budget) ... FAIL and the gate closed'], 0),
        (['test_budget (gates.Budget)', 'Release gate ... FAIL and more'], 1),
        (['--- FAIL: TestGate (0.00s) blocked'], 0),
        (['the --- FAIL: TestGate (0.00s)'], 0),
        (['VERIFIER VERDICT: no'], 0),
        (['gate: FAIL'], 0),
        (['signed off by the reviewer'], 0),
    )

    def texts(self, lines, sep, start):
        """The group at offset `start` of a result of LENGTH characters."""
        group = sep.join(lines) + sep
        before = S.filler(start - 1) + '\n' if start else ''
        full = before + group
        return full + S.filler(self.LENGTH - len(full)), len(before)

    def token_span(self, lines, index, sep, at):
        offset = at + sum(len(l) + len(sep) for l in lines[:index])
        m = signals._STANDALONE.search(lines[index]) or [p.search(lines[index]) for p in signals._VERDICT_WORDS
                                                         if p.search(lines[index])][0]
        return offset + m.start(), offset + m.end()

    def test_each_group_is_a_verdict_when_read_whole(self):
        for lines, _index in self.GROUPS:
            self.assertTrue(signals.adjudicated('\n'.join(lines)), lines)

    def test_a_visible_verdict_word_counts_at_every_alignment(self):
        tried = visible = 0
        for lines, index in self.GROUPS:
            for sep in ('\n', '\r\n'):
                width = len(sep.join(lines)) + len(sep)
                starts = (list(range(self.HALF - width - 4, self.HALF + 6))
                          + list(range(self.LENGTH - self.HALF - width - 4, self.LENGTH - self.HALF + 6)))
                for start in starts:
                    full, at = self.texts(lines, sep, start)
                    self.assertEqual(len(full), self.LENGTH)
                    tried += 1
                    a, b = self.token_span(lines, index, sep, at)
                    if not (b <= self.HALF or a >= self.LENGTH - self.HALF):
                        continue                    # the word itself lies in what is not read
                    visible += 1
                    parts = transcript._scan_parts(full, text_cap=0, scan_cap=2 * self.HALF)
                    self.assertTrue(signals._verdict_in(parts),
                                    'not seen: %r with %r, group at character %d' % (lines[index], sep, start))
        self.assertGreater(tried, 5000)
        self.assertGreater(visible, 2000)

    def test_filler_alone_is_never_a_verdict_at_this_size(self):
        parts = transcript._scan_parts(S.filler(self.LENGTH), text_cap=0, scan_cap=2 * self.HALF)
        self.assertEqual(len(parts), 4)
        self.assertFalse(signals._verdict_in(parts))


class TestTheVerdictCheckStaysFast(unittest.TestCase):
    """The hook runs on every tool batch and has 50 ms. One pattern that retried from
    every character of a long token took 16 seconds on a single 59,000-character line
    once the check could read that far. Each of these took seconds, or would if a
    pattern like that came back, or if the text were scanned again for every line that
    carries a PASS or FAIL, or if a neighbour were looked up by walking the lines.
    Measured: 3 to 25 ms each, up to 48 ms on a busy machine. The ceiling is 0.3 s,
    which a slow or busy machine still meets and none of those mistakes does. A
    slowdown by a constant factor passes; only a wrong order of growth is caught."""

    SUMMARY = '\nTests:       1 failed, 3 passed, 4 total\n'
    SHAPES = (
        ('one long token on a jest line', ' FAIL  ' + 'a' * 59000 + SUMMARY),
        ('a long token full of dots', ' PASS  ' + 'a.' * 29500 + SUMMARY),
        ('a long path of __tests__ folders', ' FAIL  ' + '/__tests__/' * 5400 + SUMMARY),
        ('a long token that ends as a test file', ' FAIL  ' + 'a' * 59000 + '/x.test.js' + SUMMARY),
        ('sixty thousand empty lines and one verdict', '\n' * 59990 + 'FAIL'),
        ('thirty thousand short lines and one verdict', 'x\n' * 29990 + 'PASS'),
        ('twelve thousand bare verdict lines', 'FAIL\n' * 12000),
        ('one long line ending in a result word', 'x' * 59000 + ' ... FAIL'),
        ('a long run of spaces after a file name', ' FAIL  a.test.js' + ' ' * 59000 + 'x' + SUMMARY),
        ('thousands of jest lines and a summary', ' PASS  src/a.test.js\n' * 2850 + SUMMARY),
        ('thousands of go packages that passed', 'PASS\nok  \tgithub.com/acme/p\t0.1s\n' * 1800),
        ('a bare result far above its package line', 'FAIL\n' + '\n' * 59960 + 'FAIL\tx/y\t0.012s\n'),
        ('bare results with blank lines between them', ('FAIL\n' + '\n' * 28) * 1800 + 'FAIL\tx/y\t0.012s\n'),
        ('thousands of go test lines above a failed package',
         '--- FAIL: TestCase (0.00s)\n' * 2100 + 'FAIL\tx/y\t0.012s\n'),
        ('thousands of go packages and a stray tab',
         'PASS\nok  \tgithub.com/acme/p\t0.1s\n' * 1790 + 'xFAIL\ty\n'),
        ('go packages behind a long run of short lines', 'x\n' * 17000 + 'PASS\nok  \tp\t0.1s\n' * 1500),
        ('one long hyphenated token', 'a-' * 30000),
        ('a long hyphenated token that ends in a gate name', 'a-' * 29990 + 'guard'),
        ('digits chained up to a guard', '1-' * 29990 + 'guard'),
        ('thousands of hyphenated words', 'alpha-beta-gamma-delta-epsilon-zeta-eta-theta\n' * 1300),
    )

    def test_no_shape_of_sixty_thousand_characters_takes_a_third_of_a_second(self):
        import time
        for name, text in self.SHAPES:
            self.assertLessEqual(len(text), 60100, name)
            t0 = time.perf_counter()
            signals.adjudicated(text)
            took = time.perf_counter() - t0
            self.assertLess(took, 0.3, '%s: the verdict check took %.2f s' % (name, took))

    def test_a_neighbour_is_found_without_reading_the_list_through(self):
        """Counted, not timed. Within 60,000 characters a neighbour search that walks
        the lines is some forty times slower, which a clock tells apart on a busy
        machine and not on a quiet one. What it reads does not depend on the machine."""
        class Counted(list):
            reads = 0

            def __getitem__(self, k):
                Counted.reads += 1
                return list.__getitem__(self, k)

            def __iter__(self):
                Counted.reads += len(self)
                return list.__iter__(self)

            def __reversed__(self):
                Counted.reads += len(self)
                return list.__reversed__(self)

        solid = Counted(range(0, 200000, 2))                 # every second line is not blank
        for i, step, expected in ((150001, 1, 150002), (150001, -1, 150000), (150000, 1, 150002),
                                  (150000, -1, 149998), (-5, 1, 0), (-5, -1, None),
                                  (199998, 1, None), (300000, -1, 199998), (0, -1, None)):
            Counted.reads = 0
            self.assertEqual(signals._neighbour(solid, i, step), expected, (i, step))
            self.assertLess(Counted.reads, 64, 'looking from line %d read %d entries' % (i, Counted.reads))

    def test_the_shapes_are_read_as_before(self):
        """Fast must not mean different: what each of these is, stays what it was."""
        expected = {'one long token on a jest line': True, 'a long token full of dots': True,
                    'a long path of __tests__ folders': True, 'a long token that ends as a test file': False,
                    'sixty thousand empty lines and one verdict': True,
                    'thirty thousand short lines and one verdict': True,
                    'twelve thousand bare verdict lines': True, 'one long line ending in a result word': True,
                    'a long run of spaces after a file name': True,
                    'thousands of jest lines and a summary': False,
                    'thousands of go packages that passed': False,
                    'a bare result far above its package line': False,
                    'bare results with blank lines between them': True,
                    'thousands of go test lines above a failed package': False,
                    'thousands of go packages and a stray tab': False,
                    'go packages behind a long run of short lines': False,
                    'one long hyphenated token': False,
                    'a long hyphenated token that ends in a gate name': True,
                    'digits chained up to a guard': False,
                    'thousands of hyphenated words': False}
        for name, text in self.SHAPES:
            self.assertEqual(signals.adjudicated(text), expected[name], name)


if __name__ == '__main__':
    unittest.main()
