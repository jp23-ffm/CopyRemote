from django import template

register = template.Library()


@register.filter
def get_item(obj, key):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


@register.filter
def lookup(obj, key):
    if obj is None:
        return ''
    if isinstance(obj, dict):
        return obj.get(key, '')
    try:
        return getattr(obj, key, '')
    except (AttributeError, TypeError):
        return ''


@register.filter
def split(value, delimiter=','):
    if not value:
        return []
    return [item.strip() for item in value.split(delimiter) if item.strip()]
