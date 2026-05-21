"""
utils.py
--------
Shared utilities for the businesscontinuity app.
Place in: businesscontinuity/utils.py
"""

from accessrights.helpers import has_perm
from userapp.models import UserPermissions, UserProfile


def is_editor(request) -> bool:
    """
    Return True if the user has editor rights on businesscontinuity.

    Two sources checked — either one is sufficient:
      1. Django permission flag : 'businesscontinuity.edit'  (via has_perm)
      2. UserPermissions field  : businesscontinuity_allowedit

    This is the single source of truth for editor checks across all views.
    Matches the logic used in server_view().
    """
    if has_perm(request.user, 'businesscontinuity.edit'):
        return True

    try:
        profile = UserProfile.objects.get(user=request.user)
        perms   = UserPermissions.objects.get(user_profile=profile)
        return bool(perms.businesscontinuity_allowedit)
    except (UserProfile.DoesNotExist, UserPermissions.DoesNotExist):
        return False
