"""What real test runners print, and what a verdict looks like. Shared by the suites.

A red test run is exactly when HORME should speak; a verdict being decided is exactly
when it must not. The difference has to survive the runners people actually use.

The unittest samples are captured output (Python 3.9 and 3.12, plain and -v, with a
docstring and a subtest in the failing set), stored under fixtures/runners with only
the paths and the timing normalised. The jest, vitest and go test samples are written
from those runners' documented line formats; none of them was run to produce these.
"""
import os

_RUNNERS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'runners')


def _captured(name):
    with open(os.path.join(_RUNNERS, name), encoding='utf-8') as fh:
        return fh.read()


UNITTEST_RED = _captured('unittest_py39_plain.txt')
UNITTEST_RED_PY312 = _captured('unittest_py312_plain.txt')
UNITTEST_VERBOSE_RED = _captured('unittest_py39_verbose.txt')
UNITTEST_VERBOSE_RED_PY312 = _captured('unittest_py312_verbose.txt')
# -v where a subTest line runs into the next test's line, and a subTest with a message
UNITTEST_VERBOSE_GLUED = _captured('unittest_py39_verbose_glued.txt')
UNITTEST_VERBOSE_GLUED_PY312 = _captured('unittest_py312_verbose_glued.txt')

# --- jest and vitest: FAIL or PASS, then the test file ---
JEST_RED = (
    ' FAIL  src/importer.test.js\n'
    '  ● merge › expands the span\n'
    '\n'
    '    expect(received).toBe(expected)\n'
    '\n'
    '    Expected: 4\n'
    '    Received: 1\n'
    '\n'
    'Tests:       1 failed, 3 passed, 4 total'
)
JEST_RED_TIMED = (
    ' FAIL  src/__tests__/importer.js (5.123 s)\n'
    '  ● merge › expands the span\n'
    '\n'
    'Tests:       1 failed, 3 passed, 4 total'
)
JEST_GREEN = (
    ' PASS  src/importer.test.js\n'
    'Tests:       4 passed, 4 total'
)
VITEST_RED = (
    ' FAIL  src/importer.test.ts > merge > expands the span\n'
    'AssertionError: expected 1 to be 4\n'
    ' Test Files  1 failed (1)\n'
    '      Tests  1 failed | 3 passed (4)'
)

# --- go test: per-test lines, a bare FAIL or PASS, then the package line ---
GO_RED = (
    '--- FAIL: TestMerge (0.00s)\n'
    '    importer_test.go:42: got 1 cells, want 4\n'
    'FAIL\n'
    'exit status 1\n'
    'FAIL\tgithub.com/acme/sheets/importer\t0.012s'
)
GO_RED_TWO_PACKAGES = (
    'ok  \tgithub.com/acme/sheets/cells\t0.009s\n'
    '--- FAIL: TestMerge (0.00s)\n'
    '    importer_test.go:42: got 1 cells, want 4\n'
    'FAIL\n'
    'FAIL\tgithub.com/acme/sheets/importer\t0.012s\n'
    'FAIL'
)
GO_GREEN = (
    'PASS\n'
    'ok  \tgithub.com/acme/sheets/importer\t0.011s'
)
GO_VERBOSE_GREEN = (
    '=== RUN   TestMerge\n'
    '--- PASS: TestMerge (0.00s)\n'
    'PASS\n'
    'ok  \tgithub.com/acme/sheets/importer\t0.010s\tcoverage: 85.0% of statements'
)

JEST_RED_SPEC = ' FAIL  src/importer.spec.ts\n  ● merge › expands the span\n\nTests:       1 failed, 3 passed, 4 total'
JEST_RED_MJS = ' FAIL  src/importer.test.mjs\n  ● merge › expands the span\n\nTests:       1 failed, 3 passed, 4 total'
JEST_RED_FOLDER = ' FAIL  src/__tests__/importer.cjs\n  ● merge › expands the span\n\nTests:       1 failed, 3 passed, 4 total'

RED_RUNS = {
    'unittest (3.9)': UNITTEST_RED,
    'unittest (3.12)': UNITTEST_RED_PY312,
    'unittest -v (3.9)': UNITTEST_VERBOSE_RED,
    'unittest -v (3.12)': UNITTEST_VERBOSE_RED_PY312,
    'unittest -v, subtest then docstring (3.9)': UNITTEST_VERBOSE_GLUED,
    'unittest -v, subtest then docstring (3.12)': UNITTEST_VERBOSE_GLUED_PY312,
    'jest': JEST_RED,
    'jest with a timing': JEST_RED_TIMED,
    'jest, a spec file in TypeScript': JEST_RED_SPEC,
    'jest, an ES module test file': JEST_RED_MJS,
    'jest, a CommonJS file under __tests__': JEST_RED_FOLDER,
    'vitest': VITEST_RED,
    'go test': GO_RED,
    'go test, two packages': GO_RED_TWO_PACKAGES,
}
GREEN_RUNS = {
    'jest': JEST_GREEN,
    'go test': GO_GREEN,
    'go test -v': GO_VERBOSE_GREEN,
}

