"""Windowed, deterministic extraction of stuck-shaped structure from a transcript.

Every count here is WINDOWED. Calibration over 438 real sessions showed whole-session
counts are worthless as evidence of thrash (the same file is edited a median of 12
times per healthy session), while windowed counts separate cleanly. No model judgment
enters this module; it only measures.
"""
import re
from bisect import bisect_left, bisect_right
from collections import Counter, namedtuple

from . import brand

DEFAULT_WINDOW = 40          # tool calls
SAMPLE_CHARS = 400
VERDICT_TAIL = 3             # how many trailing tool results the adjudication scan sees
SIG_CHARS = 120

_HEX = re.compile(r'\b[0-9a-f]{6,}\b', re.I)
_NUM = re.compile(r'\d+')
_PATH = re.compile(r'(/[^\s:,\'"]+)+')
_WS = re.compile(r'\s+')

#: Capitulation / self-report markers. Rare by design: measured at 0.3% of say-blocks
#: across the real corpus, so these boost an existing signal rather than trigger alone.
CAPITULATION = [re.compile(p, re.I) for p in (
    r"\bi(?:'m| am) (?:really |completely )?(?:not sure|unsure|stuck|confused|lost)\b",
    r"\bi (?:don'?t|do not) (?:know|understand) why\b",
    r"\blet me try (?:a |an )?(?:completely |entirely |totally )?different\b",
    r"\b(?:that|this) (?:didn'?t|did not) work\b",
    r"\bstill (?:failing|fails|broken|not working)\b",
    r"\bi apolog(?:ise|ize)\b",
    r"\bi keep (?:getting|hitting|running into)\b",
    r"\bnot sure (?:what|why|how)\b",
    r"\bgiv(?:e|ing) up\b",
)]

#: ADJUDICATION, not failure. A red test suite is exactly when encouragement helps;
#: an explicit verdict is when it could corrupt the verdict. Only the latter suppresses.
#: `\bFAIL\b` does not match "FAILED", which keeps a unittest *summary* out. It does
#: match the result lines that unittest, jest, vitest and go test print for each
#: failure, so a standalone PASS or FAIL on such a line does not count
#: (see `_verdict_outside_runner_lines`). Every other pattern sees the whole text.
STANDALONE_VERDICT = r'(?<![A-Za-z])(?:PASS|FAIL)(?![A-Za-z])'


class _GateName(object):
    """A lower-case name that ends in -guard: budget-guard, release-2-guard. A tool
    named like that is a gate, and what a gate prints is a verdict being decided.

    The rule is `pattern`, and `search` finds a name wherever that pattern would and
    nowhere else. What it hands back is a match on the `-guard` that ends the name,
    not on the whole name: callers ask only whether there is one. It is
    not run as a pattern because, searched, it starts again at every word of a long
    hyphenated token and reads to the end each time: 0.6 s on 16,000 characters, and
    the verdict check reads up to 60,000. So the name is found from its end: every
    `-guard` that ends a word, then back through the parts of the name before it.
    """
    pattern = r'\b[a-z][a-z0-9]*(?:-[a-z0-9]+)*-guard\b'
    _part_end = re.compile(r'[a-z0-9](?=-guard\b)')       # a look-ahead: `x-guard-guard` holds two
    _suffix = re.compile(r'-guard\b')
    _word = re.compile(r'\w')
    _part = frozenset('abcdefghijklmnopqrstuvwxyz0123456789')

    def search(self, text):
        for found in self._part_end.finditer(text):
            end = found.start()                          # last character of the part before -guard
            while True:
                start = end
                while start > 0 and text[start - 1] in self._part:
                    start -= 1
                before = text[start - 1] if start else ''
                if before and self._word.match(before):
                    break                                # no word boundary in front: not a name
                if 'a' <= text[start] <= 'z':
                    return self._suffix.match(text, found.end())
                # the part begins with a digit: the name can only begin further left
                if before != '-' or start < 2 or text[start - 2] not in self._part:
                    break
                end = start - 2
        return None


