import argparse
import logging
import os
import sys
from pathlib import Path
from uuid import UUID

import globus_sdk
from globus_sdk.gare import GlobusAuthorizationParameters
from globus_sdk.globus_app import UserApp, GlobusAppConfig
from globus_sdk.login_flows import LocalServerEnvironmentalLoginError
from globus_sdk.token_storage import JSONTokenStorage
from prompt_toolkit import print_formatted_text as print_fmt, HTML

from educelab.globus import config
from educelab.globus._cli import setup_logging

_APP_NAME = 'educelab-globuscp'
_APP_NAMESPACE = 'edu.uky.educelab.globuscp'
_CLIENT_ID = '061f00f1-2726-41dc-a097-3cff9d4f03d4'
_TOKEN_STORE_PATH = Path.home() / '.globuscp' / 'tokenstore.json'
# migrate old token store
if (Path.home() / '.globuscp.json').exists() and not _TOKEN_STORE_PATH.exists():
    _TOKEN_STORE_PATH.parent.mkdir(exist_ok=True)
    (Path.home() / '.globuscp.json').rename(_TOKEN_STORE_PATH)
_TOKEN_STORE = JSONTokenStorage(_TOKEN_STORE_PATH, namespace=_APP_NAMESPACE)


def _is_remote_session():
    return bool(os.environ.get('SSH_TTY') or os.environ.get('SSH_CONNECTION'))


def _make_app(browser=True):
    # Local-server flow can't bind a port in remote/headless sessions; force
    # command-line flow so SDK-triggered re-logins (token refresh failures)
    # also use a flow that works there.
    if browser and _is_remote_session():
        browser = False
    flow = 'local-server' if browser else 'command-line'
    return UserApp(app_name=_APP_NAME, client_id=_CLIENT_ID,
                   config=GlobusAppConfig(login_flow_manager=flow,
                                          token_storage=_TOKEN_STORE,
                                          request_refresh_tokens=True))


def _app_login(app, force=False, auth_params=None):
    """Call app.login(), falling back to command-line flow if browser unavailable."""
    try:
        app.login(force=force, auth_params=auth_params)
    except LocalServerEnvironmentalLoginError:
        print_fmt(HTML('<ansiyellow>Browser unavailable; falling back to '
                       'command-line login.</ansiyellow>'))
        _make_app(browser=False).login(force=True, auth_params=auth_params)


def test_endpoints(tc, endpoint_uuids, ignore_offline=False):
    """Test that the provided endpoints are accessible for transfers."""
    logger = logging.getLogger(__name__)
    success = True
    need_scopes = False
    auth_params = None
    auth_params_endpoint = None
    for uuid in endpoint_uuids:
        logger.debug(f'testing endpoint: {uuid}')
        try:
            tc.operation_ls(uuid, path="/")
        except globus_sdk.TransferAPIError as err:
            if err.code and 'GCDisconnected' in err.code:
                logger.error(err.message)
                success = ignore_offline
                continue
            elif err.info.consent_required:
                # ConsentRequired (e.g. GCSv5 data_access). Add the required
                # scopes; the next login will prompt for the new consent.
                logger.debug(f'endpoint {uuid} requires additional scopes:'
                             f' {err.info.consent_required.required_scopes}')
                tc.add_app_scope(err.info.consent_required.required_scopes)
                success = False
                need_scopes = True
            elif err.info.authorization_parameters:
                # Endpoint requires specific session credentials (e.g. identity
                # from a particular domain). Build auth_params so the login
                # loop can pass them directly to app.login().
                ap = err.info.authorization_parameters
                auth_params = GlobusAuthorizationParameters(
                    session_message=ap.session_message,
                    session_required_identities=ap.session_required_identities,
                    session_required_single_domain=ap.session_required_single_domain,
                    session_required_policies=ap.session_required_policies,
                    session_required_mfa=ap.session_required_mfa,
                )
                auth_params_endpoint = uuid
                success = False
                need_scopes = True
            elif err.code and 'LoginFailed' in err.code:
                # Endpoint rejected the identity (e.g. domain not allowed) but
                # didn't return structured auth params. Force a plain re-login.
                logger.warning(f'endpoint login failed: {err.message}')
                success = False
                need_scopes = True
            else:
                raise
    return success, need_scopes, auth_params, auth_params_endpoint


def _auth_params_signature(auth_params):
    """Stable comparable view of an auth_params object."""
    if auth_params is None:
        return None
    return (
        tuple(auth_params.session_required_identities or ()),
        tuple(auth_params.session_required_single_domain or ()),
        tuple(auth_params.session_required_policies or ()),
        auth_params.session_required_mfa,
    )


