from django.urls import path
from . import views

app_name = 'applications'

urlpatterns = [
    path('', views.application_view, name='applications'),
    path('export/<str:filetype>/', views.export_to_file, name='export_to_file'),
    path('export/status/<uuid:job_id>/<str:filetype>/', views.export_status, name='export_status'),
    path('export/download/<uuid:job_id>/<str:filetype>/', views.download_export, name='download_export'),
    path('save_search/', views.save_search, name='save_search'),
    path('load_search/<int:search_id>/', views.load_search, name='load_search'),
    path('delete_search/<int:search_id>/', views.delete_search, name='delete_search'),
    path('logs_imports/', views.log_imports, name='logs_imports'),
    path('charts/', views.chart_view, name='chart_view'),
]
