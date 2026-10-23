"""Turn a filtered copy into a single Globus transfer task.

The source is walked only as deep as the filter requires. Subtrees where the
filter depends only on basenames become recursive items with the rules handed
to Globus; everything else is listed and submitted file by file.
"""
import logging
import posixpath
from collections import deque
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import globus_sdk

logger = logging.getLogger(__name__)

LS_PAGE_SIZE = 100_000
MAX_FILTER_RULES = 20
PROGRESS_EVERY = 100


@dataclass
class Plan:
    items: list = field(default_factory=list)  # (src, dst, recursive)
    filter_rules: list = field(default_factory=list)  # (name, method, type)
    # Destination dirs no item will create (Globus creates item parents)
    mkdirs: list = field(default_factory=list)
    ls_calls: int = 0
    dirs_listed: int = 0
    depth: int = 0

    def add_to_transfer(self, tx):
        for name, method, entry_type in self.filter_rules:
            if entry_type is None:
                tx.add_filter_rule(name, method=method)
            else:
                tx.add_filter_rule(name, method=method, type=entry_type)
        for src, dst, recursive in self.items:
            tx.add_item(src, dst, recursive=recursive)


def _join(base, rel):
    return posixpath.join(base, rel) if rel else base


def ls_all(tc, endpoint_id, path, filter=None):
    """List every entry in a directory, following pages. Returns the entries
    and the number of ls calls made."""
    entries = []
    calls = 0
    while True:
        kwargs = {'show_hidden': True, 'offset': len(entries),
                  'limit': LS_PAGE_SIZE}
        if filter is not None:
            kwargs['filter'] = filter
        resp = tc.operation_ls(endpoint_id, path, **kwargs)
        calls += 1
        page = resp['DATA']
        entries.extend(page)
        if len(page) < LS_PAGE_SIZE or resp.get('has_next_page') is False:
            return entries, calls


def build_plan(tc, endpoint_id, src_path, dst_path, filt):
    """Walk the source directory as far as ``filt`` needs and build a Plan.

    All recursive items share one set of Globus filter rules (they are
    task-wide), so a subtree whose rules differ from the first delegated
    subtree's is walked instead.
    """
    for glob in filt.unpushable_globs():
        logger.warning(f'filter rule {glob!r} cannot be run by Globus; '
                       f'the source will be listed in full')

    plan = Plan()
    walked = ['']
    rules = None
    reasons = set()
    queue = deque([('', 0)])
    while queue:
        rel, depth = queue.popleft()
        src = _join(src_path, rel)
        sub_rules, reason = filt.subtree_rules(rel)
        if sub_rules is not None and len(sub_rules) > MAX_FILTER_RULES:
            sub_rules = None
            reason = f'more than {MAX_FILTER_RULES} Globus filter rules'
        if sub_rules is not None:
            if rules is None or sub_rules == rules:
                rules = sub_rules
                plan.items.append((src, _join(dst_path, rel), True))
                continue
            reason = 'rules differ from other recursive items'
        reasons.add(reason)
        logger.debug(f'listing {src}: {reason}')

        ls_filter = None if filt.needs_child_files(rel) else 'type:dir'
        entries, calls = ls_all(tc, endpoint_id, src, ls_filter)
        plan.ls_calls += calls
        plan.dirs_listed += 1
        plan.depth = max(plan.depth, depth)
        if plan.dirs_listed % PROGRESS_EVERY == 0:
            logger.info(f'listed {plan.dirs_listed} directories, '
                        f'{len(plan.items)} items so far')

        for entry in sorted(entries, key=lambda e: e['name']):
            child = _join(rel, entry['name'])
            if entry['type'] == 'dir':
                if filt.include_dir(child):
                    walked.append(child)
                    queue.append((child, depth + 1))
            elif entry['type'] == 'file':
                if filt.include_file(child):
                    plan.items.append((_join(src_path, child),
                                       _join(dst_path, child), False))
            else:
                logger.debug(f'skipping {entry["type"]} entry: {child}')

    plan.filter_rules = rules or []
    plan.mkdirs = _uncovered_dirs(plan.items, [_join(dst_path, d)
                                               for d in walked])
    if plan.dirs_listed:
        logger.info(f'listed {plan.dirs_listed} source directories '
                    f'({plan.ls_calls} ls calls, depth {plan.depth}) because '
                    f'of: {", ".join(sorted(reasons))}')
    return plan


def _uncovered_dirs(items, dirs):
    """The dirs that no transfer item creates, in their original order."""
    covered = set()
    for _, dst, recursive in items:
        path = PurePosixPath(dst)
        covered.update(str(p) for p in path.parents)
        if recursive:
            covered.add(str(path))
    return [d for d in dirs if d not in covered]


def _is_exists_error(e):
    return ((e.code or '').endswith('.Exists')
            or 'already exists' in (e.message or '').lower())


def mkdir_p(tc, endpoint_id, paths):
    """Create each directory and any missing parents, treating 'already
    exists' as success."""
    done = set()

    def make(path):
        if path in done:
            return
        logger.debug(f'creating destination directory: {path}')
        try:
            tc.operation_mkdir(endpoint_id, path)
        except globus_sdk.TransferAPIError as e:
            parent = posixpath.dirname(path)
            if e.http_status == 404 and parent != path:
                make(parent)
                done.discard(path)
                make(path)
            elif not _is_exists_error(e):
                raise
        done.add(path)

    for path in paths:
        make(path)


def walk_files(tc, endpoint_id, src_path, filt):
    """List every file the filter includes, entirely client-side. Returns
    ``(relative path, size)`` pairs."""
    files = []
    queue = deque([''])
    while queue:
        rel = queue.popleft()
        ls_filter = None if filt.needs_child_files(rel) else 'type:dir'
        entries, _ = ls_all(tc, endpoint_id, _join(src_path, rel), ls_filter)
        for entry in sorted(entries, key=lambda e: e['name']):
            child = _join(rel, entry['name'])
            if entry['type'] == 'dir':
                if filt.include_dir(child):
                    queue.append(child)
            elif entry['type'] == 'file' and filt.include_file(child):
                files.append((child, entry.get('size') or 0))
    return files


def _truncated(lines, limit):
    if limit is None or len(lines) <= limit:
        return lines
    return lines[:limit] + [f'  ... and {len(lines) - limit} more '
                            f'(use -v to list all)']


def format_plan(plan, limit=20):
    """Human-readable summary of a plan. Lists are cut to ``limit`` entries
    unless it is None."""
    lines = [f'Globus filter rules ({len(plan.filter_rules)}):']
    lines += [f'  {method} {entry_type or "any"}: {name}'
              for name, method, entry_type in plan.filter_rules]
    lines.append(f'Source directories listed: {plan.dirs_listed} '
                 f'({plan.ls_calls} ls calls, depth {plan.depth})')
    lines.append(f'Directories to create ({len(plan.mkdirs)}):')
    lines += _truncated([f'  {d}' for d in plan.mkdirs], limit)
    n_recursive = sum(1 for *_, recursive in plan.items if recursive)
    lines.append(f'Transfer items ({len(plan.items)}: {n_recursive} '
                 f'recursive, {len(plan.items) - n_recursive} files):')
    lines += _truncated([f'  [{"dir" if r else "file"}] {s} -> {d}'
                         for s, d, r in plan.items], limit)
    return '\n'.join(lines)
