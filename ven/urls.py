from django.urls import path
from . import views

app_name = 'discrepancies'

urlpatterns = [
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('servers/', views.server_view, name='servers'),
    path('api/trend/', views.trend_api_view, name='trend_api'),
    path('update_permanentfilter_field/', views.update_permanentfilter_field, name='update_permanentfilter_field'),
    path('annotation/<str:hostname>/', views.edit_annotation, name='edit_annotation'),
    path('bulk_annotation/', views.bulk_annotation, name='bulk_annotation'),
    path('export/<str:filetype>/', views.export_to_file, name='export_to_file'),
    path('export/status/<str:job_id>/<str:filetype>/', views.export_status, name='export_status'),
    path('export/download/<str:job_id>/<str:filetype>/', views.download_export, name='download_export'),
]
