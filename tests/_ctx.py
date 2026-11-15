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
