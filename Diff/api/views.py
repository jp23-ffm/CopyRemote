import csv
import datetime
import json
import os
import time
from pathlib import Path
import sys

from django.apps import apps
from django.conf import settings
from django.http import StreamingHttpResponse, HttpResponse
from django.core.exceptions import FieldError, ValidationError
from django.db import connection
from django.db.models import Q
from django.db.models.functions import Lower, Upper
#from django.db.models.functions import Upper
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
from .serializers import GenericQuerySerializer, SrvPropSerializer, BusinessContinuitySerializer, InventoryServerSerializer

from .streaming_renderers import CSVRenderer, Echo,  StreamingOneLinePerInstanceJSONRenderer

from api.management.commands import status_checks as checks


field_app_mapping = {
    'inventory': InventoryServer,
    'businesscontinuity': BCServer
}

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

        #if not field_name in allowed_fields:
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
        
        
class GetJsonEndpoint(APIView):
    
    def get(self, request, format=None):
        file_path = '/home/PREVOSTJ/data/businesscontinuity.json'

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Response(data)

        except FileNotFoundError:
            error_data = {'Error': 'JSON file not found.'}
            return Response(error_data, status=status.HTTP_404_NOT_FOUND)
            
        except json.JSONDecodeError:
            error_data = {'Error': 'JSON file not correctly encoded.'}
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def validate_json_data(data, serializer):

    # Validate the JSON data against the serializer fields.

    allowed_keys = set(serializer().fields.keys())
    for key in data:
        if key not in allowed_keys:
            raise ValueError(f"Invalid key '{key}' in JSON data. Allowed keys are: {', '.join(allowed_keys)}")
 

class ServerPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 200


def api_log(text):
    unix_ts = time.time()
    currenttime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(unix_ts))
    #with open("/tmp/api.log", mode="a", encoding="utf-8") as file:
    #    file.write(f"{currenttime} {text}\n")


