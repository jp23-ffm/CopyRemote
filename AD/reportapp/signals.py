import logging
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.conf import settings
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from userapp.models import UserPermissions, UserProfile
from common.ldap_utils import get_user_groups

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def check_user_group(sender, request, user, **kwargs):
    # Only act on SAML logins
    if "SAMLResponse" not in request.POST:
        logger.debug("[LDAP] %s is a local user – skipping group check.", user.username)
        return

    groups = get_user_groups(user.username)

    # Required group DNs (bytes, case-sensitive match)
    req1 = settings.LDAP_REQUIRED_GROUP.encode("utf-8")
    req2 = settings.LDAP_REQUIRED_GROUP2.encode("utf-8")
    req_bc_editors = settings.LDAP_REQUIRED_GROUP_BC_EDITORS.encode("utf-8")
    req_inventory_editors = settings.LDAP_REQUIRED_GROUP_INVENTORY_EDITORS.encode("utf-8")

    if req1 in groups or req2 in groups:
        logger.debug("[LDAP] %s is member of a required group – access granted.", user.username)
        try:
            user_profile = UserProfile.objects.get(user=user)
            user_permissions, created = UserPermissions.objects.get_or_create(user_profile=user_profile)

            if req_bc_editors in groups or req2 in groups:  # Edition groups
                user_permissions.businesscontinuity_allowedit = True
                logger.debug("[LDAP] %s is a BC editor.", user.username)
            else:
                user_permissions.businesscontinuity_allowedit = False
                logger.debug("[LDAP] %s is not a BC editor.", user.username)

            if req_inventory_editors in groups or req2 in groups:  # Edition groups
                user_permissions.inventory_allowedit = True
                logger.debug("[LDAP] %s is an Inventory editor.", user.username)
            else:
                user_permissions.inventory_allowedit = False
                logger.debug("[LDAP] %s is not an Inventory editor.", user.username)

            user_permissions.save()
        except UserProfile.DoesNotExist:
            logger.warning("[LDAP] UserProfile for %s does not exist.", user.username)
            return

        return


    # Deny access
    logger.warning("[LDAP] %s NOT in required groups – access denied.", user.username)
    logout(request)
    raise PermissionDenied("User is not a member of the required group(s).")
