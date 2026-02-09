"""
views_optimized.py - Version optimisée de l'API

CHANGEMENTS PAR RAPPORT À views.py:
1. Support ANNOTATION pour l'index inventory (filtres ET fields)
2. Correction du chemin hardcodé /tmp/api.log -> settings.BASE_DIR
3. Correction du bare except dans HealthCheckView
4. Amélioration du streaming CSV avec iterator()
5. Meilleure validation des filtres par index

Pour utiliser: dans urls.py, remplacer 'from . import views' par 'from . import views_optimized as views'
"""

import csv
import datetime
import json
import logging
import os
import tempfile
import time
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.http import StreamingHttpResponse, HttpResponse
from django.core.exceptions import FieldError, ValidationError
from django.db import connection
from django.db.models import Q
from django.db.models.functions import Lower
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, status, generics
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from rest_framework.views import APIView

from businesscontinuity.models import Server as BCServer, ServerUnique
from reportapp.models import Server as ReportServer
from inventory.models import Server as InventoryServer, ServerAnnotation
from monitor.views import get_cluster_status

from .custom_filters import DynamicFilterBackend
from .serializers import (
    ServerSerializer, LimitedServerSerializer, GenericQuerySerializer,
    SrvPropSerializer, BusinessContinuitySerializer, InventoryServerSerializer
)
from .streaming_renderers import CSVRenderer, Echo, StreamingOneLinePerInstanceJSONRenderer

from api.management.commands import status_checks as checks


# =============================================================================
# CONFIGURATION
# =============================================================================

field_app_mapping = {
    'reportapp': ReportServer,
    'inventory': InventoryServer,
    'businesscontinuity': BCServer
}

# Chemin du log API - utilise un répertoire portable
API_LOG_DIR = getattr(settings, 'API_LOG_DIR', None) or tempfile.gettempdir()
API_LOG_FILE = os.path.join(API_LOG_DIR, 'chimera_api.log')

# Logger Python standard (alternative au fichier)
logger = logging.getLogger('chimera.api')


def api_log(text):
    """
    Log API calls - version portable (fonctionne sur Windows et Linux)
    """
    unix_ts = time.time()
    currenttime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(unix_ts))

    try:
        with open(API_LOG_FILE, mode="a", encoding="utf-8") as file:
            file.write(f"{currenttime} {text}\n")
    except (IOError, OSError) as e:
        # Fallback sur le logger Python si le fichier n'est pas accessible
        logger.warning(f"Cannot write to {API_LOG_FILE}: {e}")
        logger.info(text)


# =============================================================================
# HELPER CLASSES
# =============================================================================

class ServerPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 200


# =============================================================================
# MODEL FIELDS VIEWS (inchangées)
# =============================================================================

class ModelFieldsContentView(APIView):
    def get_field_mapping(self, app):
        current_dir = os.path.dirname(__file__)
        fields_labels_file = os.path.join(current_dir, f'../{app}/field_labels.json')
        try:
            with open(fields_labels_file, 'r') as f:
                fields_labels = json.load(f)
        except FileNotFoundError:
            return {'error': f'Field labels file not found for app {app}'}
        except PermissionError:
            return {'error': f'Permission denied when trying to read field labels file for app {app}'}
        except json.JSONDecodeError:
            return {'error': f'Invalid JSON in field labels file for app {app}'}
        except Exception as e:
            return {'error': str(e)}

        if 'api_ModelFieldsContentView_allowed' in fields_labels:
            allowed_fields = fields_labels['api_ModelFieldsContentView_allowed']
            if app == 'businesscontinuity':
                return {field: 'server_unique__' + field if 'model_extra' in fields_labels['fields'].get(field, {}) else field for field in allowed_fields}
            else:
                return {field: field for field in allowed_fields}
        else:
            allowed_fields = {properties['inputname']: 'server_unique__' + field if app == 'businesscontinuity' and 'model_extra' in properties else field
                              for field, properties in fields_labels['fields'].items() if 'listbox' in properties}
            return allowed_fields

    def get(self, request, app):
        try:
            model = field_app_mapping[app]
        except LookupError:
            return Response({'error': 'Model not found'}, status=404)
        field_name = request.GET.get('field')
        field_mapping = self.get_field_mapping(app)
        allowed_fields = list(field_mapping.values())

        if field_name not in allowed_fields:
            return Response({'error': 'Field not allowed for query'}, status=404)

        try:
            unique_values = set(model.objects.values_list(field_name, flat=True))
        except KeyError:
            return Response({'error': 'Field not found in mapping'}, status=404)
        except FieldError as e:
            return Response({'error': f'Field not found in model: {str(e)}'}, status=404)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

        return Response({field_name: unique_values})


