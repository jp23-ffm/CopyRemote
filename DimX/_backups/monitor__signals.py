from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from monitor.models import LoginLog
import socket
   
    
@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):

    ip_address=request.META.get('REMOTE_ADDR')
    hostname = None
    if ip_address:
        try:
            hostname = socket.gethostbyaddr(ip_address)[0]
        except:
            hostname = None
    
    LoginLog.objects.create(
        username=user,
        client_ip_address=request.META.get('REMOTE_ADDR'),
        client_hostname = hostname,
        server_hostname = socket.gethostname()
    )
