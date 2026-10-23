import posixpath
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

import globus_sdk
import pytest

from educelab.globus.cp import plan as plan_mod
from educelab.globus.cp.plan import Plan, build_plan, ls_all, mkdir_p
from filter_helpers import (CHILDREN, DST, EP, FILTER_CASES, GOLDEN, SRC,
                            FakeTransferClient, api_error, build_filter,
                            case_filter, walk)

def rel_to(path, root):
    rel = posixpath.relpath(path, root)
    return '' if rel == '.' else rel


def simulate_globus(plan):
    """Execute a plan the way Globus would: file items as given, recursive
    items expanded with the basename filter rules (excluded dirs pruned).
    Returns the files copied and the directories created, relative to DST."""

    def included(name, entry_type):
        for pattern, method, rule_type in plan.filter_rules:
            if rule_type == entry_type and fnmatchcase(name, pattern):
                return method == 'include'
        return True

    def with_parents(path):
        return {path} | {str(p) for p in PurePosixPath(path).parents}

    # mkdir_p and Globus both create missing parents
    created = set()
    for d in plan.mkdirs:
        created |= with_parents(d)
    for _, dst, recursive in plan.items:
        created |= with_parents(dst if recursive else posixpath.dirname(dst))
    dirs = {rel_to(d, DST) for d in created
            if d == DST or d.startswith(DST + '/')}

    files = set()
    for src, dst, recursive in plan.items:
        if not recursive:
            files.add(rel_to(src, SRC))
            continue
        stack = [rel_to(src, SRC)]
        while stack:
            subdirs, subfiles = CHILDREN[stack.pop()]
            files |= {f for f in subfiles
                      if included(posixpath.basename(f), 'file')}
            for d in subdirs:
                if included(posixpath.basename(d), 'dir'):
                    dirs.add(d)
                    stack.append(d)
    return files, dirs


def assert_equivalent(plan, entries):
    files, dirs = simulate_globus(plan)
    assert files == {e for e in entries if not e.endswith('/')}
    assert dirs == {''} | {e.rstrip('/') for e in entries if e.endswith('/')}


@pytest.mark.parametrize('name', FILTER_CASES)
def test_split_equivalence(name, tmp_path):
    """The hybrid plan copies exactly what rclone would, and creates exactly
    the directories rclone would walk."""
    plan = build_plan(FakeTransferClient(), EP, SRC, DST,
                      case_filter(name, tmp_path))
    assert_equivalent(plan, GOLDEN[name]['entries'])


@pytest.mark.parametrize('args', [
    ['--filter', '+ *.jpg', '--filter', '- processed/', '--filter', '- *'],
    ['--exclude', 'raw/', '--include', '*.tif'],
    ['--filter', '- /data/raw/', '--filter', '- *.png'],
    ['--exclude', 'old/', '--exclude', '*.log'],
    ['--exclude', '{a,b}/', '--exclude', 'deep/'],
    ['--filter', '+ /scans/scan0*/**', '--filter', '- **'],
    ['--include', 'scan*/**'],
    ['--filter', '- /data/processed/deep/', '--filter', '+ /data/**',
     '--filter', '- **'],
    ['--filter', '+ intermediate/', '--filter', '- intermediate*'],
    ['--filter', '+ /data/raw/', '--filter', '- raw/', '--filter', '- *.tif'],
    ['--filter', '- /a/b/', '--filter', '+ a/**', '--filter', '- *'],
    ['--exclude', 'data/*'],
    ['--filter', '+ dat*/', '--filter', '- data/'],
    ['--include', '*/img.tif'],
])
def test_split_equivalence_planner_edges(args):
    """Rule shapes that stress the client/server split, checked against the
    pure matcher."""
    filt = build_filter(args)
    plan = build_plan(FakeTransferClient(), EP, SRC, DST, filt)
    assert_equivalent(plan, walk(filt))