class ModelFieldsMappingView(APIView):

    def get_field_mapping(self, app):
        current_dir = os.path.dirname(__file__)
        fields_labels_file = os.path.join(current_dir, f'../{app}/field_labels.json')
        try:
            with open(fields_labels_file, 'r') as f:
                fields_labels = json.load(f)
        except FileNotFoundError:
            return {'error': f'Field labels file not found for app {app}'}
        except PermissionError:
            return {'error': f'Permission denied when trying to read field labels file for app {app}'}
        except json.JSONDecodeError:
            return {'error': f'Invalid JSON in field labels file for app {app}'}
        except Exception as e:
            return {'error': str(e)}

        field_mapping = {}
        for field, properties in fields_labels['fields'].items():
            if app == 'businesscontinuity' and 'model_extra' in properties:
                field_mapping[properties['inputname']] = 'server_unique__' + field
            else:
                field_mapping[properties['inputname']] = field
        return field_mapping

    def get(self, request, app):
        try:
            model = field_app_mapping[app]
        except KeyError:
            return Response({'error': 'Model not found'}, status=404)
        field_name = request.GET.get('field')
        field_mapping = self.get_field_mapping(app)
        if 'error' in field_mapping:
            return Response(field_mapping, status=500)

        return Response({v: k for k, v in field_mapping.items()})


# =============================================================================
# SERVER VIEWSETS (inchangés)
# =============================================================================

class ServerViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ReportServer.objects.all()
    serializer_class = LimitedServerSerializer

    def get_queryset(self):
        query_params = self.request.query_params
        relevant_params = ['SERVER_ID', 'PAMELA_COUNTRY', 'PAMELA_OSSHORTNAME']
        query_filter = Q()

        for param in relevant_params:
            if param in query_params and query_params[param]:
                values = query_params[param].split(',')
                or_conditions = Q()
                for value in values:
                    value_pattern = value.replace('*', '.*').upper()
                    or_conditions |= Q(**{f"{param}__iregex": rf"^{value_pattern}$"})
                query_filter &= or_conditions

        search_term = query_params.get('search', None)
        if search_term:
            search_conditions = Q()
            for field in ['SERVER_ID', 'PAMELA_COUNTRY', 'PAMELA_OSSHORTNAME']:
                search_conditions |= Q(**{f"{field}__icontains": search_term})
            query_filter &= search_conditions

        if any(param in query_params and not query_params[param] for param in relevant_params + ['search']):
            return ReportServer.objects.none()

        queryset = ReportServer.objects.filter(query_filter)
        return queryset


class ServerDetailViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ServerSerializer
    filter_backends = [SearchFilter, DjangoFilterBackend, OrderingFilter]
    filterset_fields = '__all__'
    search_fields = ['SERVER_ID', 'PAMELA_COUNTRY', 'PAMELA_OSSHORTNAME']

    def get_queryset(self):
        query_params = self.request.query_params
        if any(value == '' for value in query_params.values()):
            return ReportServer.objects.none()
        if not query_params:
            return ReportServer.objects.none()
        return ReportServer.objects.all()


class ServerMultiViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ServerSerializer
    filter_backends = [SearchFilter, DjangoFilterBackend, OrderingFilter, DynamicFilterBackend]
    filterset_fields = ['SERVER_ID', 'PAMELA_COUNTRY']
    search_fields = ['SERVER_ID', 'PAMELA_COUNTRY']
    ordering_fields = ['SERVER_ID', 'PAMELA_COUNTRY']

    def get_queryset(self):
        if not self.request.query_params:
            return ReportServer.objects.none()
        return ReportServer.objects.all()


