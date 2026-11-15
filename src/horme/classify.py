"""SignalSet -> BlockReport. Deterministic diagnosis, rulebook-driven.

Stage 1 of the source brief: diagnose the type of block BEFORE choosing words.
No phrasing decisions happen here; this module only decides *whether* there is a
block, *what kind*, *how deep*, and *whether HORME is allowed to speak at all*.
"""
import hashlib
from collections import namedtuple

from . import rulebook

_OPS = {
    '>=': lambda a, b: a >= b,
    '>': lambda a, b: a > b,
    '<=': lambda a, b: a <= b,
    '<': lambda a, b: a < b,
}

BlockReport = namedtuple(
    'BlockReport',
    'session_id event episode_id block_type primary_move severity crossed evidence '
    'validate_first fired_count should_speak suppression_reason signals')


class _Report(BlockReport):
    __slots__ = ()

    def as_dict(self):
        d = dict(self._asdict())
        d['signals'] = self.signals.as_dict() if hasattr(self.signals, 'as_dict') else {}
        d['crossed'] = [dict(c) for c in self.crossed]
        return d


def _silent(sig, reason, session_id='', event='', episode_id='', fired=0,
            block_type='none', primary_move='', severity=0, crossed=(), evidence=None,
            validate_first=False):
    return _Report(session_id=session_id, event=event, episode_id=episode_id,
                   block_type=block_type, primary_move=primary_move, severity=severity,
                   crossed=list(crossed), evidence=evidence or {},
                   validate_first=validate_first, fired_count=fired,
                   should_speak=False, suppression_reason=reason, signals=sig)


def episode_id(sig):
    """Identity of *what* is blocking, so one block gets one intervention.

    Keyed on the shape of the failure rather than its text, so the same assertion at
    a different line number stays the same episode.
    """
    key = sig.top_error_signature or sig.top_command or sig.edit_thrash_file or ''
    if not key:
        return ''
    return hashlib.sha1(key.encode('utf-8', 'replace')).hexdigest()[:12]


def _crossings(sig, spec, th):
    out = []
    for rule in spec.get('any_of') or []:
        try:
            name, op, ref = rule[0], rule[1], rule[2]
            limit = th.get(ref)
            value = getattr(sig, name, 0)
            if limit is None or not _OPS.get(op, lambda a, b: False)(value, limit):
                continue
            out.append({'signal': name, 'value': value, 'threshold': limit, 'op': op})
        except Exception:
            continue
    return out


def _severity(crossed, sig, rules):
    if not crossed:
        return 0
    score = 0
    for c in crossed:
        try:
            score += min(2, int(c['value'] // max(1, c['threshold'])))
        except Exception:
            score += 1
    if sig.capitulation_hits:
        score += 1
    for limit, band in (rules.get('severity', {}).get('bands') or [[1, 1], [3, 2], [999, 3]]):
        if score <= limit:
            return band
    return 3


def classify(sig, session_id='', event='', state=None, rules=None):
    """Return a BlockReport. Never raises; on any internal failure, silence."""
    try:
        return _classify(sig, session_id, event, state, rules)
    except Exception:
        return _silent(sig, 'internal_error', session_id, event)


def _classify(sig, session_id, event, state, rules):
    rules = rulebook.load('diagnosis') if rules is None else rules
    th = rulebook.thresholds()
    types = rules.get('block_types') or {}
    order = rules.get('order') or sorted(types)

    matched = None
    crossed = []
    for name in order:
        spec = types.get(name) or {}
        hits = _crossings(sig, spec, th)
        if not hits:
            continue
        crossed.extend(hits)
        if matched is None or spec.get('overrides'):
            matched = (name, spec)
            if spec.get('overrides'):
                crossed = hits          # an override speaks for itself
                break

    if matched is None:
        return _silent(sig, 'not_stuck', session_id, event)

    name, spec = matched
    eid = episode_id(sig)
    severity = _severity(crossed, sig, rules)
    evidence = {
        'error_sample': (sig.error_samples[0] if sig.error_samples else ''),
        'error_signature': sig.top_error_signature,
        'thrash_file': sig.edit_thrash_file,
        'repeated_command': sig.top_command,
    }
    fired = 0
    try:
        fired = int(((state or {}).get('episodes') or {}).get(eid, {}).get('fired', 0))
    except Exception:
        fired = 0

    # Stage 2 of the brief: always open with validation. This is a modifier on every
    # block type, not a block type of its own — capitulation is usually a symptom.
    validate_first = sig.capitulation_hits >= th.get('capitulation_hits', 10 ** 6)

    common = dict(session_id=session_id, event=event, episode_id=eid, fired=fired,
                  block_type=name, primary_move=spec.get('primary_move', ''),
                  severity=severity, crossed=crossed, evidence=evidence,
                  validate_first=validate_first)

    # Suppression order matters: adjudication outranks everything, including severity.
    if sig.verdict_adjacent:
        return _silent(sig, 'adjudication', **common)
    if sig.horme_recent or fired > 0:
        return _silent(sig, 'already_fired', **common)
    if severity <= 0:
        return _silent(sig, 'not_stuck', **common)

    return _Report(session_id=session_id, event=event, episode_id=eid,
                   block_type=name, primary_move=spec.get('primary_move', ''),
                   severity=severity, crossed=crossed, evidence=evidence,
                   validate_first=validate_first,
                   fired_count=fired, should_speak=True, suppression_reason='',
                   signals=sig)
