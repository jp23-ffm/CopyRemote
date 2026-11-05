import os
from unittest import mock

import ldap
from django.test import SimpleTestCase, override_settings

from common import ad_credentials as adc


def _invalid_credentials():
    return ldap.INVALID_CREDENTIALS({"desc": "Invalid credentials", "info": "80090308: ... data 52e, v4563"})


@override_settings(AD_GET_CRED_CMD=["get-cred"], AD_PASSWORD_TTL=3600, AD_BIND_COOLDOWN=60)
class WithAdPasswordTests(SimpleTestCase):
    def setUp(self):
        adc._reset()

    def test_password_is_cached_in_memory(self):
        with mock.patch.object(adc, "_fetch", return_value="pw") as fetch:
            adc.get_password()
            adc.get_password()
        fetch.assert_called_once()

    def test_rotation_is_detected_and_bind_retried_once(self):
        bind = mock.Mock(side_effect=[_invalid_credentials(), "conn"])
        with mock.patch.object(adc, "_fetch", side_effect=["old", "new"]):
            with self.assertLogs("common.ad_credentials", level="WARNING") as logs:
                result = adc.with_ad_password(bind)
        self.assertEqual(result, "conn")
        self.assertEqual(bind.call_args_list, [mock.call("old"), mock.call("new")])
        self.assertTrue(any("rotation detected" in line for line in logs.output))

    def test_unchanged_password_is_not_retried_and_binds_are_suspended(self):
        bind = mock.Mock(side_effect=_invalid_credentials())
        with mock.patch.object(adc, "_fetch", return_value="same"):
            with self.assertRaises(ldap.INVALID_CREDENTIALS):
                adc.with_ad_password(bind)
            self.assertEqual(bind.call_count, 1)  # no retry: not a rotation
            with self.assertRaises(adc.BindBlocked):
                adc.with_ad_password(bind)
            self.assertEqual(bind.call_count, 1)  # AD was not contacted again

    def test_bind_refused_again_after_rotation_suspends_binds(self):
        bind = mock.Mock(side_effect=[_invalid_credentials(), _invalid_credentials()])
        with mock.patch.object(adc, "_fetch", side_effect=["old", "new"]):
            with self.assertRaises(ldap.INVALID_CREDENTIALS):
                adc.with_ad_password(bind)
            with self.assertRaises(adc.BindBlocked):
                adc.with_ad_password(bind)

    def test_other_ldap_errors_do_not_trigger_a_refresh(self):
        bind = mock.Mock(side_effect=ldap.SERVER_DOWN())
        with mock.patch.object(adc, "_fetch", return_value="pw") as fetch:
            with self.assertRaises(ldap.SERVER_DOWN):
                adc.with_ad_password(bind)
        fetch.assert_called_once()  # only the initial load

    def test_blocked_error_is_an_ldap_error(self):
        # Existing `except ldap.LDAPError` handlers must keep catching it.
        self.assertTrue(issubclass(adc.BindBlocked, ldap.LDAPError))
        self.assertTrue(issubclass(adc.CredentialError, ldap.LDAPError))


@override_settings(AD_GET_CRED_CMD=["get-cred"], AD_GET_CRED_TIMEOUT=5)
class GetCredCommandTests(SimpleTestCase):
    def setUp(self):
        adc._reset()

    def test_trailing_newline_is_stripped(self):
        completed = mock.Mock(returncode=0, stdout="secret\n")
        with mock.patch.object(adc.subprocess, "run", return_value=completed):
            self.assertEqual(adc.get_password(), "secret")

    def test_non_zero_exit_code_raises(self):
        completed = mock.Mock(returncode=1, stdout="")
        with mock.patch.object(adc.subprocess, "run", return_value=completed):
            with self.assertRaises(adc.CredentialError):
                adc.get_password()

    def test_empty_output_raises(self):
        completed = mock.Mock(returncode=0, stdout="\n")
        with mock.patch.object(adc.subprocess, "run", return_value=completed):
            with self.assertRaises(adc.CredentialError):
                adc.get_password()

    def test_timeout_raises(self):
        timeout = adc.subprocess.TimeoutExpired(cmd="get-cred", timeout=5)
        with mock.patch.object(adc.subprocess, "run", side_effect=timeout):
            with self.assertRaises(adc.CredentialError):
                adc.get_password()

    @override_settings(AD_GET_CRED_CMD=[])
    def test_environment_fallback_when_no_command_is_configured(self):
        with mock.patch.dict(os.environ, {"LDAP_BIND_PASSWORD": "dev-password"}):
            self.assertEqual(adc.get_password(), "dev-password")

    @override_settings(AD_GET_CRED_CMD=[])
    def test_missing_fallback_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(adc.CredentialError):
                adc.get_password()
