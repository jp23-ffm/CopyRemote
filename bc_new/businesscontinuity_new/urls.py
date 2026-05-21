from django.urls import path
from . import views
from .bc_rules_views import (
    apply_bc_rules_view,
    bc_datacenters,
    bc_texts,
    bc_preview,
    bc_start,
    bc_job_status,
)
#from debug_toolbar.toolbar import debug_toolbar_urls


app_name = 'businesscontinuity'

urlpatterns = [
    path('', views.server_view, name='server_view'),
    path('servers/', views.server_view, name='server_view'),
    path('load_search/<int:search_id>/', views.load_search, name='load_search'),
    path('save_search/', views.save_search, name='save_search'),
    path('delete_search/<int:search_id>/', views.delete_search, name='delete_search'),
    path('export/<str:filetype>/', views.export_to_file, name='export_to_file'),
    path('export/status/<uuid:job_id>/<str:filetype>/', views.export_status, name='export_status'),
    path('export/download/<uuid:job_id>/<str:filetype>/', views.download_export, name='download_export'),
    path('charts/', views.chart_view, name='chart_view'),
    # Business Continuity
    path('edit/<str:server_unique_id>/', views.edit_server_info, name='edit_server_info'),
    path('get_server_history/', views.get_server_history, name='get_server_history'),    
    path('bulk_update/', views.servers_bulk_update, name='servers_bulk_update'),
    path('import_csv/', views.bulk_import_csv, name='bulk_import_csv'),
    path('update_permanentfilter_field/', views.update_permanentfilter_field, name='update_permanentfilter_field'),
    path('logs_imports/', views.log_imports, name='logs_imports'),
    # Bulk update / import status
    path('bulk_update/status/<uuid:job_id>/', views.bulk_update_status, name='bulk_update_status'),
    path('import_csv/status/<uuid:job_id>/',  views.import_csv_status,  name='import_csv_status'),
    # BC Rules (views from bc_rules_views.py)
    path('apply_bc_rules/',                       apply_bc_rules_view, name='apply_bc_rules'),
    path('apply_bc_rules/datacenters/',            bc_datacenters,      name='bc_datacenters'),
    path('apply_bc_rules/texts/',                  bc_texts,            name='bc_texts'),
    path('apply_bc_rules/preview/',                bc_preview,          name='bc_preview'),
    path('apply_bc_rules/start/',                  bc_start,            name='bc_start'),
    path('apply_bc_rules/status/<uuid:job_id>/',   bc_job_status,       name='bc_job_status'),
    # DR Reset
    path('reset_dr/',                              views.reset_dr,            name='reset_dr'),
    path('reset_dr/status/<uuid:job_id>/',         views.reset_dr_status,     name='reset_dr_status'),
] #+ debug_toolbar_urls()

