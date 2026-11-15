"""Smoke test against this machine's real transcripts.

Environment-dependent by nature: it skips cleanly where no sessions exist, so the
suite stays green on a fresh checkout. Where sessions do exist it is the only test
that proves the reader survives real data and meets the hook latency budget.
"""
import os
import time
import unittest
from _ctx import fx  # noqa: F401  (path side effect)
from horme import transcript, signals

PROJECTS = os.path.expanduser('~/.claude/projects')
BUDGET_MS = 50.0          # SPEC constraint: hooks fire on every tool batch


def _transcripts(limit=120):
    out = []
    if not os.path.isdir(PROJECTS):
        return out
    for dirpath, _d, filenames in os.walk(PROJECTS):
        for fn in filenames:
            if fn.endswith('.jsonl'):
                out.append(os.path.join(dirpath, fn))
                if len(out) >= limit:
                    return out
    return out


class TestRealCorpus(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.files = _transcripts()
        if not cls.files:
            raise unittest.SkipTest('no real transcripts on this machine')

    def test_reader_survives_every_real_transcript(self):
        parsed = 0
        for f in self.files:
            ev = transcript.read_tail(f)          # must not raise on any real file
            self.assertIsInstance(ev, list)
            if ev:
                parsed += 1
        self.assertGreater(parsed, 0, 'no real transcript produced any event')

    def test_extraction_survives_every_real_transcript(self):
        for f in self.files:
            s = signals.extract(transcript.read_tail(f))
            self.assertGreaterEqual(s.tool_count, 0)
            self.assertGreaterEqual(s.repeated_error_count, 0)

    def test_meets_the_hook_latency_budget(self):
        timings = []
        for f in self.files:
            t0 = time.time()
            signals.extract(transcript.read_tail(f))
            timings.append((time.time() - t0) * 1000.0)
        timings.sort()
        p95 = timings[min(len(timings) - 1, int(0.95 * (len(timings) - 1)))]
        self.assertLess(p95, BUDGET_MS,
                        'p95 %.1f ms exceeds the %.0f ms hook budget' % (p95, BUDGET_MS))


if __name__ == '__main__':
    unittest.main()
