from django.urls import path
from . import views

app_name = 'storage'

urlpatterns = [
    path('', views.storage_view, name='shares'),
    path('objects/', views.objects_view, name='objects'),
    path('annotation/<str:resource_type>/', views.edit_annotation, name='edit_annotation'),
    path('bulk-annotation/<str:resource_type>/', views.bulk_annotation, name='bulk_annotation'),
    path('charts/<str:resource_type>/', views.chart_view, name='chart_view'),
    path('export/<str:resource_type>/<str:filetype>/', views.export_to_file, name='export_to_file'),
    path('export-status/<uuid:job_id>/<str:filetype>/', views.export_status, name='export_status'),
    path('export-download/<uuid:job_id>/<str:filetype>/', views.download_export, name='download_export'),
    path('save-search/<str:resource_type>/', views.save_search, name='save_search'),
    path('load-search/<str:resource_type>/<int:search_id>/', views.load_search, name='load_search'),
    path('delete-search/<str:resource_type>/<int:search_id>/', views.delete_search, name='delete_search'),
    path('logs-imports/', views.log_imports, name='logs_imports'),
]
