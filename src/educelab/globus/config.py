import argparse
import json as _json
import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Dict

from educelab.globus._cli import setup_logging as _setup_logging

_cfg_path = Path.home() / '.globuscp' / 'config.toml'


def has_config():
    return _cfg_path.exists()


@lru_cache(maxsize=2)
def _load_config():
    """Load config as a dictionary."""
    logger = logging.getLogger('educelab.globus')
    if not has_config():
        return {}

    if sys.version_info >= (3, 11):
        logger.debug('config backend: tomllib')
        import tomllib
    else:
        logger.debug('config backend: tomli')
        import tomli as tomllib

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


def _toml_key(name: str) -> str:
    """Return a TOML-safe table key: bare if possible, quoted otherwise."""
    if all(c.isalnum() or c in '-_' for c in name):
        return name
    return _json.dumps(name)


def _save_config(cfg: Dict) -> None:
    """Serialize cfg back to TOML and write to disk."""
    _cfg_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, vals in cfg.items():
        lines.append(f'[{_toml_key(name)}]')
        for k, v in vals.items():
            lines.append(f'{k} = {_json.dumps(str(v))}')
        lines.append('')
    _cfg_path.write_text('\n'.join(lines), encoding='utf-8')
    _load_config.cache_clear()


def _fresh_cfg() -> Dict:
    """Return a mutable deep-ish copy of the current config."""
    return {k: dict(v) for k, v in _load_config().items()}


def _prompt_value(label: str, default: str = '') -> str | None:
    """Prompt for a value with an editable default. Returns None on Ctrl-C."""
    from prompt_toolkit import prompt as _prompt
    try:
        return _prompt(f'{label}: ', default=default).strip()
    except (KeyboardInterrupt, EOFError):
        return None


def _choose() -> str:
    """Read a menu selection. Returns empty string on Ctrl-C."""
    try:
        return input('> ').strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return ''


def _edit_endpoint(cfg: Dict, name: str) -> None:
    """CLI menu for editing a single endpoint. Mutates cfg and saves on change."""
    while True:
        entry = cfg[name]
        uuid_val = entry.get('uuid', '')
        basedir_val = entry.get('basedir', '(default: /)')

        print(f'\n{name}')
        print(f'  UUID:     {uuid_val}')
        print(f'  Base dir: {basedir_val}')
        print()
        print('  1) Edit UUID')
        print('  2) Edit base directory')
        print('  3) Rename')
        print('  4) Delete')
        print('  b) Back')
        print()

        choice = _choose()

        if choice == '1':
            new_val = _prompt_value('UUID', default=uuid_val)
            if new_val is None or not new_val:
                continue
            cfg[name]['uuid'] = new_val
            _save_config(cfg)
            print('Saved.')

        elif choice == '2':
            new_val = _prompt_value('Base directory (blank to remove)',
                                    default=entry.get('basedir', ''))
            if new_val is None:
                continue
            if new_val:
                cfg[name]['basedir'] = new_val
            else:
                cfg[name].pop('basedir', None)
            _save_config(cfg)
            print('Saved.')

        elif choice == '3':
            new_name = _prompt_value('New name', default=name)
            if new_name is None or not new_name or new_name == name:
                continue
            if new_name in cfg:
                print(f'Error: "{new_name}" already exists.')
                continue
            cfg[new_name] = cfg.pop(name)
            name = new_name
            _save_config(cfg)
            print('Saved.')

        elif choice == '4':
            confirm = input(f'Delete "{name}"? [y/N] ').strip().lower()
            if confirm == 'y':
                del cfg[name]
                _save_config(cfg)
                print('Deleted.')
                return

        elif choice in ('b', ''):
            return


def edit_mode() -> None:
    """Interactive CLI menu for editing the Globus endpoint config."""
    while True:
        cfg = _fresh_cfg()
        names = list(cfg)

        print('\nEndpoints')
        print('---------')
        if names:
            for i, name in enumerate(names, 1):
                uuid_short = cfg[name].get('uuid', '')[:8] + '...'
                basedir = cfg[name].get('basedir', '/')
                suffix = f'  {basedir}'
                print(f'  {i}) {name}  [{uuid_short}]{suffix}')
            print()
            print('  Enter a number to edit that endpoint.')
        else:
            print('  (none)')
        print()
        print('  a) Add endpoint')
        print('  q) Quit')
        print()

        choice = _choose()

        if choice in ('q', ''):
            return

        if choice == 'a':
            print()
            name = _prompt_value('Name')
            if not name:
                continue
            if name in cfg:
                print(f'Error: "{name}" already exists.')
                continue
            uuid_val = _prompt_value('UUID')
            if not uuid_val:
                continue
            basedir_val = _prompt_value('Base directory (optional)')
            if basedir_val is None:
                continue
            entry: Dict = {'uuid': uuid_val}
            if basedir_val:
                entry['basedir'] = basedir_val
            cfg[name] = entry
            _save_config(cfg)
            print('Saved.')
            continue

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                _edit_endpoint(cfg, names[idx])
                continue

        print(f'Invalid choice: {choice!r}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--edit', '-e', action='store_true',
                        help='Interactively edit the config')
    log_opts = parser.add_mutually_exclusive_group()
    log_opts.add_argument('--verbose', '-v', action='store_true',
                          help='Enable debug logging')
    log_opts.add_argument('--quiet', '-q', action='store_true',
                          help='Only log warnings and errors')
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose, quiet=args.quiet)

    if args.edit:
        edit_mode()
        return

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
        print(f' - Base directory: {val.get("basedir", "/")}')
        print()


if __name__ == '__main__':
    main()
