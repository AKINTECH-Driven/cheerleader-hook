"""BlockReport -> Intervention. Pure, deterministic, rulebook-driven.

No model call, no I/O. Every sentence traces to a slot in rulebook/phrases.json and
every slot cites the study behind it. Output is checked against the denylist before
release and suppressed entirely if it trips (decided at the Feature 3 plan gate).
"""
import hashlib
import os
from collections import namedtuple

from . import brand, denylist, rulebook

Intervention = namedtuple('Intervention', 'text system_line parts suppressed reason violations')

MARKER = brand.MARKER
EMPTY = Intervention(text='', system_line='', parts=[], suppressed=True,
                     reason='not_speaking', violations=[])

#: Which slots each primary_move is allowed to use, in the brief's Stage order.
#: stand_down is deliberately a single slot: it is not an encouragement.
MOVE_SLOTS = {
    'stand_down': ['stand_down'],
    'decompose': ['validate', 'relabel', 'progress', 'decompose', 'autonomy', 'if_then'],
    'validate_then_decompose': ['validate', 'relabel', 'decompose', 'autonomy', 'if_then'],
    'mark_progress_and_return_control': ['validate', 'relabel', 'progress', 'autonomy', 'if_then'],
}
#: Slots that only earn their place as the block deepens. Escalation is in the amount
#: of scaffolding, never in the amount of enthusiasm.
MIN_SEVERITY = {'progress': 2, 'if_then': 2, 'autonomy': 1, 'validate': 1}


def _pick(options, salt):
    """Deterministic choice: stable for one episode, varied across episodes."""
    if not options:
        return None
    h = int(hashlib.sha1(str(salt).encode('utf-8', 'replace')).hexdigest()[:8], 16)
    return options[h % len(options)]


def _short_file(path):
    return os.path.basename(path) if path else ''


def _error_line(sample):
    """One trimmed line of the real error — the specificity budget set at the plan gate."""
    if not sample:
        return ''
    lines = [l.strip() for l in str(sample).splitlines() if l.strip()]
    for l in lines:
        if any(tok in l for tok in ('Error', 'error', 'assert', 'Exception', 'not found')):
            return l[:90]
    return lines[0][:90] if lines else ''


def _what_short(report):
    """A brief back-reference, so the full specific phrase is only ever said once."""
    f = _short_file(report.evidence.get('thrash_file', ''))
    if f:
        return f
    line = _error_line(report.evidence.get('error_sample', ''))
    if line:
        head = line.split(':')[0].strip()
        return head[:40] if head else line[:40]
    return 'the same failure'


def _what(report):
    """A specific, human-readable name for the block. Never returns a bare 'this'."""
    f = _short_file(report.evidence.get('thrash_file', ''))
    line = _error_line(report.evidence.get('error_sample', ''))
    if line and f:
        return '%s, in %s' % (line, f)
    if line:
        return line
    if f:
        return 'the repeated failure in %s' % f
    cmd = report.evidence.get('repeated_command', '')
    if cmd:
        return 'the repeated `%s`' % cmd[:60]
    sig = report.evidence.get('error_signature', '')
    return sig[:90] if sig else 'the current step'


def _moves(report, moves_tbl, ctx, fallbacks):
    """Concrete next actions, ordered by which signal crossed hardest. Never invented.

    A move whose template needs a filename is dropped when no file is known, rather
    than rendered with a placeholder like "the file" that reads as an unfilled slot.
    """
    out = []
    ranked = sorted(report.crossed,
                    key=lambda c: -(c.get('value', 0) / max(1, c.get('threshold', 1))))
    for c in ranked:
        tpl = moves_tbl.get(c.get('signal'))
        if not tpl:
            continue
        if '{file}' in tpl and not ctx.get('file'):
            continue
        try:
            text = tpl.format(**ctx)
        except Exception:
            continue
        if text not in out:
            out.append(text)
    for f in fallbacks or []:
        if f not in out:
            out.append(f)
    return out


def _all_moves_in(iv):
    """The distinct move phrases an intervention actually used — for the no-restatement
    test, and for --explain."""
    seen = []
    for p in iv.parts:
        for key in ('move', 'move_a', 'move_b', 'move_c'):
            v = (p.get('moves') or {}).get(key)
            if v and v not in seen:
                seen.append(v)
    return seen


def compose(report, phrases=None, deny=None):
    """Return an Intervention. Never raises; on any failure, silence."""
    try:
        return _compose(report, phrases, deny)
    except Exception:
        return EMPTY._replace(reason='internal_error')