_RULE = '=' * 70
_DASH = '-' * 70

# --- verdicts: every one of these must still silence HORME ---
VERDICTS = (
    'VERIFIER VERDICT: FAIL',
    'VERDICT: PASS',
    'review result: PASS',
    'gate: FAIL',
    'Overall: FAIL (2 critical findings)',
    'FAIL',
    'PASS',
    'FAIL: 3 critical findings in the budget table',
    'code-review requested on the diff',
    'signed off by the reviewer',
    # shaped like a runner line, but not one: each exemption is only as wide as the format
    'FAIL app.js',
    'FAIL src/a.js: 3 violations',
    'FAIL README.js docs',
    'FAIL a.js.bak',
    'FAIL a.json',
    'FAIL src/a.test.js FAIL',
    'FAIL src/a.test.js: 3 violations',
    'FAIL src/a.test.js 3 violations found',
    ' FAIL  src/a.test.ts > the gate says FAIL',
    'FAIL budget table',
    'FAIL release gate',
    'FAIL\texample.com/p\t0.003s FAIL',
    _RULE + '\nFAIL: gate rejected',
    _RULE + '\nFAIL: gate rejected\n' + _DASH,
    '=' * 30 + '\nFAIL: 3 findings',
    '=' * 30 + '\nFAIL: test_merge (gates.Budget)\n' + _DASH,
    _RULE + '\nFAIL: test_merge (gates.Budget)\nno rule of dashes follows',
    'check complete ... FAIL',
    'schema (v2) ... FAIL',
    'lint (strict) ... FAIL',
    'check_budget (gates.Budget) ... FAIL',
    'gate (v2.1)\nBudget gate ... FAIL',
    'test_x (pkg.Class)\nreview result PASS ... FAIL',
    _RULE + '\nFAIL: gate (budget)\n' + _DASH,
    _RULE + '\nFAIL: test_x (pkg.Class) [do not merge: FAIL]\n' + _DASH,
    _RULE + '\nFAIL: test_x (pkg.Class) (PASS)\n' + _DASH,
    'FAIL budget 0.5s',
    'FAIL budget [blocked]',
    'FAIL\tchecks [blocked]',
    'FAIL gate [setup failed]',
    'FAIL tests/budget.test.js',
    'FAIL docs/call.spec.ts',
    ' FAIL  budget.test.js > the draft was blocked',
    ' FAIL  src/a.test.ts > the gate says FAIL\n Test Files  1 failed (1)',
    # with the runner's summary present, the line itself still has to be a runner line
    'FAIL app.js\nTests:       1 failed, 1 total',
    'FAIL src/a.test.js 3 violations found\nTests:       1 failed, 1 total',
    # the width of each exemption, pinned from both sides
    ' FAIL  src/budget.test.js\nTests:       3 violations',
    ' FAIL  src/a.test.js.bak\nTests:       1 failed, 1 total',
    'FAIL\tsrc/budget.test.js\nTests:       1 failed, 1 total',
    ' FAIL  src/a.test.ts >gate\n Test Files  1 failed (1)',
    ' FAIL  __tests__/.js\nTests:       1 failed, 1 total',
    ' FAIL  src/__tests__x/a.js\nTests:       1 failed, 1 total',
    ' FAIL  .test.js\nTests:       1 failed, 1 total',
    ' FAIL  src/__tests__/a.js.bak\nTests:       1 failed, 1 total',
    ' FAIL  __tests__/a.json\nTests:       1 failed, 1 total',
    ' FAIL  src/__tests__/data.json\nTests:       1 failed, 1 total',
    ' FAIL  src/a.test.json\nTests:       1 failed, 1 total',
    ' FAIL  src/x__tests__/a.js\nTests:       1 failed, 1 total',
    ' FAIL  src/a.test.py\nTests:       1 failed, 1 total',
    'PASS\nFAIL\tgithub.com/acme/p\t0.1s',
    'PASS\nexit status 0\nok  \tgithub.com/acme/p\t0.1s',
    '--- FAIL: release-gate (0.1s)',
    _RULE + '\nFAIL: test_x (pkg.Class)\n' + '-' * 20,
    _RULE + '\nFAIL: test_x (pkg.Class) [first] [second]\n' + _DASH,
    # a verdict word inside a runner line is still a verdict word
    '--- FAIL: TestGate/VERIFIER (0.00s)',
    ' FAIL  src/a.test.js > code-review failed\nTests:       1 failed, 1 total',
    _RULE + '\nFAIL: test_x (pkg.Class) [VERDICT pending]\n' + _DASH,
    'test_x (pkg.Class) [signed off] ... FAIL',
    'test_x (pkg.Class) [the gate says PASS] ... FAIL',
    # a bare verdict next to go test output is go test's only where go test puts it
    'ok  \tgithub.com/acme/p\t0.1s\n\nreview complete\nFAIL\n',
    '=== RUN   TestX\n--- PASS: TestX (0.00s)\nPASS\nok  \tgithub.com/acme/p\t0.1s\ngate result\nFAIL',
    'PASS\nok  \tgithub.com/acme/p\t0.1s\nFAIL',
)

