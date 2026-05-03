import logging
from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.core.cache import cache
from django.dispatch import receiver

from .models import Permission, UserPermission

logger = logging.getLogger(__name__)

ADMIN_CODENAME = 'accessrights.admin'


@receiver(user_logged_in)
def on_user_login(sender, request, user, **kwargs):
    logger.info("User logged in: %s", user.username)

    # Auto-grant accessrights.admin to members of LDAP_REQUIRED_GROUP2.
    # Relies on the LDAP cache populated by reportapp (or common) signal.
    # If the cache is empty (e.g. local login, cache miss), skip silently —
    # the permission may already be granted from a previous login.
    ldap_group2 = getattr(settings, 'LDAP_REQUIRED_GROUP2', None)
    if not ldap_group2:
        return

    cache_key = f"ldap_groups_{user.username.lower()}"
    groups = cache.get(cache_key)

    if groups is None:
        logger.debug("[accessrights] No LDAP cache for %s — skipping auto-grant.", user.username)
        return

    if ldap_group2.encode('utf-8') not in groups:
        logger.debug("[accessrights] %s is not in LDAP_REQUIRED_GROUP2.", user.username)
        return

    try:
        perm = Permission.objects.get(codename=ADMIN_CODENAME)
    except Permission.DoesNotExist:
        logger.warning("[accessrights] Permission %s not found in DB — run seed_permissions.", ADMIN_CODENAME)
        return

    _, created = UserPermission.objects.get_or_create(
        user=user,
        permission=perm,
        defaults={'granted_by': None},
    )
    if created:
        logger.info("[accessrights] Auto-granted %s to %s (LDAP_REQUIRED_GROUP2).", ADMIN_CODENAME, user.username)
