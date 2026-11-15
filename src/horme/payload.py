"""Tolerant parser for hook stdin.

The field names in the public hooks reference are documentation, not observation:
`PostToolBatch` is documented with `tool_output` where `PostToolUse` uses
`tool_response`. Rather than bet on either, this parser accepts both spellings and
tolerates every field being absent, mistyped or hostile. `hooks/horme_probe.py`
captures the real payloads so the guesswork can be retired with evidence.
"""
import json
from collections import namedtuple

Payload = namedtuple(
    'Payload',
    'ok event session_id transcript_path cwd permission_mode '
    'tool_calls last_assistant_message user_input raw')

EMPTY = Payload(ok=False, event='', session_id='', transcript_path='', cwd='',
                permission_mode='', tool_calls=(), last_assistant_message='',
                user_input='', raw={})


def _s(v, default=''):
    """Coerce to str only when it already is one; never stringify a dict into noise."""
    return v if isinstance(v, str) else default


def _one_call(d):
    if not isinstance(d, dict):
        return None
    name = _s(d.get('tool_name'))
    inp = d.get('tool_input')
    # documented as `tool_response` on PostToolUse and `tool_output` on PostToolBatch
    out = d.get('tool_response')
    if out is None:
        out = d.get('tool_output')
    err = d.get('tool_error')
    is_error = bool(d.get('tool_response_is_error')) or err is not None
    if err is not None and out is None:
        out = err
    if not isinstance(out, str):
        out = '' if out is None else json.dumps(out, default=str)[:4000]
    return {
        'name': name,
        'input': inp if isinstance(inp, dict) else {},
        'output': out,
        'is_error': is_error,
        'tool_use_id': _s(d.get('tool_use_id')),
    }


def parse(raw):
    """bytes|str|None -> Payload. Never raises; garbage in, EMPTY out."""
    try:
        if raw is None:
            return EMPTY
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode('utf-8', errors='replace')
        if not isinstance(raw, str) or not raw.strip():
            return EMPTY
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            return EMPTY

        calls = []
        batch = obj.get('tool_calls')
        if isinstance(batch, list):
            for d in batch:
                c = _one_call(d)
                if c is not None:
                    calls.append(c)
        elif obj.get('tool_name') is not None:
            c = _one_call(obj)
            if c is not None:
                calls.append(c)

        return Payload(
            ok=True,
            event=_s(obj.get('hook_event_name')),
            session_id=_s(obj.get('session_id')),
            transcript_path=_s(obj.get('transcript_path')),
            cwd=_s(obj.get('cwd')),
            permission_mode=_s(obj.get('permission_mode')),
            tool_calls=tuple(calls),   # immutable: EMPTY is a module singleton
            last_assistant_message=_s(obj.get('last_assistant_message')),
            user_input=_s(obj.get('user_input')),
            raw=obj,
        )
    except Exception:
        return EMPTY