class SrvPropView(APIView):
    """
    Example:
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

            # Filters validation

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

            # Index selection

            if index_name == "businesscontinuity":
                index_cls = BCServer
                output_serializer = BusinessContinuitySerializer
            elif index_name == "inventory":
                index_cls = InventoryServer
                output_serializer = InventoryServerSerializer
            else:
                api_log(f"Error: Unsupported index: {index_name}")
                return Response({"error": f"Unsupported index: {index_name}"}, status=status.HTTP_400_BAD_REQUEST)

            # Annotations management (inventory only)

            annotation_in_filters = 'ANNOTATION' in filters
            annotation_in_fields = fields is not None and 'ANNOTATION' in fields
            include_annotations = annotation_in_fields

            # Check that ANNOTATION is only used with inventory
            if (annotation_in_filters or annotation_in_fields) and index_name != 'inventory':
                api_log(f"Error: ANNOTATION is only available for index 'inventory'")
                return Response({
                    "error": "ANNOTATION is only available for index 'inventory'"
                }, status=status.HTTP_400_BAD_REQUEST)

            # If ANNOTATION is present in fields, SERVER_ID must be too
            if annotation_in_fields:
                if fields and 'SERVER_ID' not in fields:
                    api_log(f"Error: ANNOTATION requires SERVER_ID in fields")
                    return Response({
                        "error": "ANNOTATION requires SERVER_ID in fields. Without SERVER_ID, annotations cannot be mapped to results."
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Remove ANNOTATION from fields for the queryset (will be added after the serialization)
                fields = [f for f in fields if f != 'ANNOTATION']

            # Alias mapping (for businesscontinuity)

            alias_map = {
                'priority_asset': 'server_unique__priority_asset',
                'in_live_play': 'server_unique__in_live_play',
                'action_during_lp': 'server_unique__action_during_lp',
                'original_action_during_lp': 'server_unique__original_action_during_lp',
                'cluster': 'server_unique__cluster',
                'cluster_type': 'server_unique__cluster_type'
            }

            # Pre-filter ANNOTATION (if ANNOTATION is in filters)

            annotation_server_ids = None

            if annotation_in_filters:
                annotation_values = filters.pop('ANNOTATION')  # Remove from dict filters
                api_log(f"Processing ANNOTATION filter with values: {annotation_values}")

                # Build the query on ServerAnnotation.notes
                has_wildcards = any('*' in v for v in annotation_values)

                if has_wildcards:
                    annotation_query = Q()
                    for value in annotation_values:
                        pattern = value.replace('*', '.*')
                        annotation_query |= Q(notes__iregex=f"^{pattern}$")
                else:
                    # Case-insensitive
                    annotation_query = Q()
                    for value in annotation_values:
                        annotation_query |= Q(notes__icontains=value)

                # Get thematching SERVER_ID
                annotation_server_ids = list(
                    ServerAnnotation.objects.filter(annotation_query)
                    .values_list('SERVER_ID', flat=True)
                )

                api_log(f"ANNOTATION filter matched {len(annotation_server_ids)} servers")

                if not annotation_server_ids:
                    # No matching annotation: empty result
                    return Response({"count": 0, "results": []}, status=status.HTTP_200_OK)

            # Mapping and filters validation

            mapped_filters = {}
            for key, value in filters.items():
                # Ignorer les champs spéciaux déjà traités
                if key in self.SPECIAL_FIELDS:
                    continue
                mapped_key = alias_map.get(key, key)
                mapped_filters[mapped_key] = value

            invalid_filters = self._validate_filters(mapped_filters, index_cls, index_name)

            if invalid_filters:
                api_log(f"Error: Invalid fields for {index_name} index: {', '.join(invalid_filters)}")
                return Response({
                    "error": f"Invalid fields for {index_name} index: {', '.join(invalid_filters)}"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Queryset

            if fields is None:
                excludefields = excludefields or []
                distinct_fields = [
                    field.name for field in index_cls._meta.fields
                    if field.name not in default_exclude and field.name not in excludefields
                ]
            else:
                # Remove the special fields from distinct_fields
                distinct_fields = [f for f in fields if f not in self.SPECIAL_FIELDS]

            queryset = index_cls.objects.all()

            # Add the pre-filter ANNOTATION if present
            if annotation_server_ids is not None:
                queryset = queryset.filter(SERVER_ID__in=annotation_server_ids)

            # Global filter
            query_filter = Q()
            lower_annotations = {}

            for field, values in mapped_filters.items():
                if not values:
                    continue

                has_wildcards = any('*' in v for v in values)

                if has_wildcards:
                    or_conditions = Q()
                    for value in values:
                        value_pattern = value.replace('*', '.*')
                        or_conditions |= Q(**{f"{field}__iregex": f"^{value_pattern}$"})
                    query_filter &= or_conditions
                else:
                    lowered_values = [v.lower() for v in values]
                    lower_field_name = f"{field}_lower"
                    lower_annotations[lower_field_name] = Lower(field)
                    query_filter &= Q(**{f"{lower_field_name}__in": lowered_values})

            # Apply the filters
            if lower_annotations:
                #queryset = queryset.annotate(**lower_annotations).filter(query_filter).distinct(*distinct_fields).order_by(*distinct_fields)
                queryset = queryset.annotate(**lower_annotations).filter(query_filter).order_by(*distinct_fields)
            else:
                #queryset = queryset.filter(query_filter).distinct(*distinct_fields).order_by(*distinct_fields)
                queryset = queryset.filter(query_filter).order_by(*distinct_fields) 

            count = queryset.count()

            if count > self.MAX_RESULTS:
                api_log(f"Error: Too many results: {count} (maximum: {self.MAX_RESULTS})")
                return Response({
                    "error": f"Too many results: {count} (maximum: {self.MAX_RESULTS})",
                    "hint": "Please refine your filters to reduce the number of results",
                    "count": count
                }, status=status.HTTP_400_BAD_REQUEST)

            # Response

            if request.GET.get('page'):
                # Mode pagination
                api_log(f"Using the Paging Mode")
                return self._handle_paginated_response(
                    request, queryset, output_serializer, fields, excludefields,
                    default_exclude, output_format, include_annotations
                )

            elif count > self.STREAMING_THRESHOLD:
                # Streaming Mode
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
                # Normal Mode
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
        # Validate the filters based on the index
        invalid_filters = []

        for fil in mapped_filters:
            field_name = fil.split('__')[0]

            # Check that the field is in the model
            if hasattr(index_cls, field_name):
                continue

            # For businesscontinuity, check also server_unique
            if index_name == 'businesscontinuity' and '__' in fil:
                related_field = fil.split('__')[1]
                if hasattr(ServerUnique, related_field):
                    continue

            invalid_filters.append(fil)

        return invalid_filters

    def _add_annotations_to_data(self, data):
        # Add the annotations to the serialized data. dicts list with at least 'SERVER_ID'
        if not data:
            return data

        server_ids = [item.get('SERVER_ID') for item in data if item.get('SERVER_ID')]

        if not server_ids:
            return data

        annotations = ServerAnnotation.objects.filter(SERVER_ID__in=server_ids)
        annotation_map = {ann.SERVER_ID: ann.notes or '' for ann in annotations}

        # Add ANNOTATION to all results
        for item in data:
            server_id = item.get('SERVER_ID')
            item['ANNOTATION'] = annotation_map.get(server_id, '')

        return data

    def _generate_json_response(self, queryset, output_serializer, count, fields, excludefields, default_exclude, include_annotations):
        # Generate a normal JSON response (small volume)
        output_serializer_instance = output_serializer(
            queryset,
            many=True,
            fields=fields,
            excludefields=excludefields,
            default_exclude=default_exclude
        )

        results = output_serializer_instance.data

        if include_annotations:
            results = self._add_annotations_to_data(list(results))

        response_data = {
            "count": count,
            "results": results
        }

        return Response(response_data, status=status.HTTP_200_OK)

    def _handle_paginated_response(self, request, queryset, output_serializer, fields, excludefields, default_exclude, output_format, include_annotations):
        # Paginated response
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

                response = paginator.get_paginated_response(results)
                return response

        return Response({"count": 0, "results": []}, status=status.HTTP_200_OK)

    def _stream_csv_response(self, queryset, serializer_class, fields, excludefields, default_exclude, include_annotations=False):
        # Stream CSV response for big volumes
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

            # Use iterator() to save RAM
            chunk = []
            for obj in queryset.iterator(chunk_size=self.STREAMING_CHUNK_SIZE):
                chunk.append(obj)

                if len(chunk) >= self.STREAMING_CHUNK_SIZE:
                    yield from self._process_csv_chunk(
                        chunk, serializer_class, fields, excludefields,
                        default_exclude, include_annotations, writer
                    )
                    chunk = []

            # Last chunk
            if chunk:
                yield from self._process_csv_chunk(
                    chunk, serializer_class, fields, excludefields,
                    default_exclude, include_annotations, writer
                )

        response = StreamingHttpResponse(generate(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="data.csv"'
        return response

    def _process_csv_chunk(self, chunk, serializer_class, fields, excludefields, default_exclude, include_annotations, writer):
        # Process one chunk for the CSV
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

    def _generate_csv_response(self, queryset, serializer_class, fields, excludefields, default_exclude, include_annotations=False):
        # Generate a non-streamed CSV response (small volume)
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

    def _stream_json_response(self, queryset, serializer_class, count, fields, excludefields, default_exclude, include_annotations=False):
        # Streamed JSON response
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

            # Last chunk
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

    def _process_json_chunk(self, chunk, serializer_class, fields, excludefields, default_exclude, include_annotations, is_first):
        # Process one chunk for the JSON streaming
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


class HealthCheckView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        if not request.META.get('REMOTE_ADDR') == '127.0.0.1':
            return HttpResponse('Forbidden', status=403)

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return Response({'status': 'healthy'}, status=200)
        except:
            return Response({'status': 'unhealthy'}, status=503)


class MonitorStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        simple = request.GET.get('simple') == 'true'
        response, status = get_cluster_status(simple)
        return Response(response, status=status)
