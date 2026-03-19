from django.urls import path
from . import views
from common.views import initiate_sso, register_view

urlpatterns = [
    path('register/', register_view, name='register'),
    path('profile/', views.profile_view, name='profile'),
    path('sso/', initiate_sso, name='initiate_sso'),
]
