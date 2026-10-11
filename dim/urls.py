from django.urls import path
from . import views
from . import discrepancy_views as disc

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

    # Missing-data discrepancies (resource_type: share | object)
    path('discrepancies/<str:resource_type>/dashboard/', disc.disc_dashboard_view, name='disc_dashboard'),
    path('discrepancies/<str:resource_type>/list/', disc.disc_list_view, name='disc_list'),
    path('discrepancies/<str:resource_type>/api/trend/', disc.disc_trend_api, name='disc_trend_api'),
    path('discrepancies/<str:resource_type>/api/dashboard-filter/', disc.disc_dashboard_filter_api, name='disc_dashboard_filter_api'),
    path('discrepancies/<str:resource_type>/export/<str:filetype>/', disc.disc_export_to_file, name='disc_export_to_file'),
    path('discrepancies/<str:resource_type>/charts/', disc.disc_chart_view, name='disc_chart_view'),
    path('discrepancies/<str:resource_type>/bulk-annotation/', disc.disc_bulk_annotation, name='disc_bulk_annotation'),
    path('discrepancies/<str:resource_type>/save-search/', disc.disc_save_search, name='disc_save_search'),
    path('discrepancies/<str:resource_type>/load-search/<int:search_id>/', disc.disc_load_search, name='disc_load_search'),
]
