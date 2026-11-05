from unittest import mock

import ldap
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from common.ldap_utils import get_user_groups

GROUP = b"CN=Some Group,DC=example"


@override_settings(
    LDAP_SERVER_URI="ldap://dc1", LDAP_SEARCH_BASE="DC=one",
    LDAP_SERVER_URI2="ldap://dc2", LDAP_SEARCH_BASE2="DC=two",
)
class GetUserGroupsTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_user_found_on_second_domain_is_cached(self):
        with mock.patch("common.ldap_utils.ldap_search_memberof", side_effect=[[], [GROUP]]) as search:
            self.assertEqual(get_user_groups("U1"), [GROUP])
            self.assertEqual(get_user_groups("u1"), [GROUP])  # cache key is case-insensitive
        self.assertEqual(search.call_count, 2)  # second call served from the cache

    def test_user_not_found_anywhere_is_cached_as_empty(self):
        with mock.patch("common.ldap_utils.ldap_search_memberof", side_effect=[[], []]) as search:
            self.assertEqual(get_user_groups("u2"), [])
            self.assertEqual(get_user_groups("u2"), [])
        self.assertEqual(search.call_count, 2)

    def test_errors_are_never_cached(self):
        # Both domains fail (e.g. a refused bind), then the next call works.
        failures = [ldap.SERVER_DOWN(), ldap.SERVER_DOWN(), [GROUP]]
        with mock.patch("common.ldap_utils.ldap_search_memberof", side_effect=failures):
            self.assertEqual(get_user_groups("u3"), [])
            self.assertEqual(get_user_groups("u3"), [GROUP])

    def test_found_user_is_cached_even_if_a_domain_failed(self):
        results = [ldap.SERVER_DOWN(), [GROUP]]
        with mock.patch("common.ldap_utils.ldap_search_memberof", side_effect=results) as search:
            self.assertEqual(get_user_groups("u4"), [GROUP])
            self.assertEqual(get_user_groups("u4"), [GROUP])
        self.assertEqual(search.call_count, 2)
