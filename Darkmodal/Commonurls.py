# common/urls.py
urlpatterns = [
    # Charts
    path('api/charts/save/', views.save_chart_view, name='save_chart_view'),
    path('api/charts/list/', views.list_saved_charts, name='list_saved_charts'),
    path('api/charts/<int:chart_id>/delete/', views.delete_saved_chart, name='delete_saved_chart'),
    
    # Preferences
    path('api/preferences/', views.get_preferences, name='get_preferences'),
    path('api/preferences/save/', views.save_preferences, name='save_preferences'),
    path('api/preferences/update/', views.update_single_preference, name='update_single_preference'),
]
