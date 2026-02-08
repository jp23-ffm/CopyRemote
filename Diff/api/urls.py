from rest_framework.routers import DefaultRouter
from .views import GetJsonEndpoint, SrvPropView, ModelFieldsContentView, ModelFieldsMappingView, HealthCheckView #, StatusCheck
from django.urls import path

router = DefaultRouter()


urlpatterns = [
    path("srvprop/", SrvPropView.as_view(), name="srvprop"),
    path("health/", HealthCheckView.as_view(), name="health"),
    #path('status/', StatusCheck.as_view(), name='global-status'),
    path('modelfieldscontent/<str:app>/', ModelFieldsContentView.as_view()),
    path('modelfieldsmapping/<str:app>/', ModelFieldsMappingView.as_view()),
] 
