import json
import os
import shutil
import stat
import tempfile
import unittest
from _ctx import fx, within  # noqa: F401
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


class TestSaveSaysWhetherItWorked(unittest.TestCase):
    """`save` stands between one intervention and a repeat on the next event. It used to
    swallow its failures, so a state folder that could not be written left the hook with
    no memory and no cap. Now it answers True only for a file that reads back."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='horme-state-')
        self._orig = state.STATE_DIR
        state.STATE_DIR = os.path.join(self.dir, 'state')

    def tearDown(self):
        state.STATE_DIR = self._orig
        shutil.rmtree(self.dir, ignore_errors=True)

    def fired(self, at=1000.0):
        return state.record_fire(state.blank(), 'ep', now=at)

    def test_it_answers_true_for_a_state_that_reads_back(self):
        s = self.fired()
        self.assertIs(state.save('sess-1', s), True)
        self.assertEqual(state.load('sess-1'), s)

    def test_it_answers_false_when_the_state_path_is_a_file(self):
        with open(state.STATE_DIR, 'w') as fh:
            fh.write('a file where the state folder should be')
        self.assertIs(state.save('sess-1', self.fired()), False)

    def test_it_answers_false_when_the_file_cannot_be_put_in_place(self):
        def refuse(*_a, **_k):
            raise OSError('no room')
        orig = state.os.replace
        state.os.replace = refuse
        try:
            answer = state.save('sess-1', self.fired())
        finally:
            state.os.replace = orig
        self.assertIs(answer, False)
        self.assertEqual(os.listdir(state.STATE_DIR), [], 'a failed save left a file behind')

    def test_it_answers_false_when_an_older_state_is_what_reads_back(self):
        """A write that seems to work and does not hold: the new file never replaces the
        old one, so the next run would read the old counts."""
        self.assertIs(state.save('sess-1', self.fired(at=1000.0)), True)
        orig = state.os.replace
        state.os.replace = lambda *_a, **_k: None
        try:
            answer = state.save('sess-1', self.fired(at=2000.0))
        finally:
            state.os.replace = orig
        self.assertIs(answer, False)

    def test_it_answers_false_and_does_not_raise_for_a_state_json_cannot_write(self):
        """Not a failure of the disk: `save` must still answer, not raise."""
        s = self.fired()
        s['extra'] = {1, 2}
        self.assertIs(state.save('sess-1', s), False)
        left = os.listdir(state.STATE_DIR) if os.path.isdir(state.STATE_DIR) else []
        self.assertEqual(left, [], 'a failed save left a file behind')

    def test_it_answers_false_when_even_the_cleanup_fails(self):
        def refuse(*_a, **_k):
            raise OSError('no')
        replace, remove = state.os.replace, state.os.remove
        state.os.replace = state.os.remove = refuse
        try:
            answer = state.save('sess-1', self.fired())
        finally:
            state.os.replace, state.os.remove = replace, remove
        self.assertIs(answer, False)

    def test_what_is_compared_is_the_text_on_disk(self):
        """A value that is not equal to itself, or that JSON hands back in another type,
        is still a recorded firing when the file holds what was written. Comparing the
        parsed values would call that not saved."""
        for odd in (float('nan'), (1, 2)):
            s = self.fired()
            s['extra'] = odd
            self.assertIs(state.save('sess-odd', s), True, 'not saved with %r in the state' % (odd,))
            self.assertEqual(state.load('sess-odd')['fired_total'], 1)


class TestTheSessionLock(unittest.TestCase):
    """Two runs that start together each used to read a state that had heard nothing, and
    each spoke. A run now takes the session's lock, without waiting, before it reads the
    state for the last time."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='horme-lock-')
        self._orig = state.STATE_DIR
        state.STATE_DIR = os.path.join(self.dir, 'state')
        self.held = []

    def tearDown(self):
        for lock in self.held:
            state.release(lock)
        state.STATE_DIR = self._orig
        shutil.rmtree(self.dir, ignore_errors=True)

    def claim(self, session_id):
        lock, why = state.claim(session_id)
        self.held.append(lock)
        return lock, why

    def test_a_run_can_take_it(self):
        lock, why = self.claim('sess-1')
        self.assertIsNotNone(lock)
        self.assertIsNot(lock, state.NO_LOCK, 'this platform has fcntl, so a real lock is expected')
        self.assertEqual(why, '')

    def test_the_lock_file_is_empty_and_private(self):
        mask = os.umask(0)                  # so that the mode asked for is the mode it gets
        try:
            self.claim('sess-1')
        finally:
            os.umask(mask)
        info = os.stat(state._path('sess-1') + '.lock')
        self.assertEqual(info.st_size, 0)
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o600, 'others can read or write the lock file')

    def test_a_second_run_finds_it_taken_and_does_not_wait(self):
        first, _why = self.claim('sess-1')
        self.assertIsNotNone(first)
        self.assertEqual(within(5, lambda: self.claim('sess-1')), (None, 'state_busy'))

    def test_it_is_free_again_once_given_back(self):
        first, _why = self.claim('sess-1')
        state.release(first)
        again, why = self.claim('sess-1')
        self.assertIsNotNone(again, why)

    def test_another_session_is_not_held_up(self):
        self.claim('sess-a')
        other, why = self.claim('sess-b')
        self.assertIsNotNone(other, why)

    def test_it_answers_unwritable_when_the_lock_file_cannot_be_made(self):
        with open(state.STATE_DIR, 'w') as fh:
            fh.write('a file where the state folder should be')
        self.assertEqual(self.claim('sess-1'), (None, 'state_unwritable'))

    def test_it_answers_and_does_not_raise_for_a_session_id_it_cannot_read(self):
        class Unreadable(object):
            def __str__(self):
                raise RuntimeError('no name')
        self.assertEqual(self.claim(Unreadable()), (None, 'state_unwritable'))

    def test_without_fcntl_nothing_is_locked_and_nothing_is_refused(self):
        kept = state.fcntl
        state.fcntl = None
        try:
            first, second = state.claim('sess-1'), state.claim('sess-1')
            state.release(first[0])
        finally:
            state.fcntl = kept
        self.assertEqual(first, (state.NO_LOCK, ''))
        self.assertEqual(second, (state.NO_LOCK, ''))
        self.assertFalse(os.path.exists(state.STATE_DIR), 'a lock file was made where no lock can be taken')

    def test_release_takes_whatever_claim_returned_and_a_second_call_does_nothing(self):
        lock, _why = state.claim('sess-1')
        for what in (None, state.NO_LOCK, lock):
            state.release(what)
        other = os.open(os.devnull, os.O_RDONLY)     # may get the number the lock had
        try:
            state.release(lock)
            os.fstat(other)                          # raises if the second call closed it
        finally:
            os.close(other)

    def test_a_hostile_session_id_cannot_put_the_lock_file_elsewhere(self):
        self.claim('../../etc/passwd')
        self.assertEqual(len(os.listdir(state.STATE_DIR)), 1)
        self.assertEqual(os.listdir(self.dir), ['state'])

    def test_a_lock_that_is_in_use_is_not_pruned(self):
        """prune() goes by the file's date. An old lock file that was pruned while a run
        held it would let a second run take a second lock on a new file."""
        first, _why = state.claim('sess-1')
        state.release(first)
        path = state._path('sess-1') + '.lock'
        os.utime(path, (0, 0))
        self.claim('sess-1')
        state.prune(ttl_days=7)
        self.assertTrue(os.path.exists(path), 'a lock that was held was pruned')
        self.assertEqual(within(5, lambda: self.claim('sess-1')), (None, 'state_busy'))

    def test_the_lock_file_is_not_the_state_and_is_pruned_with_it(self):
        lock, _why = self.claim('sess-1')
        self.assertEqual(state.load('sess-1'), state.blank())
        state.release(lock)
        path = state._path('sess-1') + '.lock'
        self.assertTrue(os.path.isfile(path))
        os.utime(path, (0, 0))
        state.prune(ttl_days=7)
        self.assertFalse(os.path.exists(path))


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