# --- known limits: runner output that is still read as a verdict. HORME stays quiet on
# these, which is the safe direction. Listed so that changing any of them is a decision.
STILL_QUIET = (
    ' FAIL  browser  src/a.test.js',              # jest with a project display name
    'FAIL tests/my test.test.js',                 # a path with a space
    ' FAIL  |unit| src/a.test.ts > x',            # vitest with a project label
    '--- FAIL: BenchmarkMerge-8',                 # go benchmark, no timing
    'Result: FAIL',                               # perl prove
    '# FAIL 1',                                   # TAP, upper case
    'test_a (pkg.mod.T) ... warning text\nFAIL',   # unittest -v when the test prints something
)

# --- the other side of the trade: output that a gate could print in exactly a
# runner's own format. Nothing in the text separates the two, so these are let through.
# Listed so that the trade is visible and a change to it is a decision.
INDISTINGUISHABLE = (
    'FAIL\tchecks\t0.2s',                                              # go test's package line
    ' FAIL  src/budget.test.js\nTests:       1 failed, 1 total',        # jest, with its summary
    _RULE + '\nFAIL: test_budget (gates.Budget)\n' + _DASH,             # unittest's failure header
    'test_budget (gates.Budget)\nRelease gate ... FAIL',                 # unittest -v with a docstring
    # jest prints its summary last, however long the run: a summary anywhere in the same
    # result vouches for a file line, at any distance
    ' FAIL  src/budget.test.js\nbudget gate rejects the draft\n' + 'built target 00001 in 0.02 s\n' * 400
    + 'Tests:       3 passed, 3 total',
)


def filler(chars):
    """Ordinary build output of exactly `chars` characters: no verdict word, no
    environment error, nothing a signal reads. Every line is whole except the last."""
    lines = chars // len('built target 00000 in 0.02 s\n') + 1     # no line is shorter than that
    return ''.join('built target %05d in 0.02 s\n' % i for i in range(lines))[:chars]


def calls(*results):
    """Transcript rows for one Bash call per entry of `results`, oldest first. An entry
    is the tool output, or (output, is_error); is_error None leaves the field out, as
    Claude Code does for a call that succeeded."""
    rows = []
    for i, entry in enumerate(results):
        output, is_error = entry if isinstance(entry, tuple) else (entry, True)
        rows.append({'type': 'assistant', 'isSidechain': False, 'timestamp': '2026-08-26T10:00:00Z',
                     'message': {'role': 'assistant', 'content': [
                         {'type': 'tool_use', 'id': 'call%d' % i, 'name': 'Bash',
                          'input': {'command': 'step %d' % i}}]}})
        block = {'type': 'tool_result', 'tool_use_id': 'call%d' % i, 'content': output}
        if is_error is not None:
            block['is_error'] = is_error
        rows.append({'type': 'user', 'isSidechain': False, 'timestamp': '2026-08-26T10:00:01Z',
                     'message': {'role': 'user', 'content': [block]}})
    return rows


def stuck_on(output, repeats=7):
    """Transcript rows for a session that keeps editing one file and hitting `output`."""
    rows = []

    def call(tid, name, inp, result, is_error):
        rows.append({'type': 'assistant', 'isSidechain': False,
                     'timestamp': '2026-08-26T10:00:00Z',
                     'message': {'role': 'assistant', 'content': [
                         {'type': 'tool_use', 'id': tid, 'name': name, 'input': inp}]}})
        block = {'type': 'tool_result', 'tool_use_id': tid, 'content': result}
        if is_error:
            block['is_error'] = True
        rows.append({'type': 'user', 'isSidechain': False,
                     'timestamp': '2026-08-26T10:00:01Z',
                     'message': {'role': 'user', 'content': [block]}})

    for i in range(repeats):
        call('edit%d' % i, 'Edit', {'file_path': '/tmp/proj/src/importer.py'}, 'ok', False)
        call('run%d' % i, 'Bash', {'command': 'run the tests'}, output, True)
    return rows
