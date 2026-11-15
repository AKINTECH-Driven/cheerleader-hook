"""Derive HORME's detector thresholds from real transcripts. Read-only.

Consumes horme.signals rather than reimplementing it, so calibration and production
measure the identical thing.

Simulates the hook: at many points during each real session, extract the windowed
SignalSet the hook *would* have seen, and record the worst value reached. Thresholds
are then set at a high percentile of that distribution, so a healthy session stays
below them by construction.

Usage: /usr/bin/python3 tools/calibrate.py [--write] [projects_dir]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from horme import transcript, signals  # noqa: E402

METRICS = ('current_error_run', 'consecutive_tool_errors', 'repeated_error_count',
           'command_repeat', 'edit_thrash', 'reread_thrash', 'calls_since_success',
           'capitulation_hits', 'env_blocked_errors')
STEP = 3
MIN_TOOLS = 20


def display_path(path):
    """The corpus path as recorded in thresholds.json, with the home folder written as ~.

    That file is meant to be committed, so it must not carry an account name."""
    home = os.path.expanduser('~')
    full = os.path.abspath(os.path.expanduser(path))
    if full == home or full.startswith(home + os.sep):
        return '~' + full[len(home):]
    return path


def pct(vals, p):
    if not vals:
        return 0
    v = sorted(vals)
    return v[min(len(v) - 1, int(round((p / 100.0) * (len(v) - 1))))]


def worst_over_session(path):
    ev = transcript.read_tail(path, max_lines=100000, max_bytes=64 * 1024 * 1024)
    cuts = [i for i, e in enumerate(ev) if e.kind == 'tool_result']
    if len(cuts) < MIN_TOOLS:
        return None
    worst = dict((m, 0) for m in METRICS)
    fired_positions = 0
    for i in cuts[::STEP]:
        s = signals.extract(ev[:i + 1])
        for m in METRICS:
            v = getattr(s, m)
            if v > worst[m]:
                worst[m] = v
        if s.verdict_adjacent:
            fired_positions += 1
    worst['_verdict_positions'] = fired_positions
    worst['_positions'] = len(cuts[::STEP])
    return worst


def main():
    write = '--write' in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    root = args[0] if args else os.path.expanduser('~/.claude/projects')

    files = []
    for dirpath, _d, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith('.jsonl'):
                files.append(os.path.join(dirpath, fn))
    files.sort()

    rows = []
    for f in files:
        try:
            w = worst_over_session(f)
        except Exception:
            continue
        if w:
            rows.append(w)

    print('sessions scanned: %d · with >=%d tool results: %d · window=%d tool calls'
          % (len(files), MIN_TOOLS, len(rows), signals.DEFAULT_WINDOW))
    if not rows:
        print('nothing to calibrate')
        return 1

    print('\nWORST WINDOWED VALUE REACHED PER SESSION (healthy corpus)')
    print('%-26s %5s %5s %5s %5s %5s' % ('signal', 'p50', 'p90', 'p95', 'p99', 'max'))
    derived = {}
    for m in METRICS:
        vals = [r[m] for r in rows]
        p95, p99, mx = pct(vals, 95), pct(vals, 99), max(vals)
        print('%-26s %5d %5d %5d %5d %5d'
              % (m, pct(vals, 50), pct(vals, 90), p95, p99, mx))
        derived[m] = max(p99 + 1, 2)      # fire only above anything the healthy corpus reached

    vp = sum(r['_verdict_positions'] for r in rows)
    tp = sum(r['_positions'] for r in rows) or 1
    print('\nadjudication-suppressed positions: %d/%d = %.1f%%' % (vp, tp, 100.0 * vp / tp))

    out = {
        '_provenance': {
            'derived_from': display_path(root),
            'sessions_scanned': len(files),
            'sessions_used': len(rows),
            'window_tool_calls': signals.DEFAULT_WINDOW,
            'rule': 'threshold = p99(worst windowed value in a healthy session) + 1, floor 2',
            'note': ('Thresholds are MEASURED, never hand-typed. Regenerate with '
                     'tools/calibrate.py --write after any change to signals.py.'),
            'limitation': ('The corpus is UNLABELLED. Treating it as healthy is an '
                           'assumption, and some of these sessions certainly contained '
                           'genuinely stuck episodes. That biases every threshold upward, '
                           'so HORME errs toward silence rather than noise. This is the '
                           'intended direction, but it is an assumption, not a finding.'),
        },
        'thresholds': derived,
    }
    if write:
        path = os.path.join(ROOT, 'rulebook', 'thresholds.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
            fh.write('\n')
        print('\nwrote %s' % path)
    else:
        print('\n(dry run — pass --write to emit rulebook/thresholds.json)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
