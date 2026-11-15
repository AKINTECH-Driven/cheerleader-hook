import json
import unittest
from _ctx import fx  # noqa: F401  (path side effect)
from horme import payload


class TestPayloadParser(unittest.TestCase):

    def test_parses_a_well_formed_stop_payload(self):
        p = payload.parse(json.dumps({
            'session_id': 's1', 'transcript_path': '/t.jsonl', 'cwd': '/p',
            'hook_event_name': 'Stop', 'last_assistant_message': 'done',
        }))
        self.assertTrue(p.ok)
        self.assertEqual(p.event, 'Stop')
        self.assertEqual(p.session_id, 's1')
        self.assertEqual(p.transcript_path, '/t.jsonl')
        self.assertEqual(p.last_assistant_message, 'done')

    def test_accepts_tool_response_spelling(self):
        p = payload.parse(json.dumps({'hook_event_name': 'PostToolBatch', 'tool_calls': [
            {'tool_name': 'Bash', 'tool_input': {'command': 'x'}, 'tool_response': 'out'}]}))
        self.assertEqual(p.tool_calls[0]['name'], 'Bash')
        self.assertEqual(p.tool_calls[0]['output'], 'out')

    def test_accepts_tool_output_spelling(self):
        """The docs disagree with themselves; the parser must not care."""
        p = payload.parse(json.dumps({'hook_event_name': 'PostToolBatch', 'tool_calls': [
            {'tool_name': 'Bash', 'tool_input': {'command': 'x'}, 'tool_output': 'out'}]}))
        self.assertEqual(p.tool_calls[0]['output'], 'out')

    def test_tool_error_marks_the_call_as_failed(self):
        p = payload.parse(json.dumps({'hook_event_name': 'PostToolUseFailure',
                                      'tool_name': 'Bash', 'tool_error': 'boom'}))
        self.assertTrue(p.tool_calls[0]['is_error'])
        self.assertEqual(p.tool_calls[0]['output'], 'boom')

    def test_tool_response_is_error_flag_is_honoured(self):
        p = payload.parse(json.dumps({'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                                      'tool_response': 'nope', 'tool_response_is_error': True}))
        self.assertTrue(p.tool_calls[0]['is_error'])

    # --- deliberate failure cases ---

    def test_non_json_input_is_not_fatal(self):
        p = payload.parse(b'not json at all')
        self.assertFalse(p.ok)
        self.assertEqual(p.event, '')
        self.assertEqual(p.tool_calls, ())

    def test_empty_input_is_not_fatal(self):
        self.assertFalse(payload.parse('').ok)
        self.assertFalse(payload.parse(None).ok)

    def test_json_that_is_not_an_object_is_not_fatal(self):
        self.assertFalse(payload.parse('[1,2,3]').ok)

    def test_tool_calls_are_immutable_so_the_EMPTY_singleton_cannot_be_poisoned(self):
        """EMPTY is shared across every failed parse in the process; a mutable
        default would let one caller corrupt every later one."""
        self.assertIsInstance(payload.EMPTY.tool_calls, tuple)
        self.assertIsInstance(payload.parse('{}').tool_calls, tuple)
        with self.assertRaises(AttributeError):
            payload.EMPTY.tool_calls.append({'name': 'poison'})

    def test_missing_fields_default_to_empty(self):
        p = payload.parse('{}')
        self.assertTrue(p.ok)
        self.assertEqual(p.session_id, '')
        self.assertEqual(p.transcript_path, '')
        self.assertEqual(p.tool_calls, ())

    def test_hostile_types_do_not_raise(self):
        p = payload.parse(json.dumps({'hook_event_name': 123, 'tool_calls': 'nope',
                                      'transcript_path': {'a': 1}}))
        self.assertEqual(p.tool_calls, ())
        self.assertIsInstance(p.event, str)
        self.assertIsInstance(p.transcript_path, str)


if __name__ == '__main__':
    unittest.main()
