from django.urls import path
from . import views

app_name = 'discrepancies'

urlpatterns = [
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('servers/', views.server_view, name='servers'),
    path('api/trend/', views.trend_api_view, name='trend_api'),
]
