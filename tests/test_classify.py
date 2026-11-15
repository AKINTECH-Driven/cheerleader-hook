import json
import unittest
from _ctx import fx
from horme import transcript, signals, classify, rulebook


def report(name, **kw):
    ev = transcript.read_tail(fx(name))
    return classify.classify(signals.extract(ev), **kw)


class TestRulebookLoading(unittest.TestCase):

    def test_diagnosis_and_thresholds_load(self):
        self.assertIn('block_types', rulebook.load('diagnosis'))
        self.assertIn('thresholds', rulebook.load('thresholds'))

    def test_every_block_type_cites_its_research(self):
        """A rule without a source is a rule nobody can audit."""
        for name, spec in rulebook.load('diagnosis')['block_types'].items():
            self.assertTrue(spec.get('research'), '%s has no research citation' % name)

    def test_every_threshold_ref_resolves(self):
        th = rulebook.load('thresholds')['thresholds']
        for name, spec in rulebook.load('diagnosis')['block_types'].items():
            for _sig, _op, ref in spec['any_of']:
                self.assertIn(ref, th, '%s references unknown threshold %s' % (name, ref))

    def test_missing_rulebook_returns_empty_not_an_exception(self):
        self.assertEqual(rulebook.load('no_such_rulebook'), {})


class TestClassification(unittest.TestCase):

    def test_clean_session_is_not_stuck_and_stays_silent(self):
        r = report('clean_control.jsonl')
        self.assertEqual(r.block_type, 'none')
        self.assertEqual(r.severity, 0)
        self.assertFalse(r.should_speak)
        self.assertEqual(r.suppression_reason, 'not_stuck')

    def test_repeated_failure_reads_as_cognitive(self):
        r = report('stuck_repeat_error.jsonl')
        self.assertEqual(r.block_type, 'cognitive')
        self.assertGreaterEqual(r.severity, 1)
        self.assertTrue(r.should_speak)

    def test_capitulation_alongside_a_concrete_failure_is_a_symptom_not_the_block(self):
        """Self-report must not outrank evidence. 'I'm not sure why' while one assertion
        keeps failing is a cognitive block: decompose it, do not merely comfort it."""
        r = report('stuck_repeat_error.jsonl')
        self.assertEqual(r.block_type, 'cognitive')
        self.assertTrue(r.validate_first, 'validation is still owed, as a preamble')

    def test_capitulation_with_no_concrete_driver_falls_back_to_the_analogue(self):
        r = classify.classify(signals.EMPTY._replace(capitulation_hits=9))
        self.assertEqual(r.block_type, 'emotional_analogue')
        self.assertEqual(r.primary_move, 'validate_then_decompose')
        self.assertTrue(r.validate_first)

    def test_validate_first_is_off_when_the_model_never_capitulated(self):
        r = classify.classify(signals.EMPTY._replace(repeated_error_count=99))
        self.assertTrue(r.should_speak)
        self.assertFalse(r.validate_first)

    def test_environment_block_reads_as_infeasible_and_overrides(self):
        """Cheering someone through a missing binary is the documented wrong move."""
        r = report('infeasible.jsonl')
        self.assertEqual(r.block_type, 'infeasible')
        self.assertEqual(r.primary_move, 'stand_down')

    def test_an_infeasible_block_carries_ONLY_its_own_evidence(self):
        """The override must narrow the evidence, not just win the label. `docker: command
        not found` repeated five times also crosses the cognitive threshold; if those
        crossings leak through, the composer would hand back decomposition advice for a
        task that cannot be done — the one move the brief explicitly rules out."""
        r = report('infeasible.jsonl')
        self.assertEqual(r.block_type, 'infeasible')
        self.assertTrue(r.crossed)
        self.assertEqual({c['signal'] for c in r.crossed}, {'env_blocked_errors'},
                         'unrelated crossings leaked into an infeasible diagnosis')

    def test_adjudication_forces_silence_even_when_very_stuck(self):
        r = report('verdict_adjacent.jsonl')
        self.assertGreaterEqual(r.severity, 1, 'fixture should still register as stuck')
        self.assertFalse(r.should_speak)
        self.assertEqual(r.suppression_reason, 'adjudication')

    def test_a_prior_injection_about_the_same_block_forces_silence(self):
        r = report('already_fired.jsonl')
        self.assertFalse(r.should_speak)
        self.assertEqual(r.suppression_reason, 'already_fired')

    def test_flailing_subagent_does_not_trigger_the_parent(self):
        self.assertFalse(report('with_sidechain.jsonl').should_speak)

    def test_episode_id_is_stable_for_the_same_block(self):
        a = report('stuck_repeat_error.jsonl')
        b = report('stuck_repeat_error.jsonl')
        self.assertEqual(a.episode_id, b.episode_id)
        self.assertTrue(a.episode_id)

    def test_episode_id_differs_for_a_different_block(self):
        self.assertNotEqual(report('stuck_repeat_error.jsonl').episode_id,
                            report('infeasible.jsonl').episode_id)

    def test_report_names_the_signals_that_crossed(self):
        r = report('stuck_repeat_error.jsonl')
        self.assertTrue(r.crossed)
        for c in r.crossed:
            self.assertIn('signal', c)
            self.assertIn('value', c)
            self.assertIn('threshold', c)
        self.assertTrue(any(c['signal'] == 'repeated_error_count' for c in r.crossed))

    def test_report_carries_concrete_evidence_for_specificity(self):
        """The brief is explicit that specific beats global. The composer cannot be
        specific unless the classifier hands it something concrete to be specific about."""
        r = report('stuck_repeat_error.jsonl')
        self.assertTrue(r.evidence.get('error_sample'))
        self.assertTrue(r.evidence.get('thrash_file', '').endswith('importer.py'))

    def test_severity_rises_with_the_depth_of_the_block(self):
        shallow = classify.classify(signals.EMPTY._replace(repeated_error_count=5))
        deep = classify.classify(signals.EMPTY._replace(
            repeated_error_count=20, current_error_run=9, edit_thrash=60,
            command_repeat=30, capitulation_hits=6))
        self.assertLess(shallow.severity, deep.severity)
        self.assertLessEqual(deep.severity, 3)

    def test_rate_limit_state_suppresses_a_repeat_within_the_same_episode(self):
        r1 = report('stuck_repeat_error.jsonl')
        state = {'episodes': {r1.episode_id: {'fired': 1}}}
        r2 = report('stuck_repeat_error.jsonl', state=state)
        self.assertFalse(r2.should_speak)
        self.assertEqual(r2.suppression_reason, 'already_fired')
        self.assertEqual(r2.fired_count, 1)

    # --- deliberate failure cases ---

    def test_empty_signals_are_silent(self):
        r = classify.classify(signals.EMPTY)
        self.assertFalse(r.should_speak)
        self.assertEqual(r.block_type, 'none')

    def test_a_broken_rulebook_fails_closed_to_silence(self):
        """Fail-closed: if the rules cannot be read, HORME says nothing at all."""
        r = classify.classify(signals.EMPTY._replace(repeated_error_count=99),
                              rules={'block_types': {}, 'order': []})
        self.assertFalse(r.should_speak)

    def test_report_is_json_serialisable(self):
        json.dumps(report('stuck_repeat_error.jsonl').as_dict())


if __name__ == '__main__':
    unittest.main()
