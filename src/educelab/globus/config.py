from pathlib import Path
import sys
from functools import lru_cache
import logging
from typing import List, Dict

_cfg_path = Path.home() / '.globuscp' / 'config.toml'


def has_config():
    return _cfg_path.exists()


@lru_cache(maxsize=2)
def _load_config():
    """Load config as a dictionary."""
    logger = logging.getLogger('educelab.globus')
    if not has_config():
        return {}

    if sys.version_info < (3, 11):
        logger.debug('config backend: configparser')
        import configparser
        with _cfg_path.open('r') as f:
            cfg = configparser.ConfigParser()
            cfg.read_file(f)
            cfg = {s: dict(cfg.items(s)) for s in cfg.sections()}

    else:
        logger.debug('config backend: tomllib')
        import tomllib
        with _cfg_path.open('rb') as f:
            cfg = tomllib.load(f)

    return cfg


def endpoints() -> Dict:
    return _load_config()


def endpoint_names() -> List[str]:
    cfg = _load_config()
    return list(cfg.keys())


def endpoint_uuids() -> List[str]:
    cfg = _load_config()
    return [c['uuid'] for c in cfg.values()]


def get_endpoint(key: str):
    cfg = _load_config()
    return cfg.get(key, None)


def main():
    config_present = has_config()
    print(f'Config detected: {config_present}')
    if not config_present:
        return

    end_pts = endpoints()
    print(f'Number of endpoints: {len(end_pts)}')
    print()

    for name, val in end_pts.items():
        print(f'[{name}]')
        print(f' - UUID: {val["uuid"]}')
        if 'basedir' in val.keys():
            print(f' - Base directory: {val["basedir"]}')
        print()


if __name__ == '__main__':
    main()
