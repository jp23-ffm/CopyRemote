from django.urls import path
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter

from api.views import MonitorStatusView

app_name = 'monitor'

urlpatterns = [
    path('status', MonitorStatusView.as_view(), name='status'),
    path('dashboard/', TemplateView.as_view(template_name='dashboard.html'), name='dashboard'),
] 
