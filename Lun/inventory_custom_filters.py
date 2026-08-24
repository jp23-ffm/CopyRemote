from django import template
from django.utils.dateparse import parse_datetime

register = template.Library()


@register.filter
def format_iso_date(value):
    """Format an ISO-8601 date string (as stored in ServerAnnotation.history) as d/m/Y H:i."""
    if not value:
        return ''
    dt = parse_datetime(value)
    return dt.strftime('%d/%m/%Y %H:%M') if dt else value

@register.filter
def get_item(obj, key):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
    
    

@register.filter
def lookup(obj, key):
    """
    Filter Template to dynamically access to a dictionary value or object attribute
    Usage: {{ my_dict|lookup:"my_key" }} or {{ my_object|lookup:"my_attribute" }}
    """
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
def is_column_visible(column_name, visible_columns_str):
    """
    Check if a column is in the visible columns list.
    Used for lazy loading - only render data for visible columns.

    Usage: {{ field.name|is_column_visible:visible_columns }}

    Args:
        column_name: The name of the column to check
        visible_columns_str: Comma-separated string of visible column names

    Returns:
        True if the column is visible or if no visible_columns specified (show all by default)
    """
    # If no visible columns specified, check against default visible columns
    if not visible_columns_str:
        # Default: show SERVER_ID and columns marked as ischecked in field_labels.json
        # For simplicity, return True to show all columns by default
        return True

    # Parse the comma-separated string
    visible_columns = set(col.strip() for col in visible_columns_str.split(',') if col.strip())

    # SERVER_ID is always visible
    if column_name == 'SERVER_ID':
        return True

    return column_name in visible_columns


@register.filter
def split(value, delimiter=','):
    """
    Split a string by delimiter and return a list.
    Usage: {{ "a,b,c"|split:"," }}
    """
    if not value:
        return []
    return [item.strip() for item in value.split(delimiter) if item.strip()]


