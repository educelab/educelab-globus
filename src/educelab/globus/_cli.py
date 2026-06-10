import logging
import os
import sys


_LEVEL_COLORS = {
    logging.DEBUG: '\033[36m',     # cyan
    logging.INFO: '',              # default
    logging.WARNING: '\033[33m',   # yellow
    logging.ERROR: '\033[31m',     # red
    logging.CRITICAL: '\033[31m',  # red
}
_RESET = '\033[0m'
# Width of the longest bracketed level name we render: '[warning]' = 9 chars.
_LABEL_WIDTH = 9


def _use_color(stream):
    if os.environ.get('NO_COLOR'):
        return False
    return hasattr(stream, 'isatty') and stream.isatty()


class _CLIFormatter(logging.Formatter):
    def __init__(self, color):
        super().__init__()
        self.color = color

    def format(self, record):
        label = f'[{record.levelname.lower()}]'.ljust(_LABEL_WIDTH)
        if self.color:
            ansi = _LEVEL_COLORS.get(record.levelno, '')
            if ansi:
                label = f'{ansi}{label}{_RESET}'
        msg = record.getMessage()
        if record.exc_info:
            msg = f'{msg}\n{self.formatException(record.exc_info)}'
        return f'{label} {msg}'


def setup_logging(verbose=False, quiet=False):
    """Configure stderr logging for the CLI entry points.

    verbose -> DEBUG, quiet -> WARNING, otherwise INFO. verbose wins if both
    are set. Idempotent: replaces any existing handlers on the
    educelab.globus logger so repeated calls (e.g. tests) don't duplicate
    output.
    """
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_CLIFormatter(color=_use_color(sys.stderr)))

    root = logging.getLogger('educelab.globus')
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
