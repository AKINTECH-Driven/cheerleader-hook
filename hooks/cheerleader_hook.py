#!/usr/bin/env python3
"""HORME hook entry point. Wire every watched event to this one script.

It dispatches internally on hook_event_name, always exits 0, and always writes
valid JSON to stdout. Zero third-party imports, by rule.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

if '--selftest' in sys.argv[1:]:
    # Asked by `install.py --doctor`. The one path where a failure is reported instead
    # of hidden; still exit 0, because the answer is in the JSON.
    try:
        from horme.cli import selftest
        result = selftest()
    except Exception as exc:
        result = {'ok': False, 'stage': 'import', 'error': repr(exc), 'detail': ''}
    sys.stdout.write(json.dumps({'selftest': result}))
    sys.exit(0)

try:
    from horme.cli import main
except Exception:
    # If HORME itself cannot be imported, the session must carry on regardless.
    sys.stdout.write('{}')
    sys.exit(0)

if __name__ == '__main__':
    sys.exit(main())
