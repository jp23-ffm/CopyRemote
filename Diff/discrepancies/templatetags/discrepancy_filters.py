from django import template

register = template.Library()

@register.filter
def get_item(obj, key):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
    

@register.filter
def lookup(obj, key):
    # Filter Template to dynamically access to a dictionary value or object attribute
    # Usage: {{ my_dict|lookup:"my_key" }} or {{ my_object|lookup:"my_attribute" }}

    if obj is None:
        return ''

    if isinstance(obj, dict):
        return obj.get(key, '')

    # For all the objects models
    try:
        return getattr(obj, key, '')
    except (AttributeError, TypeError):
        return ''


@register.filter
def split(value, delimiter=','):
    # Split a string by delimiter and return a list.
    # Usage: {{ "a,b,c"|split:"," }}

    if not value:
        return []
    return [item.strip() for item in value.split(delimiter) if item.strip()]


@register.simple_tag
def get_cell_error_class(server, field_name, validation_errors_config):
    """
    Returns the appropriate CSS class for a table cell based on:
    1. If the field value is 'MISSING' -> 'error-missing'
    2. If the field is affected by a validation error -> corresponding css_class
    """
    
    # Check if field value is MISSING
    field_value = getattr(server, field_name, None)
    if field_value == 'MISSING':
        return 'error-missing'
    
    # Check validation errors
    for error_flag, error_config in validation_errors_config.items():
        # Check if this server has this validation error (KO status)
        error_status = getattr(server, error_flag, 'OK')
        
        if error_status == 'KO':
            # Check if this field is affected by this validation error
            affected_fields = error_config.get('affected_fields', [])
            if field_name in affected_fields:
                return error_config.get('css_class', 'error-inconsistent')
    
    return ''