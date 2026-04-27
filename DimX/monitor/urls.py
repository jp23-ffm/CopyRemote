from django.urls import path
from django.views.generic import TemplateView
from api.views import MonitorStatusView
from monitor import views

app_name = 'monitor'

urlpatterns = [
    path('status', MonitorStatusView.as_view(), name='status'),
    path('dashboard/', TemplateView.as_view(template_name='dashboard.html'), name='dashboard'),

    # Stats dashboard
    path('stats/', views.stats_dashboard, name='stats_dashboard'),

    # JSON endpoints for Chart.js
    path('stats/top-views/', views.stats_top_views, name='stats_top_views'),
    path('stats/hits-by-day/', views.stats_hits_by_day, name='stats_hits_by_day'),
    path('stats/hits-by-app/', views.stats_hits_by_app, name='stats_hits_by_app'),
    path('stats/concurrent/', views.stats_concurrent, name='stats_concurrent'),
    path('stats/connections/', views.stats_connections, name='stats_connections'),
    path('stats/export/xlsx/', views.stats_export_xlsx, name='stats_export_xlsx'),
]
