from django.db.models import F
from django.utils import timezone

_IGNORED_APP_NAMES = {'admin', 'staticfiles', 'monitor'}
_IGNORED_PATH_PREFIXES = ('/static/', '/favicon', '/admin/')


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

        path = request.path
        for prefix in _IGNORED_PATH_PREFIXES:
            if path.startswith(prefix):
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

        if app_name in _IGNORED_APP_NAMES:
            return response

        _upsert_hit(request.user, app_name, view_name, request.method)
        return response


def _app_from_path(path):
    parts = path.strip('/').split('/')
    return parts[0] if parts else ''


def _upsert_hit(user, app_name, view_name, method):
    from monitor.models import StatsRequest
    today = timezone.localdate()
    obj, created = StatsRequest.objects.get_or_create(
        date=today,
        app_name=app_name,
        view_name=view_name,
        method=method,
        user=user,
        defaults={'hit_count': 1},
    )
    if not created:
        StatsRequest.objects.filter(pk=obj.pk).update(hit_count=F('hit_count') + 1)
