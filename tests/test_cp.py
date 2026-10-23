import sys

import pytest
from pathlib import PurePosixPath

import educelab.globus as globus
from educelab.globus.cp import main as cp_main
from educelab.globus.cp.main import to_posix_path, resolve_path, _fmt_bytes
from filter_helpers import DST, EP, SRC, FakeTransferClient


# ---------------------------------------------------------------------------
# to_posix_path
# ---------------------------------------------------------------------------

class TestToPosixPath:
    def test_posix_absolute(self):
        assert to_posix_path('/data/files') == PurePosixPath('/data/files')

    def test_posix_relative(self):
        assert to_posix_path('data/files') == PurePosixPath('data/files')

    def test_windows_backslashes(self):
        assert to_posix_path('data\\files\\item') == PurePosixPath('data/files/item')

    def test_windows_drive_letter(self):
        assert to_posix_path('C:\\Users\\user\\data') == PurePosixPath('/C/Users/user/data')

    def test_windows_lowercase_drive(self):
        assert to_posix_path('d:\\projects\\exp') == PurePosixPath('/d/projects/exp')

    def test_posix_root(self):
        assert to_posix_path('/') == PurePosixPath('/')


# ---------------------------------------------------------------------------
# resolve_path
# ---------------------------------------------------------------------------

class TestResolvePath:
    def test_absolute_path_ignores_basedir(self):
        ep = {'uuid': 'x', 'basedir': '/base'}
        assert resolve_path(ep, '/abs/path') == '/abs/path'

    def test_absolute_path_no_basedir(self):
        ep = {'uuid': 'x'}
        assert resolve_path(ep, '/abs/path') == '/abs/path'

    def test_relative_path_joined_to_basedir(self):
        ep = {'uuid': 'x', 'basedir': '/base'}
        assert resolve_path(ep, 'rel/path') == '/base/rel/path'

    def test_empty_path_returns_basedir(self):
        ep = {'uuid': 'x', 'basedir': '/base/dir'}
        assert resolve_path(ep, '') == '/base/dir'

    def test_relative_path_no_basedir_raises(self):
        with pytest.raises(ValueError, match='basedir'):
            resolve_path({'uuid': 'x'}, 'rel/path')

    def test_empty_path_no_basedir_raises(self):
        with pytest.raises(ValueError, match='basedir'):
            resolve_path({'uuid': 'x'}, '')

    def test_windows_path_resolved(self):
        ep = {'uuid': 'x', 'basedir': '/base'}
        result = resolve_path(ep, 'sub\\dir')
        assert result == '/base/sub/dir'


# ---------------------------------------------------------------------------
# _fmt_bytes
# ---------------------------------------------------------------------------

class TestFmtBytes:
    @pytest.mark.parametrize('n,expected', [
        (0,              '0.0 B'),
        (512,            '512.0 B'),
        (1023,           '1023.0 B'),
        (1024,           '1.0 KB'),
        (1536,           '1.5 KB'),
        (1024 ** 2,      '1.0 MB'),
        (1024 ** 3,      '1.0 GB'),
        (1024 ** 4,      '1.0 TB'),
        (1024 ** 5,      '1.0 PB'),
    ])
    def test_units(self, n, expected):
        assert _fmt_bytes(n) == expected


# ---------------------------------------------------------------------------
# main() with a fake TransferClient
# ---------------------------------------------------------------------------

class CpTransferClient(FakeTransferClient):
    def __init__(self):
        super().__init__()
        self.submitted = []

    def operation_stat(self, endpoint_id, path):
        return {'type': 'dir' if path == SRC else 'file', 'size': 10}

    def submit_transfer(self, tx):
        self.submitted.append(tx)
        return {'task_id': 'task-1'}


@pytest.fixture
def run_cp(monkeypatch):
    tc = CpTransferClient()
    endpoints = {'src': {'uuid': EP}, 'dst': {'uuid': 'dst-uuid'}}
    monkeypatch.setattr(globus, 'endpoint_names', lambda: list(endpoints))
    monkeypatch.setattr(globus, 'get_endpoint', endpoints.__getitem__)
    monkeypatch.setattr(globus, 'login', lambda uuids: tc)

    def run(*args, src=SRC):
        monkeypatch.setattr(sys, 'argv', ['el-globus-cp', f'src:{src}',
                                          f'dst:{DST}', '--background',
                                          *args])
        try:
            cp_main.main()
        except SystemExit as e:
            if e.code:
                raise
        return tc

    return run


class TestMain:
    def test_filtered_transfer(self, run_cp):
        tc = run_cp('--filter', '- intermediate.tar.gz',
                    '--filter', '+ /data/**', '--filter', '- **')
        assert tc.mkdirs == []
        tx, = tc.submitted
        assert [r['name'] for r in tx['filter_rules']] == [
            'intermediate.tar.gz']
        assert [(i['source_path'], i['recursive']) for i in tx['DATA']] == [
            (f'{SRC}/data', True)]

    def test_unfiltered_transfer_unchanged(self, run_cp):
        tc = run_cp()
        tx, = tc.submitted
        assert 'filter_rules' not in tx
        assert [(i['source_path'], i['destination_path'], i['recursive'])
                for i in tx['DATA']] == [(SRC, DST, True)]
        assert tc.ls_calls == []

    def test_empty_dirs_created_before_submit(self, run_cp):
        tc = run_cp('--include', '/logs/run1.log', '--include', '/empty/x')
        assert f'{DST}/empty' in tc.existing
        tx, = tc.submitted
        assert [i['source_path'] for i in tx['DATA']] == [
            f'{SRC}/logs/run1.log']

    def test_nothing_matched_skips_submit(self, run_cp):
        tc = run_cp('--include', '/missing/x')
        assert DST in tc.existing
        assert tc.submitted == []

    def test_dry_run_changes_nothing(self, run_cp, capsys):
        tc = run_cp('--dry-run', '--include', '/a/b/c.txt')
        assert tc.mkdirs == [] and tc.submitted == []
        out = capsys.readouterr().out
        assert f'[file] {SRC}/a/b/c.txt -> {DST}/a/b/c.txt' in out
        assert 'Source directories listed: 3' in out

    def test_dry_run_files(self, run_cp, capsys):
        tc = run_cp('--dry-run-files', '--include', '*.json')
        assert tc.mkdirs == [] and tc.submitted == []
        assert capsys.readouterr().out.splitlines() == [
            'scans/scan01/meta.json', 'scans/scan02/meta.json',
            '2 files, 20.0 B']

    def test_filters_on_file_source_fail(self, run_cp):
        with pytest.raises(SystemExit) as e:
            run_cp('--exclude', '*.tmp', src=f'{SRC}/README.md')
        assert e.value.code == 1

    def test_bad_rule_is_usage_error(self, run_cp):
        with pytest.raises(SystemExit) as e:
            run_cp('--filter', 'oops')
        assert e.value.code == 2
