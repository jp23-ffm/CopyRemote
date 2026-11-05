"""
Shared LDAP helpers: group membership lookup for a user.

Used by the login signal (reportapp.signals) and by the Business Continuity
middleware, which used to carry two identical copies of this code.
The service account password comes from common.ad_credentials.
"""
import contextlib
import logging

import ldap
from django.conf import settings
from django.core.cache import cache

from common.ad_credentials import with_ad_password

logger = logging.getLogger("common.ldap_utils")

# The cache key format is also read by accessrights.signals: do not change it.
GROUPS_CACHE_KEY = "ldap_groups_{username}"
GROUPS_CACHE_TTL = 600  # seconds

# (label, setting holding the server URI, setting holding the search base),
# queried in this order until the user is found.
_DOMAINS = (
    ("EURO", "LDAP_SERVER_URI", "LDAP_SEARCH_BASE"),
    ("GAIA", "LDAP_SERVER_URI2", "LDAP_SEARCH_BASE2"),
    ("AMER", "LDAP_SERVER_URI3", "LDAP_SEARCH_BASE3"),
    ("APAC", "LDAP_SERVER_URI4", "LDAP_SEARCH_BASE4"),
)


def ldap_search_memberof(server_uri, base_dn, username):
    """
    Return the list of memberOf values (bytes) of the user, or [] if not found.
    Raises ldap.LDAPError on bind/search errors.
    """
    def _bind(password):
        conn = ldap.initialize(server_uri)
        conn.set_option(ldap.OPT_REFERRALS, 0)
        try:
            conn.simple_bind_s(settings.LDAP_BIND_DN, password)
        except ldap.LDAPError:
            # Do not leak the connection when the bind is refused (it may be retried).
            with contextlib.suppress(ldap.LDAPError):
                conn.unbind_s()
            raise
        return conn

    conn = with_ad_password(_bind)
    try:
        search_filter = f"(&(EmployeeID={username})(!(samAccountName=adm*))(!(samAccountName=tec*)))"
        results = conn.search_s(base_dn, ldap.SCOPE_SUBTREE, search_filter, ["memberOf"])

        member_of = []
        for dn, attrs in results:
            if dn and isinstance(attrs, dict):
                member_of = attrs.get("memberOf", [])
                logger.debug("[LDAP] User %s found in %s (DN=%s) - %d groups",
                             username, base_dn, dn, len(member_of))
                break
        return member_of
    finally:
        with contextlib.suppress(ldap.LDAPError):
            conn.unbind_s()


def _lookup_groups(username):
    """
    Query each configured domain controller in turn until the user is found.

    Returns (groups, trustworthy). `trustworthy` is False when the user was not
    found AND at least one controller could not be queried: an empty list is
    then "unknown", not "has no groups", and must not be cached.
    """
    had_error = False
    for label, uri_setting, base_setting in _DOMAINS:
        uri = getattr(settings, uri_setting, None)
        base = getattr(settings, base_setting, None)
        if not uri or not base:
            logger.debug("[LDAP] %s is not configured, skipping", label)
            continue
        try:
            groups = ldap_search_memberof(uri, base, username)
        except ldap.LDAPError as exc:
            had_error = True
            logger.error("[LDAP] %s server error: %s", label, exc)
            continue
        if groups:
            return groups, True
    return [], not had_error


def get_user_groups(username):
    """
    Return the memberOf values (bytes) of the user, cached for GROUPS_CACHE_TTL.

    Errors are never cached: previously a failed bind (for instance right after
    a password rotation) stored an empty list for 10 minutes and silently locked
    users out.
    """
    cache_key = GROUPS_CACHE_KEY.format(username=username.lower())
    groups = cache.get(cache_key)
    if groups is not None:
        logger.debug("[LDAP] Using cached groups for %s", username)
        return groups

    groups, trustworthy = _lookup_groups(username)
    if not groups:
        if trustworthy:
            logger.warning("[LDAP] User %s was not found in any configured domain.", username)
        else:
            logger.warning("[LDAP] User %s was not found and at least one domain could not be "
                           "queried: result not cached.", username)
    if trustworthy:
        cache.set(cache_key, groups, timeout=GROUPS_CACHE_TTL)
    return groups
