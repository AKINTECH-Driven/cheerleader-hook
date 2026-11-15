"""Fail-closed check over HORME's own output.

Group A is the source brief's backfire table: phrasings measured to reverse the
intended effect. Group B is HORME-specific and not in the brief at all — correctness
claims. HORME's characteristic failure is not bad morale advice, it is sycophancy:
an encouragement layer that speaks near a verdict is exactly what could push a FAIL
into a PASS. Group B makes asserting correctness structurally impossible.

Fail-closed has to cover the guard as well as the text. A denylist that is missing,
unreadable, half-empty or holds a rule that does not compile cannot vouch for
anything, so `check` answers with a trip in group `unavailable` and the composer
suppresses the whole message. The same goes for a failure inside the check. It used
to answer `clean` in all of those cases, which is failing open.
"""
import re

from . import rulebook

GROUPS = ('group_a_backfires', 'group_b_correctness_claims')
UNAVAILABLE = 'unavailable'

#: Each group has to prove it still catches what it exists for. A rulebook can load
#: and compile and still match nothing (every pattern gutted, the two groups swapped),
#: and that vouches for every message as surely as a missing file does.
CANARIES = {
    'group_a_backfires': "You're so smart, you'll get this.",
    'group_b_correctness_claims': 'That looks right to me.',
}

_COMPILED = None
_PROBLEMS = None


def reset():
    """Forget what was compiled. The next check compiles again from the rulebook as
    the loader holds it; `problems(refresh=True)` also reads the file again."""
    global _COMPILED, _PROBLEMS
    _COMPILED = None
    _PROBLEMS = None


def _load():
    """(compiled, problems). Any problem at all means the denylist cannot be trusted."""
    rb = rulebook.load('denylist')
    compiled, problems = [], []
    if not isinstance(rb, dict) or not rb:
        return compiled, ['rulebook/denylist.json is missing, unreadable or empty']
    for group in GROUPS:
        items = rb.get(group)
        if not isinstance(items, list) or not items:
            problems.append('%s has no entries' % group)
            continue
        for i, e in enumerate(items):
            pattern = e.get('pattern') if isinstance(e, dict) else None
            if not isinstance(pattern, str) or not pattern:
                problems.append('%s entry %d has no pattern' % (group, i))
                continue
            try:
                rx = re.compile(pattern, re.I)
            except re.error as exc:
                problems.append('%s entry %d does not compile: %s (%s)' % (group, i, pattern, exc))
                continue
            d = dict(e)
            d['group'] = group
            compiled.append((rx, d))
        if not any(rx.search(CANARIES[group]) for rx, d in compiled if d['group'] == group):
            problems.append('%s no longer catches its canary phrase %r' % (group, CANARIES[group]))
    return compiled, problems


def _ensure(refresh=False):
    global _COMPILED, _PROBLEMS
    if refresh:
        rulebook.load('denylist', refresh=True)       # the loader caches the file too
    if _COMPILED is None or _PROBLEMS is None or refresh:
        _COMPILED, _PROBLEMS = _load()
    return _COMPILED, _PROBLEMS


def entries():
    return [e for _rx, e in _ensure()[0]]


def patterns(refresh=False):
    return _ensure(refresh)[0]


def problems(refresh=False):
    """Why the denylist cannot be trusted right now. [] means it can."""
    return list(_ensure(refresh)[1])


def _unavailable(why):
    return {'group': UNAVAILABLE, 'pattern': '', 'why': why}


def check(text):
    """Return the entries this text trips. [] means checked and clean. Never raises.

    A denylist that cannot be trusted, or a check that fails, is reported as a trip in
    group UNAVAILABLE: the caller must suppress, exactly as for a real match.
    """
    try:
        found = problems()
        if found:
            return [_unavailable('; '.join(found))]
        if not isinstance(text, str) or not text:
            return []
        return [e for rx, e in patterns() if rx.search(text)]
    except Exception as exc:
        return [_unavailable('the denylist check failed: %r' % (exc,))]
