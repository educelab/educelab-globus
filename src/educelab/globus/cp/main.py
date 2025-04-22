import argparse
import json
import logging
import sys
from datetime import datetime as dt, timezone as tz
from pathlib import PurePosixPath, PureWindowsPath

import globus_sdk

import educelab.globus as globus


def to_posix_path(path):
    # make a path-native object
    if '\\' in path:
        path = PureWindowsPath(path)
    else:
        # nothing to do if already posix
        return PurePosixPath(path)

    # change slash direction
    parts = [p.replace('\\', '') for p in path.parts]

    # replace drive root
    if ':' in parts[0]:
        parts[0] = '/' + parts[0].replace(':', '')

    # return as posix path
    return PurePosixPath(*parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path', nargs='+', help='relative/path/')
    parser.add_argument('--source-endpoint', '-s', required=True,
                        choices=globus.endpoint_names(),
                        help='Recognized name of Globus endpoint')
    parser.add_argument('--destination-endpoint', '-d', required=True,
                        choices=globus.endpoint_names(),
                        help='Recognized name of Globus endpoint')
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
    args = parser.parse_args()

    # set up logging
    logger = logging.getLogger('educelab-globuscp')

    # get endpoint info from config
    src = globus.get_endpoint(args.source_endpoint)
    dst = globus.get_endpoint(args.destination_endpoint)
    logging.info(f'source endpoint: {args.source_endpoint}, '
                 f'destination endpoint: {args.destination_endpoint}')

    # run the login flow for the needed endpoints
    uuids = [src['uuid'], dst['uuid']]
    logger.debug(f'logging in to Globus endpoints: {", ".join(uuids)}')
    try:
        tc = globus.login(uuids)
    except RuntimeError:
        logger.exception('failed to login to all endpoints')
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
                                 notify_on_succeeded=args.notify_success,
                                 notify_on_failed=args.notify_failed,
                                 notify_on_inactive=args.notify_inactive,
                                 verify_checksum=args.verify)

    for d in args.path:
        d = to_posix_path(d)
        src_path = str(to_posix_path(src['basedir']) / d)
        dst_path = str(to_posix_path(dst['basedir']) / d)

        # Check path type: 'file', 'dir', 'invalid_symlink'
        # Unix only: 'chr', 'blk', 'pipe', 'other'
        pathtype = tc.operation_stat(src['uuid'], src_path).get('type')
        recursive = pathtype == 'dir'

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

    # exit early if background mode requested
    if args.background:
        sys.exit()

    # wait for completion
    logger.info('waiting for transfer to complete...')
    while not tc.task_wait(task_id):
        task_events = \
            tc.task_event_list(task_id, query_params={'filter': 'is_error:1'})[
                'DATA']
        if len(task_events):
            logger.debug(task_events)
            e = task_events[0]
            err_desc = e['description']
            err_path = '.'
            details = json.loads(e['details'])['context'][0]
            if 'path' in details.keys():
                err_path = f": '{details['path']}'"
            logger.error(f'transfer failed. {err_desc}{err_path}')
            tc.cancel_task(task_id)
            sys.exit(1)

    task_info = tc.get_task(task_id)
    if task_info['status'] == 'FAILED':
        err_desc = task_info['fatal_error']['description']
        logger.error(f'transfer task failed: {err_desc}')
        sys.exit(1)
    logger.info('done.')


if __name__ == "__main__":
    main()
