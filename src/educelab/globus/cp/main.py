import argparse
import json
import logging
import shutil
import sys
import time
from datetime import datetime as dt, timezone as tz
from pathlib import PurePosixPath, PureWindowsPath

import globus_sdk

import educelab.globus as globus
from educelab.globus._cli import setup_logging


def to_posix_path(path):
    if '\\' in path:
        path = PureWindowsPath(path)
    else:
        return PurePosixPath(path)

    parts = [p.replace('\\', '') for p in path.parts]

    if ':' in parts[0]:
        parts[0] = '/' + parts[0].replace(':', '')

    return PurePosixPath(*parts)


def resolve_path(endpoint, path_str):
    """Resolve a user-supplied path string against the endpoint's basedir."""
    basedir = endpoint.get('basedir', '')
    if not path_str:
        if not basedir:
            raise ValueError(
                'no path provided and endpoint has no basedir configured')
        return str(to_posix_path(basedir))
    path = to_posix_path(path_str)
    if path.is_absolute():
        return str(path)
    if not basedir:
        raise ValueError(
            f'relative path {path_str!r} requires endpoint basedir to be configured')
    return str(to_posix_path(basedir) / path)


def _fmt_bytes(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(n) < 1024:
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} PB'


def _print_progress(task_info):
    status = task_info.get('status', 'ACTIVE')
    files_done = task_info.get('files_transferred') or 0
    files_total = task_info.get('files') or 0
    transferred = task_info.get('bytes_transferred') or 0
    speed = task_info.get('effective_bytes_per_second') or 0

    if status == 'INACTIVE':
        line = 'Transfer paused (INACTIVE) — check Globus Web App for details'
    elif files_total == 0:
        line = 'Queued, waiting for transfer to start...'
    else:
        line = (f'{files_done}/{files_total} files  '
                f'{_fmt_bytes(transferred)} transferred  '
                f'{_fmt_bytes(speed)}/s')

    cols = shutil.get_terminal_size().columns
    print(f'\r{line:<{cols}}', end='', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'src', metavar='endpoint:path',
        help='Source in endpoint-name:/abs/path or endpoint-name:rel/path format')
    parser.add_argument(
        'dst', metavar='endpoint:path',
        help='Destination in endpoint-name:/abs/path or endpoint-name:rel/path format')
    parser.add_argument('--label', help='Transfer label shown in the Globus UI')

    tx_opts = parser.add_argument_group('transfer options')
    tx_opts.add_argument('--background', '-b', action='store_true',
                         help='Background mode: Exit immediately after '
                              'submitting the transfer task')
    tx_opts.add_argument('--notify-success', default=False,
                         action=argparse.BooleanOptionalAction,
                         help='Send a notification e-mail when the transfer '
                              'completes successfully')
    tx_opts.add_argument('--notify-failed', default=True,
                         action=argparse.BooleanOptionalAction,
                         help='Send a notification e-mail when the transfer '
                              'fails')
    tx_opts.add_argument('--notify-inactive', default=True,
                         action=argparse.BooleanOptionalAction,
                         help='Send a notification e-mail when the transfer '
                              'enters an inactive state')
    tx_opts.add_argument('--verify', default=False, action='store_true',
                         help='Enable checksum verification on transfer')
    tx_opts.add_argument('--sync-level', choices=('exists', 'size', 'mtime',
                                                  'checksum'),
                         help='Only transfer files where the destination does '
                              'not match the source: exists (dst missing), '
                              'size (size differs), mtime (dst older than '
                              'src), checksum (checksums differ). Default: '
                              'transfer all files unconditionally')
    log_opts = parser.add_mutually_exclusive_group()
    log_opts.add_argument('--verbose', '-v', action='store_true',
                          help='Enable debug logging')
    log_opts.add_argument('--quiet', '-q', action='store_true',
                          help='Only log warnings and errors')
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, quiet=args.quiet)
    logger = logging.getLogger(__name__)

    valid_endpoints = globus.endpoint_names()

    def parse_ep_path(arg, label):
        if ':' not in arg:
            parser.error(
                f"{label}: expected 'endpoint-name:path' format, got '{arg}'")
        name, _, path_str = arg.partition(':')
        if name not in valid_endpoints:
            parser.error(
                f"{label}: unknown endpoint '{name}', "
                f"choose from: {', '.join(valid_endpoints)}")
        return name, path_str

    src_name, src_path_str = parse_ep_path(args.src, 'src')
    dst_name, dst_path_str = parse_ep_path(args.dst, 'dst')

    src = globus.get_endpoint(src_name)
    dst = globus.get_endpoint(dst_name)
    logger.info(f'source endpoint: {src_name}, destination endpoint: {dst_name}')

    try:
        src_path = resolve_path(src, src_path_str)
        dst_path = resolve_path(dst, dst_path_str)
    except ValueError as e:
        parser.error(str(e))

    # login
    uuids = [src['uuid'], dst['uuid']]
    logger.debug(f'logging in to Globus endpoints: {", ".join(uuids)}')
    try:
        tc = globus.login(uuids)
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)
    except globus_sdk.TransferAPIError as e:
        logger.error(f'Globus API error during login: {e.message}')
        sys.exit(1)

    # stat source to determine file vs directory
    try:
        stat = tc.operation_stat(src['uuid'], src_path)
    except globus_sdk.TransferAPIError as e:
        if e.http_status == 404:
            logger.error(f'source path not found: {src_path}')
        elif e.http_status == 403:
            logger.error(f'permission denied reading source: {src_path}')
        else:
            logger.error(f'error accessing source path: {e.message}')
        sys.exit(1)
    pathtype = stat.get('type')
    recursive = pathtype == 'dir'

    # ensure the destination directory (or parent, for file transfers) exists
    mkdir_path = dst_path if recursive else str(PurePosixPath(dst_path).parent)
    logger.debug(f'ensuring destination directory exists: {mkdir_path}')
    try:
        tc.operation_mkdir(dst['uuid'], mkdir_path)
    except globus_sdk.TransferAPIError as e:
        if 'Exists' in (e.code or '') or 'exist' in (e.message or '').lower():
            pass
        else:
            logger.error(f'failed to create destination directory: {e.message}')
            sys.exit(1)

    # build the transfer task
    label = args.label
    if args.label is None:
        now = dt.now(tz=tz.utc)
        now_str = now.strftime('%m/%d/%Y, %H:%M:%S')
        label = f'Pipeline transfer ({now_str})'
    logger.info(f'building transfer task: {label}')
    tx = globus_sdk.TransferData(source_endpoint=src['uuid'],
                                 destination_endpoint=dst['uuid'],
                                 label=label,
                                 sync_level=args.sync_level,
                                 notify_on_succeeded=args.notify_success,
                                 notify_on_failed=args.notify_failed,
                                 notify_on_inactive=args.notify_inactive,
                                 verify_checksum=args.verify)

    logger.debug(f'{src_path} -> {dst_path} (recursive: {recursive})')
    tx.add_item(src_path, dst_path, recursive=recursive)

    # queue the transfer task
    logger.info('submitting transfer task...')
    try:
        task = tc.submit_transfer(tx)
    except globus_sdk.TransferAPIError as e:
        logger.error(f'failed to submit transfer task: {e.message}')
        sys.exit(1)
    task_id = task['task_id']
    logger.info(f'successfully submitted transfer task: {task_id}')

    if args.background:
        sys.exit()

    # wait for completion
    logger.info('waiting for transfer to complete...')
    use_progress = sys.stdout.isatty()
    while True:
        try:
            task_info = tc.get_task(task_id)
        except globus_sdk.TransferAPIError as e:
            logger.warning(f'error polling task status: {e.message}')
            time.sleep(5)
            continue

        if task_info['status'] == 'ACTIVE':
            try:
                task_events = tc.task_event_list(
                    task_id, query_params={'filter': 'is_error:1'})['DATA']
            except globus_sdk.TransferAPIError as e:
                logger.debug(f'error fetching task events: {e.message}')
                task_events = []

            if task_events:
                if use_progress:
                    print(flush=True)
                logger.debug(task_events)
                ev = task_events[0]
                err_desc = ev.get('description', 'unknown error')
                err_path = ''
                try:
                    details = json.loads(ev.get('details', '{}'))
                    path = details['context'][0].get('path')
                    if path:
                        err_path = f": '{path}'"
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    pass
                logger.error(f'transfer failed. {err_desc}{err_path}')
                try:
                    tc.cancel_task(task_id)
                except globus_sdk.TransferAPIError:
                    pass
                sys.exit(1)

        if use_progress:
            _print_progress(task_info)

        if task_info['status'] not in ('ACTIVE', 'INACTIVE'):
            break

        time.sleep(5)

    if use_progress:
        print(flush=True)
    if task_info['status'] == 'FAILED':
        fatal = task_info.get('fatal_error') or {}
        err_desc = fatal.get('description', 'unknown error')
        logger.error(f'transfer task failed: {err_desc}')
        sys.exit(1)
    logger.info('done.')


if __name__ == "__main__":
    main()