# =============================================================================
# GENERIC QUERY VIEW (inchangé)
# =============================================================================

def validate_json_data(data, serializer):
    allowed_keys = set(serializer().fields.keys())
    for key in data:
        if key not in allowed_keys:
            raise ValueError(f"Invalid key '{key}' in JSON data. Allowed keys are: {', '.join(allowed_keys)}")


class GenericQueryView(APIView):

    def post(self, request):
        try:
            try:
                validate_json_data(request.data, GenericQuerySerializer)
            except ValueError as e:
                return Response({"Error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

            serializer = GenericQuerySerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            index_name = serializer.validated_data["index"]
            filters = serializer.validated_data.get("filters", {})
            fields = serializer.validated_data.get("fields", None)
            excludefields = serializer.validated_data.get("excludefields", None)
            default_exclude = ['id']

            if index_name == "reportapp":
                index_cls = ReportServer
                output_serializer = ServerSerializer
            elif index_name == "businesscontinuity":
                index_cls = BCServer
                output_serializer = BusinessContinuitySerializer
            else:
                return Response({"Error": f"Unsupported index: {index_name}"}, status=status.HTTP_400_BAD_REQUEST)

            invalid_filters = [fil for fil in filters if not hasattr(index_cls, fil) and not hasattr(ServerUnique, fil.split('__')[1] if '__' in fil else '')]
            if invalid_filters:
                return Response({"Error": f"Invalid fields for {index_name} index: {', '.join(invalid_filters)}"}, status=status.HTTP_400_BAD_REQUEST)

            queryset = index_cls.objects.filter(**filters)
            output_serializer_instance = output_serializer(queryset, many=True, fields=fields, excludefields=excludefields, default_exclude=default_exclude)
            return Response(output_serializer_instance.data, status=status.HTTP_200_OK)

        except Exception as e:
            error_data = {'Unexpected Error': f"{e}"}
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# =============================================================================
# SRVPROP VIEW - VERSION OPTIMISÉE AVEC SUPPORT ANNOTATION
# =============================================================================

class SrvPropView(APIView):
    """
    Endpoint principal de requête de propriétés serveur.

    NOUVEAU: Support du champ ANNOTATION pour l'index inventory.

    Usage ANNOTATION:
    - Dans filters: {"ANNOTATION": ["texte à chercher"]} -> filtre les serveurs ayant cette annotation
    - Dans fields: ["SERVER_ID", "ANNOTATION", ...] -> retourne les annotations avec les résultats
    - IMPORTANT: Si ANNOTATION est dans fields, SERVER_ID doit aussi y être

    Exemple de requête avec ANNOTATION:
    {
        "index": "inventory",
        "filters": {"ENVIRONMENT": ["PROD"]},
        "fields": ["SERVER_ID", "OSSHORTNAME", "ANNOTATION"]
    }

    Négation avec préfixe !:
    - Utiliser ! devant une valeur pour l'exclure
    - Compatible avec les wildcards: !*TEST*

    Exemple avec négation:
    {
        "index": "inventory",
        "filters": {"STATUS": ["!DEAD", "!DECOMMISSIONED"], "ENVIRONMENT": ["PROD"]},
        "fields": ["SERVER_ID", "STATUS"]
    }
    """

    renderer_classes = [JSONRenderer, CSVRenderer]
    pagination_class = ServerPagination

    STREAMING_THRESHOLD = 200
    STREAMING_CHUNK_SIZE = 10000

    MAX_RESULTS = 2000000
    MAX_FILTER_FIELDS = 15
    MAX_FILTER_VALUES_PER_FIELD = 15000

    # Champs spéciaux qui ne sont pas dans le modèle principal
    SPECIAL_FIELDS = {'ANNOTATION'}

    def post(self, request):
        try:
            api_log("------------------------")
            api_log(f"User: {request.user}")
            api_log(f"Payload: {request.data}")

            serializer = SrvPropSerializer(data=request.data)
            if not serializer.is_valid():
                api_log(f"Error: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            index_name = serializer.validated_data["index"]
            filters = dict(serializer.validated_data.get("filters", {}))  # Copie pour modification
            fields = serializer.validated_data.get("fields", None)
            excludefields = serializer.validated_data.get("excludefields", None)
            default_exclude = ['id']
            output_format = serializer.validated_data.get("format", "json")

            # ================================================================
            # VALIDATION DES FILTRES
            # ================================================================

            if len(filters) == 0:
                api_log(f"Error: The field 'filters' can't be empty")
                return Response({
                    "error": "The field 'filters' can't be empty"
                }, status=400)

            if len(filters) > self.MAX_FILTER_FIELDS:
                api_log(f"Error: Too many fields filters: {len(filters)} (max: {self.MAX_FILTER_FIELDS})")
                return Response({
                    "error": f"Too many fields filters: {len(filters)} (max: {self.MAX_FILTER_FIELDS})"
                }, status=400)

            for field, values in filters.items():
                if len(values) > self.MAX_FILTER_VALUES_PER_FIELD:
                    api_log(f"Error: Too many values for '{field}': {len(values)} (max: {self.MAX_FILTER_VALUES_PER_FIELD})")
                    return Response({
                        "error": f"Too many values for '{field}': {len(values)} (max: {self.MAX_FILTER_VALUES_PER_FIELD})"
                    }, status=400)

            # ================================================================
            # SÉLECTION DE L'INDEX
            # ================================================================

            if index_name == "reportapp":
                index_cls = ReportServer
                output_serializer = ServerSerializer
            elif index_name == "businesscontinuity":
                index_cls = BCServer
                output_serializer = BusinessContinuitySerializer
            elif index_name == "inventory":
                index_cls = InventoryServer
                output_serializer = InventoryServerSerializer
            else:
                api_log(f"Error: Unsupported index: {index_name}")
                return Response({"error": f"Unsupported index: {index_name}"}, status=status.HTTP_400_BAD_REQUEST)

            # ================================================================
            # NOUVEAU: GESTION DES ANNOTATIONS (inventory uniquement)
            # ================================================================

            annotation_in_filters = 'ANNOTATION' in filters
            annotation_in_fields = fields is not None and 'ANNOTATION' in fields
            include_annotations = annotation_in_fields

            # Vérifier que ANNOTATION n'est utilisé qu'avec inventory
            if (annotation_in_filters or annotation_in_fields) and index_name != 'inventory':
                api_log(f"Error: ANNOTATION is only available for index 'inventory'")
                return Response({
                    "error": "ANNOTATION is only available for index 'inventory'"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Si ANNOTATION dans fields, SERVER_ID doit aussi être présent
            if annotation_in_fields:
                if fields and 'SERVER_ID' not in fields:
                    api_log(f"Error: ANNOTATION requires SERVER_ID in fields")
                    return Response({
                        "error": "ANNOTATION requires SERVER_ID in fields. Without SERVER_ID, annotations cannot be mapped to results."
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Retirer ANNOTATION des fields pour le queryset (on l'ajoutera après la sérialisation)
                fields = [f for f in fields if f != 'ANNOTATION']

            # ================================================================
            # ALIAS MAPPING (businesscontinuity)
            # ================================================================

            alias_map = {
                'priority_asset': 'server_unique__priority_asset',
                'in_live_play': 'server_unique__in_live_play',
                'action_during_lp': 'server_unique__action_during_lp',
                'original_action_during_lp': 'server_unique__original_action_during_lp',
                'cluster': 'server_unique__cluster',
                'cluster_type': 'server_unique__cluster_type'
            }

            # ================================================================
            # PRE-FILTRE ANNOTATION (si ANNOTATION dans filters)
            # ================================================================

            annotation_server_ids = None
            annotation_exclude_server_ids = None

            if annotation_in_filters:
                annotation_values = filters.pop('ANNOTATION')  # Retirer du dict filters
                api_log(f"Processing ANNOTATION filter with values: {annotation_values}")

                # Séparer les valeurs d'inclusion et d'exclusion
                include_values = [v for v in annotation_values if not v.startswith('!')]
                exclude_values = [v[1:] for v in annotation_values if v.startswith('!')]  # Retirer le préfixe !

                # Traitement des valeurs d'inclusion
                if include_values:
                    has_wildcards = any('*' in v for v in include_values)

                    if has_wildcards:
                        annotation_query = Q()
                        for value in include_values:
                            pattern = value.replace('*', '.*')
                            annotation_query |= Q(notes__iregex=f"^{pattern}$")
                    else:
                        annotation_query = Q()
                        for value in include_values:
                            annotation_query |= Q(notes__icontains=value)

                    annotation_server_ids = list(
                        ServerAnnotation.objects.filter(annotation_query)
                        .values_list('SERVER_ID', flat=True)
                    )
                    api_log(f"ANNOTATION include filter matched {len(annotation_server_ids)} servers")

                    if not annotation_server_ids:
                        return Response({"count": 0, "results": []}, status=status.HTTP_200_OK)

                # Traitement des valeurs d'exclusion (négation avec !)
                if exclude_values:
                    has_wildcards = any('*' in v for v in exclude_values)

                    if has_wildcards:
                        exclude_query = Q()
                        for value in exclude_values:
                            pattern = value.replace('*', '.*')
                            exclude_query |= Q(notes__iregex=f"^{pattern}$")
                    else:
                        exclude_query = Q()
                        for value in exclude_values:
                            exclude_query |= Q(notes__icontains=value)

                    annotation_exclude_server_ids = list(
                        ServerAnnotation.objects.filter(exclude_query)
                        .values_list('SERVER_ID', flat=True)
                    )
                    api_log(f"ANNOTATION exclude filter matched {len(annotation_exclude_server_ids)} servers to exclude")

            # ================================================================
            # MAPPING ET VALIDATION DES FILTRES
            # ================================================================

            mapped_filters = {}
            for key, value in filters.items():
                # Ignorer les champs spéciaux déjà traités
                if key in self.SPECIAL_FIELDS:
                    continue
                mapped_key = alias_map.get(key, key)
                mapped_filters[mapped_key] = value

            # Validation des filtres selon l'index
            invalid_filters = self._validate_filters(mapped_filters, index_cls, index_name)

            if invalid_filters:
                api_log(f"Error: Invalid fields for {index_name} index: {', '.join(invalid_filters)}")
                return Response({
                    "error": f"Invalid fields for {index_name} index: {', '.join(invalid_filters)}"
                }, status=status.HTTP_400_BAD_REQUEST)

            # ================================================================
            # CONSTRUCTION DU QUERYSET
            # ================================================================

            # Déterminer les champs pour distinct
            if fields is None:
                excludefields = excludefields or []
                distinct_fields = [
                    field.name for field in index_cls._meta.fields
                    if field.name not in default_exclude and field.name not in excludefields
                ]
            else:
                # Retirer les champs spéciaux des distinct_fields
                distinct_fields = [f for f in fields if f not in self.SPECIAL_FIELDS]

            queryset = index_cls.objects.all()

            # Appliquer le pré-filtre ANNOTATION si présent
            if annotation_server_ids is not None:
                queryset = queryset.filter(SERVER_ID__in=annotation_server_ids)

            # Exclure les serveurs avec annotations correspondantes (négation avec !)
            if annotation_exclude_server_ids is not None:
                queryset = queryset.exclude(SERVER_ID__in=annotation_exclude_server_ids)

            # Construction du filtre global
            query_filter = Q()
            exclude_filter = Q()
            lower_annotations = {}
            exclude_lower_annotations = {}

            for field, values in mapped_filters.items():
                if not values:
                    continue

                # Séparer les valeurs normales des valeurs négatives (préfixées par !)
                include_values = [v for v in values if not v.startswith('!')]
                exclude_values = [v[1:] for v in values if v.startswith('!')]  # Retirer le préfixe !

                # Traitement des valeurs d'inclusion
                if include_values:
                    has_wildcards = any('*' in v for v in include_values)

                    if has_wildcards:
                        or_conditions = Q()
                        for value in include_values:
                            value_pattern = value.replace('*', '.*')
                            or_conditions |= Q(**{f"{field}__iregex": f"^{value_pattern}$"})
                        query_filter &= or_conditions
                    else:
                        lowered_values = [v.lower() for v in include_values]
                        lower_field_name = f"{field}_lower"
                        lower_annotations[lower_field_name] = Lower(field)
                        query_filter &= Q(**{f"{lower_field_name}__in": lowered_values})

                # Traitement des valeurs d'exclusion (négation avec !)
                if exclude_values:
                    has_wildcards = any('*' in v for v in exclude_values)

                    if has_wildcards:
                        for value in exclude_values:
                            value_pattern = value.replace('*', '.*')
                            exclude_filter |= Q(**{f"{field}__iregex": f"^{value_pattern}$"})
                    else:
                        lowered_values = [v.lower() for v in exclude_values]
                        lower_field_name = f"{field}_lower"
                        exclude_lower_annotations[lower_field_name] = Lower(field)
                        exclude_filter |= Q(**{f"{lower_field_name}__in": lowered_values})

            # Fusionner les annotations
            all_annotations = {**lower_annotations, **exclude_lower_annotations}

            # Appliquer les filtres
            if all_annotations:
                queryset = queryset.annotate(**all_annotations)

            if query_filter:
                queryset = queryset.filter(query_filter)

            if exclude_filter:
                queryset = queryset.exclude(exclude_filter)

            queryset = queryset.distinct(*distinct_fields).order_by(*distinct_fields)

            count = queryset.count()

            if count > self.MAX_RESULTS:
                api_log(f"Error: Too many results: {count} (maximum: {self.MAX_RESULTS})")
                return Response({
                    "error": f"Too many results: {count} (maximum: {self.MAX_RESULTS})",
                    "hint": "Please refine your filters to reduce the number of results",
                    "count": count
                }, status=status.HTTP_400_BAD_REQUEST)

            # ================================================================
            # GÉNÉRATION DE LA RÉPONSE
            # ================================================================

            if request.GET.get('page'):
                # Mode pagination
                api_log(f"Using the Paging Mode")
                return self._handle_paginated_response(
                    request, queryset, output_serializer, fields, excludefields,
                    default_exclude, output_format, include_annotations
                )

            elif count > self.STREAMING_THRESHOLD:
                # Mode streaming
                api_log(f"Nb items: {count} - Using the Streaming Mode")
                if output_format == "csv":
                    return self._stream_csv_response(
                        queryset, output_serializer, fields, excludefields,
                        default_exclude, include_annotations
                    )
                else:
                    return self._stream_json_response(
                        queryset, output_serializer, count, fields, excludefields,
                        default_exclude, include_annotations
                    )

            else:
                # Mode normal
                api_log(f"Nb items: {count} - Using the Normal Mode")
                if output_format == "csv":
                    return self._generate_csv_response(
                        queryset, output_serializer, fields, excludefields,
                        default_exclude, include_annotations
                    )
                else:
                    return self._generate_json_response(
                        queryset, output_serializer, count, fields, excludefields,
                        default_exclude, include_annotations
                    )

        except Exception as e:
            error_data = {"Unexpected Error": f"{e}"}
            api_log(f"Error: {e}")
            import traceback
            api_log(f"Traceback: {traceback.format_exc()}")
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        finally:
            api_log("End")

    def _validate_filters(self, mapped_filters, index_cls, index_name):
        """Valide les filtres selon l'index"""
        invalid_filters = []

        for fil in mapped_filters:
            field_name = fil.split('__')[0]

            # Vérifier si le champ existe sur le modèle principal
            if hasattr(index_cls, field_name):
                continue

            # Pour businesscontinuity, vérifier aussi server_unique
            if index_name == 'businesscontinuity' and '__' in fil:
                related_field = fil.split('__')[1]
                if hasattr(ServerUnique, related_field):
                    continue

            invalid_filters.append(fil)

        return invalid_filters

    def _add_annotations_to_data(self, data):
        """
        Ajoute les annotations aux données sérialisées.
        data: list de dicts avec au moins 'SERVER_ID'
        """
        if not data:
            return data

        # Récupérer tous les SERVER_ID
        server_ids = [item.get('SERVER_ID') for item in data if item.get('SERVER_ID')]

        if not server_ids:
            return data

        # Charger les annotations en une seule requête
        annotations = ServerAnnotation.objects.filter(SERVER_ID__in=server_ids)
        annotation_map = {ann.SERVER_ID: ann.notes or '' for ann in annotations}

        # Ajouter ANNOTATION à chaque résultat
        for item in data:
            server_id = item.get('SERVER_ID')
            item['ANNOTATION'] = annotation_map.get(server_id, '')

        return data

    def _generate_json_response(self, queryset, output_serializer, count, fields,
                                 excludefields, default_exclude, include_annotations):
        """Génère une réponse JSON normale (petit volume)"""
        output_serializer_instance = output_serializer(
            queryset,
            many=True,
            fields=fields,
            excludefields=excludefields,
            default_exclude=default_exclude
        )

        results = output_serializer_instance.data

        # Ajouter les annotations si demandé
        if include_annotations:
            results = self._add_annotations_to_data(list(results))

        response_data = {
            "count": count,
            "results": results
        }

        return Response(response_data, status=status.HTTP_200_OK)

    def _handle_paginated_response(self, request, queryset, output_serializer, fields,
                                    excludefields, default_exclude, output_format, include_annotations):
        """Gère la réponse paginée"""
        paginator = ServerPagination()
        page = paginator.paginate_queryset(queryset, request)

        if page is not None:
            serializer_instance = output_serializer(
                page, many=True,
                fields=fields,
                excludefields=excludefields,
                default_exclude=default_exclude
            )

            if output_format == "csv":
                return self._generate_csv_response(
                    page, output_serializer, fields, excludefields,
                    default_exclude, include_annotations
                )
            else:
                results = serializer_instance.data
                if include_annotations:
                    results = self._add_annotations_to_data(list(results))

                # Modifier la réponse paginée pour inclure les annotations
                response = paginator.get_paginated_response(results)
                return response

        return Response({"count": 0, "results": []}, status=status.HTTP_200_OK)

    def _stream_csv_response(self, queryset, serializer_class, fields, excludefields,
                            default_exclude, include_annotations=False):
        """
        Stream CSV response optimisé avec support annotations
        """
        def generate():
            pseudo_buffer = Echo()
            writer = csv.writer(pseudo_buffer)

            # Header
            first_obj = queryset.first()
            if first_obj:
                header_serializer = serializer_class(
                    first_obj,
                    fields=fields,
                    excludefields=excludefields,
                    default_exclude=default_exclude
                )
                header = list(header_serializer.data.keys())
                if include_annotations:
                    header.append('ANNOTATION')
                yield writer.writerow(header)

            # Utiliser iterator() pour économiser la mémoire
            chunk = []
            for obj in queryset.iterator(chunk_size=self.STREAMING_CHUNK_SIZE):
                chunk.append(obj)

                if len(chunk) >= self.STREAMING_CHUNK_SIZE:
                    yield from self._process_csv_chunk(
                        chunk, serializer_class, fields, excludefields,
                        default_exclude, include_annotations, writer
                    )
                    chunk = []

            # Traiter le dernier chunk
            if chunk:
                yield from self._process_csv_chunk(
                    chunk, serializer_class, fields, excludefields,
                    default_exclude, include_annotations, writer
                )

        response = StreamingHttpResponse(generate(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="data.csv"'
        return response

    def _process_csv_chunk(self, chunk, serializer_class, fields, excludefields,
                           default_exclude, include_annotations, writer):
        """Traite un chunk pour le CSV"""
        serializer = serializer_class(
            chunk,
            many=True,
            fields=fields,
            excludefields=excludefields,
            default_exclude=default_exclude
        )

        data = list(serializer.data)

        if include_annotations:
            data = self._add_annotations_to_data(data)

        for item in data:
            yield writer.writerow(item.values())

    def _generate_csv_response(self, queryset, serializer_class, fields, excludefields,
                               default_exclude, include_annotations=False):
        """Génère une réponse CSV non-streamée (petit volume)"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="data.csv"'
        writer = csv.writer(response)

        # Header
        if isinstance(queryset, list):
            first = queryset[0] if queryset else None
        else:
            first = queryset.first()

        if first:
            serializer = serializer_class(
                first,
                fields=fields,
                excludefields=excludefields,
                default_exclude=default_exclude
            )
            header = list(serializer.data.keys())
            if include_annotations:
                header.append('ANNOTATION')
            writer.writerow(header)

        # Data
        serializer_instance = serializer_class(
            queryset,
            many=True,
            fields=fields,
            excludefields=excludefields,
            default_exclude=default_exclude
        )

        data = list(serializer_instance.data)

        if include_annotations:
            data = self._add_annotations_to_data(data)

        for item in data:
            writer.writerow(item.values())

        return response

    def _stream_json_response(self, queryset, serializer_class, count, fields,
                             excludefields, default_exclude, include_annotations=False):
        """
        Stream JSON response optimisé avec support annotations
        """
        def generate():
            yield b'{"count": '
            yield str(count).encode('utf-8')
            yield b', "results": ['

            first = True
            chunk = []

            for obj in queryset.iterator(chunk_size=self.STREAMING_CHUNK_SIZE):
                chunk.append(obj)

                if len(chunk) >= self.STREAMING_CHUNK_SIZE:
                    for json_bytes in self._process_json_chunk(
                        chunk, serializer_class, fields, excludefields,
                        default_exclude, include_annotations, first
                    ):
                        yield json_bytes
                        first = False
                    chunk = []

            # Traiter le dernier chunk
            if chunk:
                for json_bytes in self._process_json_chunk(
                    chunk, serializer_class, fields, excludefields,
                    default_exclude, include_annotations, first
                ):
                    yield json_bytes
                    first = False

            yield b']}'

        response = StreamingHttpResponse(
            generate(),
            content_type='application/json'
        )
        response['X-Total-Count'] = str(count)
        response['Cache-Control'] = 'no-cache'
        return response

    def _process_json_chunk(self, chunk, serializer_class, fields, excludefields,
                            default_exclude, include_annotations, is_first):
        """Traite un chunk pour le JSON streaming"""
        serializer = serializer_class(
            chunk,
            many=True,
            fields=fields,
            excludefields=excludefields,
            default_exclude=default_exclude
        )

        data = list(serializer.data)

        if include_annotations:
            data = self._add_annotations_to_data(data)

        first = is_first
        for obj_data in data:
            if not first:
                yield b','
            first = False
            yield json.dumps(obj_data).encode('utf-8')


# =============================================================================
# HEALTH CHECK VIEW - CORRIGÉ
# =============================================================================

class HealthCheckView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        if request.META.get('REMOTE_ADDR') != '127.0.0.1':
            return HttpResponse('Forbidden', status=403)

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return Response({'status': 'healthy'}, status=200)
        except Exception as e:
            # CORRIGÉ: Capture explicite de l'exception au lieu de bare except
            logger.error(f"Health check failed: {e}")
            return Response({'status': 'unhealthy', 'error': str(e)}, status=503)


# =============================================================================
# MONITOR STATUS VIEW (inchangé)
# =============================================================================

class MonitorStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        simple = request.GET.get('simple') == 'true'
        response, http_status = get_cluster_status(simple)
        return Response(response, status=http_status)


# =============================================================================
# LEGACY: GetJsonEndpoint - CORRIGÉ
# =============================================================================

class GetJsonEndpoint(APIView):
    """
    ATTENTION: Cet endpoint utilise un chemin hardcodé.
    À modifier pour utiliser settings.DATA_DIR ou similaire.
    """

    def get(self, request, format=None):
        # CORRIGÉ: Utiliser settings au lieu d'un chemin hardcodé
        data_dir = getattr(settings, 'DATA_DIR', os.path.join(settings.BASE_DIR, 'data'))
        file_path = os.path.join(data_dir, 'businesscontinuity.json')

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Response(data)

        except FileNotFoundError:
            error_data = {'Error': f'JSON file not found at {file_path}'}
            return Response(error_data, status=status.HTTP_404_NOT_FOUND)

        except json.JSONDecodeError:
            error_data = {'Error': 'JSON file not correctly encoded.'}
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
