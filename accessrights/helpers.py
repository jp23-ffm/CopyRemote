"""
Access Rights helpers — import these in your views.

Usage:
    from accessrights.helpers import has_perm, user_perms

    # Check a single permission
    if has_perm(request.user, 'inventory.edit'):
        ...

    # Get all permissions for template context
    context['perms'] = user_perms(request.user)
    # Then in template: {% if 'inventory.edit' in perms %}
"""
from accessrights.models import UserPermission


def has_perm(user, codename):
    """
    Check if a user has a specific permission.
    Returns True/False.
    """
    if not user or not user.is_authenticated:
        return False
    return UserPermission.objects.filter(
        user=user,
        permission__codename=codename,
    ).exists()


def user_perms(user):
    """
    Returns a set of all permission codenames for a user.
    Efficient for checking multiple permissions at once.
    """
    if not user or not user.is_authenticated:
        return set()
    return set(
        UserPermission.objects.filter(user=user)
        .values_list('permission__codename', flat=True)
    )
