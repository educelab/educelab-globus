# Rule parsing and matching are a port of rclone's fs/filter package (v1.75.2),
# Copyright (C) 2012 by Nick Craig-Wood, used under the MIT License (see NOTICE).
"""rclone-compatible include/exclude filtering for el-globus-cp.

Paths are relative to the transfer source, use ``/`` separators and have no
leading slash. See https://rclone.org/filtering/ for the rule syntax.
"""
import functools
import logging
import posixpath
import re
import sys
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class FilterError(ValueError):
    pass


def glob_to_regex(glob):
    """Translate an rclone path glob into a regular expression string."""
    out = []
    if glob.startswith('/'):
        glob = glob[1:]
        out.append('^')
    else:
        out.append('(^|/)')

    stars = 0

    def insert_stars():
        nonlocal stars
        if stars == 1:
            out.append('[^/]*')
        elif stars == 2:
            out.append('.*')
        elif stars > 2:
            raise FilterError(f'too many stars in {glob!r}')
        stars = 0

    brace_depth = 0
    in_brackets = 0
    slashed = False
    in_regex = False
    in_regex_end = False
    last = ''
    prev = ''
    for c in glob:
        last, prev = prev, c
        if slashed:
            out.append(c)
            slashed = False
            continue
        if in_regex_end:
            # Extra '}' after '}}' belong to the regex: keep the longest run
            if c == '}':
                out[-1] = '}'
                out.append(')')
                continue
            in_regex_end = False
        if in_regex:
            if c == '}' and last == '}':
                in_regex = False
                in_regex_end = True
                out[-1] = ')'
            else:
                out.append(c)
            continue
        if c != '*':
            insert_stars()
        if in_brackets:
            if c == '^' and out[-1] == '[':
                # Unlike rclone, a negated class never matches '/'
                out.append('^/')
                continue
            out.append(c)
            if c == '[':
                in_brackets += 1
            elif c == ']':
                in_brackets -= 1
            continue
        if c == '\\':
            out.append(c)
            slashed = True
        elif c == '*':
            stars += 1
        elif c == '?':
            out.append('[^/]')
        elif c == '[':
            out.append(c)
            in_brackets += 1
        elif c == ']':
            raise FilterError(f"mismatched ']' in glob {glob!r}")
        elif c == '{':
            if brace_depth > 0 and last == '{':
                # '{{' opens a raw regex; the first '{' already wrote its '('
                in_regex = True
                brace_depth -= 1
            else:
                brace_depth += 1
                out.append('(')
        elif c == '}':
            if brace_depth <= 0:
                raise FilterError(f"mismatched '{{' and '}}' in glob {glob!r}")
            out.append(')')
            brace_depth -= 1
        elif c == ',':
            out.append('|' if brace_depth > 0 else c)
        elif c in '.+()|^$':
            out.append('\\' + c)
        else:
            out.append(c)
    insert_stars()
    if in_brackets:
        raise FilterError(f"mismatched '[' and ']' in glob {glob!r}")
    if brace_depth:
        raise FilterError(f"mismatched '{{' and '}}' in glob {glob!r}")
    if in_regex:
        raise FilterError(f"mismatched '{{{{' and '}}}}' in glob {glob!r}")
    out.append(r'\Z')
    return ''.join(out)


def compile_glob(glob):
    regex = glob_to_regex(glob)
    try:
        return re.compile(regex)
    except re.error as e:
        raise FilterError(
            f'bad glob pattern {glob!r} (regexp {regex!r}): {e}') from None


_TOO_HARD_RE = re.compile(r'(\{[^{}]*(\*\*|/)[^{}]*\})|\{\{|\}\}|\{[^{}]*\{')


def glob_to_dir_globs(glob):
    """Directory globs that match any directory which could contain a match
    for the file glob. Used to decide which directories an include must walk.
    """
    if _TOO_HARD_RE.search(glob):
        logger.info(f"can't figure out directory filters from {glob!r}: "
                    f'looking in all directories')
        return ['/**']

    glob = re.sub('/{2,}', '/', glob)
    out = []
    while True:
        i = glob.rfind('/')
        j = glob.rfind('**')
        what = ''
        if j > i:
            i = j
            what = '**'
        if i < 0:
            if not out:
                out.append('/**')
            break
        glob = glob[:i]
        new_glob = glob + what + '/'
        if not out or out[-1] != new_glob:
            out.append(new_glob)
    return out


