import argparse
import logging
import sys
from pathlib import Path
from uuid import UUID

import globus_sdk
from globus_sdk.globus_app import UserApp, GlobusAppConfig
from globus_sdk.tokenstorage import JSONTokenStorage
from prompt_toolkit import print_formatted_text as print_fmt, HTML

from educelab.globus import config

_APP_NAME = 'educelab-globuscp'
_APP_NAMESPACE = 'edu.uky.educelab.globuscp'
_CLIENT_ID = '061f00f1-2726-41dc-a097-3cff9d4f03d4'
_TOKEN_STORE_PATH = Path.home() / '.globuscp' / 'tokenstore.json'
# migrate old token store
if (Path.home() / '.globuscp.json').exists() and not _TOKEN_STORE_PATH.exists():
    _TOKEN_STORE_PATH.parent.mkdir(exist_ok=True)
    (Path.home() / '.globuscp.json').rename(_TOKEN_STORE_PATH)
_TOKEN_STORE = JSONTokenStorage(_TOKEN_STORE_PATH, namespace=_APP_NAMESPACE)
_APP = UserApp(app_name=_APP_NAME, client_id=_CLIENT_ID,
               config=GlobusAppConfig(token_storage=_TOKEN_STORE,
                                      request_refresh_tokens=True))


def test_endpoints(tc, endpoint_uuids, ignore_offline=False):
    """Test that the provided endpoints are accessible for transfers"""
    logger = logging.getLogger(__name__)
    success = True
    need_scopes = False
    for uuid in endpoint_uuids:
        logger.debug(f'testing endpoint: {uuid}')
        try:
            tc.operation_ls(uuid, path="/")
        except globus_sdk.TransferAPIError as err:
            if 'GCDisconnected' in err.code:
                logger.error(err.message)
                success = ignore_offline
                continue
            elif not err.info.consent_required:
                # unhandled error
                raise

            tc.add_app_scope(err.info.consent_required.required_scopes)
            success = False
            need_scopes = True
    return success, need_scopes


def login(endpoint_uuids, force=False, ignore_offline=False):
    """Login to the Globus service"""
    _APP.login(force=force)
    # set up client
    tc = globus_sdk.TransferClient(app=_APP)

    # try five times to get all scopes
    success = True
    for tries in range(5):
        success, need_scopes = test_endpoints(tc, endpoint_uuids,
                                              ignore_offline)
        if not need_scopes:
            break

        print_fmt(HTML('<ansiyellow>Endpoints require additional scopes. '
                       'Please login again.</ansiyellow>'))
        _APP.login()
        print()
    if not success:
        raise RuntimeError('Failed to login to all Globus endpoints')
    return tc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--endpoints', '-e', nargs='+',
                        help='List of endpoints to verify. Should be either a '
                             'recognized name in the configuration file or an '
                             'endpoint UUID. Default: All endpoints in the '
                             'configuration file')
    parser.add_argument('--force', '-f', action='store_true',
                        help='Force new login')
    parser.add_argument('--ignore-offline', action='store_true',
                        help='Offline endpoints are not a hard failure')
    args = parser.parse_args()

    # set up logging
    logger = logging.getLogger('educelab.globus.login')

    if args.endpoints is None:
        endpoints = set(config.endpoint_uuids())
    else:
        endpoints = set()
        for e in args.endpoints:
            # Check config first
            ep_uuid = config.get_endpoint(e)
            if ep_uuid is not None:
                endpoints.add(ep_uuid['uuid'])
                continue

            # try to convert to uuid
            try:
                UUID(e)
                endpoints.add(e)
            except ValueError:
                logger.error(f'\'{e}\' is not a recognized endpoint name or '
                             f'UUID')
                sys.exit(1)

    try:
        login(endpoints, force=args.force, ignore_offline=args.ignore_offline)
    except RuntimeError as err:
        print(err)
        sys.exit(1)
    print('Login successful')


if __name__ == '__main__':
    main()
