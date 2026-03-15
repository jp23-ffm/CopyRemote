from django.urls import path
from . import views

app_name = 'discrepancies'

urlpatterns = [
    path('dashboard/', views.dashboard_view, name='dashboard_view'),
    path('servers/', views.server_view, name='servers'),
    path('export/<str:filetype>/', views.export_to_file, name='export_to_file'),
    path('export/status/<uuid:job_id>/<str:filetype>/', views.export_status, name='export_status'),
    path('export/download/<uuid:job_id>/<str:filetype>/', views.download_export, name='download_export'),
    path('api/trend/', views.trend_api_view, name='trend_api'),
    path('api/dashboard-filter/', views.dashboard_filter_api, name='dashboard_filter_api'),
    path('update_permanentfilter_field/', views.update_permanentfilter_field, name='update_permanentfilter_field'),
    path('charts/', views.chart_view, name='chart_view'),
    path('annotation/<str:hostname>/', views.edit_annotation, name='edit_annotation'),
    path('bulk_annotation/', views.bulk_annotation, name='bulk_annotation'),
    path('logs_imports/', views.log_imports, name='logs_imports'),
    path('exclusions/', views.exclusion_list_api, name='exclusion_list_api'),
    path('exclusions/export/csv/', views.exclusion_export_csv, name='exclusion_export_csv'),
    path('exclusions/export/excel/', views.exclusion_export_excel, name='exclusion_export_excel'),
    path('dashboard/export/', views.dashboard_export_excel, name='dashboard_export_excel'),
    path('exclusions/<int:pk>/delete/', views.exclusion_delete_api, name='exclusion_delete_api'),
    path('exclusions/<int:pk>/update/', views.exclusion_update_api, name='exclusion_update_api'),
    path('save_search/', views.save_search, name='save_search'),
    path('load_search/<int:search_id>/', views.load_search, name='load_search'),
    path('delete_search/<int:search_id>/', views.delete_search, name='delete_search'),
]
