from django.urls import path
#from . import views
from . import views_optimized as views

app_name = 'inventory'

urlpatterns = [
  
    path('', views.server_view, name='server_view'),
    path('servers/', views.server_view, name='server_view'),

    path('api/columns/', views.api_column_data, name='api_column_data'),
    path('api/column-data/', views.api_column_data, name='api_column_data_alt'),

    path('annotation/<str:hostname>/', views.edit_annotation, name='edit_annotation'),


    path('load_search/<int:search_id>/', views.load_search, name='load_search'),
    path('save_search/', views.save_search, name='save_search'),
    path('delete_search/<int:search_id>/', views.delete_search, name='delete_search'),

    path('export/<str:filetype>/', views.export_to_file, name='export_to_file'),
    path('export/grouped/<str:filetype>/', views.export_to_file_grouped, name='export_grouped'),
    path('export/status/<uuid:job_id>/<str:filetype>/', views.export_status, name='export_status'),
    path('export/download/<uuid:job_id>/<str:filetype>/', views.download_export, name='download_export'),

    path('update_permanentfilter_field/', views.update_permanentfilter_field, name='update_permanentfilter_field'),
    path('bulk_update/', views.servers_bulk_update, name='servers_bulk_update'),
    path('import_csv/', views.bulk_import_csv, name='bulk_import_csv'),
    path('logs_imports/', views.log_imports, name='logs_imports'),
    path('charts/', views.chart_view, name='chart_view'),
]
