from rest_framework.routers import DefaultRouter
#from .views import ServerViewSet, ServerDetailViewSet, ServerMultiViewSet, GetJsonEndpoint, GenericQueryView, SrvPropView, ModelFieldsContentView, ModelFieldsMappingView, HealthCheckView #, QueryBuilderView, StatusCheck
#from .views_v2 import SrvPropView as SrvPropView2, QueryBuilderView
from .views import SrvPropView, AppliPropView, ModelFieldsContentView, ModelFieldsMappingView, HealthCheckView, QueryBuilderView #,ServerViewSet, ServerDetailViewSet, ServerMultiViewSet, GetJsonEndpoint, GenericQueryView,
#from .views import ServerViewSet, ServerDetailViewSet, ServerMultiViewSet, GetJsonEndpoint, GenericQueryView, ModelFieldsContentView, ModelFieldsMappingView, HealthCheckView, QueryBuilderView, SrvPropView
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

app_name = 'api'
router = DefaultRouter()
#router.register('servers', ServerViewSet, basename='server')

urlpatterns = [
    #path("query/", GenericQueryView.as_view(), name="generic-query"),
    path("srvprop/", SrvPropView.as_view(), name="srvprop"),
    path("srvprop2/", SrvPropView.as_view(), name="srvprop2"),
    path("appliprop/", AppliPropView.as_view(), name="appliprop"),
    path("query-builder/", QueryBuilderView.as_view(), name="query_builder"),
    path("health/", HealthCheckView.as_view(), name="health"),
    path('modelfieldscontent/<str:app>/', ModelFieldsContentView.as_view()),
    path('modelfieldsmapping/<str:app>/', ModelFieldsMappingView.as_view()),
    # OpenAPI schema + docs
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='api:schema'), name='swagger-ui'),
    path('redoc/', SpectacularRedocView.as_view(url_name='api:schema'), name='redoc'),
]# + router.urls
