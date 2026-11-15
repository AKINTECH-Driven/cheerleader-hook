"""Generate HORME test fixtures in the *verified* Claude Code transcript schema.

Regenerate with: /usr/bin/python3 tools/make_fixtures.py
Fixtures are committed; this script exists so they stay schema-faithful, not so they float.
"""
import json, os, itertools

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tests', 'fixtures')
_ids = itertools.count(1)
SESSION = 'fixture-session-0001'


def _base(kind, ts, **kw):
    d = {
        'type': kind, 'sessionId': SESSION, 'uuid': 'u%04d' % next(_ids),
        'timestamp': '2026-08-26T10:%02d:%02dZ' % (ts // 60, ts % 60),
        'isSidechain': False, 'cwd': '/tmp/proj', 'version': '2.0.0',
        'gitBranch': 'main', 'userType': 'external', 'entrypoint': 'cli',
    }
    d.update(kw)
    return d


def say(ts, text, thinking=False):
    key = 'thinking' if thinking else 'text'
    return _base('assistant', ts, requestId='req%04d' % next(_ids), message={
        'role': 'assistant', 'model': 'claude-opus-5', 'type': 'message',
        'content': [{'type': key, key: text}],
    })


def tool_use(ts, tuid, name, inp):
    return _base('assistant', ts, requestId='req%04d' % next(_ids), message={
        'role': 'assistant', 'model': 'claude-opus-5', 'type': 'message',
        'content': [{'type': 'tool_use', 'id': tuid, 'name': name, 'input': inp}],
    })


def tool_result(ts, tuid, content, is_error=False, tur=None):
    blk = {'type': 'tool_result', 'tool_use_id': tuid, 'content': content}
    if is_error:
        blk['is_error'] = True
    d = _base('user', ts, message={'role': 'user', 'content': [blk]})
    if tur is not None:
        d['toolUseResult'] = tur
    return d


def human(ts, text):
    return _base('user', ts, promptId='p%04d' % next(_ids),
                 message={'role': 'user', 'content': text})


def stop_hook(ts, contexts):
    return _base('system', ts, subtype='stop_hook_summary', hookCount=1,
                 hookInfos=[{'command': 'horme'}], hookErrors=[],
                 hookAdditionalContext=contexts, preventedContinuation=False,
                 stopReason='', hasOutput=bool(contexts), level='suggestion',
                 toolUseID='t%04d' % next(_ids))


def write(name, rows):
    path = os.path.join(OUT, name)
    with open(path, 'w', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    return path, len(rows)


def call(rows, ts, name, inp, out, is_error=False, tur=None):
    tuid = 'toolu_%04d' % next(_ids)
    rows.append(tool_use(ts, tuid, name, inp))
    rows.append(tool_result(ts + 1, tuid, out, is_error, tur))


# ---------------------------------------------------------------- clean control
def clean_control():
    r = [human(0, 'Add a slug helper and test it.')]
    t = 2
    call(r, t, 'Read', {'file_path': '/tmp/proj/src/util.py'}, 'def x(): pass', tur={'file': {'filePath': '/tmp/proj/src/util.py'}})
    t += 4
    r.append(say(t, 'Straightforward. I will add the helper and a test.'))
    t += 2
    call(r, t, 'Write', {'file_path': '/tmp/proj/tests/test_slug.py'}, 'ok', tur={'filePath': '/tmp/proj/tests/test_slug.py'})
    t += 4
    call(r, t, 'Bash', {'command': 'python3 -m unittest discover -s tests'},
         'Ran 1 test in 0.001s\n\nFAILED (errors=1)\nNameError: slugify', is_error=True,
         tur={'stdout': '', 'stderr': 'NameError', 'interrupted': False})
    t += 4
    call(r, t, 'Edit', {'file_path': '/tmp/proj/src/util.py', 'old_string': 'def x', 'new_string': 'def slugify'},
         'ok', tur={'filePath': '/tmp/proj/src/util.py', 'oldString': 'def x', 'newString': 'def slugify'})
    t += 4
    call(r, t, 'Bash', {'command': 'python3 -m unittest discover -s tests'},
         'Ran 1 test in 0.001s\n\nOK', tur={'stdout': 'OK', 'stderr': '', 'interrupted': False})
    t += 4
    r.append(say(t, 'Green. The helper is in and the suite passes.'))
    for i in range(6):
        t += 3
        call(r, t, 'Read', {'file_path': '/tmp/proj/src/mod%d.py' % i}, 'contents', tur={'file': {}})
    return r


# ------------------------------------------------------- stuck: repeated error
def stuck_repeat_error():
    r = [human(0, 'Make the importer handle merged cells.')]
    t = 2
    for i in range(6):
        call(r, t, 'Edit',
             {'file_path': '/tmp/proj/src/importer.py', 'old_string': 'v%d' % i, 'new_string': 'v%d' % (i + 1)},
             'ok', tur={'filePath': '/tmp/proj/src/importer.py'})
        t += 3
        call(r, t, 'Bash', {'command': 'python3 -m unittest tests.test_importer'},
             'Ran 3 tests in 0.02s\n\nFAILED (failures=1)\n'
             'AssertionError: expected 4 cells, got 1\n  File "/tmp/proj/src/importer.py", line 88',
             is_error=True,
             tur={'stdout': '', 'stderr': 'AssertionError: expected 4 cells, got 1', 'interrupted': False})
        t += 3
        if i >= 3:
            r.append(say(t, "That didn't work either. I'm not sure why the merge span is collapsing.", thinking=True))
            t += 2
    r.append(say(t, 'Let me try a completely different approach to the span expansion.'))
    return r


# --------------------------------------------------- verdict-adjacent (suppress)
def verdict_adjacent():
    r = stuck_repeat_error()
    t = 200
    call(r, t, 'Bash', {'command': 'python3 -m unittest discover -s tests -v'},
         'Ran 41 tests in 0.31s\n\nFAILED (failures=1)\n\nVERIFIER VERDICT: FAIL', is_error=True,
         tur={'stdout': '', 'stderr': 'FAILED (failures=1)', 'interrupted': False})
    return r


# ------------------------------------------------------------------ infeasible
def infeasible():
    r = [human(0, 'Run the pipeline in Docker and render the PDF with pandoc.')]
    t = 2
    for i in range(5):
        call(r, t, 'Bash', {'command': 'docker run --rm pipeline:latest'},
             'Exit code 127\nzsh: command not found: docker', is_error=True,
             tur={'stdout': '', 'stderr': 'command not found: docker', 'interrupted': False})
        t += 3
        call(r, t, 'Bash', {'command': 'pandoc in.md -o out.pdf'},
             'Exit code 127\nzsh: command not found: pandoc', is_error=True,
             tur={'stdout': '', 'stderr': 'command not found: pandoc', 'interrupted': False})
        t += 3
    r.append(say(t, 'Neither docker nor pandoc is installed on this machine and I cannot install them.'))
    return r


# ------------------------------------------------------------ already-fired
def already_fired():
    r = stuck_repeat_error()
    r.append(stop_hook(300, ['[CHEERLEADER] This step is genuinely hard. Smallest next move: ...']))
    return r


# ------------------------------------------------- sidechain (subagent) noise
def with_sidechain():
    """A calm main thread while a subagent fails loudly.

    Subagent lines carry isSidechain: true. They must NOT leak into the main scope,
    or every Explore/Task call would look like the parent session flailing.
    """
    r = clean_control()
    t = 400
    for i in range(8):
        tuid = 'toolu_sc%02d' % i
        r.append(_base('assistant', t, isSidechain=True, requestId='rq%02d' % i, message={
            'role': 'assistant', 'model': 'claude-opus-5', 'type': 'message',
            'content': [{'type': 'tool_use', 'id': tuid, 'name': 'Bash',
                         'input': {'command': 'python3 -m unittest tests.test_sub'}}]}))
        r.append(_base('user', t + 1, isSidechain=True, message={'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': tuid, 'is_error': True,
             'content': 'Ran 2 tests\n\nFAILED (errors=2)\nZeroDivisionError: division by zero'}]}))
        r.append(_base('assistant', t + 2, isSidechain=True, requestId='rqs%02d' % i, message={
            'role': 'assistant', 'model': 'claude-opus-5', 'type': 'message',
            'content': [{'type': 'text', 'text': "I'm not sure why this keeps failing."}]}))
        t += 4
    return r


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    for name, fn in [
        ('clean_control.jsonl', clean_control),
        ('stuck_repeat_error.jsonl', stuck_repeat_error),
        ('verdict_adjacent.jsonl', verdict_adjacent),
        ('infeasible.jsonl', infeasible),
        ('already_fired.jsonl', already_fired),
        ('with_sidechain.jsonl', with_sidechain),
    ]:
        p, n = write(name, fn())
        print('%-28s %3d lines' % (name, n))

    # deliberate defects — a validator that never fails is untested
    good = os.path.join(OUT, 'stuck_repeat_error.jsonl')
    with open(good, encoding='utf-8') as fh:
        lines = fh.readlines()
    with open(os.path.join(OUT, 'truncated.jsonl'), 'w', encoding='utf-8') as fh:
        fh.writelines(lines[:-1])
        fh.write(lines[-1][:len(lines[-1]) // 2])          # cut mid-JSON, no newline
    print('%-28s %3d lines (final line cut mid-JSON)' % ('truncated.jsonl', len(lines)))
    with open(os.path.join(OUT, 'garbage.jsonl'), 'w', encoding='utf-8') as fh:
        fh.write('not json at all\n\n{{{\n\x00\x01binary\n[1,2,3]\n')
    print('%-28s   5 lines (pure garbage)' % 'garbage.jsonl')
    with open(os.path.join(OUT, 'empty.jsonl'), 'w', encoding='utf-8') as fh:
        pass
    print('%-28s   0 lines (empty)' % 'empty.jsonl')


if __name__ == '__main__':
    main()
