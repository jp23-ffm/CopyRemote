from django.urls import path
from . import views

app_name = 'claude'

urlpatterns = [
    path('', views.server_list, name='server_list'),
    path('servers/', views.server_list, name='servers'),
    path('annotation/<str:hostname>/', views.edit_annotation, name='edit_annotation'),
]