def _expand_braces(pattern):
    """Expand ``{a,b}`` alternations (brackets are opaque). Returns None on
    unbalanced braces."""
    depth = 0
    in_brackets = False
    start = None
    commas = []
    for i, c in enumerate(pattern):
        if in_brackets:
            in_brackets = c != ']'
        elif c == '[':
            in_brackets = True
        elif c == '{':
            if depth == 0:
                start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth < 0:
                return None
            if depth == 0:
                head, tail = pattern[:start], pattern[i + 1:]
                bounds = [start] + commas + [i]
                out = []
                for a, b in zip(bounds, bounds[1:]):
                    expanded = _expand_braces(head + pattern[a + 1:b] + tail)
                    if expanded is None:
                        return None
                    out.extend(expanded)
                return out
        elif c == ',' and depth == 1:
            commas.append(i)
    return None if depth else [pattern]


def _to_fnmatch(pattern):
    """Convert rclone bracket syntax to fnmatch. Raises ValueError for
    classes fnmatch can't express."""
    if '\\' in pattern:
        raise ValueError(pattern)
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c != '[':
            out.append(c)
            i += 1
            continue
        end = pattern.find(']', i + 1)
        body = pattern[i + 1:end]
        if end < 0 or not body or body.startswith('!') or '[' in body:
            raise ValueError(pattern)
        if body.startswith('^'):
            body = '!' + body[1:]
        out.append(f'[{body}]')
        i = end + 1
    return ''.join(out)


@dataclass
class _Rules:
    """Ordered first-match-wins matchers, deduplicated like rclone's."""
    rules: list = field(default_factory=list)
    _seen: set = field(default_factory=set)

    def add(self, include, glob):
        regex = compile_glob(glob)
        key = (include, regex.pattern)
        if key not in self._seen:
            self._seen.add(key)
            self.rules.append((include, regex, glob))

    def clear(self):
        self.rules.clear()
        self._seen.clear()

    def include(self, path):
        for include, regex, _ in self.rules:
            if regex.search(path):
                return include
        return True

    def __len__(self):
        return len(self.rules)


# Subtree analysis: work out what each compiled rule can still match below a
# directory, so rules that only depend on basenames can be run by Globus.
_STAR = object()  # zero or more path components
_ANY = object()  # exactly one component
_END = object()  # end of the path

NEVER, ALWAYS, PATH = 'never', 'always', 'path'


@functools.lru_cache(maxsize=None)
def _glob_tokens(glob, kind):
    """Split a path glob into per-component tokens, or None if it can't be
    analysed component by component. Directories (``kind == 'dir'``) are
    matched with a trailing slash, files without."""
    if _TOO_HARD_RE.search(glob) or '\\/' in glob:
        return None
    anchored = glob.startswith('/')
    segments = (glob[1:] if anchored else glob).split('/')
    tokens = [] if anchored else [_STAR]
    for i, seg in enumerate(segments):
        last = i == len(segments) - 1
        if last and seg == '':
            return (*tokens, _END) if kind == 'dir' else ()
        if seg == '**':
            if last:
                tail = (_STAR, _END) if kind == 'dir' else (_ANY, _STAR, _END)
                return (*tokens, *tail)
            tokens += [_ANY, _STAR]
        elif not seg or '**' in seg:
            return None
        else:
            tokens.append(_ANY if seg == '*' else seg)
    # A directory path ends in '/', so it can't end on a component
    return (*tokens, _END) if kind == 'file' else ()


@functools.lru_cache(maxsize=None)
def _segment_regex(segment):
    return compile_glob('/' + segment)


def _closure(tokens, states):
    out = set(states)
    todo = list(states)
    while todo:
        i = todo.pop()
        if tokens[i] is _STAR and i + 1 not in out:
            out.add(i + 1)
            todo.append(i + 1)
    return out


def _states(tokens, components):
    """Token positions reachable after matching ``components``."""
    if not tokens:
        return set()
    states = _closure(tokens, {0})
    for name in components:
        step = set()
        for i in states:
            t = tokens[i]
            if t is _STAR:
                step.add(i)
            elif t is _ANY or (t is not _END and _segment_regex(t).search(name)):
                step.add(i + 1)
        states = _closure(tokens, step)
    return states


class _Prune(list):
    """Basename globs whose matching entries *and everything beneath them*
    are matched, e.g. ``raw/**``."""


def _classify_subtree(tokens, states):
    """What a rule matches among everything below a directory: NEVER, ALWAYS,
    PATH (depends on more than the basename), a list of basename globs, or a
    _Prune list."""
    # Positions reachable from a STAR match a subset of what the STAR does
    covered = set()
    for i in states:
        if tokens[i] is _STAR:
            covered |= _closure(tokens, {i}) - {i}
    rests = [tokens[i:] for i in states - covered if tokens[i] is not _END]
    if any(r in ((_STAR, _END), (_STAR, _ANY, _END), (_ANY, _STAR, _END))
           for r in rests):
        return ALWAYS
    names = []
    prune = _Prune()
    for rest in rests:
        if len(rest) < 3 or rest[0] is not _STAR \
                or not isinstance(rest[1], str):
            return PATH
        if rest[2:] == (_END,):
            names.append(rest[1])
        elif rest[2:] in ((_STAR, _END), (_ANY, _STAR, _END)):
            prune.append(rest[1])
        else:
            return PATH
    if prune:
        return PATH if names else prune
    return names or NEVER


