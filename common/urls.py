# common/urls.py
from django.urls import path
from . import views

app_name = 'common'

urlpatterns = [
    # Charts APIs - réutilisables
    path('api/charts/save/', views.save_chart_view, name='save_chart_view'),
    path('api/charts/list/', views.list_saved_charts, name='list_saved_charts'),
    path('api/charts/<int:chart_id>/delete/', views.delete_saved_chart, name='delete_saved_chart'),
]
