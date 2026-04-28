import json
import os
import time
from pathlib import Path

from django.db.models import F
from django.utils import timezone

_CONFIG_PATH = Path(__file__).resolve().parent / 'stats_config.json'
_CACHE_TTL = 60  # seconds

_cache = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}


def _load_config():
    """Return parsed config, reloading from disk if file changed or TTL expired."""
    now = time.monotonic()
    if now - _cache['checked_at'] < _CACHE_TTL:
        return _cache['data']

    _cache['checked_at'] = now
    try:
        mtime = os.path.getmtime(_CONFIG_PATH)
        if mtime != _cache['mtime'] or _cache['data'] is None:
            with open(_CONFIG_PATH, encoding='utf-8') as f:
                data = json.load(f)
            _cache['data'] = {
                'include_apps': set(data.get('include_apps', [])),
                'exclude_apps': set(data.get('exclude_apps', [])),
                'include_paths': tuple(data.get('include_paths', [])),
                'exclude_paths': tuple(data.get('exclude_paths', [])),
            }
            _cache['mtime'] = mtime
    except Exception:
        pass  # keep stale config on error

    return _cache['data']


class StatsMiddleware:
    """Records aggregated view hit counts per authenticated user."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            return response

        if response.status_code in (404, 500):
            return response

        cfg = _load_config()
        if cfg is None:
            return response

        path = request.path

        # include_paths: force-track even if app is excluded
        if cfg['include_paths'] and path.startswith(cfg['include_paths']):
            _upsert_hit(request, path)
            return response

        if path.startswith(cfg['exclude_paths']):
            return response

        resolver_match = getattr(request, 'resolver_match', None)
        if resolver_match is None:
            return response

        view_name = resolver_match.view_name or ''
        if not view_name:
            return response

        app_name = (
            resolver_match.app_name
            or resolver_match.namespace
            or _app_from_path(path)
        )

        if app_name in cfg['exclude_apps']:
            return response

        if cfg['include_apps'] and app_name not in cfg['include_apps']:
            return response

        _upsert_hit(request, path, app_name, view_name)
        return response


def _app_from_path(path):
    parts = path.strip('/').split('/')
    return parts[0] if parts else ''


def _upsert_hit(request, path, app_name=None, view_name=None):
    from monitor.models import StatsRequest

    if app_name is None:
        resolver_match = getattr(request, 'resolver_match', None)
        app_name = (
            resolver_match.app_name or resolver_match.namespace or _app_from_path(path)
            if resolver_match else _app_from_path(path)
        )
    if view_name is None:
        resolver_match = getattr(request, 'resolver_match', None)
        view_name = resolver_match.view_name if resolver_match else path

    today = timezone.localdate()
    obj, created = StatsRequest.objects.get_or_create(
        date=today,
        app_name=app_name,
        view_name=view_name,
        method=request.method,
        user=request.user,
        defaults={'hit_count': 1},
    )
    if not created:
        StatsRequest.objects.filter(pk=obj.pk).update(hit_count=F('hit_count') + 1)
