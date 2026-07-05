from django import template

register = template.Library()


@register.filter
def lookup(obj, key):
    # Filter Template to dynamically access to a dictionary value or object attribute
    # Usage: {{ my_dict|lookup:"my_key" }} or {{ my_object|lookup:"my_attribute" }}

    if obj is None:
        return ''

    if isinstance(obj, dict):
        return obj.get(key, '')

    try:
        return getattr(obj, key, '')
    except (AttributeError, TypeError):
        return ''
