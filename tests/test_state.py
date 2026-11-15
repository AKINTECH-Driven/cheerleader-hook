import json
import os
import shutil
import tempfile
import unittest
from _ctx import fx  # noqa: F401
from horme import state


class TestSessionState(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='horme-state-')
        self._orig = state.STATE_DIR
        state.STATE_DIR = self.dir

    def tearDown(self):
        state.STATE_DIR = self._orig
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_fresh_session_has_empty_state(self):
        s = state.load('sess-1')
        self.assertEqual(s['episodes'], {})
        self.assertEqual(s['fired_total'], 0)

    def test_a_recorded_firing_survives_a_round_trip(self):
        s = state.load('sess-1')
        state.record_fire(s, 'ep-abc', now=1000.0)
        state.save('sess-1', s)
        again = state.load('sess-1')
        self.assertEqual(again['episodes']['ep-abc']['fired'], 1)
        self.assertEqual(again['fired_total'], 1)
        self.assertEqual(again['last_fired_at'], 1000.0)

    def test_session_ids_are_isolated(self):
        a = state.load('sess-a')
        state.record_fire(a, 'ep', now=1.0)
        state.save('sess-a', a)
        self.assertEqual(state.load('sess-b')['fired_total'], 0)

    def test_a_hostile_session_id_cannot_escape_the_state_dir(self):
        """The session id arrives from hook stdin; it is not trusted input.

        Asserting on the COMPUTED PATH, not on which files happen to appear: under a
        /tmp state dir an escaping write merely fails on permissions, which would hide
        a missing sanitiser. Under the real ~/.claude/cheerleader/state it would not.
        """
        root = os.path.realpath(self.dir) + os.sep
        for hostile in ('../../etc/passwd', '/etc/passwd', '..', '../../../root/.ssh/id_rsa',
                        'a/b/c', '....//x', '\\..\\..\\win.ini', ''):
            resolved = os.path.realpath(state._path(hostile))
            self.assertTrue(resolved.startswith(root),
                            'session id %r escaped to %s' % (hostile, resolved))
        state.save('../../etc/passwd', state.blank())
        self.assertFalse(os.path.exists('/etc/passwd.json'))

    def test_corrupt_state_file_is_treated_as_empty_not_fatal(self):
        with open(os.path.join(self.dir, 'sess-x.json'), 'w') as fh:
            fh.write('{not json')
        self.assertEqual(state.load('sess-x')['fired_total'], 0)

    def test_an_unwritable_state_dir_never_raises(self):
        state.STATE_DIR = '/proc/nonexistent/horme'
        s = {'episodes': {}, 'fired_total': 0}
        state.save('sess-1', s)          # must not raise

    def test_prune_removes_only_expired_files(self):
        old = os.path.join(self.dir, 'old.json')
        new = os.path.join(self.dir, 'new.json')
        for p in (old, new):
            with open(p, 'w') as fh:
                json.dump({}, fh)
        os.utime(old, (0, 0))
        state.prune(ttl_days=7)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))


class TestRateLimits(unittest.TestCase):

    def test_a_fresh_session_may_speak(self):
        ok, why = state.rate_limit({'episodes': {}, 'fired_total': 0, 'last_fired_at': 0},
                                   'ep', now=1000.0)
        self.assertTrue(ok, why)

    def test_the_session_cap_stops_it(self):
        s = {'episodes': {}, 'fired_total': 99, 'last_fired_at': 0}
        ok, why = state.rate_limit(s, 'ep', now=10 ** 9)
        self.assertFalse(ok)
        self.assertEqual(why, 'max_per_session')

    def test_the_cooldown_stops_it(self):
        s = {'episodes': {}, 'fired_total': 1, 'last_fired_at': 1000.0}
        ok, why = state.rate_limit(s, 'ep', now=1001.0)
        self.assertFalse(ok)
        self.assertEqual(why, 'cooldown')

    def test_the_same_episode_only_ever_speaks_once(self):
        s = {'episodes': {'ep': {'fired': 1}}, 'fired_total': 1, 'last_fired_at': 0}
        ok, why = state.rate_limit(s, 'ep', now=10 ** 9)
        self.assertFalse(ok)
        self.assertEqual(why, 'max_per_episode')

    def test_a_different_episode_may_speak_after_the_cooldown(self):
        s = {'episodes': {'ep-old': {'fired': 1}}, 'fired_total': 1, 'last_fired_at': 1000.0}
        ok, _ = state.rate_limit(s, 'ep-new', now=1000.0 + 10 ** 6)
        self.assertTrue(ok)


if __name__ == '__main__':
    unittest.main()
