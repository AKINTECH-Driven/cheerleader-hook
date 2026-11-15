#!/usr/bin/env python3
"""Remove HORME's hooks from ~/.claude/settings.json, restoring the backup byte-for-byte."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
from horme import install as inst  # noqa: E402


def main(argv):
    path = inst.DEFAULT_SETTINGS
    if '--settings' in argv:
        path = argv[argv.index('--settings') + 1]
    res = inst.uninstall(path)
    if not res['ok']:
        print('REFUSING: %s' % res['error'])
        return 1
    print('removed %d HORME hook entr%s from %s'
          % (res['removed'], 'y' if res['removed'] == 1 else 'ies', path))
    if not res['removed']:
        print('(nothing to remove — HORME was not installed there)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
