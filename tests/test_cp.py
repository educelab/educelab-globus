import pytest
from pathlib import PurePosixPath

from educelab.globus.cp.main import to_posix_path, resolve_path, _fmt_bytes


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
