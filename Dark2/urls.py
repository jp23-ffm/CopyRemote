from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.server_list, name='server_list'),
    path('servers/', views.server_list, name='servers'),
    path('annotation/<str:hostname>/', views.edit_annotation, name='edit_annotation'),
    path('export/grouped/', views.export_grouped_csv, name='export_grouped_csv'),
    path('charts/', views.chart_view, name='chart_view'),
    path('test-chart-data/', views.test_chart_data, name='test_chart_data'),

]