class TestBuildPlan:
    def plan(self, args, tc=None):
        tc = tc or FakeTransferClient()
        return build_plan(tc, EP, SRC, DST, build_filter(args)), tc

    def test_no_filter_single_recursive_item(self):
        plan, tc = self.plan([])
        assert plan.items == [(SRC, DST, True)]
        assert plan.filter_rules == []
        assert plan.mkdirs == []
        assert tc.ls_calls == []

    def test_basename_rules_pushed_without_listing(self):
        plan, tc = self.plan(['--exclude', 'intermediate.tar.gz',
                              '--exclude', 'raw/'])
        assert plan.items == [(SRC, DST, True)]
        assert plan.filter_rules == [
            ('intermediate.tar.gz', 'exclude', 'file'),
            ('raw', 'exclude', 'dir')]
        assert tc.ls_calls == []

    def test_subdir_selection(self):
        plan, tc = self.plan(['--filter', '- intermediate.tar.gz',
                              '--filter', '+ /data/**',
                              '--filter', '+ /scans/**',
                              '--filter', '- **'])
        assert plan.items == [(f'{SRC}/data', f'{DST}/data', True),
                              (f'{SRC}/scans', f'{DST}/scans', True)]
        assert plan.filter_rules == [
            ('intermediate.tar.gz', 'exclude', 'file')]
        # only the root is listed, and only for directories
        assert tc.ls_calls == [(SRC, 0, plan_mod.LS_PAGE_SIZE, 'type:dir')]
        assert plan.mkdirs == []

    def test_anchored_file_walks_only_its_parents(self):
        plan, tc = self.plan(['--include', '/a/b/c.txt'])
        assert plan.items == [(f'{SRC}/a/b/c.txt', f'{DST}/a/b/c.txt',
                               False)]
        assert [c[0] for c in tc.ls_calls] == [SRC, f'{SRC}/a',
                                               f'{SRC}/a/b']
        assert plan.mkdirs == []
        assert plan.dirs_listed == 3
        assert plan.depth == 2

    def test_only_empty_dirs_need_mkdir(self):
        plan, _ = self.plan(['--include', '/logs/run1.log',
                             '--include', '/empty/x'])
        assert plan.items == [(f'{SRC}/logs/run1.log', f'{DST}/logs/run1.log',
                               False)]
        # the root and logs/ are created as parents of logs/run1.log
        assert plan.mkdirs == [f'{DST}/empty']

    def test_nothing_matched_creates_root(self):
        plan, _ = self.plan(['--include', '/missing/x'])
        assert plan.items == []
        assert plan.mkdirs == [DST]

    def test_conflicting_subtree_rules_are_walked(self):
        # data/ and logs/ would need different Globus rules
        plan, _ = self.plan(['--filter', '- /data/*.png',
                             '--filter', '- /logs/*.log'])
        recursive = [i for i in plan.items if i[2]]
        assert len({i[0] for i in recursive}) == len(recursive)
        assert (f'{SRC}/logs/run1.log', f'{DST}/logs/run1.log',
                False) not in plan.items

    def test_too_many_rules_falls_back_to_walk(self, monkeypatch):
        monkeypatch.setattr(plan_mod, 'MAX_FILTER_RULES', 1)
        plan, tc = self.plan(['--exclude', '*.{tif,log}'])
        assert plan.filter_rules == []
        assert all(not recursive for _, _, recursive in plan.items)
        assert plan.dirs_listed == len(CHILDREN)

    def test_unpushable_rule_warns(self, caplog):
        plan, _ = self.plan(['--exclude', '{{\\d}}.tif'])
        assert 'cannot be run by Globus' in caplog.text
        assert plan.dirs_listed == len(CHILDREN)

    def test_files_from_lists_only_parents(self, tmp_path):
        tc = FakeTransferClient()
        plan = build_plan(tc, EP, SRC, DST, case_filter('files_from', tmp_path))
        assert sorted(c[0] for c in tc.ls_calls) == sorted(
            [SRC, f'{SRC}/data', f'{SRC}/logs', f'{SRC}/logs/old',
             f'{SRC}/scans', f'{SRC}/scans/scan01'])
        assert all(not recursive for _, _, recursive in plan.items)

    def test_ls_error_propagates(self):
        tc = FakeTransferClient(children={})
        with pytest.raises(globus_sdk.TransferAPIError):
            build_plan(tc, EP, SRC, DST, build_filter(['--include', '/a/**']))