ADJUDICATION = [re.compile(p) for p in (
    r'\bVERDICT\b',
    r'\bVERIFIER\b',
    STANDALONE_VERDICT,
)] + [_GateName()] + [re.compile(p) for p in (
    r'\bcode-review\b',
    r'\bsign(?:ed)?[ -]off\b',
)]
_STANDALONE = re.compile(STANDALONE_VERDICT)
_VERDICT_WORDS = [p for p in ADJUDICATION if p.pattern != STANDALONE_VERDICT]

#: What a test runner prints for a result. Each pattern is as narrow as the runner's
#: own format and anchored at both ends, because the same words are how a gate
#: reports: `FAIL: 3 findings`, `FAIL app.js`, `lint (strict) ... FAIL` and a bare
#: `FAIL` are verdicts unless the line, and where it takes that its neighbours, prove
#: a runner wrote it. The unittest shapes were checked against real output (Python 3.9
#: and 3.12); the jest, vitest and go shapes follow their documented formats.
_IDENT = r'[A-Za-z_]\w*'
_UNITTEST_ID = r'test\w* \(' + _IDENT + r'(?:\.' + _IDENT + r')+\)'   # test_x (pkg.mod.Class)
_UNITTEST_SUB = r'(?: \[[^\]]*\])?(?: \([^()]*\))?'                    # subTest: [msg] (i=2)
_UNITTEST_RULE = re.compile(r'^={70}$')          # unittest prints exactly seventy
_UNITTEST_DASH = re.compile(r'^-{70}$')
_UNITTEST_HEAD = re.compile(r'^FAIL: (' + _UNITTEST_ID + _UNITTEST_SUB + r')$')
_UNITTEST_ID_AT_END = re.compile(r'(?:^|\.\.\. )' + _UNITTEST_ID + r'$')
_UNITTEST_VERBOSE = re.compile(r'^\s*((?:' + _UNITTEST_ID + _UNITTEST_SUB + r' \.\.\. )+)FAIL$')
_UNITTEST_DOC_RESULT = re.compile(r'^(.+) \.\.\. FAIL$')
_JS_LINE = re.compile(r'^ ?(?:PASS|FAIL) {1,2}(\S+)(.*)$')                   # jest, vitest
_JS_SPEC_NAME = re.compile(r'[^/\s]\.(?:test|spec)\.[cm]?[jt]sx?$')         # importer.test.js, a.spec.ts
_JS_TESTS_DIR = re.compile(r'(?:^|/)__tests__/')                            # or a script under __tests__/
_JS_SCRIPT = re.compile(r'\.[cm]?[jt]sx?$')
_JS_TAIL = re.compile(r'^(?:\s+\(\d+(?:\.\d+)?\s?m?s\))?$|^\s+>\s')   # a timing, or vitest's trail
_JS_SUMMARY = re.compile(r'^\s*(?:Tests|Test Suites|Test Files):?\s+\d+ (?:failed|passed|skipped|todo)\b')
_GO_TEST_LINE = re.compile(                       # go test functions start with one of four words
    r'^\s*--- (?:PASS|FAIL|SKIP): (?:Test|Example|Benchmark|Fuzz)\S* \(\d+(?:\.\d+)?s\)$')
_GO_PACKAGE_LINE = re.compile(                    # go separates the columns with tabs
    r'^(ok  |FAIL)\t[\w./@~-]+(?:\t(?:\d+(?:\.\d+)?s|\(cached\))(?:\tcoverage: [\d.]+% of statements)?'
    r'| \[(?:build failed|setup failed)\])$')
_GO_EXIT_LINE = re.compile(r'^exit status [1-9]\d*$')        # printed only after a failure
_BARE_VERDICT = re.compile(r'^(PASS|FAIL)$')

