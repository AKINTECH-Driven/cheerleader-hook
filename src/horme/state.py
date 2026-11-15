"""Per-session firing state: what HORME has already said, and when.

Lives outside the project, under ~/.claude/cheerleader/state/. Every function here is
best-effort. load(), save(), claim(), release(), rate_limit() and prune() never raise: a
state file that cannot be read counts as empty, so that session starts again from zero,
and a state that cannot be saved is reported by save() answering False, after which the
caller gives no intervention. The hook around them exits 0 whatever happens here and
never crashes the session it is supposed to be helping.
"""
import json
import os
import re
import time

try:
    import fcntl
except ImportError:                 # no fcntl on this platform: there is no lock to take
    fcntl = None

from . import brand, rulebook

STATE_DIR = brand.STATE_DIR
_SAFE = re.compile(r'[^A-Za-z0-9_.-]')

DEFAULT_LIMITS = {'max_per_session': 4, 'min_seconds_between': 90,
                  'max_per_episode': 1, 'state_ttl_days': 7}


def limits():
    lim = dict(DEFAULT_LIMITS)
    try:
        lim.update((rulebook.load('hooks').get('limits') or {}))
    except Exception:
        pass
    return lim


def _safe_name(session_id):
    """The session id arrives from hook stdin. Treat it as untrusted: no traversal."""
    name = _SAFE.sub('_', str(session_id or 'unknown'))
    name = name.strip('.') or 'unknown'
    return name[:120] + '.json'


def _path(session_id):
    return os.path.join(STATE_DIR, _safe_name(session_id))


def blank():
    return {'episodes': {}, 'fired_total': 0, 'last_fired_at': 0.0}


def load(session_id):
    try:
        with open(_path(session_id), encoding='utf-8') as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return blank()
        base = blank()
        base.update(data)
        if not isinstance(base.get('episodes'), dict):
            base['episodes'] = {}
        return base
    except Exception:
        return blank()


def save(session_id, data):
    """Write the state and read it back. True only when the file now holds the text
    that was written.

    Atomic where possible, and it never raises. A caller that gets anything but True
    must not speak: a firing that was not recorded can repeat on the next event, with
    no session cap, cooldown or per-block limit left to stop it.
    """
    tmp = ''
    try:
        text = json.dumps(data)
        target = _path(session_id)
        tmp = target + '.tmp'
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, target)
        with open(target, encoding='utf-8') as fh:
            return fh.read() == text
    except Exception:
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


#: What claim() hands back where there is no fcntl. Nothing was locked.
NO_LOCK = object()


class _Held(object):
    """A session lock that is held: the open descriptor, until release() takes it out."""
    __slots__ = ('fd',)

    def __init__(self, fd):
        self.fd = fd


def claim(session_id):
    """Take the session's lock without waiting. Returns (lock, why), and never raises.

    Two runs that start together would each read a state that has heard nothing, and each
    would speak. So a run takes this lock before it reads the state for the last time,
    and keeps it until its firing is saved.

    - (lock, ''): the lock is held. Hand `lock` to release().
    - (None, 'state_busy'): another run holds it. That run is deciding; this one says nothing.
    - (None, 'state_unwritable'): the lock file could not be made or locked.
    - (NO_LOCK, ''): this platform has no fcntl, so nothing was locked.
    """
    if fcntl is None:
        return NO_LOCK, ''
    fd = None
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        fd = os.open(_path(session_id) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        _close(fd)
        return None, 'state_busy'
    except Exception:
        _close(fd)
        return None, 'state_unwritable'
    try:
        os.utime(fd)                # a lock in use is a fresh file, so prune() leaves it alone
    except Exception:
        pass
    return _Held(fd), ''


def release(lock):
    """Give the lock back. Takes whatever claim() returned, and a second call does nothing."""
    if not isinstance(lock, _Held):
        return
    fd, lock.fd = lock.fd, None
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except Exception:
        pass
    _close(fd)


def _close(fd):
    try:
        if fd is not None:
            os.close(fd)
    except Exception:
        pass


def record_fire(data, episode_id, now=None):
    now = time.time() if now is None else now
    ep = data.setdefault('episodes', {}).setdefault(episode_id or '_', {'fired': 0})
    ep['fired'] = int(ep.get('fired', 0)) + 1
    ep['last_at'] = now
    data['fired_total'] = int(data.get('fired_total', 0)) + 1
    data['last_fired_at'] = now
    return data


def rate_limit(data, episode_id, now=None, lim=None):
    """(may_speak, reason). Reason is '' when speaking is allowed."""
    try:
        now = time.time() if now is None else now
        lim = lim or limits()
        if int(data.get('fired_total', 0)) >= int(lim['max_per_session']):
            return False, 'max_per_session'
        ep = (data.get('episodes') or {}).get(episode_id or '_') or {}
        if int(ep.get('fired', 0)) >= int(lim['max_per_episode']):
            return False, 'max_per_episode'
        last = float(data.get('last_fired_at', 0) or 0)
        if last and (now - last) < float(lim['min_seconds_between']):
            return False, 'cooldown'
        return True, ''
    except Exception:
        return False, 'internal_error'      # fail closed: doubt means silence


def prune(ttl_days=None):
    try:
        ttl = float(ttl_days if ttl_days is not None else limits()['state_ttl_days'])
        cutoff = time.time() - ttl * 86400.0
        for fn in os.listdir(STATE_DIR):
            path = os.path.join(STATE_DIR, fn)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except Exception:
                continue
    except Exception:
        pass
