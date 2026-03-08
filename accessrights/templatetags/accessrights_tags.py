"""
Template tags for access rights.

Usage in templates:
    {% load accessrights_tags %}

    {% has_perm user 'inventory.edit' as can_edit %}
    {% if can_edit %}
        <button>Edit</button>
    {% endif %}
"""
from django import template
from accessrights.helpers import has_perm as _has_perm

register = template.Library()


@register.simple_tag
def has_perm(user, codename):
    return _has_perm(user, codename)
