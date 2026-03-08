from django.urls import path
from . import views

app_name = 'accessrights'

urlpatterns = [
    # Dashboard page
    path('', views.dashboard, name='dashboard'),

    # JSON endpoints
    path('config/', views.get_config, name='config'),
    path('update/', views.update_permissions, name='update'),
    path('audit-log/', views.get_audit_log, name='audit_log'),
]
