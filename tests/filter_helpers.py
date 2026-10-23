import argparse
import json
import posixpath

import globus_sdk
import requests

from educelab.globus.cp.filters import Filter, add_filter_arguments
from gen_filter_golden import CASES_FILE, GOLDEN_FILE, normalize_case

SPEC = json.loads(CASES_FILE.read_text())
GOLDEN = json.loads(GOLDEN_FILE.read_text())['cases']
FILTER_CASES = sorted(name for name, result in GOLDEN.items()
                      if 'error' not in result)


def tree_children(tree):
    """Map each directory ('' = root) to its (subdirs, files)."""
    children = {'': (set(), set())}
    for entry in tree:
        path = entry.rstrip('/')
        parts = path.split('/')
        for i in range(1, len(parts)):
            parent, d = '/'.join(parts[:i - 1]), '/'.join(parts[:i])
            children.setdefault(d, (set(), set()))
            children[parent][0].add(d)
        parent = posixpath.dirname(path)
        if entry.endswith('/'):
            children.setdefault(path, (set(), set()))
            children[parent][0].add(path)
        else:
            children[parent][1].add(path)
    return children


CHILDREN = tree_children(SPEC['tree'])


def walk(filt):
    """List entries the way `rclone lsf -R` does: prune excluded dirs."""
    out = []
    stack = ['']
    while stack:
        subdirs, files = CHILDREN[stack.pop()]
        out.extend(f for f in files if filt.include_file(f))
        for d in subdirs:
            if filt.include_dir(d):
                out.append(d + '/')
                stack.append(d)
    return sorted(out)


def build_filter(args):
    parser = argparse.ArgumentParser()
    add_filter_arguments(parser)
    return Filter.from_args(parser.parse_args(args))


def case_filter(name, tmp_path):
    """Build the filter for a named case, writing its -from files to
    tmp_path."""
    case = normalize_case(SPEC['cases'][name])
    for fname, content in case['files'].items():
        (tmp_path / fname).write_text(content)
    return build_filter([a.replace('{tmp}', str(tmp_path))
                         for a in case['args']])


SRC = '/src/root'
DST = '/dst/root'
EP = 'src-uuid'


def api_error(code, message, status=502):
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps({'code': code, 'message': message}).encode()
    r.headers['Content-Type'] = 'application/json'
    r.request = requests.Request('POST', 'https://example.org/x').prepare()
    r.url = r.request.url
    return globus_sdk.TransferAPIError(r)


class FakeTransferClient:
    """In-memory operation_ls / operation_mkdir over the fixture tree."""

    def __init__(self, children=CHILDREN, existing=('/',),
                 mkdir_errors=None):
        self.children = children
        self.ls_calls = []
        self.mkdirs = []
        self.existing = set(existing)
        self.mkdir_errors = mkdir_errors or {}

    def operation_ls(self, endpoint_id, path, *, show_hidden=True,
                     limit=100_000, offset=0, filter=None):
        assert endpoint_id == EP
        self.ls_calls.append((path, offset, limit, filter))
        rel = posixpath.relpath(path, SRC)
        rel = '' if rel == '.' else rel
        if rel not in self.children:
            raise api_error('ClientError.NotFound', 'not found', 404)
        dirs, files = self.children[rel]
        entries = [{'name': posixpath.basename(d), 'type': 'dir', 'size': 0}
                   for d in sorted(dirs)]
        if filter is None:
            entries += [{'name': posixpath.basename(f), 'type': 'file',
                         'size': 10} for f in sorted(files)]
        else:
            assert filter == 'type:dir'
        return {'DATA': entries[offset:offset + limit]}

    def operation_mkdir(self, endpoint_id, path):
        self.mkdirs.append(path)
        if path in self.mkdir_errors:
            raise self.mkdir_errors[path]
        if path in self.existing:
            raise api_error('ExternalError.MkdirFailed.Exists',
                            'Path already exists')
        if posixpath.dirname(path) not in self.existing:
            raise api_error('NotFound', 'Path not found', 404)
        self.existing.add(path)
