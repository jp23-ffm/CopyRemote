# urls.py
from django.urls import path

urlpatterns = [
    # ... tes URLs existantes ...
    path('charts/', views.chart_view, name='chart_view'),
    
    # Saved queries
    path('api/saved-queries/', views.list_saved_queries, name='list_saved_queries'),
    path('api/saved-queries/save/', views.save_chart_query, name='save_chart_query'),
    path('api/saved-queries/<int:query_id>/delete/', views.delete_saved_query, name='delete_saved_query'),
    path('api/saved-queries/<int:query_id>/load/', views.load_saved_query, name='load_saved_query'),
]