def _classify_children(tokens, states):
    """Like _classify_subtree, but only for direct children."""
    names = []
    for i in states:
        t = tokens[i]
        if t is _END:
            continue
        after = _closure(tokens, {i} if t is _STAR else {i + 1})
        if not any(tokens[j] is _END for j in after):
            continue
        if t is _STAR or t is _ANY:
            return ALWAYS
        names.append(t)
    return names or NEVER


def _components(path):
    path = path.strip('/')
    return path.split('/') if path else []


class Filter:
    """rclone filter: file rules decide which files are included, directory
    rules decide which directories are walked.
    """

    def __init__(self):
        self._file_rules = _Rules()
        self._dir_rules = _Rules()
        self.files = None
        self._dirs = None
        self._file_parents = None

    @classmethod
    def from_options(cls, *, include=(), include_from=(), exclude=(),
                     exclude_from=(), filter=(), filter_from=(),
                     files_from=()):
        """Build a filter from command-line style options.

        As in rclone, the order is fixed regardless of the command line:
        includes, excludes, then filter rules, then an implicit ``- /**``
        if any include rule was given.
        """
        if [*include_from, *exclude_from, *filter_from,
                *files_from].count('-') > 1:
            raise FilterError('only one -from option can read from stdin')
        f = cls()
        include = list(include) + [line for path in include_from
                                   for line in read_lines(path)]
        exclude = list(exclude) + [line for path in exclude_from
                                   for line in read_lines(path)]
        if include and exclude:
            logger.warning('using --filter is recommended instead of both '
                           '--include and --exclude as the order they are '
                           'parsed in is indeterminate')
        for glob in include:
            f.add(True, glob)
        for glob in exclude:
            f.add(False, glob)
        for rule in list(filter) + [line for path in filter_from
                                    for line in read_lines(path)]:
            f.add_rule(rule)
        if include:
            f.add(False, '/**')

        if files_from:
            if f._file_rules or f._dir_rules:
                raise FilterError(
                    'the usage of --files-from overrides all other filters, '
                    'it should be used alone')
            f.files = set()
            f._dirs = set()
            f._file_parents = set()
            for path in files_from:
                for line in read_lines(path):
                    f.add_file(line)
        return f

    @classmethod
    def from_args(cls, args):
        """Build a filter from an argparse namespace populated by
        :func:`add_filter_arguments`."""
        return cls.from_options(
            include=args.include, include_from=args.include_from,
            exclude=args.exclude, exclude_from=args.exclude_from,
            filter=args.filter, filter_from=args.filter_from,
            files_from=args.files_from)

    @property
    def active(self):
        return (self.files is not None or bool(self._file_rules)
                or bool(self._dir_rules))

    def add(self, include, glob):
        is_dir_rule = glob.endswith('/')
        is_file_rule = not is_dir_rule
        # Excluding "dir/" is the same as excluding "dir/**"
        if is_dir_rule and not include:
            glob += '**'
        if '**' in glob:
            is_dir_rule = is_file_rule = True
        if is_file_rule:
            self._file_rules.add(include, glob)
            # An include tells us which directories must be walked; an
            # exclude can't rule any out unless it is '*'
            if include or glob == '*':
                for dir_glob in glob_to_dir_globs(glob):
                    if dir_glob != '/':
                        self._dir_rules.add(include, dir_glob)
        if is_dir_rule:
            self._dir_rules.add(include, glob)

    def add_rule(self, rule):
        """Add a ``+ glob``, ``- glob`` or ``!`` (clear) rule."""
        if rule == '!':
            self.clear()
        elif rule.startswith('- '):
            self.add(False, rule[2:])
        elif rule.startswith('+ '):
            self.add(True, rule[2:])
        else:
            raise FilterError(f'malformed rule {rule!r}')

    def add_file(self, path):
        path = path.strip('/')
        self.files.add(path)
        self._file_parents.add(posixpath.dirname(path))
        while (path := posixpath.dirname(path)) and path not in self._dirs:
            self._dirs.add(path)

    def clear(self):
        self._file_rules.clear()
        self._dir_rules.clear()

    def include_file(self, path):
        if self.files is not None:
            return path in self.files
        return self._file_rules.include(path)

    def include_dir(self, path):
        """Whether the directory at ``path`` should be walked."""
        path = path.strip('/')
        if not path:
            return True
        if self.files is not None:
            return path in self._dirs
        return self._dir_rules.include(path + '/')


    def subtree_rules(self, path):
        """Globus filter rules that give the same result as this filter for
        everything below directory ``path``.

        Returns ``(rules, None)`` with rules as ``(name, method, type)``
        tuples, or ``(None, reason)`` if the directory has to be walked.
        """
        if self.files is not None:
            return None, '--files-from'
        components = _components(path)
        # Directories go first: excluded ones are pruned, which can make
        # path-dependent file rules irrelevant
        pruned = set()
        dir_seq, reason = self._subtree_seq('dir', components, pruned)
        if reason:
            return None, reason
        file_seq, reason = self._subtree_seq('file', components, pruned)
        if reason:
            return None, reason

        out = []
        for kind, seq in (('file', file_seq), ('dir', dir_seq)):
            for include, glob, names in seq:
                method = 'include' if include else 'exclude'
                for name in names:
                    try:
                        patterns = [_to_fnmatch(n)
                                    for n in _expand_braces(name) or ()]
                    except ValueError:
                        patterns = None
                    if not patterns:
                        return None, glob
                    out.extend((p, method, kind) for p in patterns)
        return list(dict.fromkeys(out)), None

    def _subtree_seq(self, kind, components, pruned):
        """Effective ``(include, glob, basename globs)`` rules of one kind
        below a directory, or ``(None, reason)``."""
        rules = self._dir_rules if kind == 'dir' else self._file_rules
        seq = []
        for include, _, glob in rules.rules:
            tokens = _glob_tokens(glob, kind)
            if tokens is None:
                return None, glob
            match = _classify_subtree(tokens, _states(tokens, components))
            if match is NEVER:
                continue
            if match is PATH:
                return None, glob
            if isinstance(match, _Prune):
                # Excluding "raw/**" acts like excluding dirs named raw, as
                # long as no earlier rule could let such a dir through
                if include or any(inc for inc, _, _ in seq):
                    return None, glob
                if kind == 'file':
                    if not pruned.issuperset(match):
                        return None, glob
                    continue
                pruned.update(match)
            seq.append((include, glob, ['*'] if match is ALWAYS else match))
            if match is ALWAYS:
                break
        # Trailing includes behave like the default
        while seq and seq[-1][0]:
            seq.pop()
        return seq, None

    def unpushable_globs(self):
        """Compiled globs that can't be analysed per path component, so the
        source has to be listed in full."""
        rules = [(kind, glob) for kind, rs in (('file', self._file_rules),
                                               ('dir', self._dir_rules))
                 for _, _, glob in rs.rules]
        return list(dict.fromkeys(glob for kind, glob in rules
                                  if _glob_tokens(glob, kind) is None))

    def needs_child_files(self, path):
        """Whether any file directly in directory ``path`` could be
        included."""
        path = path.strip('/')
        if self.files is not None:
            return path in self._file_parents
        components = _components(path)
        for include, _, glob in self._file_rules.rules:
            tokens = _glob_tokens(glob, 'file')
            if tokens is None:
                return True
            match = _classify_children(tokens, _states(tokens, components))
            if match is NEVER:
                continue
            if include:
                return True
            if match is ALWAYS:
                return False
        return True


