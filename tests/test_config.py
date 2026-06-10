import pytest
import educelab.globus.config as config_mod
from educelab.globus.config import (
    _toml_key, _save_config, _load_config,
    has_config, endpoint_names, endpoint_uuids, get_endpoint,
)


@pytest.fixture(autouse=True)
def clear_lru_cache():
    _load_config.cache_clear()
    yield
    _load_config.cache_clear()


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    """Redirect the config module's path to a temp file."""
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(config_mod, '_cfg_path', path)
    return path


# ---------------------------------------------------------------------------
# _toml_key
# ---------------------------------------------------------------------------

class TestTomlKey:
    def test_alphanumeric(self):
        assert _toml_key('myendpoint') == 'myendpoint'

    def test_dash_and_underscore(self):
        assert _toml_key('my-endpoint_1') == 'my-endpoint_1'

    def test_dot_gets_quoted(self):
        assert _toml_key('server.name') == '"server.name"'

    def test_space_gets_quoted(self):
        assert _toml_key('my endpoint') == '"my endpoint"'

    def test_brackets_get_quoted(self):
        assert _toml_key('ep[0]') == '"ep[0]"'


# ---------------------------------------------------------------------------
# _save_config / _load_config round-trip
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_roundtrip_with_basedir(self, cfg_file):
        _save_config({'alpha': {'uuid': 'uuid-a', 'basedir': '/data/a'}})
        cfg = _load_config()
        assert cfg['alpha']['uuid'] == 'uuid-a'
        assert cfg['alpha']['basedir'] == '/data/a'

    def test_roundtrip_without_basedir(self, cfg_file):
        _save_config({'beta': {'uuid': 'uuid-b'}})
        cfg = _load_config()
        assert cfg['beta']['uuid'] == 'uuid-b'
        assert 'basedir' not in cfg['beta']

    def test_roundtrip_quoted_key(self, cfg_file):
        _save_config({'server.herc': {'uuid': 'uuid-dot'}})
        cfg = _load_config()
        assert 'server.herc' in cfg
        assert cfg['server.herc']['uuid'] == 'uuid-dot'

    def test_multiple_endpoints(self, cfg_file):
        data = {
            'ep-a': {'uuid': 'aaa', 'basedir': '/a'},
            'ep-b': {'uuid': 'bbb'},
        }
        _save_config(data)
        cfg = _load_config()
        assert set(cfg.keys()) == {'ep-a', 'ep-b'}

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        path = tmp_path / 'subdir' / 'config.toml'
        monkeypatch.setattr(config_mod, '_cfg_path', path)
        _save_config({'ep': {'uuid': 'x'}})
        assert path.exists()

    def test_cache_cleared_after_save(self, cfg_file):
        _save_config({'first': {'uuid': '1'}})
        assert 'first' in _load_config()
        _save_config({'second': {'uuid': '2'}})
        cfg = _load_config()
        assert 'second' in cfg
        assert 'first' not in cfg

    def test_missing_file_returns_empty(self, cfg_file):
        assert _load_config() == {}


# ---------------------------------------------------------------------------
# has_config
# ---------------------------------------------------------------------------

class TestHasConfig:
    def test_true_when_file_exists(self, cfg_file):
        cfg_file.write_text('')
        assert has_config() is True

    def test_false_when_missing(self, cfg_file):
        assert has_config() is False


# ---------------------------------------------------------------------------
# Accessor functions
# ---------------------------------------------------------------------------

SAMPLE = {
    'endpoint-a': {'uuid': 'aaa', 'basedir': '/mnt/a'},
    'endpoint-b': {'uuid': 'bbb'},
}


@pytest.fixture
def sample_config(cfg_file):
    _save_config(SAMPLE)


class TestAccessors:
    def test_endpoint_names(self, sample_config):
        assert set(endpoint_names()) == {'endpoint-a', 'endpoint-b'}

    def test_endpoint_uuids(self, sample_config):
        assert set(endpoint_uuids()) == {'aaa', 'bbb'}

    def test_get_endpoint_found(self, sample_config):
        ep = get_endpoint('endpoint-a')
        assert ep['uuid'] == 'aaa'
        assert ep['basedir'] == '/mnt/a'

    def test_get_endpoint_no_basedir(self, sample_config):
        ep = get_endpoint('endpoint-b')
        assert ep['uuid'] == 'bbb'
        assert 'basedir' not in ep

    def test_get_endpoint_missing(self, sample_config):
        assert get_endpoint('does-not-exist') is None

    def test_empty_config(self, cfg_file):
        assert endpoint_names() == []
        assert endpoint_uuids() == []
