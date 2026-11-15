import unittest
from _ctx import fx
from horme import transcript, signals, classify, compose, denylist


def rep(name, **kw):
    return classify.classify(signals.extract(transcript.read_tail(fx(name))), **kw)


def forced(block_type, **sig_kw):
    """Build a speaking report directly, to reach severities the fixtures don't."""
    s = signals.EMPTY._replace(**sig_kw)
    return classify.classify(s)


class TestComposition(unittest.TestCase):

    def test_a_cognitive_block_produces_a_next_step(self):
        iv = compose.compose(rep('stuck_repeat_error.jsonl'))
        self.assertFalse(iv.suppressed)
        self.assertIn('Smallest next move', iv.text)

    def test_output_is_tagged_so_it_can_dedupe_against_itself(self):
        """signals.horme_recent looks for this marker in hookAdditionalContext."""
        self.assertTrue(compose.compose(rep('stuck_repeat_error.jsonl')).text.startswith(compose.MARKER))

    def test_output_is_specific_and_names_the_real_file(self):
        """The brief's strongest style finding: specific beats global."""
        iv = compose.compose(rep('stuck_repeat_error.jsonl'))
        self.assertIn('importer.py', iv.text)

    def test_no_shipped_template_ever_trips_the_denylist(self):
        """The load-bearing safety test: exercise every block type at every severity."""
        cases = [
            rep('stuck_repeat_error.jsonl'),
            rep('infeasible.jsonl'),
            forced('cognitive', repeated_error_count=99, edit_thrash=99, command_repeat=99,
                   current_error_run=9, calls_since_success=9, capitulation_hits=9,
                   reread_thrash=99, top_error_signature='assertionerror: x',
                   edit_thrash_file='/a/b.py', top_command='pytest', error_samples=('AssertionError: x',)),
            forced('motivational', command_repeat=99, reread_thrash=99, top_command='ls'),
            forced('emotional', capitulation_hits=9),
            forced('cognitive_min', repeated_error_count=5, top_error_signature='keyerror: k'),
        ]
        checked = 0
        for r in cases:
            iv = compose.compose(r)
            if iv.suppressed and iv.reason == 'not_speaking':
                continue
            checked += 1
            self.assertFalse(iv.violations, 'shipped template tripped denylist: %s' % (iv.violations,))
            self.assertEqual(denylist.check(iv.text), [], 'denylist trips on: %r' % iv.text)
        self.assertGreaterEqual(checked, 4, 'not enough live cases exercised')

    def test_a_poisoned_template_is_caught_and_suppresses_everything(self):
        """A denylist that never fires is untested. Fail-closed means the WHOLE
        intervention dies, not just the bad clause — decided at the F3 plan gate."""
        poisoned = {'slots': {'decompose': {'source': 'x',
                    'templates': ["You're so smart, just push through {move}."]}},
                    'moves': {'repeated_error_count': 'do the thing'}}
        iv = compose.compose(rep('stuck_repeat_error.jsonl'), phrases=poisoned)
        self.assertTrue(iv.suppressed)
        self.assertEqual(iv.reason, 'denylist')
        self.assertTrue(iv.violations, 'the violation must be reported, not swallowed')
        self.assertEqual(iv.text, '')

    def test_an_unusable_denylist_suppresses_with_its_own_reason(self):
        """Not a template bug, and it must not be reported as one: the guard itself
        is gone. Still the whole intervention dies."""
        def gone(_text):
            return [{'group': denylist.UNAVAILABLE, 'pattern': '', 'why': 'denylist.json is missing'}]
        iv = compose.compose(rep('stuck_repeat_error.jsonl'), deny=gone)
        self.assertTrue(iv.suppressed)
        self.assertEqual(iv.reason, 'denylist_unavailable')
        self.assertEqual(iv.text, '')
        self.assertTrue(iv.violations)

    def test_a_checker_that_does_not_answer_with_a_list_suppresses_everything(self):
        """`None`, `False` or an empty tuple is not `checked and clean`. Only a list
        is an answer; anything else means the guard did not do its job."""
        for answer in (None, False, 0, (), {}, 'clean'):
            iv = compose.compose(rep('stuck_repeat_error.jsonl'), deny=lambda _t, a=answer: a)
            self.assertTrue(iv.suppressed, 'accepted %r as a clean check' % (answer,))
            self.assertEqual(iv.reason, 'denylist_unavailable')
        iv = compose.compose(rep('stuck_repeat_error.jsonl'), deny=lambda _t: [])
        self.assertFalse(iv.suppressed)

    def test_a_checker_that_raises_suppresses_everything(self):
        def boom(_text):
            raise RuntimeError('injected failure')
        iv = compose.compose(rep('stuck_repeat_error.jsonl'), deny=boom)
        self.assertTrue(iv.suppressed)
        self.assertEqual(iv.reason, 'denylist_unavailable')
        self.assertEqual(iv.text, '')

    def test_stand_down_never_encourages(self):
        """Cheering someone through a missing binary is the documented wrong move."""
        iv = compose.compose(rep('infeasible.jsonl'))
        self.assertFalse(iv.suppressed)
        low = iv.text.lower()
        self.assertNotIn('yet', low)
        self.assertNotIn('smallest next move', low)
        for word in ('hard', 'you could', 'normal shape'):
            self.assertNotIn(word, low)
        self.assertIn('environment is blocking', low)

    def test_the_autonomy_clause_never_offers_an_exit_from_the_work(self):
        """Decided at the plan gate: autonomy over approach, never over continuing."""
        for r in (rep('stuck_repeat_error.jsonl'),
                  forced('m', command_repeat=99, reread_thrash=99, top_command='ls')):
            low = compose.compose(r).text.lower()
            for exit_phrase in ('park this', 'give up', 'stop working', 'abandon',
                                'whether to continue', 'walk away'):
                self.assertNotIn(exit_phrase, low)

    def test_severity_escalates_scaffolding_not_enthusiasm(self):
        shallow = compose.compose(forced('c', repeated_error_count=5,
                                         top_error_signature='keyerror: k'))
        deep = compose.compose(forced('c', repeated_error_count=99, edit_thrash=99,
                                      command_repeat=99, capitulation_hits=9,
                                      top_error_signature='assertionerror: x',
                                      edit_thrash_file='/a/b.py', top_command='pytest'))
        self.assertGreater(len(deep.parts), len(shallow.parts))
        self.assertIn('if_then', [p['slot'] for p in deep.parts])
        self.assertNotIn('if_then', [p['slot'] for p in shallow.parts])

    def test_validate_first_adds_the_validation_slot(self):
        with_cap = compose.compose(forced('c', repeated_error_count=99, capitulation_hits=9,
                                          top_error_signature='assertionerror: x'))
        without = compose.compose(forced('c', repeated_error_count=99,
                                         top_error_signature='assertionerror: x'))
        self.assertIn('validate', [p['slot'] for p in with_cap.parts])
        self.assertNotIn('validate', [p['slot'] for p in without.parts])

    def test_composition_is_deterministic(self):
        a = compose.compose(rep('stuck_repeat_error.jsonl'))
        b = compose.compose(rep('stuck_repeat_error.jsonl'))
        self.assertEqual(a.text, b.text)

    def test_every_part_carries_its_research_provenance(self):
        for p in compose.compose(rep('stuck_repeat_error.jsonl')).parts:
            self.assertTrue(p.get('source'), 'slot %s has no citation' % p['slot'])

    def test_the_human_facing_line_is_short_and_single_line(self):
        iv = compose.compose(rep('stuck_repeat_error.jsonl'))
        self.assertNotIn('\n', iv.system_line)
        self.assertLessEqual(len(iv.system_line), 120)

    def test_no_unrendered_placeholders_leak_into_the_output(self):
        for r in (rep('stuck_repeat_error.jsonl'), rep('infeasible.jsonl'),
                  forced('m', command_repeat=99, reread_thrash=99, top_command='ls')):
            iv = compose.compose(r)
            if not iv.suppressed:
                self.assertNotIn('{', iv.text)
                self.assertNotIn('}', iv.text)

    def test_its_own_output_is_recognised_by_the_detector(self):
        """Round-trip, not a constant comparison. `compose` writes the marker and
        `signals` reads it back to dedupe. Before these shared one constant they were
        two independent literals in two files: change one and the tool silently stops
        recognising its own past interventions and repeats itself forever."""
        iv = compose.compose(rep('stuck_repeat_error.jsonl'))
        self.assertFalse(iv.suppressed)
        echoed = [transcript.Event(kind='hook', ts='2026-08-26T10:00:00Z', name='',
                                   input={}, tool_use_id='', text=iv.text, is_error=False)]
        self.assertTrue(signals.extract(echoed).horme_recent,
                        'the detector no longer recognises what the composer writes')

    # --- quality properties: green tests did not catch these, reading the output did ---

    def test_the_specific_phrase_is_said_once_not_three_times(self):
        """Repeating the same specific string in every slot reads as generated text and
        undercuts the sincerity the brief says is load-bearing."""
        r = rep('stuck_repeat_error.jsonl')
        what = compose._what(r)
        self.assertTrue(what)
        self.assertEqual(compose.compose(r).text.count(what), 1)

    def test_no_slot_restates_another_slots_step(self):
        """'Smallest next move: X. You could X, or Y' is twice the length for no gain."""
        for r in (rep('stuck_repeat_error.jsonl'),
                  forced('m', command_repeat=99, reread_thrash=99, top_command='ls'),
                  forced('c', repeated_error_count=99, edit_thrash=99, capitulation_hits=9,
                         top_error_signature='assertionerror: x', edit_thrash_file='/a/b.py')):
            iv = compose.compose(r)
            if iv.suppressed:
                continue
            texts = [p['text'] for p in iv.parts if p['slot'] in ('decompose', 'autonomy', 'if_then')]
            joined = ' '.join(texts)
            for phrase in compose._all_moves_in(iv):
                self.assertEqual(joined.count(phrase), 1,
                                 'move restated across slots: %r' % phrase)

    def test_the_named_count_matches_the_named_failure(self):
        """'docker: command not found, 10 times' when docker failed 5 and pandoc 5 is a
        false statement about the very thing it just pointed at."""
        r = rep('infeasible.jsonl')
        iv = compose.compose(r)
        self.assertIn('%d times' % r.signals.repeated_error_count, iv.text)
        self.assertNotIn('%d times' % r.signals.env_blocked_errors, iv.text)

    def test_no_move_invents_a_file_that_is_not_known(self):
        iv = compose.compose(forced('m', command_repeat=99, reread_thrash=99, top_command='ls'))
        self.assertNotIn('about the file', iv.text)
        self.assertNotIn('editing the file', iv.text)

    def test_no_double_contrast_in_the_if_then_clause(self):
        deep = compose.compose(forced('c', repeated_error_count=99, edit_thrash=99,
                                      command_repeat=99, capitulation_hits=9,
                                      top_error_signature='assertionerror: x',
                                      edit_thrash_file='/a/b.py', top_command='pytest'))
        for part in deep.parts:
            if part['slot'] == 'if_then':
                self.assertLessEqual(part['text'].count('instead'), 1)
                self.assertLessEqual(part['text'].count('rather than'), 1)

    # --- deliberate failure cases ---

    def test_a_non_speaking_report_produces_nothing(self):
        iv = compose.compose(rep('clean_control.jsonl'))
        self.assertTrue(iv.suppressed)
        self.assertEqual(iv.text, '')

    def test_a_suppressed_report_is_never_composed(self):
        iv = compose.compose(rep('verdict_adjacent.jsonl'))
        self.assertTrue(iv.suppressed)
        self.assertEqual(iv.text, '')

    def test_an_empty_rulebook_fails_closed_to_silence(self):
        iv = compose.compose(rep('stuck_repeat_error.jsonl'), phrases={})
        self.assertTrue(iv.suppressed)
        self.assertEqual(iv.text, '')


if __name__ == '__main__':
    unittest.main()
