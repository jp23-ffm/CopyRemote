import ldap
import logging
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.conf import settings
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.core.cache import cache


logger = logging.getLogger(__name__)

def ldap_search_memberof(server_uri: str, base_dn: str, username: str):
    """
    Returns the list of memberOf values (bytes) for the user, or [] if not found.
    Raises ldap.LDAPError on bind/search errors.
    """
    conn = ldap.initialize(server_uri)
    conn.set_option(ldap.OPT_REFERRALS, 0)
    conn.simple_bind_s(settings.LDAP_BIND_DN, settings.LDAP_BIND_PASSWORD)

    #search_filter = f"(sAMAccountName={username})"
    #search_filter = f"(sAMAccountName={username})"
    ##search_filter = f"(sAMAccountName=*{username}*)"
    search_filter = f"(EmployeeID={username})"
    results = conn.search_s(base_dn, ldap.SCOPE_SUBTREE, search_filter, ["memberOf"])

    member_of = []
    for dn, attrs in results:
        if dn and isinstance(attrs, dict):
            member_of = attrs.get("memberOf", [])
            logger.debug("[LDAP] User %s found in %s (DN=%s) – %d groups",
                         username, base_dn, dn, len(member_of))
            break

    conn.unbind_s()
    return member_of


@receiver(user_logged_in)
def check_user_group(sender, request, user, **kwargs):
    # Only act on SAML logins
    if "SAMLResponse" not in request.POST:
        logger.debug("[LDAP] %s is a local user – skipping group check.", user.username)
        return

    cache_key = f"ldap_groups_{user.username.lower()}"
    groups = cache.get(cache_key)

    if groups is None:
        groups = []

        # First attempt: primary EURO DC
        try:
            groups = ldap_search_memberof(settings.LDAP_SERVER_URI,
                                          settings.LDAP_SEARCH_BASE,
                                          user.username)
        except ldap.LDAPError as exc:
            logger.error("[LDAP] EURO server error: %s", exc)

        # If not found, second attempt: GAIA DC
        if not groups:
            try:
                groups = ldap_search_memberof(settings.LDAP_SERVER_URI2,
                                              settings.LDAP_SEARCH_BASE2,
                                              user.username)
            except ldap.LDAPError as exc:
                logger.error("[LDAP] GAIA server error: %s", exc)

        if not groups:
            logger.warning("[LDAP] User %s not found in EURO or GAIA.", user.username)

        # Cache for 10 minutes
        cache.set(cache_key, groups, timeout=600)
    else:
        logger.debug("[LDAP] Using cached groups for %s", user.username)

    # Required group DNs (bytes, case-sensitive match)
    req1 = settings.LDAP_REQUIRED_GROUP.encode("utf-8")
    req2 = settings.LDAP_REQUIRED_GROUP2.encode("utf-8")

    if req1 in groups or req2 in groups:
        logger.debug("[LDAP] %s is member of a required group – access granted.", user.username)
        return

    # Deny access
    logger.warning("[LDAP] %s NOT in required groups – access denied.", user.username)
    logout(request)
    raise PermissionDenied("User is not a member of the required group(s).")
    

