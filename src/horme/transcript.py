"""Bounded tail-read of a Claude Code session transcript.

Schema verified 2026-08-26 against real sessions in ~/.claude/projects; see docs/NOTES.md.
Nothing here raises: a transcript that cannot be read yields no events, and a hook
that yields no events stays silent, which is the correct failure mode.
"""
import json
import os
from collections import namedtuple

#: kind: 'tool_use' | 'tool_result' | 'say' | 'human' | 'hook'
#: name:  tool name for tool_use; 'text'/'thinking' for say; '' otherwise
#: scan:  tool_result only, and only when the result is longer than `text`: the texts
#:        the verdict check reads instead of `text`, see SCAN_CAP
Event = namedtuple('Event', 'kind ts name input tool_use_id text is_error scan', defaults=((),))

DEFAULT_MAX_LINES = 400
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
TEXT_CAP = 4000          # per-event text kept; transcripts hold megabytes we never need

#: A tool result is also kept whole, up to this many characters, for one reader only:
#: the verdict check. A verifier prints its findings and then its verdict, so the cut
#: at TEXT_CAP removed exactly the line that check exists to see. Every other signal
#: still reads `text`; the thresholds were calibrated on that.
#:
#: The cap is a decision about the hook's time budget: the check is linear in what it
#: reads, 3 to 5 ms for 60,000 characters of ordinary output and up to about 25 ms for
#: the worst shape found (tens of thousands of blank lines around a few result lines).
SCAN_CAP = 60000
CUT_MARK = '[...]'


def _mk(kind, ts, name='', inp=None, tool_use_id='', text='', is_error=False, scan=()):
    return Event(kind, ts, name, inp or {}, tool_use_id, text, is_error, scan)


def _scan_parts(full, text_cap=TEXT_CAP, scan_cap=SCAN_CAP):
    """What the verdict check reads of a tool result when `text` is not all of it: a
    tuple of (text, whole_lines). () when `text` holds everything, so a short result is
    not stored twice. Up to the scan cap, the result itself.

    Past the cap, the first and the last half, each as two texts:
      - its whole lines, read like any output, where a runner's result line is excused;
      - the one line the cut went through, kept apart and marked as not whole. What
        is left of such a line can be a runner's line to the letter, or the start of
        a summary that would vouch for one, so it is read as it stands: any verdict
        word in it counts, and it takes no part in what the whole lines are.
    The whole lines of the first half end in CUT_MARK. go test's closing FAIL is
    excused only as the last line of the output, and that line is not the last.

    So nothing in one half can vouch for a line in the other, and every effect of the
    cut is toward silence. The middle is not read.
    """
    if len(full) <= text_cap:
        return ()
    if len(full) <= scan_cap:
        return ((full, True),)
    half = scan_cap // 2
    head = full[:half].splitlines(keepends=True)
    tail = full[-half:].splitlines(keepends=True)
    return ((''.join(head[:-1]) + CUT_MARK, True), (head[-1], False),
            (tail[0], False), (''.join(tail[1:]), True))


def _flatten(content):
    """tool_result.content is a str in practice but a list of blocks in the schema."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                parts.append(str(b.get('text', '') or b.get('content', '')))
            elif isinstance(b, str):
                parts.append(b)
        return ' '.join(parts)
    if content is None:
        return ''
    return str(content)


def _tail_lines(path, max_lines, max_bytes):
    """Read at most max_bytes from the end, keep at most max_lines whole lines."""
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                blob = fh.read()
                nl = blob.find(b'\n')          # first line is cut: drop it
                blob = blob[nl + 1:] if nl >= 0 else b''
            else:
                blob = fh.read()
    except (OSError, ValueError):
        return []
    text = blob.decode('utf-8', errors='replace')
    lines = text.split('\n')
    return lines[-max_lines:] if max_lines and len(lines) > max_lines else lines


def read_tail(path, max_lines=DEFAULT_MAX_LINES, max_bytes=DEFAULT_MAX_BYTES,
              include_sidechain=False):
    """Return Events oldest-first from the tail of a transcript. Never raises."""
    if not path or not isinstance(path, str):
        return []
    events = []
    for line in _tail_lines(path, max_lines, max_bytes):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue                            # truncated or corrupt line: skip it
        if not isinstance(o, dict):
            continue
        if o.get('isSidechain') and not include_sidechain:
            continue
        try:
            events.extend(_events_from(o))
        except Exception:
            continue
    return events


def _events_from(o):
    kind = o.get('type')
    ts = str(o.get('timestamp') or '')
    msg = o.get('message')
    out = []

    if kind == 'assistant' and isinstance(msg, dict):
        for b in msg.get('content') or []:
            if not isinstance(b, dict):
                continue
            bt = b.get('type')
            if bt == 'tool_use':
                inp = b.get('input')
                out.append(_mk('tool_use', ts, name=str(b.get('name') or ''),
                               inp=inp if isinstance(inp, dict) else {},
                               tool_use_id=str(b.get('id') or '')))
            elif bt in ('text', 'thinking'):
                txt = b.get(bt) or b.get('text') or ''
                if isinstance(txt, str) and txt.strip():
                    out.append(_mk('say', ts, name=bt, text=txt[:TEXT_CAP]))

    elif kind == 'user' and isinstance(msg, dict):
        content = msg.get('content')
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get('type') == 'tool_result':
                    full = _flatten(b.get('content'))
                    out.append(_mk('tool_result', ts,
                                   tool_use_id=str(b.get('tool_use_id') or ''),
                                   text=full[:TEXT_CAP],
                                   is_error=bool(b.get('is_error')),
                                   scan=_scan_parts(full)))
        elif isinstance(content, str) and content.strip():
            out.append(_mk('human', ts, text=content[:TEXT_CAP]))

    elif kind == 'system' and o.get('subtype') == 'stop_hook_summary':
        ctxs = o.get('hookAdditionalContext') or []
        joined = ' '.join(str(c) for c in ctxs if c)
        if joined.strip():
            out.append(_mk('hook', ts, text=joined[:TEXT_CAP]))

    return out