class TestLsAll:
    def test_pages(self, monkeypatch):
        monkeypatch.setattr(plan_mod, 'LS_PAGE_SIZE', 2)
        children = {'': ({f'd{i}' for i in range(5)}, set())}
        entries, calls = ls_all(FakeTransferClient(children), EP, SRC)
        assert sorted(e['name'] for e in entries) == [f'd{i}'
                                                      for i in range(5)]
        assert calls == 3

    def test_exact_multiple_of_page_size(self, monkeypatch):
        monkeypatch.setattr(plan_mod, 'LS_PAGE_SIZE', 2)
        children = {'': ({'a', 'b', 'c', 'd'}, set())}
        tc = FakeTransferClient(children)
        entries, calls = ls_all(tc, EP, SRC)
        assert len(entries) == 4
        assert [c[1] for c in tc.ls_calls] == [0, 2, 4]

    def test_has_next_page_false_stops(self, monkeypatch):
        monkeypatch.setattr(plan_mod, 'LS_PAGE_SIZE', 2)

        class TC:
            calls = 0

            def operation_ls(self, *args, **kwargs):
                self.calls += 1
                return {'DATA': [{'name': 'a'}, {'name': 'b'}],
                        'has_next_page': False}

        tc = TC()
        assert ls_all(tc, EP, SRC)[1] == 1


class TestMkdirP:
    def test_creates_in_order_and_dedupes(self):
        tc = FakeTransferClient()
        mkdir_p(tc, EP, ['/d', '/d/a', '/d', '/d/a/b'])
        assert tc.mkdirs == ['/d', '/d/a', '/d/a/b']

    def test_creates_missing_parents(self):
        tc = FakeTransferClient(existing={'/', '/d'})
        mkdir_p(tc, EP, ['/d/a/b', '/d/a/c'])
        assert tc.existing == {'/', '/d', '/d/a', '/d/a/b', '/d/a/c'}
        assert tc.mkdirs == ['/d/a/b', '/d/a', '/d/a/b', '/d/a/c']

    def test_exists_is_success(self):
        tc = FakeTransferClient(existing={'/d'})
        mkdir_p(tc, EP, ['/d', '/d/a'])
        assert tc.mkdirs == ['/d', '/d/a']

    def test_other_errors_raise(self):
        err = api_error('ExternalError.MkdirFailed.PermissionDenied',
                        'Permission denied')
        tc = FakeTransferClient(mkdir_errors={'/d/a': err})
        with pytest.raises(globus_sdk.TransferAPIError):
            mkdir_p(tc, EP, ['/d', '/d/a', '/d/a/b'])
        assert tc.mkdirs == ['/d', '/d/a']

    def test_persistent_not_found_raises(self):
        err = api_error('NotFound', 'Path not found', 404)
        tc = FakeTransferClient(existing={'/', '/d'},
                                mkdir_errors={'/d/a': err})
        with pytest.raises(globus_sdk.TransferAPIError):
            mkdir_p(tc, EP, ['/d/a'])
        assert tc.mkdirs == ['/d/a', '/d', '/d/a']

    def test_not_found_at_root_raises(self):
        err = api_error('NotFound', 'Path not found', 404)
        tc = FakeTransferClient(mkdir_errors={'/': err, '/d': err})
        with pytest.raises(globus_sdk.TransferAPIError):
            mkdir_p(tc, EP, ['/d'])


def test_add_to_transfer():
    tx = globus_sdk.TransferData(source_endpoint='a', destination_endpoint='b')
    Plan(items=[('/s', '/d', True), ('/s/f', '/d/f', False)],
         filter_rules=[('*.tmp', 'exclude', 'file'),
                       ('raw', 'exclude', 'dir')]).add_to_transfer(tx)
    rules = [{k: v for k, v in r.items() if v is not globus_sdk.MISSING}
             for r in tx['filter_rules']]
    assert rules == [
        {'DATA_TYPE': 'filter_rule', 'name': '*.tmp', 'method': 'exclude',
         'type': 'file'},
        {'DATA_TYPE': 'filter_rule', 'name': 'raw', 'method': 'exclude',
         'type': 'dir'}]
    assert [(i['source_path'], i['recursive']) for i in tx['DATA']] == [
        ('/s', True), ('/s/f', False)]
