#!/usr/bin/env python3
"""Capture real hook payloads so HORME's schema stops being a guess.

Install temporarily, run a session, then read ~/.claude/horme/probe/*.json.
Writes nothing to the transcript, blocks nothing, always exits 0.
"""
import json
import os
import sys
import time

OUT = os.path.expanduser('~/.claude/horme/probe')


def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ''
    try:
        os.makedirs(OUT, exist_ok=True)
        try:
            obj = json.loads(raw)
            event = obj.get('hook_event_name', 'unknown') if isinstance(obj, dict) else 'nonobject'
            keys = sorted(obj.keys()) if isinstance(obj, dict) else []
        except Exception:
            obj, event, keys = None, 'unparseable', []
        stamp = time.strftime('%Y%m%dT%H%M%S')
        path = os.path.join(OUT, '%s-%s-%d.json' % (stamp, event, os.getpid()))
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'event': event, 'top_level_keys': keys,
                       'raw_len': len(raw), 'payload': obj if obj is not None else raw[:8000]},
                      fh, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass
    sys.stdout.write('{}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