#: The environment is blocking, not the approach. The brief is explicit that
#: encouraging persistence on an unachievable goal is the wrong move.
ENV_BLOCKED = [re.compile(p, re.I) for p in (
    r'command not found',
    r'\bno such file or directory\b',
    r'\bnot installed\b',
    r'\bpermission denied\b',
    r'\bcannot find module\b',
    r'\bunsupported (?:platform|architecture)\b',
    r'\bno matching distribution\b',
    r'\brequires? (?:docker|homebrew|sudo|root)\b',
)]

EDIT_TOOLS = ('Edit', 'Write', 'NotebookEdit', 'MultiEdit')

_FIELDS = ('window tool_count error_count consecutive_tool_errors current_error_run '
           'calls_since_success '
           'repeated_error_count top_error_signature error_samples env_blocked_errors '
           'command_repeat top_command edit_thrash edit_thrash_file reread_thrash '
           'capitulation_hits say_count verdict_adjacent horme_recent')


class SignalSet(namedtuple('SignalSet', _FIELDS)):
    """Pure measurement. Interpretation belongs to the classifier, not here."""
    __slots__ = ()

    def as_dict(self):
        return dict(self._asdict())


EMPTY = SignalSet(
    window=0, tool_count=0, error_count=0, consecutive_tool_errors=0,
    current_error_run=0, calls_since_success=0, repeated_error_count=0, top_error_signature='',
    error_samples=(), env_blocked_errors=0, command_repeat=0, top_command='',
    edit_thrash=0, edit_thrash_file='', reread_thrash=0, capitulation_hits=0,
    say_count=0, verdict_adjacent=False, horme_recent=False,
)


def signature(text, keep=SIG_CHARS):
    """Collapse a failure to its shape: paths, hashes and numbers carry no identity.

    The same assertion at a different line number is the same failure; a different
    exception type is a different failure.
    """
    t = (text or '')[:800]
    t = _PATH.sub('/P', t)
    t = _HEX.sub('#H', t)
    t = _NUM.sub('#N', t)
    return _WS.sub(' ', t).strip().lower()[:keep]


def _window_slice(events, window):
    """Tail of `events` containing at most `window` tool_use events."""
    if window is None or window <= 0:
        return list(events)
    seen = 0
    for i in range(len(events) - 1, -1, -1):
        if events[i].kind == 'tool_use':
            seen += 1
            if seen > window:
                return list(events[i + 1:])
    return list(events)


def _any(patterns, text):
    return any(p.search(text) for p in patterns)


def _js_test_file(path):
    """Does `path` name a test file the way jest and vitest find them: `x.test.js`,
    `x.spec.ts`, or a script somewhere under a `__tests__/` folder?

    Three searches, each linear in the length of `path`. Written as one pattern
    (`[^/\\s]+\\.(?:test|spec)...`, searched) this was retried from every character
    of the token and took 16 seconds on one line of 59,000 characters."""
    if _JS_SPEC_NAME.search(path):
        return True
    folder, script = _JS_TESTS_DIR.search(path), _JS_SCRIPT.search(path)
    return bool(folder and script and script.start() > folder.end())


def _js_runner_line(line):
    """` FAIL  src/importer.test.js`: FAIL or PASS, a test file, and nothing after it
    but a timing or vitest's `> suite > test` trail. A script that is not a test file,
    or any further PASS or FAIL on the line, makes it somebody's verdict."""
    m = _JS_LINE.match(line)
    if not m:
        return False
    path, rest = m.groups()
    return bool(_js_test_file(path) and _JS_TAIL.match(rest)
                and not _STANDALONE.search(rest))


def _neighbour(solid, i, step):
    """Index of the nearest non-blank line before (step -1) or after (step 1) line `i`.
    `solid` holds the indices of all non-blank lines, in order: found by bisection,
    because walking a long run of blank lines once per bare PASS or FAIL added up."""
    k = bisect_right(solid, i) if step > 0 else bisect_left(solid, i) - 1
    return solid[k] if 0 <= k < len(solid) else None