def login(endpoint_uuids, force=False, ignore_offline=False, browser=True):
    """Log into Globus and return a ``TransferClient`` authorized for the
    given endpoints.

    Acquires (or refreshes) tokens, prompts for any required consents or
    session credentials (re-running the auth flow up to five times), and
    verifies that each endpoint is reachable via ``operation_ls``.

    Parameters
    ----------
    endpoint_uuids : iterable of str
        UUIDs of the Globus endpoints to authorize.
    force : bool, optional
        Force a new login even if cached tokens are valid. Default ``False``.
    ignore_offline : bool, optional
        Treat offline (``GCDisconnected``) endpoints as non-fatal. Default
        ``False``.
    browser : bool, optional
        Use the local-server (browser) login flow. Automatically disabled on
        remote/SSH sessions. Default ``True``.

    Returns
    -------
    globus_sdk.TransferClient
        An authorized transfer client.

    Raises
    ------
    RuntimeError
        If any endpoint could not be authorized after the retry budget is
        exhausted (e.g. user did not satisfy a session requirement).
    """
    app = _make_app(browser=browser)
    _app_login(app, force=force)
    tc = globus_sdk.TransferClient(app=app)

    # try five times to acquire all needed scopes / session credentials
    success = True
    last_auth_sig = None
    for _ in range(5):
        try:
            success, need_scopes, auth_params, ap_endpoint = test_endpoints(
                tc, endpoint_uuids, ignore_offline)
        except globus_sdk.AuthAPIError as err:
            if err.raw_json and err.raw_json.get('error') == 'invalid_grant':
                print_fmt(HTML('<ansiyellow>Stored tokens are no longer valid. '
                               'Please login again.</ansiyellow>'))
                _app_login(app, force=True)
                tc = globus_sdk.TransferClient(app=app)
                continue
            raise

        if not need_scopes:
            break

        if auth_params:
            # If the same session requirement comes back after a login attempt,
            # the user isn't satisfying it (e.g. authenticating as the wrong
            # identity, no MFA). Bail with detail instead of looping silently.
            sig = _auth_params_signature(auth_params)
            if sig == last_auth_sig:
                detail = [f'endpoint {ap_endpoint} still requires session '
                          f'credentials after login']
                if auth_params.session_message:
                    detail.append(f'message: {auth_params.session_message}')
                if auth_params.session_required_identities:
                    ids = ', '.join(auth_params.session_required_identities)
                    detail.append(f'required identities: {ids}')
                if auth_params.session_required_single_domain:
                    doms = ', '.join(auth_params.session_required_single_domain)
                    detail.append(f'required identity domain(s): {doms}')
                if auth_params.session_required_mfa:
                    detail.append('MFA required')
                raise RuntimeError('; '.join(detail))
            last_auth_sig = sig

            msg = f'Endpoint {ap_endpoint} requires specific session credentials.'
            if auth_params.session_required_single_domain:
                domains = ', '.join(auth_params.session_required_single_domain)
                msg += f' Required identity domain(s): {domains}.'
            if auth_params.session_required_mfa:
                msg += ' MFA required.'
            if auth_params.session_message:
                msg += f' ({auth_params.session_message})'
            print_fmt(HTML(f'<ansiyellow>{msg} Please login again.</ansiyellow>'))
            _app_login(app, force=True, auth_params=auth_params)
        else:
            last_auth_sig = None
            print_fmt(HTML('<ansiyellow>Endpoints require additional scopes. '
                           'Please login again.</ansiyellow>'))
            _app_login(app)
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
    parser.add_argument('--no-browser', action='store_true',
                        help='Print the auth URL instead of opening a browser')
    parser.add_argument('--ignore-offline', action='store_true',
                        help='Offline endpoints are not a hard failure')
    log_opts = parser.add_mutually_exclusive_group()
    log_opts.add_argument('--verbose', '-v', action='store_true',
                          help='Enable debug logging')
    log_opts.add_argument('--quiet', '-q', action='store_true',
                          help='Only log warnings and errors')
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, quiet=args.quiet)
    logger = logging.getLogger(__name__)

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
        login(endpoints, force=args.force, ignore_offline=args.ignore_offline,
              browser=not args.no_browser)
    except RuntimeError as err:
        logger.error(str(err))
        sys.exit(1)
    except globus_sdk.TransferAPIError as err:
        logger.error(f'Globus API error: {err.message}')
        sys.exit(1)
    logger.info('login successful')


if __name__ == '__main__':
    main()
