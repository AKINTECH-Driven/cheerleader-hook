"""Per-session firing state: what HORME has already said, and when.

Lives outside the project, under ~/.claude/cheerleader/state/. Every function here is
best-effort: a hook that cannot read its own state must still exit 0 and stay quiet,
never crash the session it is supposed to be helping.
"""
import json
import os
import re
import time

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
    """Atomic where possible; silent where not."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        target = _path(session_id)
        tmp = target + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh)
        os.replace(tmp, target)
    except Exception:
        try:
            if os.path.exists(target + '.tmp'):
                os.remove(target + '.tmp')
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
