from django import template

register = template.Library()

@register.filter
def get_item(obj, key):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
    
@register.filter
def is_lowercase(value):
    return value.islower()    
