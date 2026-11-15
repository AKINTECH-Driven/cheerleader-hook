"""Build the installable `cheerleader` skill folder from this repo.

The export is GENERATED, never hand-maintained: the repo stays the single source of
truth, so the shipped skill cannot quietly drift from the tested one.

Two shapes:
  (default)         src, rulebook and hooks, plus SKILL.md, README.md, LICENSE, NOTICE, install.py and
                    uninstall.py. Smallest thing that runs. There is no --lean flag: it is the default.
  --with-tests      also ships tests/ and tools/, so the installed copy stays
                    verifiable and re-tunable in place.

Either way the build verifies before it ships: the full suite runs inside a staging
copy, and the final artefact is then smoke-tested as a real process. A hard file-count
cap guards against exceeding an uploader's limit silently.

Usage: /usr/bin/python3 tools/export_skill.py [--out DIR] [--zip] [--with-tests] [--max-files N]
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = 'cheerleader'
DEFAULT_MAX_FILES = 200

CODE_DIRS = ['src', 'rulebook', 'hooks']
DEV_DIRS = ['tests', 'tools']
FILES = ['SKILL.md', 'README.md', 'LICENSE', 'NOTICE', 'install.py', 'uninstall.py']
PRUNE = {'__pycache__', '.git', '.pytest_cache', 'snapshots', 'dist', '.DS_Store'}


def _copy(src, dst):
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*PRUNE))


def _stage(dest, dirs):
    os.makedirs(dest)
    for d in dirs:
        src = os.path.join(ROOT, d)
        if os.path.isdir(src):
            _copy(src, os.path.join(dest, d))
    for f in FILES:
        src = os.path.join(ROOT, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dest, f))
    return dest


def count_files(path):
    n = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in PRUNE]
        n += len([f for f in filenames if f not in PRUNE])
    return n


def run_suite(staging):
    proc = subprocess.run(
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-t', 'tests'],
        cwd=staging, capture_output=True, text=True)
    tail = [l for l in (proc.stderr or '').strip().splitlines() if l.startswith('Ran ')]
    return proc.returncode == 0, (tail[0] if tail else 'no test output')


def smoke(target):
    """Prove the SHIPPED artefact works as a process, with no tests dir to lean on."""
    fixture = os.path.join(ROOT, 'tests', 'fixtures', 'stuck_repeat_error.jsonl')
    tmp = tempfile.mkdtemp(prefix='cheerleader-smoke-')
    try:
        local = os.path.join(tmp, 'transcript.jsonl')
        shutil.copy2(fixture, local)
        hook = os.path.join(target, 'hooks', 'cheerleader_hook.py')
        payload = json.dumps({'hook_event_name': 'PostToolBatch',
                              'session_id': 'export-smoke-%d' % os.getpid(),
                              'transcript_path': local})
        proc = subprocess.run([sys.executable, hook], input=payload,
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return False, 'hook exited %d' % proc.returncode
        out = json.loads(proc.stdout or '{}')
        ctx = (out.get('hookSpecificOutput') or {}).get('additionalContext', '')
        if 'Smallest next move' not in ctx:
            return False, 'shipped hook produced no intervention'
        return True, 'live hook emitted a %d-char intervention' % len(ctx)
    except Exception as exc:
        return False, repr(exc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        st = os.path.expanduser('~/.claude/cheerleader/state')
        for fn in os.listdir(st) if os.path.isdir(st) else []:
            if fn.startswith('export-smoke-'):
                try:
                    os.remove(os.path.join(st, fn))
                except OSError:
                    pass


def make_zip(target, max_files):
    path = target + '.zip'
    if os.path.exists(path):
        os.remove(path)
    n = 0
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in PRUNE]
            for fn in filenames:
                if fn in PRUNE:
                    continue
                full = os.path.join(dirpath, fn)
                z.write(full, os.path.join(NAME, os.path.relpath(full, target)))
                n += 1
    return path, n


def main(argv):
    out = os.path.join(ROOT, 'dist')
    if '--out' in argv:
        out = os.path.expanduser(argv[argv.index('--out') + 1])
    max_files = DEFAULT_MAX_FILES
    if '--max-files' in argv:
        max_files = int(argv[argv.index('--max-files') + 1])
    with_tests = '--with-tests' in argv
    os.makedirs(out, exist_ok=True)

    # 1. Stage the FULL tree and run the suite inside it.
    staging = _stage(os.path.join(tempfile.mkdtemp(prefix='cheerleader-stage-'), NAME),
                     CODE_DIRS + DEV_DIRS)
    ok, verdict = run_suite(staging)
    print('verify   : %s — %s' % ('OK' if ok else 'FAILED', verdict))
    if not ok:
        print('\nEXPORT ABORTED — refusing to ship a skill whose tests do not pass.')
        return 1

    # 2. Build the actual artefact.
    target = os.path.join(out, NAME)
    if os.path.exists(target):
        shutil.rmtree(target)
    _stage(target, CODE_DIRS + (DEV_DIRS if with_tests else []))
    shutil.rmtree(os.path.dirname(staging), ignore_errors=True)

    # 3. Smoke-test what actually ships.
    sok, smsg = smoke(target)
    print('smoke    : %s — %s' % ('OK' if sok else 'FAILED', smsg))
    if not sok:
        print('\nEXPORT ABORTED — the shipped artefact does not run.')
        return 1

    n = count_files(target)
    print('shape    : %s' % ('with tests + tools' if with_tests else 'lean (code, rulebook, hooks, top-level docs and installers)'))
    print('exported : %s' % target)
    print('files    : %d  (cap %d)' % (n, max_files))
    if n > max_files:
        print('\nEXPORT ABORTED — %d files exceeds the %d-file cap.' % (n, max_files))
        return 1

    if '--zip' in argv:
        path, zn = make_zip(target, max_files)
        print('zip      : %s  (%d entries, %.0f KB)'
              % (path, zn, os.path.getsize(path) / 1024.0))

    print('\nAdd it with:\n  mkdir -p ~/.claude/skills && cp -R %s ~/.claude/skills/' % target)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
