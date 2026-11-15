import json
import os
import shutil
import tempfile
import unittest
from _ctx import fx
import _samples as S
from horme import brand, signals, transcript


class TestReadTail(unittest.TestCase):

    def test_returns_events_in_forward_chronological_order(self):
        ev = transcript.read_tail(fx('clean_control.jsonl'))
        self.assertTrue(ev, 'clean fixture should yield events')
        stamps = [e.ts for e in ev if e.ts]
        self.assertEqual(stamps, sorted(stamps), 'events must come back oldest-first')

    def test_classifies_the_verified_block_kinds(self):
        ev = transcript.read_tail(fx('clean_control.jsonl'))
        kinds = {e.kind for e in ev}
        self.assertIn('tool_use', kinds)
        self.assertIn('tool_result', kinds)
        self.assertIn('say', kinds)
        self.assertIn('human', kinds)

    def test_tool_use_carries_name_and_input(self):
        ev = transcript.read_tail(fx('clean_control.jsonl'))
        uses = [e for e in ev if e.kind == 'tool_use']
        self.assertTrue(any(e.name == 'Bash' for e in uses))
        bash = [e for e in uses if e.name == 'Bash'][0]
        self.assertIn('command', bash.input)

    def test_is_error_is_read_from_tool_result(self):
        ev = transcript.read_tail(fx('stuck_repeat_error.jsonl'))
        errs = [e for e in ev if e.kind == 'tool_result' and e.is_error]
        self.assertGreaterEqual(len(errs), 6)
        self.assertIn('AssertionError', errs[0].text)

    def test_hook_events_expose_prior_injections(self):
        ev = transcript.read_tail(fx('already_fired.jsonl'))
        hooks = [e for e in ev if e.kind == 'hook']
        self.assertEqual(len(hooks), 1)
        self.assertIn(brand.MARKER, hooks[0].text)

    def test_subagent_lines_are_excluded_from_the_main_scope(self):
        """A failing Explore/Task subagent must not make the parent session look stuck."""
        ev = transcript.read_tail(fx('with_sidechain.jsonl'))
        errs = [e for e in ev if e.kind == 'tool_result' and e.is_error]
        self.assertLessEqual(len(errs), 1, 'sidechain errors leaked into the main scope')
        self.assertFalse(any('ZeroDivisionError' in e.text for e in ev))

    def test_subagent_lines_can_be_opted_back_in(self):
        ev = transcript.read_tail(fx('with_sidechain.jsonl'), include_sidechain=True)
        self.assertTrue(any('ZeroDivisionError' in e.text for e in ev))

    # --- deliberate failure cases: a reader that never fails is untested ---

    def test_truncated_final_line_is_skipped_not_fatal(self):
        good = transcript.read_tail(fx('stuck_repeat_error.jsonl'))
        cut = transcript.read_tail(fx('truncated.jsonl'))
        self.assertTrue(cut)
        self.assertLess(len(cut), len(good))

    def test_pure_garbage_yields_no_events_and_does_not_raise(self):
        self.assertEqual(transcript.read_tail(fx('garbage.jsonl')), [])

    def test_empty_file_yields_no_events(self):
        self.assertEqual(transcript.read_tail(fx('empty.jsonl')), [])

    def test_missing_file_yields_no_events(self):
        self.assertEqual(transcript.read_tail(fx('does_not_exist.jsonl')), [])

    def test_max_lines_bounds_the_read(self):
        full = transcript.read_tail(fx('stuck_repeat_error.jsonl'))
        clipped = transcript.read_tail(fx('stuck_repeat_error.jsonl'), max_lines=6)
        self.assertLess(len(clipped), len(full))
        self.assertEqual([e.ts for e in clipped], sorted(e.ts for e in clipped))

    def test_max_bytes_bounds_the_read(self):
        clipped = transcript.read_tail(fx('stuck_repeat_error.jsonl'), max_bytes=2000)
        full = transcript.read_tail(fx('stuck_repeat_error.jsonl'))
        self.assertLess(len(clipped), len(full))


