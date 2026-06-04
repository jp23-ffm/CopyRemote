from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

from django.conf import settings
from django.conf.urls import include
from django.conf.urls.static import static

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url='/static/inventory/img/favicon.svg', permanent=True)),
    path('admin/', admin.site.urls),
    path('user/', include('userapp.urls')),    
    path('inventory/', include('inventory.urls', namespace='inventory')),
    path('common/', include('common.urls', namespace='common')),   
    path('businesscontinuity/', include('businesscontinuity.urls', namespace='businesscontinuity')),
    path('discrepancies/', include('discrepancies.urls')),    
    path('api/', include('api.urls')),
    path('accessrights/', include('accessrights.urls')),
    path('monitor/', include('monitor.urls', namespace='monitor')),
    path('hardware/', include('hardware.urls', namespace='hardware')),    
]
