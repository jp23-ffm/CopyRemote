"""
views.py - Chimera API views

Refactored SrvPropView with decomposed pipeline:
  post() -> _parse_request -> _resolve_index -> _process_annotations
         -> _map_and_validate_filters -> _build_queryset -> _build_response
"""

import csv
import datetime
import json
import logging
import os
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

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
from rest_framework.renderers import JSONRenderer, BrowsableAPIRenderer
from rest_framework.views import APIView

from businesscontinuity.models import Server as BCServer, ServerUnique
from inventory.models import Server as InventoryServer, ServerAnnotation
from monitor.views import get_cluster_status

from .custom_filters import DynamicFilterBackend
from .serializers import (
    SrvPropSerializer, EnrichSerializer, BusinessContinuitySerializer, InventoryServerSerializer
)
from .streaming_renderers import CSVRenderer, Echo, StreamingOneLinePerInstanceJSONRenderer

from api.management.commands import status_checks as checks


# =============================================================================
# CONFIGURATION
# =============================================================================

field_app_mapping = {
    'inventory': InventoryServer,
    'businesscontinuity': BCServer
}

# API log path - uses a portable directory
API_LOG_DIR = getattr(settings, 'API_LOG_DIR', None) or tempfile.gettempdir()
API_LOG_FILE = os.path.join(API_LOG_DIR, 'chimera_api.log')

# Standard Python logger (fallback)
logger = logging.getLogger('chimera.api')


def api_log(text):
    """Log API calls - portable version (works on Windows and Linux)"""
    unix_ts = time.time()
    currenttime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(unix_ts))
    print(text)

    try:
        with open(API_LOG_FILE, mode="a", encoding="utf-8") as file:
            file.write(f"{currenttime} {text}\n")
    except (IOError, OSError) as e:
        logger.warning(f"Cannot write to {API_LOG_FILE}: {e}")
        logger.info(text)


# =============================================================================
# EXCEPTIONS
# =============================================================================