def _unittest_line(lines, i):
    """Is line `i` unittest reporting a failed test? Three shapes, all of which name
    the test as `test_x (package.module.Class)`; none may carry a second PASS or FAIL."""
    line = lines[i]
    m = _UNITTEST_HEAD.match(line)
    if m:
        # The header of a failure report: under the rule of '=', over the rule of '-'
        # (one line lower when the test has a docstring).
        return bool(i > 0 and _UNITTEST_RULE.match(lines[i - 1])
                    and any(_UNITTEST_DASH.match(l) for l in lines[i + 1:i + 3])
                    and not _STANDALONE.search(m.group(1)))
    m = _UNITTEST_VERBOSE.match(line)
    if m:                                            # -v: `test_x (pkg.Class) ... FAIL`
        return not _STANDALONE.search(m.group(1))
    # -v with a docstring: the id ends the line above, `<docstring> ... FAIL` follows.
    m = _UNITTEST_DOC_RESULT.match(line)
    return bool(m and i > 0 and _UNITTEST_ID_AT_END.search(lines[i - 1])
                and not _STANDALONE.search(m.group(1)))


def _go_bare_line(lines, solid, i, a_package_failed):
    """go test prints a bare PASS or FAIL just above the package line it sums up, and
    one more bare FAIL at the very end when any package failed. Nowhere else."""
    below = _neighbour(solid, i, 1)
    if below is not None and _GO_EXIT_LINE.match(lines[below]):
        below = _neighbour(solid, below, 1)
    package = _GO_PACKAGE_LINE.match(lines[below]) if below is not None else None
    if lines[i] == 'PASS':
        return bool(package and package.group(1) != 'FAIL')
    if package:
        return package.group(1) == 'FAIL'
    above = _neighbour(solid, i, -1)
    return bool(a_package_failed and below is None and above is not None
                and _GO_PACKAGE_LINE.match(lines[above]))


def _verdict_outside_runner_lines(text):
    """Is there a standalone PASS or FAIL on a line that no test runner printed?

    A red run is when HORME should speak, so a runner's own FAIL must not read as a
    verdict. Only unmistakable runner lines are excused: unittest's failure headers and
    -v result lines, go test's per-test, per-package and summary lines, and a jest or
    vitest line naming a test file when the same output also carries that runner's
    summary (a line like `FAIL src/a.test.js` on its own is how a gate reports too).

    Only the lines that carry a PASS or FAIL are examined; the rest is their context.
    That keeps the cost of a long result with a handful of such lines close to the
    cost of splitting it.
    """
    lines = [l.rstrip() for l in text.splitlines()]
    carrying = [i for i, l in enumerate(lines) if _STANDALONE.search(l)]
    if not carrying:
        return False
    # Each needs a pass over every line, so each is skipped when the text cannot hold
    # the line it looks for: a summary starts with `Test`, a failed package with `FAIL<tab>`.
    js_run = 'Test' in text and any(_JS_SUMMARY.match(l) for l in lines)
    a_package_failed = 'FAIL\t' in text and any(
        m and m.group(1) == 'FAIL' for m in map(_GO_PACKAGE_LINE.match, lines))
    solid = None                           # indices of the non-blank lines, built on first need
    for i in carrying:
        line = lines[i]
        if (js_run and _js_runner_line(line)) or _GO_TEST_LINE.match(line) or _GO_PACKAGE_LINE.match(line):
            continue
        if _unittest_line(lines, i):
            continue
        if _BARE_VERDICT.match(line):
            if solid is None:
                solid = [j for j, l in enumerate(lines) if l]
            if _go_bare_line(lines, solid, i, a_package_failed):
                continue
        return True
    return False


def adjudicated(text):
    """Is a verdict being decided in this text? Errs toward yes."""
    if not text:
        return False
    if _any(_VERDICT_WORDS, text):
        return True
    if not _STANDALONE.search(text):       # one pass, and most output ends here
        return False
    return _verdict_outside_runner_lines(text)


