import pytest
from unittest.mock import MagicMock
import globus_sdk

from educelab.globus.login import test_endpoints as _probe_endpoints


# ---------------------------------------------------------------------------
# Mock infrastructure
#
# TransferAPIError.__init__ requires a requests.Response, so we subclass it
# and bypass the parent __init__, setting only the attributes we need.
# ---------------------------------------------------------------------------

class _Falsy:
    """Stands in for an ErrorInfo sub-object that tests as False."""
    def __bool__(self):
        return False


class _ConsentRequired:
    def __init__(self, scopes=None):
        self.required_scopes = scopes or []

    def __bool__(self):
        return True


class _AuthzParams:
    def __init__(self, **kwargs):
        self.session_message = kwargs.get('session_message')
        self.session_required_identities = kwargs.get('session_required_identities')
        self.session_required_single_domain = kwargs.get('session_required_single_domain')
        self.session_required_policies = kwargs.get('session_required_policies')
        self.session_required_mfa = kwargs.get('session_required_mfa')
        self.required_scopes = kwargs.get('required_scopes')

    def __bool__(self):
        return True


class _ErrorInfo:
    def __init__(self, consent_required=None, authorization_parameters=None):
        self.consent_required = consent_required or _Falsy()
        self.authorization_parameters = authorization_parameters or _Falsy()


class _TransferError(globus_sdk.TransferAPIError):
    """Concrete TransferAPIError for tests — no requests.Response needed."""

    def __init__(self, *, code=None, message='error',
                 consent_required=None, authorization_parameters=None):
        self.http_status = 400
        self.code = code
        self.messages = [message] if message else []
        self._mock_info = _ErrorInfo(
            consent_required=consent_required,
            authorization_parameters=authorization_parameters,
        )

    @property
    def info(self):
        return self._mock_info

    @property
    def message(self):
        return '; '.join(self.messages) if self.messages else None


def _tc(*side_effects):
    """Return a mock TransferClient whose operation_ls raises in sequence."""
    tc = MagicMock()
    if side_effects:
        tc.operation_ls.side_effect = list(side_effects)
    return tc


# ---------------------------------------------------------------------------
# test_endpoints
# ---------------------------------------------------------------------------