def _compose(report, phrases, deny):
    if report is None or not getattr(report, 'should_speak', False):
        return EMPTY

    rb = rulebook.load('phrases') if phrases is None else phrases
    slots = (rb or {}).get('slots') or {}
    moves_tbl = (rb or {}).get('moves') or {}
    if not slots:
        return EMPTY._replace(reason='no_rulebook')

    sig = report.signals
    what = _what(report)
    ctx = {
        'what': what,
        'what_short': _what_short(report),
        'file': _short_file(report.evidence.get('thrash_file', '')),
        # Count the failure we NAME, not every failure in the window: saying
        # "docker: command not found, 10 times" when docker failed 5 and pandoc 5
        # is a false statement about the thing it just pointed at.
        'n_fail': sig.repeated_error_count or sig.error_count,
        'n_edits': sig.edit_thrash,
        'n_cmd': sig.command_repeat,
        'n_tools': sig.tool_count,
        'n_ok': max(0, sig.tool_count - sig.error_count),
    }
    fallbacks = ((rb or {}).get('fallback_moves') or {}).get('moves') or []
    move_list = _moves(report, moves_tbl, ctx, fallbacks)

    allowed = [n for n in MOVE_SLOTS.get(report.primary_move, MOVE_SLOTS['decompose'])
               if not (n == 'validate' and not report.validate_first)
               and report.severity >= MIN_SEVERITY.get(n, 0)
               and (slots.get(n) or {}).get('templates')]

    # Allocate a DISTINCT move to each slot that needs one, so autonomy never restates
    # the step decompose just gave. Repetition is the fastest way for an intervention
    # to read as generated rather than considered.
    cursor = 0
    if 'decompose' in allowed:
        ctx['move'] = move_list[cursor] if move_list else 'reduce the problem to the smallest failing case'
        cursor += 1
    ctx['move_a'] = move_list[cursor] if len(move_list) > cursor else 'reproduce the failure in isolation'
    cursor += 1
    ctx['move_b'] = move_list[cursor] if len(move_list) > cursor else 're-read the failure output end to end'
    cursor += 1
    ctx['move_c'] = move_list[cursor] if len(move_list) > cursor else 'reduce the case until it is small enough to reason about'

    parts = []
    what_used = False
    for name in allowed:
        spec = slots.get(name) or {}
        tpl = _pick(spec.get('templates') or [], '%s|%s' % (report.episode_id, name))
        if not tpl:
            continue
        local = dict(ctx)
        if what_used:
            local['what'] = ctx['what_short']      # full form is said once, then referred back to
        try:
            text = tpl.format(**local)
        except Exception:
            continue                      # an unrenderable template is dropped, not leaked
        if ctx['what'] and ctx['what'] in text:
            what_used = True
        parts.append({'slot': name, 'text': text, 'source': spec.get('source', ''),
                      'moves': {k: local.get(k) for k in ('move', 'move_a', 'move_b', 'move_c')
                                if local.get(k) and local[k] in text}})

    if not parts:
        return EMPTY._replace(reason='no_slots')

    body = ' '.join(p['text'] for p in parts)
    text = '%s %s' % (MARKER, body)

    checker = denylist.check if deny is None else deny
    try:
        violations = checker(text)
        if not isinstance(violations, list):          # None or False is not `clean`
            raise TypeError('it answered %r, which is not a list' % (violations,))
    except Exception as exc:
        violations = [{'group': denylist.UNAVAILABLE, 'pattern': '',
                       'why': 'the denylist check raised %r' % (exc,)}]
    if violations:
        # Fail closed, loudly. Every template is ours, so a trip is a template bug;
        # a guard that could not run is not a trip at all, and is named as what it is.
        gone = any(isinstance(v, dict) and v.get('group') == denylist.UNAVAILABLE
                   for v in violations)
        return Intervention(text='', system_line='', parts=parts, suppressed=True,
                            reason='denylist_unavailable' if gone else 'denylist',
                            violations=violations)

    label = {'stand_down': 'environment blocked'}.get(report.primary_move,
                                                      '%s block' % report.block_type)
    system_line = ('%s: %s, severity %d — %s'
                   % (brand.LABEL, label, report.severity, what))[:120]
    return Intervention(text=text, system_line=system_line, parts=parts,
                        suppressed=False, reason='', violations=[])
