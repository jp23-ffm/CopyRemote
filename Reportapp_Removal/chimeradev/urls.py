from django.contrib import admin
from django.urls import path, include
from common.views import custom_login, root_redirect
from django.contrib.auth import views as auth_views
from djangosaml2.views import LoginView, LogoutView, MetadataView, AssertionConsumerServiceView

from django.conf import settings
from django.conf.urls import include
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView


urlpatterns = [
    path('', root_redirect),
    path('admin/', admin.site.urls),
    path('user/', include('userapp.urls')),
    path('reportapp/', include('reportapp.urls')),
    #path('continuity/', include('continuity.urls')),
    path('login/', custom_login, name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('saml2/login/', LoginView.as_view(), name='saml2_login'),
    path('saml2/logout/', LogoutView.as_view(), name='saml2_logout'),
    path('saml2/metadata/', MetadataView.as_view(), name='saml2_metadata'),
    #path('saml2/acs/', CustomAssertionConsumerServiceView.as_view(), name='saml2_acs'),
    path('saml2/acs/', AssertionConsumerServiceView.as_view(), name='saml2_acs'),
    path('api/', include('api.urls')),
    #path('servernodb', include('reportappnodb.urls')),
    path('businesscontinuity/', include('businesscontinuity.urls', namespace='businesscontinuity')),
    #path('servers/', include('servers.urls', namespace='servers')),
    path('inventory/', include('inventory.urls', namespace='inventory')),
    path('monitor/', include('monitor.urls', namespace='monitor')),
    path('common/', include('common.urls', namespace='common')),
    path('discrepancies/', include('discrepancies.urls', namespace='discrepancies')),
    path('accessrights/', include('accessrights.urls')),
    #path('serversgroups/', include('claude.urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    # Optional UI:
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),    
    
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

#if settings.DEBUG:
#    import debug_toolbar
#    urlpatterns += [
#        path('__debug__/', include(debug_toolbar.urls)),
#    ]
