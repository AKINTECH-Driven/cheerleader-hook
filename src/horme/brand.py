"""User-visible identity, in one place.

The marker is written by `compose` and read back by `signals` to dedupe against past
interventions. Before this module they were two independent string literals in two
files: change one and the tool silently stops recognising its own output, repeating
itself forever. One constant, and a test that they cannot drift.

The Python package stays `horme` (the engine's name); only the user-facing skill is
`cheerleader`.
"""
import os

NAME = 'cheerleader'
LABEL = 'CHEERLEADER'
MARKER = '[CHEERLEADER]'
HOOK_FILENAME = 'cheerleader_hook.py'

#: The newer name first; the old one still works so an early install keeps its off switch.
ENV_DISABLE = ('CHEERLEADER_DISABLE', 'HORME_DISABLE')

RUNTIME_DIR = os.path.expanduser('~/.claude/cheerleader')
STATE_DIR = os.path.join(RUNTIME_DIR, 'state')
DISABLE_FILE = os.path.join(RUNTIME_DIR, 'DISABLED')


def disabled(disable_file=None):
    if any(os.environ.get(v) for v in ENV_DISABLE):
        return True
    return os.path.exists(disable_file or DISABLE_FILE)
