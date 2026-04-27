from rest_framework.routers import DefaultRouter

app_name = 'api'
from .views import GetJsonEndpoint, SrvPropView, ModelFieldsContentView, ModelFieldsMappingView, HealthCheckView, QueryBuilderView #, StatusCheck
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

router = DefaultRouter()


urlpatterns = [
    path("srvprop/", SrvPropView.as_view(), name="srvprop"),
    path("query-builder/", QueryBuilderView.as_view(), name="query_builder"),
    #path("health/", HealthCheckView.as_view(), name="health"),
    #path('status/', StatusCheck.as_view(), name='global-status'),
    path('modelfieldscontent/<str:app>/', ModelFieldsContentView.as_view()),
    path('modelfieldsmapping/<str:app>/', ModelFieldsMappingView.as_view()),
    # OpenAPI schema + docs
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
