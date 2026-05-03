import logging

logger = logging.getLogger(__name__)


class ClientLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only log API calls
        if not request.path.startswith('/api/srvprop'):
            return self.get_response(request)
        
        # Get client IP (handles X-Forwarded-For from nginx)
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        
        # Log relevant information
        logger.info(
            "Client request",
            extra={
                'ip': ip,
                'user': str(request.user) if request.user.is_authenticated else 'anonymous',
                'method': request.method,
                'path': request.path,
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            }
        )
        
        return self.get_response(request)
