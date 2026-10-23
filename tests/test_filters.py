import pytest

from educelab.globus.cp.filters import FilterError
from filter_helpers import GOLDEN, SPEC, build_filter, case_filter, walk


@pytest.mark.parametrize('name', sorted(SPEC['cases']))
def test_golden(name, tmp_path):
    expected = GOLDEN[name]
    if 'error' in expected:
        with pytest.raises(FilterError):
            case_filter(name, tmp_path)
        return
    assert walk(case_filter(name, tmp_path)) == expected['entries']


def test_golden_covers_all_cases():
    assert set(GOLDEN) == set(SPEC['cases'])


class TestSubtreeRules:
    @pytest.mark.parametrize('args,path,expected', [
        ([], '', []),
        (['--exclude', 'intermediate.tar.gz'], '',
         [('intermediate.tar.gz', 'exclude', 'file')]),
        (['--exclude', 'raw/'], '', [('raw', 'exclude', 'dir')]),
        (['--exclude', '*'], '',
         [('*', 'exclude', 'file'), ('*', 'exclude', 'dir')]),
        (['--include', '*.{jpg,png}'], 'data',
         [('*.jpg', 'include', 'file'), ('*.png', 'include', 'file'),
          ('*', 'exclude', 'file')]),
        (['--exclude', 'run[^0].log'], '',
         [('run[!0].log', 'exclude', 'file')]),
        # anchored rules resolve once the walk is inside them
        (['--filter', '- *.tmp', '--filter', '+ /data/**',
          '--filter', '- **'], 'data', [('*.tmp', 'exclude', 'file')]),
        (['--exclude', '/data/raw/'], 'data/processed', []),
        (['--include', '/data/**/*.jpg'], 'data/processed',
         [('*.jpg', 'include', 'file'), ('*', 'exclude', 'file')]),
    ])
    def test_pushable(self, args, path, expected):
        rules, reason = build_filter(args).subtree_rules(path)
        assert reason is None
        assert rules == expected

    @pytest.mark.parametrize('args,path', [
        (['--exclude', '/data/raw/'], ''),
        (['--exclude', '/data/raw/'], 'data'),
        (['--include', '/data/**'], ''),
        (['--exclude', 'b/c.txt'], ''),
        (['--include', '/logs/*.log'], 'logs'),
        (['--include', '{{scan\\d+}}/meta.json'], 'scans'),
        (['--exclude', 'x\\[1\\].txt'], ''),
        (['--exclude', '**.tmp'], 'data'),
        (['--include', '/data/**/*.jpg'], 'data'),
        # an earlier include could let a raw/ dir through
        (['--filter', '+ /data/raw/', '--filter', '- raw/'], 'data'),
    ])
    def test_walk_needed(self, args, path):
        rules, reason = build_filter(args).subtree_rules(path)
        assert rules is None and reason

    def test_files_from(self, tmp_path):
        filt = case_filter('files_from', tmp_path)
        assert filt.subtree_rules('') == (None, '--files-from')


class TestNeedsChildFiles:
    @pytest.mark.parametrize('args,path,expected', [
        ([], '', True),
        (['--include', '/data/**'], '', False),
        (['--include', '/data/**'], 'data', True),
        (['--include', '*.jpg'], '', True),
        (['--filter', '+ /logs/', '--filter', '- *'], 'logs', False),
        (['--exclude', '*.tif'], '', True),
    ])
    def test_rules(self, args, path, expected):
        assert build_filter(args).needs_child_files(path) is expected

    def test_files_from(self, tmp_path):
        filt = case_filter('files_from', tmp_path)
        assert filt.needs_child_files('data')
        assert not filt.needs_child_files('scans')


def test_negated_class_excludes_slash():
    filt = build_filter(['--exclude', 'a[^x]b'])
    assert not filt.include_file('dir/a-b')
    assert filt.include_file('a/b')


def test_rules_track_clear():
    filt = build_filter(['--filter', '- *.jpg', '--filter', '!',
                         '--filter', '- *.png'])
    assert [str(r) for r in filt.rules] == ['- *.png']


def test_include_adds_implicit_exclude():
    filt = build_filter(['--include', '*.jpg'])
    assert [str(r) for r in filt.rules] == ['+ *.jpg', '- /**']
