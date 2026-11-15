"""Shared test context: put src/ on the path and locate fixtures."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, 'src')
FIXTURES = os.path.join(HERE, 'fixtures')
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def fx(name):
    return os.path.join(FIXTURES, name)


def within(seconds, call):
    """Run `call` on another thread and hand back what it returned. Raises AssertionError
    when it has not come back in `seconds`: a lock that waits would otherwise stop the
    whole suite instead of failing one test."""
    import threading
    box = []

    def work():
        try:
            box.append((True, call()))
        except BaseException as exc:            # handed to the caller below
            box.append((False, exc))

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise AssertionError('still waiting after %s seconds' % seconds)
    ok, value = box[0]
    if not ok:
        raise value
    return value
