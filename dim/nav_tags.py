"""
Template tag for the topbar app selector(s).

Usage in templates:
    {% load nav_tags %}
    {% render_nav 'inventory' %}
    {% render_nav 'inventory' 'history' %}
"""
from django import template
from django.urls import reverse, NoReverseMatch

from accessrights.helpers import user_perms
from common.nav import get_nav_config

register = template.Library()


def _resolve_entries(entries, perms, current_key):
    resolved = []
    for entry in entries:
        perm = entry.get('permission')
        if perm and perm not in perms:
            continue
        try:
            url = reverse(entry['url_name'])
        except NoReverseMatch:
            continue
        resolved.append({
            'label': entry['label'],
            'url': url,
            'new_tab': entry.get('new_tab', False),
            'current': current_key is not None and entry.get('key') == current_key,
        })
    return resolved


@register.inclusion_tag('common/nav_selector.html', takes_context=True)
def render_nav(context, current_app, current_page=None):
    user = context.get('user')
    perms = user_perms(user)
    config = get_nav_config() or {}

    nav_main = _resolve_entries(config.get('main', []), perms, current_app)
    nav_sub = _resolve_entries(config.get('sub', {}).get(current_app, []), perms, current_page)
    sub_has_current = any(item['current'] for item in nav_sub)

    return {
        'nav_main': nav_main,
        'nav_sub': nav_sub,
        'sub_has_current': sub_has_current,
        # A single sub-page only needs a selector when it's not the page you're already on.
        'nav_sub_visible': bool(nav_sub) and not (len(nav_sub) == 1 and sub_has_current),
    }