def _verdict_in(parts):
    """Is a verdict being decided in what was kept of one tool result? `parts` is what
    the transcript reader kept: (text, whole_lines) pairs. A text of whole lines is read
    with the runner rules. A line that the reader's cut went through is not: any
    verdict word in it counts, since nothing can vouch for half a line."""
    return any(adjudicated(text) if whole_lines else _any(ADJUDICATION, text)
               for text, whole_lines in parts)


def extract(events, window=DEFAULT_WINDOW):
    """events -> SignalSet. Never raises; an unreadable session is a silent one."""
    try:
        return _extract(events, window)
    except Exception:
        return EMPTY


def _extract(events, window):
    win = _window_slice(events or [], window)
    if not win:
        return EMPTY

    pending = {}                     # tool_use_id -> (name, input)
    err_sigs = Counter()
    cmd_sigs = Counter()
    edits = Counter()
    reads = Counter()
    samples = []
    tool_count = error_count = env_blocked = cap_hits = say_count = 0
    run = max_run = 0          # run = the streak ending at the tail; max_run = worst in window
    since_success = 0
    results_tail = []
    horme_recent = False

    for e in win:
        if e.kind == 'tool_use':
            tool_count += 1
            since_success += 1
            pending[e.tool_use_id] = (e.name, e.input)
            if e.name == 'Bash':
                cmd = str(e.input.get('command', ''))
                if cmd:
                    cmd_sigs[signature(cmd, 80)] += 1
            elif e.name in EDIT_TOOLS:
                fp = str(e.input.get('file_path', ''))
                if fp:
                    edits[fp] += 1
            elif e.name == 'Read':
                fp = str(e.input.get('file_path', ''))
                if fp:
                    reads[fp] += 1

        elif e.kind == 'tool_result':
            # The verdict check alone reads the result as far as the transcript reader
            # kept it; everything below reads the first TEXT_CAP characters, as calibrated.
            results_tail.append(e.scan or ((e.text, True),))
            if e.is_error:
                error_count += 1
                run += 1
                max_run = max(max_run, run)
                err_sigs[signature(e.text)] += 1
                if len(samples) < 3:
                    samples.append(e.text[:SAMPLE_CHARS])
                if _any(ENV_BLOCKED, e.text):
                    env_blocked += 1
            else:
                run = 0
                since_success = 0

        elif e.kind == 'say':
            say_count += 1
            if _any(CAPITULATION, e.text):
                cap_hits += 1

        elif e.kind == 'hook':
            if brand.MARKER in e.text:
                horme_recent = True

    top_err = err_sigs.most_common(1)
    top_cmd = cmd_sigs.most_common(1)
    top_edit = edits.most_common(1)
    top_read = reads.most_common(1)

    # Each result on its own: whether a bare FAIL is go test's depends on its neighbours.
    verdict_adjacent = any(_verdict_in(parts) for parts in results_tail[-VERDICT_TAIL:])

    return SignalSet(
        window=len(win),
        tool_count=tool_count,
        error_count=error_count,
        consecutive_tool_errors=max_run,
        current_error_run=run,
        calls_since_success=since_success,
        repeated_error_count=(top_err[0][1] if top_err else 0),
        top_error_signature=(top_err[0][0] if top_err else ''),
        error_samples=tuple(samples),
        env_blocked_errors=env_blocked,
        command_repeat=(top_cmd[0][1] if top_cmd else 0),
        top_command=(top_cmd[0][0] if top_cmd else ''),
        edit_thrash=(top_edit[0][1] if top_edit else 0),
        edit_thrash_file=(top_edit[0][0] if top_edit else ''),
        reread_thrash=(top_read[0][1] if top_read else 0),
        capitulation_hits=cap_hits,
        say_count=say_count,
        verdict_adjacent=verdict_adjacent,
        horme_recent=horme_recent,
    )
