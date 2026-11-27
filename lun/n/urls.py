from django.urls import path
from . import views
from . import discrepancy_views as disc

app_name = 'hardware'

urlpatterns = [
    path('', views.server_view, name='servers'),
    path('annotation/<str:hostname>/', views.edit_annotation, name='edit_annotation'),   
    path('bulk_annotation/', views.bulk_annotation, name='bulk_annotation'),   
    path('export/<str:filetype>/', views.export_to_file, name='export_to_file'),
    path('export/status/<uuid:job_id>/<str:filetype>/', views.export_status, name='export_status'),
    path('export/download/<uuid:job_id>/<str:filetype>/', views.download_export, name='download_export'),
    path('save_search/', views.save_search, name='save_search'),
    path('load_search/<int:search_id>/', views.load_search, name='load_search'),
    path('delete_search/<int:search_id>/', views.delete_search, name='delete_search'),
    path('logs_imports/', views.log_imports, name='logs_imports'),    
    path('charts/', views.chart_view, name='chart_view'),

    # Data-quality discrepancies (missing / invalid fields)
    path('discrepancies/dashboard/', disc.disc_dashboard_view, name='disc_dashboard'),
    path('discrepancies/list/', disc.disc_list_view, name='disc_list'),
    path('discrepancies/api/trend/', disc.disc_trend_api, name='disc_trend_api'),
    path('discrepancies/api/dashboard-filter/', disc.disc_dashboard_filter_api, name='disc_dashboard_filter_api'),
    path('discrepancies/export/<str:filetype>/', disc.disc_export_to_file, name='disc_export_to_file'),
    path('discrepancies/charts/', disc.disc_chart_view, name='disc_chart_view'),
    path('discrepancies/bulk-annotation/', disc.disc_bulk_annotation, name='disc_bulk_annotation'),
    path('discrepancies/save-search/', disc.disc_save_search, name='disc_save_search'),
    path('discrepancies/load-search/<int:search_id>/', disc.disc_load_search, name='disc_load_search'),
 ]