def read_lines(path):
    """Read rule/file lines from ``path`` (``-`` for stdin), skipping blank
    lines and ``#``/``;`` comments."""
    try:
        if path == '-':
            lines = sys.stdin.read().splitlines()
        else:
            with open(path, encoding='utf-8') as f:
                lines = f.read().splitlines()
    except OSError as e:
        raise FilterError(f'failed to read {path!r}: {e}') from None
    lines = (line.strip() for line in lines)
    return [line for line in lines if line and line[0] not in '#;']


def add_filter_arguments(parser):
    group = parser.add_argument_group(
        'filtering', 'rclone-style filter rules, see '
                     'https://rclone.org/filtering/')
    group.add_argument('--filter', action='append', default=[],
                       metavar='RULE',
                       help="Add a filter rule: '+ glob', '- glob' or '!'")
    group.add_argument('--filter-from', action='append', default=[],
                       metavar='FILE',
                       help='Read filter rules from a file (- for stdin)')
    group.add_argument('--include', action='append', default=[],
                       metavar='GLOB', help='Include files matching glob')
    group.add_argument('--include-from', action='append', default=[],
                       metavar='FILE',
                       help='Read include globs from a file (- for stdin)')
    group.add_argument('--exclude', action='append', default=[],
                       metavar='GLOB', help='Exclude files matching glob')
    group.add_argument('--exclude-from', action='append', default=[],
                       metavar='FILE',
                       help='Read exclude globs from a file (- for stdin)')
    group.add_argument('--files-from', action='append', default=[],
                       metavar='FILE',
                       help='Transfer only the files listed in FILE '
                            '(- for stdin)')
    return group
