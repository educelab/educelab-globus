"""Regenerate tests/data/filter_golden.json by running rclone on the cases in
tests/data/filter_cases.json.

rclone is only needed to regenerate the golden file, not to run the tests:

    python tests/gen_filter_golden.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DATA_DIR = Path(__file__).parent / 'data'
CASES_FILE = DATA_DIR / 'filter_cases.json'
GOLDEN_FILE = DATA_DIR / 'filter_golden.json'


def normalize_case(case):
    """Cases are either a list of args or {'args': [...], 'files': {...}}."""
    if isinstance(case, list):
        return {'args': case, 'files': {}}
    return {'args': case['args'], 'files': case.get('files', {})}


def build_tree(root, tree):
    for entry in tree:
        path = root / entry
        if entry.endswith('/'):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(entry)


def run_rclone(rclone, src, args, env):
    proc = subprocess.run([rclone, 'lsf', '-R', *args, str(src)],
                          capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        return {'error': proc.stderr.strip().splitlines()[-1]}
    return {'entries': sorted(proc.stdout.splitlines())}


def main():
    rclone = shutil.which('rclone')
    if rclone is None:
        sys.exit('rclone not found on PATH')
    version = subprocess.run([rclone, 'version'], capture_output=True,
                             text=True, check=True).stdout.splitlines()[0]

    spec = json.loads(CASES_FILE.read_text())
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / 'src'
        build_tree(src, spec['tree'])
        conf = tmp / 'rclone.conf'
        conf.touch()
        env = {**os.environ, 'RCLONE_CONFIG': str(conf)}

        for name, case in spec['cases'].items():
            case = normalize_case(case)
            case_dir = tmp / 'cases' / name
            case_dir.mkdir(parents=True)
            for fname, content in case['files'].items():
                (case_dir / fname).write_text(content)
            args = [a.replace('{tmp}', str(case_dir)) for a in case['args']]
            results[name] = run_rclone(rclone, src, args, env)
            outcome = ('error' if 'error' in results[name]
                       else f'{len(results[name]["entries"])} entries')
            print(f'{name}: {outcome}')

    golden = {'generator': version, 'cases': results}
    GOLDEN_FILE.write_text(json.dumps(golden, indent=2) + '\n')
    print(f'wrote {GOLDEN_FILE}')


if __name__ == '__main__':
    main()