class TestLongToolResults(unittest.TestCase):
    """`text` is cut to TEXT_CAP because nothing but the verdict check needs more. The
    verdict check does: a verdict is usually the last line of long output, and the cut
    used to remove exactly that line. So a tool result is also kept in `scan`: whole up
    to SCAN_CAP, and past that as its first and its last half, two separate texts.

    The sizes are written out here on purpose. They are decisions (what the thresholds
    were calibrated on, what the time budget allows), so a test that read them from the
    module would follow any change to them."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='horme-long-')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def events_of(self, rows):
        path = os.path.join(self.dir, 'one.jsonl')
        with open(path, 'w', encoding='utf-8') as fh:
            for row in rows:
                fh.write(json.dumps(row) + '\n')
        return transcript.read_tail(path)

    def result_of(self, content, is_error=True):
        """The tool_result event the reader makes of one tool result holding `content`."""
        found = [e for e in self.events_of(S.calls((content, is_error))) if e.kind == 'tool_result']
        self.assertEqual(len(found), 1)
        return found[0]

    def test_the_two_caps_are_what_was_decided(self):
        """4,000: what every signal but the verdict check reads, and what the thresholds
        were calibrated on. 60,000: what the verdict check may read of one result inside
        the hook's time budget."""
        self.assertEqual(transcript.TEXT_CAP, 4000)
        self.assertEqual(transcript.SCAN_CAP, 60000)

    def test_text_keeps_its_cap(self):
        full = S.filler(12000)
        for is_error in (True, False, None):
            self.assertEqual(self.result_of(full, is_error).text, full[:4000])

    def test_a_result_within_the_text_cap_carries_no_second_copy(self):
        full = S.filler(4000)
        e = self.result_of(full)
        self.assertEqual((e.text, e.scan), (full, ()))

    def test_a_longer_result_is_kept_whole_for_the_verdict_check(self):
        for n in (4001, 20000, 60000):
            full = S.filler(n - 14) + 'VERDICT: FAIL\n'
            self.assertEqual(len(full), n)
            for is_error in (True, False, None):       # a verifier's answer is not an error
                self.assertEqual(self.result_of(full, is_error).scan, ((full, True),), (n, is_error))

    def test_content_given_as_blocks_is_flattened_before_it_is_cut(self):
        blocks = [{'type': 'text', 'text': S.filler(9000)}, {'type': 'text', 'text': 'VERDICT: FAIL'}]
        scan = self.result_of(blocks).scan
        self.assertEqual(len(scan), 1)
        self.assertTrue(scan[0][0].endswith('VERDICT: FAIL'))

    def long_result(self, middle):
        """A result whose two halves end and begin in known lines: 30,000 characters,
        `middle` characters that are not kept, 30,000 characters."""
        first = S.filler(30000 - len('HEAD WHOLE LINE\nHEAD CUT')) + 'HEAD WHOLE LINE\nHEAD CUT'
        second = ' TAIL CUT\nTAIL WHOLE LINE\n'
        second += S.filler(30000 - len(second))
        self.assertEqual((len(first), len(second)), (30000, 30000))
        return first + ' LINE GOES ON\n' + S.filler(middle - 29) + '\nLINE THAT ENDS' + second

    def test_past_the_scan_cap_each_half_is_kept_as_its_whole_lines_and_its_cut_line(self):
        """Four texts. The whole lines of each half are read like any output. The line
        the cut went through is kept apart and marked as not whole. The whole lines of
        the first half end in a mark, so its last line is not taken for the end of the
        output."""
        for middle in (40000, 90000, 940000):
            full = self.long_result(middle)
            self.assertEqual(len(full), 60000 + middle)
            scan = self.result_of(full, False).scan
            self.assertEqual(len(scan), 4, middle)
            (head, head_whole), (head_cut, head_cut_whole), (tail_cut, tail_cut_whole), (tail, tail_whole) = scan
            self.assertEqual((head_whole, head_cut_whole, tail_cut_whole, tail_whole), (True, False, False, True))
            self.assertEqual(head, full[:30000 - len('HEAD CUT')] + '[...]')
            self.assertEqual(head_cut, 'HEAD CUT')
            self.assertEqual(tail_cut, ' TAIL CUT\n')
            self.assertEqual(tail, full[-(30000 - len(' TAIL CUT\n')):])
            self.assertTrue(tail.startswith('TAIL WHOLE LINE\n'))
            self.assertNotIn('LINE GOES ON', ''.join(text for text, _ in scan))
        self.assertFalse(signals.adjudicated('[...]'), 'the mark after the first half reads as a verdict')

    def test_one_character_past_the_scan_cap_is_already_cut(self):
        full = S.filler(60001)
        self.assertEqual(len(self.result_of(full).scan), 4)
        self.assertEqual(len(self.result_of(full[:60000]).scan), 1)

    def test_a_result_of_one_line_is_all_cut_line(self):
        full = 'x' * 70000
        scan = self.result_of(full).scan
        self.assertEqual([(len(text), whole) for text, whole in scan],
                         [(len('[...]'), True), (30000, False), (30000, False), (0, True)])

    def test_other_kinds_of_event_keep_only_the_capped_text(self):
        long_text = S.filler(9000)
        rows = [
            {'type': 'assistant', 'isSidechain': False, 'timestamp': 't',
             'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': long_text},
                                                          {'type': 'thinking', 'thinking': long_text}]}},
            {'type': 'user', 'isSidechain': False, 'timestamp': 't',
             'message': {'role': 'user', 'content': long_text}},
            {'type': 'system', 'subtype': 'stop_hook_summary', 'isSidechain': False, 'timestamp': 't',
             'hookAdditionalContext': [long_text]},
        ]
        events = self.events_of(rows)
        self.assertEqual(sorted(e.kind for e in events), ['hook', 'human', 'say', 'say'])
        for e in events:
            self.assertEqual((len(e.text), e.scan), (4000, ()), e.kind)

    def test_an_event_built_without_a_scan_text_has_none(self):
        self.assertEqual(transcript._mk('tool_result', '', text='x').scan, ())
        self.assertEqual(transcript.Event('say', '', 'text', {}, '', 'x', False).scan, ())


if __name__ == '__main__':
    unittest.main()
