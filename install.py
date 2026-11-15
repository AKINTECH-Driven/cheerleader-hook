#!/usr/bin/env python3
"""Install HORME's hooks into ~/.claude/settings.json. Backs up first; refuses on corrupt input."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
from horme import brand, install as inst  # noqa: E402


def main(argv):
    path = inst.DEFAULT_SETTINGS
    if '--settings' in argv:
        path = argv[argv.index('--settings') + 1]

    if '--doctor' in argv:
        d = inst.doctor(path)
        print('settings : %s' % d['settings'])
        print('installed: %s%s' % (d['installed'], (' on ' + ', '.join(d['events'])) if d['events'] else ''))
        print('engine   : %s%s' % ('ok' if d['engine_ok'] else 'FAILED', d['engine_error'] and ' — ' + d['engine_error']))
        if d.get('kill_switch'):
            print('disabled : yes — the kill switch is on, so the hook stays silent by choice')
        if d['command_ok'] is not None:
            print('command  : %s%s' % ('ok' if d['command_ok'] else 'FAILED', d['command_error'] and ' — ' + d['command_error']))
        if d['error']:
            print('error    : %s' % d['error'])
        return 0 if (d['engine_ok'] and not d['error'] and d['command_ok'] is not False) else 1

    if '--dry-run' in argv:
        text, data, err = inst._read(path)
        if err:
            print('REFUSING: %s' % err)
            return 1
        print('would back up : %s -> %s.%s-backup-<timestamp>' % (path, path, brand.NAME))
        print('would add a hook on: %s' % ', '.join(inst.watched_events()))
        print('would run     : %s' % inst.hook_command())
        existing = sorted((data.get('hooks') or {}).keys())
        print('existing hooks preserved on: %s' % (', '.join(existing) or '(none)'))
        print('\nnothing has been changed. re-run without --dry-run to apply.')
        return 0

    res = inst.install(path)
    if not res['ok']:
        print('REFUSING: %s' % res['error'])
        return 1
    print('installed on : %s' % ', '.join(res['events']))
    print('backup       : %s' % (res['backup'] or '(no previous file)'))
    print('command      : %s' % res['command'])
    print('\nIf the hook does not show up in a running session, restart Claude Code.')
    print('Disable any time with: export %s=1' % brand.ENV_DISABLE[0])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
