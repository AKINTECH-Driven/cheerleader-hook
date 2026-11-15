"""Install / uninstall HORME's hooks in a Claude Code settings.json.

This is the only part of HORME that writes outside its own directory, and the file it
writes is the user's global configuration. Rules, in order:
  1. Back up first, timestamped, before a single byte changes.
  2. Refuse loudly on a file we cannot parse. Never clobber what we did not understand.
  3. Patch, never replace: existing hooks on the same event are preserved.
  4. Uninstall surgically, then verify byte-identity against the backup — a blind
     copy-back would silently discard anything the user changed after installing.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

from . import brand, rulebook

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(ROOT, 'hooks', brand.HOOK_FILENAME)
MARKER = brand.HOOK_FILENAME
DEFAULT_SETTINGS = os.path.expanduser('~/.claude/settings.json')


def hook_command(python=None, hook_path=None):
    """The shell command Claude Code runs on every watched event.

    The bare form `python3 hook.py` exits 2 when the script is gone (python cannot
    open the file), and 2 is the one status a hook must never return. According to
    the public hooks reference (read 2026-11-13) exit 2 stops the agentic loop on
    PostToolBatch and keeps Claude from stopping on Stop and SubagentStop. The
    reference makes one exception on Stop and SubagentStop: exit 2 with empty stdout
    and a missing-file message on stderr counts as a non-blocking error. None of this
    was observed in a live session, so the command does not lean on how an exit
    status is read. A moved or deleted folder has to degrade to silence:
      - the script runs only if it exists (no error text on every tool batch);
      - its output is held back and printed only if it exited 0, so a hook that dies
        halfway leaves nothing behind;
      - whatever else goes wrong ends in `true`.
    Both paths are shell-quoted: a space or a non-ASCII character used to produce a
    command that could not run, and `$(...)` in a folder name would have been run.
    The script is named once, through a variable, so the marker appears exactly once
    per entry, and always as an absolute path (a relative one starting with a dash
    would be read by python as an option). `_parse_command` is the inverse and must be
    kept in step.
    """
    return ('cl_h=%s; [ -f "$cl_h" ] && cl_o=$(%s "$cl_h") && printf \'%%s\' "$cl_o" || true'
            % (shlex.quote(os.path.abspath(hook_path or HOOK)), shlex.quote(python or sys.executable)))


_SHAPE = re.compile(r'^cl_h=(?P<hook>.+); \[ -f "\$cl_h" \] && cl_o=\$\((?P<python>.+) "\$cl_h"\) '
                    r'&& printf \'%s\' "\$cl_o" \|\| true$', re.S)
_OLD_SHAPE = re.compile(r'^(?P<python>\S+) "(?P<hook>[^"]*)"$')


def _parse_command(cmd):
    """(python, hook) if `cmd` is exactly what hook_command writes, else None.

    Exact means it survives the round trip: the two paths are taken out, quoted
    again, and the result must equal `cmd` character for character. Anything else in
    settings.json that mentions the hook was written by someone else, or tampered
    with, and doctor must not run it.
    """
    m = _SHAPE.match(cmd) if isinstance(cmd, str) else None
    if not m:
        return None
    try:
        hook, python = shlex.split(m.group('hook')), shlex.split(m.group('python'))
    except ValueError:
        return None
    if len(hook) != 1 or len(python) != 1 or os.path.basename(hook[0]) != MARKER:
        return None
    return (python[0], hook[0]) if hook_command(python[0], hook[0]) == cmd else None


def watched_events():
    """Every event HORME listens on: those that detect, plus SessionStart for pruning."""
    cfg = rulebook.load('hooks').get('events') or {}
    evs = [name for name, spec in cfg.items() if spec.get('detect')]
    if 'SessionStart' not in evs:
        evs.append('SessionStart')
    return sorted(evs)


def _read(path):
    """(text, parsed, error). error is set when the file exists but cannot be used."""
    if not os.path.exists(path):
        return '', {}, ''
    try:
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
    except Exception as exc:
        return '', None, 'could not read %s: %r' % (path, exc)
    if not text.strip():
        return text, {}, ''
    try:
        data = json.loads(text)
    except Exception as exc:
        return text, None, 'could not parse %s as JSON: %s' % (path, exc)
    if not isinstance(data, dict):
        return text, None, 'settings root is %s, expected an object' % type(data).__name__
    return text, data, ''


def _backup(path, text):
    if not os.path.exists(path):
        return ''
    dest = '%s.%s-backup-%s' % (path, brand.NAME, time.strftime('%Y%m%dT%H%M%S'))
    try:
        shutil.copy2(path, dest)
        return dest
    except Exception:
        try:
            with open(dest, 'w', encoding='utf-8') as fh:
                fh.write(text)
            return dest
        except Exception:
            return ''


def _is_ours(entry):
    try:
        return MARKER in json.dumps(entry)
    except Exception:
        return False


def _strip(data):
    """Remove every HORME hook entry, and any container it leaves empty."""
    hooks = data.get('hooks')
    if not isinstance(hooks, dict):
        return data, 0
    removed = 0
    for event in list(hooks):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            inner = group.get('hooks')
            if isinstance(inner, list):
                kept = [h for h in inner if not _is_ours(h)]
                removed += len(inner) - len(kept)
                if not kept:
                    continue                       # the whole group was ours
                group = dict(group, hooks=kept)
            elif _is_ours(group):
                removed += 1
                continue
            kept_groups.append(group)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not hooks:
        data.pop('hooks', None)
    return data, removed


def install(settings_path=None, python=None, hook_path=None):
    path = settings_path or DEFAULT_SETTINGS
    text, data, err = _read(path)
    if err:
        return {'ok': False, 'error': err, 'backup': ''}

    backup = _backup(path, text)
    data, _removed = _strip(data)                  # idempotent: clear ours, then re-add
    cmd = hook_command(python, hook_path)
    hooks = data.setdefault('hooks', {})
    events = watched_events()
    for event in events:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            groups = []
            hooks[event] = groups
        groups.append({'hooks': [{'type': 'command', 'command': cmd,
                                  'statusMessage': brand.LABEL}]})
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2)
            fh.write('\n')
    except Exception as exc:
        return {'ok': False, 'error': 'could not write %s: %r' % (path, exc), 'backup': backup}
    return {'ok': True, 'error': '', 'backup': backup, 'events': events, 'command': cmd}


def uninstall(settings_path=None):
    path = settings_path or DEFAULT_SETTINGS
    text, data, err = _read(path)
    if err:
        return {'ok': False, 'error': err, 'removed': 0}
    if not data:
        return {'ok': True, 'error': '', 'removed': 0}

    data, removed = _strip(data)
    if not removed:
        return {'ok': True, 'error': '', 'removed': 0}

    # If the stripped structure matches a pre-install backup exactly, restore that
    # backup's BYTES so formatting survives too. Anything else, and we write our own
    # formatting rather than discarding the user's later edits.
    payload = None
    for cand in sorted(_backups(path), reverse=True):
        try:
            with open(cand, encoding='utf-8') as fh:
                btext = fh.read()
            if json.loads(btext) == data:
                payload = btext
                break
        except Exception:
            continue
    if payload is None:
        payload = json.dumps(data, indent=2) + '\n'
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(payload)
    except Exception as exc:
        return {'ok': False, 'error': 'could not write %s: %r' % (path, exc), 'removed': 0}
    return {'ok': True, 'error': '', 'removed': removed}


def _backups(path):
    d = os.path.dirname(path) or '.'
    base = os.path.basename(path) + '.%s-backup-' % brand.NAME
    try:
        return [os.path.join(d, f) for f in os.listdir(d) if f.startswith(base)]
    except Exception:
        return []


def _our_commands(data):
    """Every command string HORME wrote into this settings object, each one once."""
    found = []
    hooks = data.get('hooks') if isinstance(data, dict) else None
    for groups in (hooks.values() if isinstance(hooks, dict) else []):
        for group in (groups if isinstance(groups, list) else []):
            if not isinstance(group, dict):
                continue
            inner = group.get('hooks')
            for h in (inner if isinstance(inner, list) else [group]):
                cmd = h.get('command') if isinstance(h, dict) else None
                if isinstance(cmd, str) and MARKER in cmd and cmd not in found:
                    found.append(cmd)
    return found


def doctor(settings_path=None, hook_path=None):
    """Is HORME wired in, does the engine work, and does the stored command still run?

    Three separate questions, because the hook is built to hide every failure from the
    session: it prints `{}` and exits 0 whether the engine ran or could not even be
    imported. Looking at that exit status proves nothing. So the engine is asked to
    prove itself (`--selftest` runs every stage on a synthetic stuck session), and
    each command in settings.json is run exactly as Claude Code would run it.

    Only a command in the exact shape `hook_command` writes is run. An entry from an
    older version is reported and left alone, and so is anything else that merely
    mentions the hook's file name: a health check has no business executing what it
    did not write. `command_ok` is None when nothing is installed.
    """
    path = settings_path or DEFAULT_SETTINGS
    hook = hook_path or HOOK
    _text, data, err = _read(path)
    out = {'settings': path, 'installed': False, 'events': [], 'error': err,
           'engine_ok': False, 'engine_error': '', 'selftest': {}, 'hook': hook,
           'kill_switch': False, 'command_ok': None, 'command_error': ''}
    if isinstance(data, dict):
        for event, groups in (data.get('hooks') or {}).items():
            if _is_ours(groups):
                out['events'].append(event)
        out['events'].sort()
        out['installed'] = bool(out['events'])

    try:
        proc = subprocess.run([sys.executable, hook, '--selftest'], input='',
                              capture_output=True, text=True, timeout=30)
        answer = json.loads(proc.stdout or '{}')
        res = answer.get('selftest') if isinstance(answer, dict) else None
        if not isinstance(res, dict):
            out['engine_error'] = ('the hook did not answer the self-test (exit %d) %s'
                                   % (proc.returncode, (proc.stderr or proc.stdout)[-300:]))
        else:
            out['selftest'] = res
            out['kill_switch'] = bool(res.get('kill_switch'))
            out['engine_ok'] = bool(res.get('ok')) and proc.returncode == 0
            if not out['engine_ok']:
                out['engine_error'] = '%s: %s' % (res.get('stage') or 'self-test',
                                                  res.get('error') or 'failed')
    except Exception as exc:
        out['engine_error'] = repr(exc)

    commands = _our_commands(data)
    if commands:
        wrong = []
        for cmd in commands:
            parsed = _parse_command(cmd)
            if not parsed:
                old = _OLD_SHAPE.match(cmd)
                if old and os.path.basename(old.group('hook')) == MARKER:
                    wrong.append('written by an older version, which exits 2 on every event if '
                                 'the folder moves; run install.py again; not run: %s' % cmd)
                else:
                    wrong.append('mentions the hook but is not a command this tool writes; '
                                 'not run: %s' % cmd)
                continue
            python, script = parsed
            if not os.path.isfile(script):
                wrong.append('the hook script is gone: %s (has the folder moved?)' % script)
                continue
            if not (os.path.isfile(python) and os.access(python, os.X_OK)):
                wrong.append('the interpreter is gone: %s; run install.py again' % python)
                continue
            try:
                proc = subprocess.run(cmd, shell=True, input='{}', capture_output=True,
                                      text=True, timeout=30)
                if proc.returncode != 0:
                    wrong.append('exit %d from: %s' % (proc.returncode, cmd))
                elif not (proc.stdout or '').strip():
                    wrong.append('no output from: %s' % cmd)
                else:
                    json.loads(proc.stdout)
            except Exception as exc:
                wrong.append('%r from: %s' % (exc, cmd))
        out['command_ok'] = not wrong
        out['command_error'] = '; '.join(wrong)
    return out
