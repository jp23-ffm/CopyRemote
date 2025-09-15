# templatetags/server_extras.py
from django import template

register = template.Library()

@register.filter
def lookup(obj, key):
    """
    Template filter pour accéder aux valeurs d'un dictionnaire ou attribut d'objet dynamiquement
    Usage: {{ my_dict|lookup:"my_key" }} ou {{ my_object|lookup:"my_attribute" }}
    """
    if obj is None:
        return ''
        
    if isinstance(obj, dict):
        return obj.get(key, '')
    
    # Pour les objets modèles
    try:
        return getattr(obj, key, '')
    except (AttributeError, TypeError):
        return ''