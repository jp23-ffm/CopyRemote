import socket

from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.dispatch import receiver

from monitor.models import AuditConnection, LoginLog


def _get_ip(request):
    return request.META.get('REMOTE_ADDR')


def _get_user_agent(request):
    return request.META.get('HTTP_USER_AGENT', '')


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    ip_address = _get_ip(request)
    hostname = None
    if ip_address:
        try:
            hostname = socket.gethostbyaddr(ip_address)[0]
        except Exception:
            hostname = None

    # Keep existing LoginLog for backwards compatibility
    LoginLog.objects.create(
        username=user,
        client_ip_address=ip_address,
        client_hostname=hostname,
        server_hostname=socket.gethostname(),
    )

    AuditConnection.objects.create(
        user=user,
        username=str(user),
        action='login',
        ip_address=ip_address,
        user_agent=_get_user_agent(request),
    )


@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    if user is None:
        return
    AuditConnection.objects.create(
        user=user,
        username=str(user),
        action='logout',
        ip_address=_get_ip(request),
        user_agent=_get_user_agent(request),
    )


@receiver(user_login_failed)
def log_login_failed(sender, credentials, request, **kwargs):
    AuditConnection.objects.create(
        user=None,
        username=credentials.get('username', ''),
        action='login_failed',
        ip_address=_get_ip(request),
        user_agent=_get_user_agent(request),
    )