class TestTestEndpoints:
    def test_success(self):
        tc = _tc()
        success, need_scopes, auth_params, ap_ep = _probe_endpoints(tc, ['a', 'b'])
        assert success is True
        assert need_scopes is False
        assert auth_params is None
        assert ap_ep is None
        assert tc.operation_ls.call_count == 2

    def test_empty_endpoint_list(self):
        tc = _tc()
        success, need_scopes, auth_params, _ = _probe_endpoints(tc, [])
        assert success is True
        assert need_scopes is False
        assert tc.operation_ls.call_count == 0

    # --- GCDisconnected ---

    def test_gc_disconnected_is_failure(self):
        tc = _tc(_TransferError(code='GCDisconnected'))
        success, need_scopes, *_ = _probe_endpoints(tc, ['a'])
        assert success is False
        assert need_scopes is False

    def test_gc_disconnected_ignored_when_flag_set(self):
        tc = _tc(_TransferError(code='GCDisconnected'))
        success, need_scopes, *_ = _probe_endpoints(tc, ['a'], ignore_offline=True)
        assert success is True

    def test_gc_disconnected_continues_to_next_endpoint(self):
        tc = _tc(_TransferError(code='GCDisconnected'), None)  # 'b' succeeds
        success, *_ = _probe_endpoints(tc, ['a', 'b'])
        assert tc.operation_ls.call_count == 2

    # --- consent_required ---

    def test_consent_required_triggers_scope_request(self):
        err = _TransferError(
            consent_required=_ConsentRequired(scopes=['scope:read', 'scope:write'])
        )
        tc = _tc(err)
        success, need_scopes, auth_params, _ = _probe_endpoints(tc, ['a'])
        assert success is False
        assert need_scopes is True
        assert auth_params is None
        tc.add_app_scope.assert_called_once_with(['scope:read', 'scope:write'])

    # --- authorization_parameters (issue #1) ---

    def test_authorization_parameters_sets_auth_params(self):
        ap = _AuthzParams(session_required_single_domain=['uky.edu'])
        err = _TransferError(
            code='ExternalError.DirListingFailed.LoginFailed',
            authorization_parameters=ap,
        )
        tc = _tc(err)
        success, need_scopes, auth_params, ap_ep = _probe_endpoints(tc, ['a'])
        assert success is False
        assert need_scopes is True
        assert auth_params is not None
        assert auth_params.session_required_single_domain == ['uky.edu']
        assert ap_ep == 'a'

    def test_authorization_parameters_passes_all_fields(self):
        ap = _AuthzParams(
            session_message='Please use your university account',
            session_required_single_domain=['uky.edu'],
            session_required_identities=['id-123'],
            session_required_policies=['policy-a'],
            session_required_mfa=True,
        )
        tc = _tc(_TransferError(authorization_parameters=ap))
        _, _, auth_params, _ = _probe_endpoints(tc, ['a'])
        assert auth_params.session_message == 'Please use your university account'
        assert auth_params.session_required_identities == ['id-123']
        assert auth_params.session_required_policies == ['policy-a']
        assert auth_params.session_required_mfa is True

    def test_consent_required_takes_priority_over_auth_params(self):
        # GCSv5 data_access ConsentRequired responses include BOTH a
        # consent_required body and an authorization_parameters body. The
        # consent flow must win or we miss the required_scopes.
        ap = _AuthzParams(session_message='Missing required data_access consent')
        scopes = ['urn:globus:auth:scope:transfer.api.globus.org:all'
                  '[*https://auth.globus.org/scopes/abc/data_access]']
        err = _TransferError(
            code='ConsentRequired',
            consent_required=_ConsentRequired(scopes=scopes),
            authorization_parameters=ap,
        )
        tc = _tc(err)
        success, need_scopes, auth_params, _ = _probe_endpoints(tc, ['a'])
        assert success is False
        assert need_scopes is True
        assert auth_params is None
        tc.add_app_scope.assert_called_once_with(scopes)

    # --- LoginFailed without structured auth params ---

    def test_login_failed_unstructured_triggers_retry(self):
        err = _TransferError(code='ExternalError.DirListingFailed.LoginFailed')
        tc = _tc(err)
        success, need_scopes, auth_params, _ = _probe_endpoints(tc, ['a'])
        assert success is False
        assert need_scopes is True
        assert auth_params is None  # no structured params, plain re-login

    # --- unhandled errors ---

    def test_unhandled_error_reraises(self):
        tc = _tc(_TransferError(code='SomeUnexpectedError'))
        with pytest.raises(globus_sdk.TransferAPIError):
            _probe_endpoints(tc, ['a'])

    def test_unhandled_error_does_not_swallow_on_second_endpoint(self):
        tc = _tc(None, _TransferError(code='SomeUnexpectedError'))
        with pytest.raises(globus_sdk.TransferAPIError):
            _probe_endpoints(tc, ['a', 'b'])

    # --- multiple endpoints, mixed results ---

    def test_one_offline_one_ok(self):
        tc = _tc(_TransferError(code='GCDisconnected'), None)
        success, need_scopes, *_ = _probe_endpoints(tc, ['a', 'b'])
        assert success is False
        assert need_scopes is False
        assert tc.operation_ls.call_count == 2

    def test_one_needs_consent_one_ok(self):
        err = _TransferError(consent_required=_ConsentRequired(scopes=['s']))
        tc = _tc(err, None)
        success, need_scopes, *_ = _probe_endpoints(tc, ['a', 'b'])
        assert need_scopes is True
        assert tc.operation_ls.call_count == 2
