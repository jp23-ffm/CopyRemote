"""
Signals for access rights.
Currently: logs user login timestamp.
Optional: AD group sync on login (uncomment the AD section below).
"""
import logging
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def on_user_login(sender, request, user, **kwargs):
    """
    Triggered on every login.
    You can add AD sync logic here if needed.
    """
    logger.info(f"User logged in: {user.username}")

    # ── Optional: AD group sync ──
    # Uncomment and adapt to your AD backend if you want
    # automatic permission sync on login.
    #
    # from accessrights.models import Permission, UserPermission
    #
    # AD_GROUP_MAPPING = {
    #     'INV-Editors':  ['inventory.view', 'inventory.edit'],
    #     'INV-Viewers':  ['inventory.view'],
    #     'BC-Editors':   ['businesscontinuity.view', 'businesscontinuity.edit'],
    #     'DISC-Viewers': ['discrepancies.view'],
    # }
    #
    # ad_groups = user.groups.values_list('name', flat=True)
    # codenames_to_grant = set()
    # for group_name in ad_groups:
    #     if group_name in AD_GROUP_MAPPING:
    #         codenames_to_grant.update(AD_GROUP_MAPPING[group_name])
    #
    # for codename in codenames_to_grant:
    #     try:
    #         perm = Permission.objects.get(codename=codename)
    #         UserPermission.objects.get_or_create(
    #             user=user,
    #             permission=perm,
    #             defaults={'granted_by': None}  # NULL = automated
    #         )
    #     except Permission.DoesNotExist:
    #         logger.warning(f"Permission {codename} not found for AD sync")
