"""Load JSON rulebooks. Data, not code: rules change more often than orchestration.

Fail-closed by design. A rulebook that cannot be read returns {}, which the classifier
turns into silence — never into a guess.
"""
import json
import os

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'rulebook')
_CACHE = {}


def path_for(name):
    return os.path.join(_DIR, '%s.json' % name)


def load(name, refresh=False):
    """Return a rulebook dict, or {} if it is missing or unreadable. Never raises."""
    if not refresh and name in _CACHE:
        return _CACHE[name]
    try:
        with open(path_for(name), encoding='utf-8') as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    _CACHE[name] = data
    return data


def thresholds():
    return load('thresholds').get('thresholds', {}) or {}