class QueryValidationError(Exception):
    def __init__(self, detail: dict, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(str(detail))


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class QueryContext:
    # From the request
    index_name: str
    filters: Dict[str, List[str]]
    fields: Optional[List[str]]
    excludefields: Optional[List[str]]
    output_format: str                                      # "json" or "csv"

    # Resolved by _resolve_index
    index_cls: Optional[Type] = None
    output_serializer: Optional[Type] = None

    # Annotations
    include_annotations: bool = False
    annotation_server_ids: Optional[List[str]] = None
    annotation_exclude_server_ids: Optional[List[str]] = None

    # Unify (deduplication with concatenation)
    unify_fields: Optional[List[str]] = None
    unified_data: Optional[List[dict]] = None

    # Groupedby (sub-groups in JSON response)
    groupedby_field: Optional[str] = None
    grouped_data: Optional[List[dict]] = None

    # Enrich (cross-index enrichment by SERVER_ID)
    enrich_config: Optional[dict] = None
    enriched_data: Optional[List[dict]] = None

    # Built by _build_queryset
    mapped_filters: Dict[str, List[str]] = field(default_factory=dict)
    distinct_fields: List[str] = field(default_factory=list)
    queryset: Optional[Any] = None
    count: int = 0

    # Constants
    default_exclude: List[str] = field(default_factory=lambda: ['id'])


# =============================================================================
# HELPER CLASSES
# =============================================================================

class ServerPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 200


# =============================================================================
# MODEL FIELDS VIEWS
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
# SRVPROP VIEW - REFACTORED
# =============================================================================

class SrvPropView(APIView):
    """
    Endpoint principal de requete de proprietes serveur.

    Support du champ ANNOTATION pour l'index inventory.

    Usage ANNOTATION:
    - Dans filters: {"ANNOTATION": ["texte a chercher"]} -> filtre les serveurs ayant cette annotation
    - Dans fields: ["SERVER_ID", "ANNOTATION", ...] -> retourne les annotations avec les resultats
    - IMPORTANT: Si ANNOTATION est dans fields, SERVER_ID doit aussi y etre

    Negation avec prefixe !:
    - Utiliser ! devant une valeur pour l'exclure
    - Compatible avec les wildcards: !*TEST*

    Exemple:
    {
        "index": "inventory",
        "filters": {"ENVIRONMENT": ["PROD"]},
        "fields": ["SERVER_ID", "OSSHORTNAME", "ANNOTATION"]
    }
    """

    renderer_classes = [BrowsableAPIRenderer, JSONRenderer, CSVRenderer]
    pagination_class = ServerPagination

    STREAMING_THRESHOLD = 200
    STREAMING_CHUNK_SIZE = 10000

    MAX_RESULTS = 2000000
    MAX_FILTER_FIELDS = 15
    MAX_FILTER_VALUES_PER_FIELD = 15000

    SPECIAL_FIELDS = {'ANNOTATION'}

    INDEX_REGISTRY = {
        "inventory":          (InventoryServer, InventoryServerSerializer),
        "businesscontinuity": (BCServer, BusinessContinuitySerializer),
    }

    ALIAS_MAP = {
        'priority_asset': 'server_unique__priority_asset',
        'in_live_play': 'server_unique__in_live_play',
        'action_during_lp': 'server_unique__action_during_lp',
        'original_action_during_lp': 'server_unique__original_action_during_lp',
        'cluster': 'server_unique__cluster',
        'cluster_type': 'server_unique__cluster_type',
    }

    # =========================================================================
    # PIPELINE: post() orchestrator
    # =========================================================================

    def post(self, request):
        try:
            api_log("------------------------")
            api_log(f"User: {request.user}")
            api_log(f"Payload: {request.data}")

            ctx = self._parse_request(request)
            self._resolve_index(ctx)
            self._process_annotations(ctx)
            self._map_and_validate_filters(ctx)
            self._build_queryset(ctx)
            self._enrich_results(ctx)
            self._unify_results(ctx)
            self._group_results(ctx)
            return self._build_response(request, ctx)

        except QueryValidationError as e:
            api_log(f"Error: {e.detail}")
            return Response(e.detail, status=e.status_code)

        except Exception as e:
            api_log(f"Error: {e}")
            api_log(f"Traceback: {traceback.format_exc()}")
            return Response({"Unexpected Error": str(e)}, status=500)

        finally:
            api_log("End")

    # =========================================================================
    # STEP 1: Parse and validate the request
    # =========================================================================

    def _parse_request(self, request):
        serializer = SrvPropSerializer(data=request.data)
        if not serializer.is_valid():
            raise QueryValidationError(serializer.errors)

        index_name = serializer.validated_data["index"]
        filters = dict(serializer.validated_data.get("filters", {}))
        fields = serializer.validated_data.get("fields", None)
        excludefields = serializer.validated_data.get("excludefields", None)
        output_format = serializer.validated_data.get("format", "json")
        unify_fields = serializer.validated_data.get("unify", None)
        groupedby_field = serializer.validated_data.get("groupedby", None)
        enrich_config = serializer.validated_data.get("enrich", None)

        if enrich_config and enrich_config["index"] == index_name:
            raise QueryValidationError({
                "error": "enrich.index must be different from the main index"
            })

        if len(filters) == 0:
            raise QueryValidationError({"error": "The field 'filters' can't be empty"})

        if len(filters) > self.MAX_FILTER_FIELDS:
            raise QueryValidationError({
                "error": f"Too many fields filters: {len(filters)} (max: {self.MAX_FILTER_FIELDS})"
            })

        for field_name, values in filters.items():
            if len(values) > self.MAX_FILTER_VALUES_PER_FIELD:
                raise QueryValidationError({
                    "error": f"Too many values for '{field_name}': {len(values)} (max: {self.MAX_FILTER_VALUES_PER_FIELD})"
                })

        return QueryContext(
            index_name=index_name,
            filters=filters,
            fields=fields,
            excludefields=excludefields,
            output_format=output_format,
            unify_fields=unify_fields,
            groupedby_field=groupedby_field,
            enrich_config=enrich_config,
        )

    # =========================================================================
    # STEP 2: Resolve the index model and serializer
    # =========================================================================

    def _resolve_index(self, ctx):
        entry = self.INDEX_REGISTRY.get(ctx.index_name)
        if entry is None:
            raise QueryValidationError(
                {"error": f"Unsupported index: {ctx.index_name}"}
            )
        ctx.index_cls, ctx.output_serializer = entry

    # =========================================================================
    # STEP 3: Process ANNOTATION filters and fields
    # =========================================================================

    @staticmethod
    def _build_annotation_query(values):
        """Build a Q object for include or exclude on ServerAnnotation.notes."""
        has_wildcards = any('*' in v for v in values)
        query = Q()
        if has_wildcards:
            for value in values:
                pattern = value.replace('*', '.*')
                query |= Q(notes__iregex=f"^{pattern}$")
        else:
            for value in values:
                query |= Q(notes__icontains=value)
        return query

    def _process_annotations(self, ctx):
        annotation_in_filters = 'ANNOTATION' in ctx.filters
        annotation_in_fields = ctx.fields is not None and 'ANNOTATION' in ctx.fields
        ctx.include_annotations = annotation_in_fields

        # ANNOTATION only available with inventory
        if (annotation_in_filters or annotation_in_fields) and ctx.index_name != 'inventory':
            raise QueryValidationError({
                "error": "ANNOTATION is only available for index 'inventory'"
            })

        # If ANNOTATION in fields, SERVER_ID must also be present
        if annotation_in_fields:
            if ctx.fields and 'SERVER_ID' not in ctx.fields:
                raise QueryValidationError({
                    "error": "ANNOTATION requires SERVER_ID in fields. Without SERVER_ID, annotations cannot be mapped to results."
                })
            # Remove ANNOTATION from fields for the queryset (added after serialization)
            ctx.fields = [f for f in ctx.fields if f != 'ANNOTATION']

        if not annotation_in_filters:
            return

        annotation_values = ctx.filters.pop('ANNOTATION')
        api_log(f"Processing ANNOTATION filter with values: {annotation_values}")

        # Separate include and exclude values
        include_values = [v for v in annotation_values if not v.startswith('!')]
        exclude_values = [v[1:] for v in annotation_values if v.startswith('!')]

        # Process inclusion values
        if include_values:
            annotation_query = self._build_annotation_query(include_values)
            ctx.annotation_server_ids = list(
                ServerAnnotation.objects.filter(annotation_query)
                .values_list('SERVER_ID', flat=True)
            )
            api_log(f"ANNOTATION include filter matched {len(ctx.annotation_server_ids)} servers")

            if not ctx.annotation_server_ids:
                # Empty list -> queryset will naturally be empty
                ctx.annotation_server_ids = []

        # Process exclusion values (negation with !)
        if exclude_values:
            exclude_query = self._build_annotation_query(exclude_values)
            ctx.annotation_exclude_server_ids = list(
                ServerAnnotation.objects.filter(exclude_query)
                .values_list('SERVER_ID', flat=True)
            )
            api_log(f"ANNOTATION exclude filter matched {len(ctx.annotation_exclude_server_ids)} servers to exclude")

    # =========================================================================
    # STEP 4: Map aliases and validate filters
    # =========================================================================

    def _map_and_validate_filters(self, ctx):
        mapped_filters = {}
        for key, value in ctx.filters.items():
            if key in self.SPECIAL_FIELDS:
                continue
            mapped_key = self.ALIAS_MAP.get(key, key)
            mapped_filters[mapped_key] = value

        invalid_filters = self._validate_filters(mapped_filters, ctx.index_cls, ctx.index_name)
        if invalid_filters:
            raise QueryValidationError({
                "error": f"Invalid fields for {ctx.index_name} index: {', '.join(invalid_filters)}"
            })

        ctx.mapped_filters = mapped_filters

    def _validate_filters(self, mapped_filters, index_cls, index_name):
        """Validate filter fields against the index model."""
        invalid_filters = []

        for fil in mapped_filters:
            field_name = fil.split('__')[0]

            if hasattr(index_cls, field_name):
                continue

            # For businesscontinuity, also check server_unique
            if index_name == 'businesscontinuity' and '__' in fil:
                related_field = fil.split('__')[1]
                if hasattr(ServerUnique, related_field):
                    continue

            invalid_filters.append(fil)

        return invalid_filters

    # =========================================================================
    # STEP 5: Build the queryset
    # =========================================================================

    @staticmethod
    def _build_q_objects(mapped_filters):
        """Build Q objects for include/exclude from mapped filters.

        Returns (query_filter, exclude_filter, all_annotations).
        """
        query_filter = Q()
        exclude_filter = Q()
        lower_annotations = {}
        exclude_lower_annotations = {}

        for field_name, values in mapped_filters.items():
            if not values:
                continue

            # Separate normal values from negated values (prefixed with !)
            include_values = [v for v in values if not v.startswith('!')]
            exclude_values = [v[1:] for v in values if v.startswith('!')]

            # Process inclusion values
            if include_values:
                has_wildcards = any('*' in v for v in include_values)

                if has_wildcards:
                    or_conditions = Q()
                    for value in include_values:
                        value_pattern = value.replace('*', '.*')
                        or_conditions |= Q(**{f"{field_name}__iregex": f"^{value_pattern}$"})
                    query_filter &= or_conditions
                else:
                    lowered_values = [v.lower() for v in include_values]
                    lower_field = f"{field_name}_lower"
                    lower_annotations[lower_field] = Lower(field_name)
                    query_filter &= Q(**{f"{lower_field}__in": lowered_values})

            # Process exclusion values (negation with !)
            if exclude_values:
                has_wildcards = any('*' in v for v in exclude_values)

                if has_wildcards:
                    for value in exclude_values:
                        value_pattern = value.replace('*', '.*')
                        exclude_filter |= Q(**{f"{field_name}__iregex": f"^{value_pattern}$"})
                else:
                    lowered_values = [v.lower() for v in exclude_values]
                    lower_field = f"{field_name}_lower"
                    exclude_lower_annotations[lower_field] = Lower(field_name)
                    exclude_filter |= Q(**{f"{lower_field}__in": lowered_values})

        all_annotations = {**lower_annotations, **exclude_lower_annotations}
        return query_filter, exclude_filter, all_annotations

    def _build_queryset(self, ctx):
        # Determine distinct fields
        if ctx.fields is None:
            excludefields = ctx.excludefields or []
            ctx.distinct_fields = [
                f.name for f in ctx.index_cls._meta.fields
                if f.name not in ctx.default_exclude and f.name not in excludefields
            ]
        else:
            ctx.distinct_fields = [f for f in ctx.fields if f not in self.SPECIAL_FIELDS]

        queryset = ctx.index_cls.objects.all()

        # Apply ANNOTATION pre-filters
        if ctx.annotation_server_ids is not None:
            queryset = queryset.filter(SERVER_ID__in=ctx.annotation_server_ids)
        if ctx.annotation_exclude_server_ids is not None:
            queryset = queryset.exclude(SERVER_ID__in=ctx.annotation_exclude_server_ids)

        # Build Q objects from mapped filters
        query_filter, exclude_filter, all_annotations = self._build_q_objects(ctx.mapped_filters)

        # Apply annotations and filters
        if all_annotations:
            queryset = queryset.annotate(**all_annotations)
        if query_filter:
            queryset = queryset.filter(query_filter)
        if exclude_filter:
            queryset = queryset.exclude(exclude_filter)

        #queryset = queryset.distinct(*ctx.distinct_fields).order_by(*ctx.distinct_fields)
        queryset = queryset.order_by(*ctx.distinct_fields)

        ctx.queryset = queryset
        ctx.count = queryset.count()

        if ctx.count > self.MAX_RESULTS:
            raise QueryValidationError({
                "error": f"Too many results: {ctx.count} (maximum: {self.MAX_RESULTS})",
                "hint": "Please refine your filters to reduce the number of results",
                "count": ctx.count
            })

    # =========================================================================
    # STEP 5b: Enrich results from another index
    # =========================================================================

    def _enrich_results(self, ctx):
        if not ctx.enrich_config:
            return

        enrich_index_name = ctx.enrich_config["index"]
        enrich_fields = ctx.enrich_config["fields"]

        enrich_entry = self.INDEX_REGISTRY.get(enrich_index_name)
        if enrich_entry is None:
            raise QueryValidationError({
                "error": f"Unsupported enrich index: {enrich_index_name}"
            })
        enrich_cls, enrich_serializer_cls = enrich_entry

        api_log(f"Enriching from {enrich_index_name} with fields {enrich_fields}")

        # Serialize main results in chunks to reduce peak RAM
        main_data = []
        server_ids_set = set()
        chunk = []
        for obj in ctx.queryset.iterator(chunk_size=self.STREAMING_CHUNK_SIZE):
            chunk.append(obj)
            if len(chunk) >= self.STREAMING_CHUNK_SIZE:
                chunk_data = self._serialize_chunk(ctx, chunk)
                for item in chunk_data:
                    sid = item.get('SERVER_ID')
                    if sid:
                        server_ids_set.add(sid)
                main_data.extend(chunk_data)
                chunk = []
        if chunk:
            chunk_data = self._serialize_chunk(ctx, chunk)
            for item in chunk_data:
                sid = item.get('SERVER_ID')
                if sid:
                    server_ids_set.add(sid)
            main_data.extend(chunk_data)
            chunk = []

        server_ids = list(server_ids_set)

        if not server_ids:
            ctx.enriched_data = main_data
            ctx.count = len(main_data)
            return

        # Query enrich index in chunks to build enrich_map
        enrich_query_fields = enrich_fields if 'SERVER_ID' in enrich_fields else ['SERVER_ID'] + enrich_fields
        enrich_qs = enrich_cls.objects.filter(SERVER_ID__in=server_ids)

        enrich_map = {}
        enrich_total = 0
        enrich_chunk = []
        for obj in enrich_qs.iterator(chunk_size=self.STREAMING_CHUNK_SIZE):
            enrich_chunk.append(obj)
            if len(enrich_chunk) >= self.STREAMING_CHUNK_SIZE:
                self._accumulate_enrich_chunk(
                    enrich_chunk, enrich_serializer_cls, enrich_query_fields, enrich_fields, enrich_map
                )
                enrich_total += len(enrich_chunk)
                enrich_chunk = []
        if enrich_chunk:
            self._accumulate_enrich_chunk(
                enrich_chunk, enrich_serializer_cls, enrich_query_fields, enrich_fields, enrich_map
            )
            enrich_total += len(enrich_chunk)

        api_log(f"Enrich query returned {enrich_total} rows")

        # Merge enriched fields into main data
        for item in main_data:
            sid = item.get('SERVER_ID', '')
            if sid in enrich_map:
                for fname in enrich_fields:
                    values = sorted(enrich_map[sid][fname])
                    item[fname] = ' | '.join(values) if values else ''
            else:
                for fname in enrich_fields:
                    item[fname] = ''

        ctx.enriched_data = main_data
        ctx.count = len(main_data)
        api_log(f"Enriched {len(main_data)} rows with {len(enrich_map)} matches from {enrich_index_name}")

    def _accumulate_enrich_chunk(self, chunk, serializer_cls, query_fields, enrich_fields, enrich_map):
        """Serialize an enrich chunk and accumulate unique values into enrich_map."""
        ser = serializer_cls(chunk, many=True, fields=query_fields, default_exclude=['id'])
        for item in ser.data:
            sid = item.get('SERVER_ID', '')
            if not sid:
                continue
            if sid not in enrich_map:
                enrich_map[sid] = {f: set() for f in enrich_fields}
            for fname in enrich_fields:
                val = item.get(fname)
                if val is not None and val != '':
                    enrich_map[sid][fname].add(str(val))

    # =========================================================================
    # STEP 5c: Unify results (deduplicate with concatenation)
    # =========================================================================

    def _accumulate_into_groups(self, data, unify_fields, groups, group_order):
        """Accumulate serialized rows into the groups dict (chunked-friendly)."""
        for item in data:
            key = tuple(item.get(f, '') or '' for f in unify_fields)
            if key not in groups:
                groups[key] = {fname: set() for fname in item}
                group_order.append(key)
            for fname, val in item.items():
                if val is not None and val != '':
                    groups[key][fname].add(str(val))

    def _build_unified_from_groups(self, groups, group_order):
        """Build the final unified list from accumulated groups."""
        unified = []
        for key in group_order:
            row = {}
            for fname, values in groups[key].items():
                sorted_vals = sorted(values)
                row[fname] = ' | '.join(sorted_vals) if sorted_vals else ''
            unified.append(row)
        return unified

    def _unify_results(self, ctx):
        if not ctx.unify_fields:
            return

        api_log(f"Unifying results by {ctx.unify_fields}")

        groups = {}        # key -> {field: set()}
        group_order = []   # preserve insertion order
        total_rows = 0

        if ctx.enriched_data is not None:
            # Enriched data is already in memory, accumulate directly
            self._accumulate_into_groups(ctx.enriched_data, ctx.unify_fields, groups, group_order)
            total_rows = len(ctx.enriched_data)
        else:
            # Chunked processing: iterate queryset in chunks to avoid RAM spike
            chunk = []
            for obj in ctx.queryset.iterator(chunk_size=self.STREAMING_CHUNK_SIZE):
                chunk.append(obj)

                if len(chunk) >= self.STREAMING_CHUNK_SIZE:
                    chunk_data = self._serialize_chunk(ctx, chunk)
                    self._accumulate_into_groups(chunk_data, ctx.unify_fields, groups, group_order)
                    total_rows += len(chunk_data)
                    chunk = []

            # Last chunk
            if chunk:
                chunk_data = self._serialize_chunk(ctx, chunk)
                self._accumulate_into_groups(chunk_data, ctx.unify_fields, groups, group_order)
                total_rows += len(chunk_data)

        # Build unified result from the compact groups dict
        ctx.unified_data = self._build_unified_from_groups(groups, group_order)
        ctx.count = len(ctx.unified_data)
        api_log(f"Unified: {total_rows} rows -> {ctx.count} groups")

    def _serialize_chunk(self, ctx, chunk):
        """Serialize a chunk of objects and optionally add annotations."""
        serializer = ctx.output_serializer(
            chunk, many=True,
            fields=ctx.fields,
            excludefields=ctx.excludefields,
            default_exclude=ctx.default_exclude
        )
        data = list(serializer.data)

        if ctx.include_annotations:
            data = self._add_annotations_to_data(data)

        return data

    # =========================================================================
    # STEP 5d: Group results by field
    # =========================================================================

    def _group_results(self, ctx):
        if not ctx.groupedby_field:
            return

        api_log(f"Grouping results by {ctx.groupedby_field}")

        # Get the data to group (from previous pipeline steps or queryset)
        if ctx.unified_data is not None:
            raw_data = ctx.unified_data
        elif ctx.enriched_data is not None:
            raw_data = ctx.enriched_data
        else:
            # Chunked serialization from queryset
            raw_data = []
            chunk = []
            for obj in ctx.queryset.iterator(chunk_size=self.STREAMING_CHUNK_SIZE):
                chunk.append(obj)
                if len(chunk) >= self.STREAMING_CHUNK_SIZE:
                    raw_data.extend(self._serialize_chunk(ctx, chunk))
                    chunk = []
            if chunk:
                raw_data.extend(self._serialize_chunk(ctx, chunk))

        # Group by field
        groups = {}
        group_order = []
        for item in raw_data:
            key = item.get(ctx.groupedby_field, '') or ''
            if key not in groups:
                groups[key] = []
                group_order.append(key)
            groups[key].append(item)

        # Build grouped result
        grouped = []
        for key in group_order:
            grouped.append({
                "group": key,
                "count": len(groups[key]),
                "items": groups[key]
            })

        ctx.grouped_data = grouped
        ctx.count = len(raw_data)
        api_log(f"Grouped: {len(raw_data)} rows -> {len(grouped)} groups")

    # =========================================================================
    # STEP 6: Build and return the response
    # =========================================================================

    def _build_response(self, request, ctx):
        # In-memory data (grouped, unified, enriched): stream if above threshold
        if ctx.grouped_data is not None:
            in_memory_data, label = ctx.grouped_data, "grouped"
        elif ctx.unified_data is not None:
            in_memory_data, label = ctx.unified_data, "unified"
        elif ctx.enriched_data is not None:
            in_memory_data, label = ctx.enriched_data, "enriched"
        else:
            in_memory_data = None

        if in_memory_data is not None:

            if ctx.count > self.STREAMING_THRESHOLD:
                api_log(f"Nb items: {ctx.count} - Using the Streaming Mode ({label})")
                if ctx.output_format == "csv" and not ctx.grouped_data:
                    return self._stream_in_memory_csv(ctx, in_memory_data)
                else:
                    return self._stream_in_memory_json(ctx, in_memory_data)
            else:
                api_log(f"Nb items: {ctx.count} - Using the Normal Mode ({label})")
                if ctx.output_format == "csv" and not ctx.grouped_data:
                    return self._generate_csv_response(ctx)
                else:
                    return self._generate_json_response(ctx)

        if request.GET.get('page'):
            api_log("Using the Paging Mode")
            return self._handle_paginated_response(request, ctx)
        elif ctx.count > self.STREAMING_THRESHOLD:
            api_log(f"Nb items: {ctx.count} - Using the Streaming Mode")
            if ctx.output_format == "csv":
                return self._stream_csv_response(ctx)
            else:
                return self._stream_json_response(ctx)
        else:
            api_log(f"Nb items: {ctx.count} - Using the Normal Mode")
            if ctx.output_format == "csv":
                return self._generate_csv_response(ctx)
            else:
                return self._generate_json_response(ctx)

    # --- Normal responses ---

    def _generate_json_response(self, ctx):
        """Generate a normal JSON response (small volume)."""
        if ctx.grouped_data is not None:
            return Response({"count": ctx.count, "results": ctx.grouped_data}, status=200)

        if ctx.unified_data is not None:
            return Response({"count": ctx.count, "results": ctx.unified_data}, status=200)

        if ctx.enriched_data is not None:
            return Response({"count": ctx.count, "results": ctx.enriched_data}, status=200)

        output_serializer_instance = ctx.output_serializer(
            ctx.queryset,
            many=True,
            fields=ctx.fields,
            excludefields=ctx.excludefields,
            default_exclude=ctx.default_exclude
        )

        results = output_serializer_instance.data

        if ctx.include_annotations:
            results = self._add_annotations_to_data(list(results))

        response_data = {
            "count": ctx.count,
            "results": results
        }

        return Response(response_data, status=status.HTTP_200_OK)

    def _generate_csv_response(self, ctx):
        """Generate a non-streamed CSV response (small volume)."""
        # Early return for in-memory data (unified or enriched)
        in_memory_data = ctx.unified_data if ctx.unified_data is not None else ctx.enriched_data
        if in_memory_data is not None:
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="data.csv"'
            writer = csv.writer(response)
            if in_memory_data:
                writer.writerow(list(in_memory_data[0].keys()))
            for item in in_memory_data:
                writer.writerow(item.values())
            return response

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="data.csv"'
        writer = csv.writer(response)

        # Header
        first = ctx.queryset.first()
        if first:
            serializer = ctx.output_serializer(
                first,
                fields=ctx.fields,
                excludefields=ctx.excludefields,
                default_exclude=ctx.default_exclude
            )
            header = list(serializer.data.keys())
            if ctx.include_annotations:
                header.append('ANNOTATION')
            writer.writerow(header)

        # Data
        serializer_instance = ctx.output_serializer(
            ctx.queryset,
            many=True,
            fields=ctx.fields,
            excludefields=ctx.excludefields,
            default_exclude=ctx.default_exclude
        )

        data = list(serializer_instance.data)

        if ctx.include_annotations:
            data = self._add_annotations_to_data(data)

        for item in data:
            writer.writerow(item.values())

        return response

    # --- Paginated response ---

    def _handle_paginated_response(self, request, ctx):
        """Handle paginated response (JSON or CSV)."""
        paginator = ServerPagination()
        page = paginator.paginate_queryset(ctx.queryset, request)

        if page is not None:
            serializer_instance = ctx.output_serializer(
                page, many=True,
                fields=ctx.fields,
                excludefields=ctx.excludefields,
                default_exclude=ctx.default_exclude
            )

            if ctx.output_format == "csv":
                response = HttpResponse(content_type='text/csv')
                response['Content-Disposition'] = 'attachment; filename="data.csv"'
                writer = csv.writer(response)

                data = list(serializer_instance.data)
                if ctx.include_annotations:
                    data = self._add_annotations_to_data(data)

                if data:
                    header = list(data[0].keys())
                    writer.writerow(header)

                for item in data:
                    writer.writerow(item.values())

                return response
            else:
                results = serializer_instance.data
                if ctx.include_annotations:
                    results = self._add_annotations_to_data(list(results))

                return paginator.get_paginated_response(results)

        return Response({"count": 0, "results": []}, status=status.HTTP_200_OK)

    # --- Streaming in-memory data ---

    def _stream_in_memory_json(self, ctx, data):
        """Stream an in-memory list of dicts as JSON response."""
        def generate():
            yield b'{"count": '
            yield str(ctx.count).encode('utf-8')
            yield b', "results": ['

            first = True
            for item in data:
                if not first:
                    yield b','
                first = False
                yield json.dumps(item).encode('utf-8')

            yield b']}'

        response = StreamingHttpResponse(
            generate(),
            content_type='application/json'
        )
        response['X-Total-Count'] = str(ctx.count)
        response['Cache-Control'] = 'no-cache'
        return response

    def _stream_in_memory_csv(self, ctx, data):
        """Stream an in-memory list of dicts as CSV response."""
        def generate():
            pseudo_buffer = Echo()
            writer = csv.writer(pseudo_buffer)

            if data:
                yield writer.writerow(list(data[0].keys()))

            for item in data:
                yield writer.writerow(item.values())

        response = StreamingHttpResponse(generate(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="data.csv"'
        return response

    # --- Streaming queryset responses ---

    def _stream_csv_response(self, ctx):
        """Stream CSV response for large volumes."""
        def generate():
            pseudo_buffer = Echo()
            writer = csv.writer(pseudo_buffer)

            # Header
            first_obj = ctx.queryset.first()
            if first_obj:
                header_serializer = ctx.output_serializer(
                    first_obj,
                    fields=ctx.fields,
                    excludefields=ctx.excludefields,
                    default_exclude=ctx.default_exclude
                )
                header = list(header_serializer.data.keys())
                if ctx.include_annotations:
                    header.append('ANNOTATION')
                yield writer.writerow(header)

            # Use iterator() to save memory
            chunk = []
            for obj in ctx.queryset.iterator(chunk_size=self.STREAMING_CHUNK_SIZE):
                chunk.append(obj)

                if len(chunk) >= self.STREAMING_CHUNK_SIZE:
                    yield from self._process_csv_chunk(ctx, chunk, writer)
                    chunk = []

            # Last chunk
            if chunk:
                yield from self._process_csv_chunk(ctx, chunk, writer)

        response = StreamingHttpResponse(generate(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="data.csv"'
        return response

    def _process_csv_chunk(self, ctx, chunk, writer):
        """Process a chunk for CSV streaming."""
        serializer = ctx.output_serializer(
            chunk,
            many=True,
            fields=ctx.fields,
            excludefields=ctx.excludefields,
            default_exclude=ctx.default_exclude
        )

        data = list(serializer.data)

        if ctx.include_annotations:
            data = self._add_annotations_to_data(data)

        for item in data:
            yield writer.writerow(item.values())

    def _stream_json_response(self, ctx):
        """Stream JSON response for large volumes."""
        def generate():
            yield b'{"count": '
            yield str(ctx.count).encode('utf-8')
            yield b', "results": ['

            first = True
            chunk = []

            for obj in ctx.queryset.iterator(chunk_size=self.STREAMING_CHUNK_SIZE):
                chunk.append(obj)

                if len(chunk) >= self.STREAMING_CHUNK_SIZE:
                    for json_bytes in self._process_json_chunk(ctx, chunk, first):
                        yield json_bytes
                        first = False
                    chunk = []

            # Last chunk
            if chunk:
                for json_bytes in self._process_json_chunk(ctx, chunk, first):
                    yield json_bytes
                    first = False

            yield b']}'

        response = StreamingHttpResponse(
            generate(),
            content_type='application/json'
        )
        response['X-Total-Count'] = str(ctx.count)
        response['Cache-Control'] = 'no-cache'
        return response

    def _process_json_chunk(self, ctx, chunk, is_first):
        """Process a chunk for JSON streaming."""
        serializer = ctx.output_serializer(
            chunk,
            many=True,
            fields=ctx.fields,
            excludefields=ctx.excludefields,
            default_exclude=ctx.default_exclude
        )

        data = list(serializer.data)

        if ctx.include_annotations:
            data = self._add_annotations_to_data(data)

        first = is_first
        for obj_data in data:
            if not first:
                yield b','
            first = False
            yield json.dumps(obj_data).encode('utf-8')

    # --- Annotation helper (unchanged) ---

    def _add_annotations_to_data(self, data):
        """Add annotations to serialized data. Expects list of dicts with SERVER_ID."""
        if not data:
            return data

        server_ids = [item.get('SERVER_ID') for item in data if item.get('SERVER_ID')]

        if not server_ids:
            return data

        annotations = ServerAnnotation.objects.filter(SERVER_ID__in=server_ids)
        annotation_map = {ann.SERVER_ID: ann.notes or '' for ann in annotations}

        for item in data:
            server_id = item.get('SERVER_ID')
            item['ANNOTATION'] = annotation_map.get(server_id, '')

        return data


# =============================================================================
# HEALTH CHECK VIEW
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
            logger.error(f"Health check failed: {e}")
            return Response({'status': 'unhealthy', 'error': str(e)}, status=503)


# =============================================================================
# MONITOR STATUS VIEW
# =============================================================================

class MonitorStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        simple = request.GET.get('simple') == 'true'
        response, http_status = get_cluster_status(simple)
        return Response(response, status=http_status)


# =============================================================================
# LEGACY: GetJsonEndpoint
# =============================================================================

class GetJsonEndpoint(APIView):
    def get(self, request, format=None):
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
