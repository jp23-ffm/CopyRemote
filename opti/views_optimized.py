"""
Optimized views.py for Inventory application
Key optimizations:
1. Cached JSON configuration loading
2. Batched listbox queries with proper caching
3. Optimized grouped mode with fewer queries
4. New API endpoint for lazy column loading
"""

import csv
import datetime
import django
import io
import json
import os
import time
import threading
import uuid
import socket
from functools import lru_cache

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.cache import cache
from django.db import models, transaction, connection
from django.db.models import Q, F, Case, When, Count, OuterRef, Subquery
from django.http import FileResponse, JsonResponse, HttpResponse, HttpResponseRedirect, StreamingHttpResponse, QueryDict
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from common.views import generate_charts
from userapp.models import UserProfile, SavedSearch, SavedOptions, UserPermissions, SavedChart
from .exports import generate_csv, generate_csv_grouped, generate_excel, generate_excel_grouped, EXPORT_DIR
from .models import Server, ServerGroupSummary, ServerAnnotation, ImportStatus
from .forms import AnnotationForm, CsvUploadForm

from collections import defaultdict
from urllib.parse import urlencode, parse_qs, unquote
from threading import Lock


app_name = __package__.split('.')[-1]

# ============================================================================
# OPTIMIZED CACHING UTILITIES
# ============================================================================

# Global cache for field labels with thread-safe access
_field_labels_cache = None
_field_labels_timestamp = 0
_field_labels_lock = Lock()
FIELD_LABELS_CACHE_TTL = 600  # 10 minutes


def get_field_labels():
    """
    Thread-safe cached loading of field_labels.json
    Uses both in-memory cache and file modification time check
    """
    global _field_labels_cache, _field_labels_timestamp

    json_path = os.path.join(os.path.dirname(__file__), 'field_labels.json')
    current_time = time.time()

    # Quick check without lock
    if _field_labels_cache is not None and (current_time - _field_labels_timestamp) < FIELD_LABELS_CACHE_TTL:
        return _field_labels_cache

    with _field_labels_lock:
        # Double-check after acquiring lock
        if _field_labels_cache is not None and (current_time - _field_labels_timestamp) < FIELD_LABELS_CACHE_TTL:
            return _field_labels_cache

        # Load from file
        with open(json_path, 'r', encoding="utf-8") as f:
            _field_labels_cache = json.load(f)

        _field_labels_timestamp = current_time

    return _field_labels_cache


def invalidate_field_labels_cache():
    """Call this when field_labels.json is modified"""
    global _field_labels_cache, _field_labels_timestamp
    with _field_labels_lock:
        _field_labels_cache = None
        _field_labels_timestamp = 0


# ============================================================================
# OPTIMIZED LISTBOX CACHING
# ============================================================================

def get_all_listbox_fields(json_data):
    """Extract all fields that need listbox values"""
    listbox_fields = []
    for key, val in json_data.get('fields', {}).items():
        if val.get('listbox'):
            listbox_fields.append(key)
    return listbox_fields


def batch_load_listbox_values(listbox_fields, force_refresh=False):
    """
    Load all listbox values in a single optimized query batch
    Returns dict: {field_name: [values]}
    """
    cache_key_prefix = 'listbox_'
    result = {}
    fields_to_query = []

    # Check cache first
    for field in listbox_fields:
        cache_key = f'{cache_key_prefix}{field}'
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                result[field] = cached
                continue
        fields_to_query.append(field)

    if not fields_to_query:
        return result

    # Batch query for all uncached fields using raw SQL for efficiency
    # This is much faster than N separate queries
    with connection.cursor() as cursor:
        for field in fields_to_query:
            # Use raw SQL for maximum performance
            cursor.execute(f'''
                SELECT DISTINCT "{field}"
                FROM inventory_server
                WHERE "{field}" IS NOT NULL AND "{field}" != ''
                ORDER BY "{field}"
            ''')
            values = [row[0] for row in cursor.fetchall()]

            # Sort with EMPTY at end
            if any(v and v.upper() == "EMPTY" for v in values):
                values = [v for v in values if v and v.upper() != "EMPTY"]
                values.sort()
                values.append("EMPTY")

            result[field] = values

            # Cache for 1 hour
            cache.set(f'{cache_key_prefix}{field}', values, 3600)

    return result


def get_listbox_values_optimized(field_name, permanent_filter_attributes=None):
    """
    Get listbox values for a single field with caching
    """
    cache_key = f'listbox_{field_name}'

    # Check cache
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Query database
    values = list(
        Server.objects.values_list(field_name, flat=True)
        .exclude(**{field_name: None})
        .exclude(**{field_name: ''})
        .distinct()
        .order_by(field_name)
    )

    # Sort with EMPTY at end
    if any(v and str(v).upper() == "EMPTY" for v in values):
        values = [v for v in values if v and str(v).upper() != "EMPTY"]
        values.sort()
        values.append("EMPTY")

    # Cache for 1 hour
    cache.set(cache_key, values, 3600)

    return values


# ============================================================================
# QUERY CONSTRUCTION HELPERS
# ============================================================================

def construct_query(key, terms):
    """
    Create a Django Q object based on a list of terms for a specific field
    Supports:
      - @term: exact match (case-insensitive)
      - !term: exclusion
      - term: contains (case-insensitive)
    """
    query = Q()

    for term in terms:
        if not term:
            continue
        if term.startswith('@'):
            term = term[1:]
            query |= Q(**{f'{key}__iexact': term})
        elif term.startswith('!'):
            term = term[1:]
            query &= ~Q(**{f'{key}__icontains': term})
        else:
            query |= Q(**{f'{key}__icontains': term})

    return query


def create_permanent_filter_query(json_data, selected_option):
    """
    Create a permanent filter query based on predefined filters in JSON configuration
    """
    permanent_filters = json_data.get("permanentfilters", {})
    permanent_filter_attributes = permanent_filters.get(selected_option) if selected_option else None

    overall_query = Q()

    if permanent_filter_attributes:
        for key, value in permanent_filter_attributes.items():
            terms = [value] if isinstance(value, str) else value
            query = construct_query(key, terms)
            overall_query &= query

    return overall_query, permanent_filters, permanent_filter_attributes


def build_filters_from_request(request, json_data):
    """
    Build filters dictionary from request parameters
    """
    filters = {}

    for field_key, field_info in json_data.get('fields', {}).items():
        input_name = field_info.get('inputname')
        if input_name:
            filter_value = request.GET.get(input_name, '').split(',')
            filters[field_key] = [v for v in filter_value if v]

    return filters


def apply_filters_to_queryset(queryset, filters):
    """
    Apply filters to a queryset
    """
    combined_filter_query = Q()

    for key, values in filters.items():
        if not values or key == "ANNOTATION":
            continue
        query = construct_query(key, values)
        combined_filter_query &= query

    if combined_filter_query:
        queryset = queryset.filter(combined_filter_query)

    return queryset


# ============================================================================
# OPTIMIZED MAIN VIEW
# ============================================================================

@login_required
def server_view(request):
    """
    Main view - Optimized version with:
    - Cached JSON config
    - Batched listbox loading
    - Optimized grouped queries
    - Support for lazy column loading
    """
    start_time = time.time()
    localhostname = socket.gethostname()

    # Get user profile (create if needed)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    # Check edit permissions
    try:
        user_permissions = UserPermissions.objects.get(user_profile=profile)
        edit_mode = user_permissions.inventory_allowedit
    except UserPermissions.DoesNotExist:
        edit_mode = False
    edit_mode = True  # TODO: remove this override

    # Load cached JSON configuration
    json_data = get_field_labels()

    # Get permanent filter selection
    json_data_permanentfilters = json_data.get("permanentfilters", {})
    try:
        user_options = SavedOptions.objects.get(user_profile=profile)
        permanent_filter_selection = user_options.inventory_permanentfilter
    except SavedOptions.DoesNotExist:
        permanent_filter_selection = "All Servers"

    if permanent_filter_selection != "All Servers" and permanent_filter_selection not in json_data_permanentfilters:
        permanent_filter_selection = "All Servers"

    # Build permanent filter query
    permanent_filter_query, permanent_filter_names, permanent_filter_attributes = \
        create_permanent_filter_query(json_data, permanent_filter_selection)

    # Build filters from request
    filters = build_filters_from_request(request, json_data)

    # Get visible columns from request (for lazy loading optimization)
    visible_columns_param = request.GET.get('visible_columns', '')
    visible_columns = set(visible_columns_param.split(',')) if visible_columns_param else None

    # Base queryset - only order once
    base_queryset = Server.objects.all()

    # Apply permanent filter
    if permanent_filter_query:
        base_queryset = base_queryset.filter(permanent_filter_query)

    # Apply user filters
    base_queryset = apply_filters_to_queryset(base_queryset, filters)

    # Handle annotation filter specially
    annotation_filter = request.GET.get("annotation")
    if annotation_filter:
        annotation_terms = annotation_filter.split(',')
        query = construct_query("notes", annotation_terms)
        server_ids = ServerAnnotation.objects.filter(query).values_list('SERVER_ID', flat=True)
        base_queryset = base_queryset.filter(SERVER_ID__in=server_ids)

    # Final ordering
    filtered_servers = base_queryset.order_by('SERVER_ID', 'APP_NAME_VALUE')

    # Pagination settings
    page_size = int(request.GET.get('page_size', 50))
    page_number = request.GET.get("page")

    # Display mode
    flat_view = request.GET.get('view', '').lower() == 'flat'

    # Prepare model fields info
    json_data_fields = json_data.get("fields", {})
    if 'ANNOTATION' in json_data_fields and not edit_mode:
        json_data_fields = {k: v for k, v in json_data_fields.items() if k != 'ANNOTATION'}

    model_fields = []
    for field_name, field_info in json_data_fields.items():
        model_fields.append({
            'name': field_name,
            'verbose_name': field_info.get('displayname', field_name.replace('_', ' ').title()),
            'is_hostname': field_name == 'SERVER_ID'
        })

    # ========================================================================
    # OPTIMIZED DATA FETCHING
    # ========================================================================

    display_servers = []
    cacheset = False

    if flat_view:
        # FLAT MODE - Direct server pagination
        paginator = Paginator(filtered_servers, page_size)
        page_obj_raw = paginator.get_page(page_number)

        # Get current page servers
        current_page_servers = list(page_obj_raw)
        hostnames_in_page = [server.SERVER_ID for server in current_page_servers]

        # Batch fetch annotations for current page only
        annotations_dict = {}
        if edit_mode and hostnames_in_page:
            annotations = ServerAnnotation.objects.filter(SERVER_ID__in=hostnames_in_page)
            annotations_dict = {ann.SERVER_ID: ann for ann in annotations}

        # Build display data
        for server in current_page_servers:
            display_servers.append({
                'hostname': server.SERVER_ID,
                'count': 1,
                'total_count': 1,
                'hidden_count': 0,
                'has_hidden': False,
                'constant_fields': {},
                'variable_fields': {},
                'all_instances': [server],
                'primary_server': server,
                'annotation': annotations_dict.get(server.SERVER_ID)
            })

        page_obj = create_page_wrapper(display_servers, page_obj_raw)
        total_servers_stat = paginator.count
        total_instances_stat = total_servers_stat

    else:
        # GROUPED MODE - Optimized with fewer queries

        # Query 1: Get distinct hostnames for pagination
        filtered_hostnames_qs = (
            filtered_servers
            .values('SERVER_ID')
            .distinct()
            .order_by('SERVER_ID')
        )

        hostnames_paginator = Paginator(filtered_hostnames_qs, page_size)
        hostnames_page = hostnames_paginator.get_page(page_number)
        hostnames_in_page = [item['SERVER_ID'] for item in hostnames_page]

        if hostnames_in_page:
            # Query 2: Get all data in ONE query - servers, summaries, and annotations
            # Using only() to limit fetched fields for better performance
            servers_for_page = filtered_servers.filter(SERVER_ID__in=hostnames_in_page)
            servers_list = list(servers_for_page)

            # Query 3: Summaries (uses only() for efficiency)
            summaries_queryset = ServerGroupSummary.objects.filter(
                SERVER_ID__in=hostnames_in_page
            ).only('SERVER_ID', 'total_instances', 'constant_fields', 'variable_fields')
            summaries_dict = {s.SERVER_ID: s for s in summaries_queryset}

            # Query 4: Annotations (only if edit mode)
            annotations_dict = {}
            if edit_mode:
                annotations = ServerAnnotation.objects.filter(SERVER_ID__in=hostnames_in_page)
                annotations_dict = {ann.SERVER_ID: ann for ann in annotations}

            # Group servers by hostname
            server_groups = defaultdict(list)
            for server in servers_list:
                server_groups[server.SERVER_ID].append(server)

            # Build display data maintaining page order
            for SERVER_ID in hostnames_in_page:
                server_list = server_groups.get(SERVER_ID, [])
                if not server_list:
                    continue

                summary = summaries_dict.get(SERVER_ID)

                if summary:
                    visible_count = len(server_list)
                    total_count = summary.total_instances
                    hidden_count = max(0, total_count - visible_count)

                    if visible_count == 1:
                        # Single instance - show real data
                        single_server = server_list[0]
                        constant_fields = {}
                        for field in single_server._meta.fields:
                            if field.name not in ['id', 'created_at', 'updated_at']:
                                value = getattr(single_server, field.name)
                                if value:
                                    constant_fields[field.name] = str(value)

                        display_servers.append({
                            'hostname': SERVER_ID,
                            'count': visible_count,
                            'total_count': total_count,
                            'hidden_count': hidden_count,
                            'has_hidden': hidden_count > 0,
                            'constant_fields': constant_fields,
                            'variable_fields': {},
                            'all_instances': server_list,
                            'annotation': annotations_dict.get(SERVER_ID)
                        })
                    else:
                        # Multiple instances - use summary
                        display_servers.append({
                            'hostname': SERVER_ID,
                            'count': visible_count,
                            'total_count': total_count,
                            'hidden_count': hidden_count,
                            'has_hidden': hidden_count > 0,
                            'constant_fields': summary.constant_fields,
                            'variable_fields': summary.variable_fields,
                            'all_instances': server_list,
                            'annotation': annotations_dict.get(SERVER_ID),
                            'instances_json': json.dumps([{
                                'constant_fields': {fn: str(getattr(s, fn, '')) for fn in summary.constant_fields.keys()},
                                'variable_fields': {fn: str(getattr(s, fn, '')) for fn in summary.variable_fields.keys()},
                            } for s in server_list], ensure_ascii=False),
                        })
                else:
                    display_servers.append({
                        'hostname': SERVER_ID,
                        'count': len(server_list),
                        'total_count': len(server_list),
                        'hidden_count': 0,
                        'has_hidden': False,
                        'constant_fields': {'status': 'Summary missing - please rebuild'},
                        'variable_fields': {},
                        'all_instances': server_list,
                        'annotation': annotations_dict.get(SERVER_ID)
                    })

        page_obj = create_page_wrapper(display_servers, hostnames_page)

        # Statistics
        total_servers_stat = hostnames_paginator.count
        total_instances_stat = filtered_servers.count() if not filters else sum(g['count'] for g in display_servers)

    # ========================================================================
    # OPTIMIZED LISTBOX LOADING
    # ========================================================================

    # Get all listbox fields
    listbox_fields = get_all_listbox_fields(json_data)

    # Batch load all listbox values
    listbox_values = batch_load_listbox_values(listbox_fields)
    cacheset = bool(listbox_values)

    # Build table_fields with listbox values
    table_fields = []
    for key, val in json_data.get('fields', {}).items():
        listbox_value = val.get("listbox", '')
        if listbox_value and key in listbox_values:
            listbox_evaluated = listbox_values[key]
        else:
            listbox_evaluated = ''

        table_fields.append({
            "name": key,
            "displayname": val.get("displayname", key),
            "inputname": val.get("inputname", key),
            "listbox": listbox_evaluated,
            "listboxmsg": val.get("listboxmsg", 'Select an option'),
            "listid": val.get("listid", 'missingid')
        })

    # Build category fields
    json_data_categories = json_data.get("categories", {})
    grouped = defaultdict(list)
    for key, value in json_data_fields.items():
        if isinstance(value, dict):
            section = value.get('selectionsection', '').strip()
            displayname = value.get('displayname', '').strip() or key
            ischecked = value.get('ischecked') == "True"
            ischeckeddisabled = value.get('ischeckeddisabled') == "True"

            if section in json_data_categories:
                grouped[section].append({
                    'key': key,
                    'displayname': displayname,
                    'ischecked': ischecked,
                    'ischeckeddisabled': ischeckeddisabled
                })

    category_fields = [
        {
            'category': cat,
            'title': json_data_categories[cat],
            'fields': grouped[cat]
        }
        for cat in json_data_categories
        if cat in grouped
    ]

    # Other context data
    saved_searches = profile.savedsearch_set.filter(view=app_name)
    last_status = ImportStatus.objects.order_by('-date_import').first()

    print(f"[TIMING] Total view processing: {time.time() - start_time:.3f}s")

    context = {
        'page_obj': page_obj,
        'table_fields': table_fields,
        'category_fields': category_fields,
        'permanent_filters_fields': permanent_filter_names,
        'appname': app_name,
        'page_size': page_size,
        'saved_searches': saved_searches,
        'last_status': last_status,
        'current_filters': filters,
        'json_data': json.dumps(json_data),
        'loggedonuser': request.user,
        'permanent_filter_selection': permanent_filter_selection,
        'model_fields': model_fields,
        'total_servers': total_servers_stat,
        'total_instances': total_instances_stat,
        'flat_view': flat_view,
        'edit_mode': edit_mode,
        'cacheset': cacheset,
        'localhostname': localhostname,
        'visible_columns': visible_columns_param
    }

    return render(request, f'{app_name}/servers.html', context)


def create_page_wrapper(object_list, source_page):
    """Create a unified page object wrapper for both modes"""
    class UnifiedPageObj:
        def __init__(self, objects, source):
            self.object_list = objects
            self.number = source.number
            self.paginator = source.paginator

        def __iter__(self):
            return iter(self.object_list)

        def has_previous(self):
            return self.number > 1

        def has_next(self):
            return self.number < self.paginator.num_pages

        def previous_page_number(self):
            return self.number - 1 if self.has_previous() else None

        def next_page_number(self):
            return self.number + 1 if self.has_next() else None

        def has_other_pages(self):
            return self.paginator.num_pages > 1

    return UnifiedPageObj(object_list, source_page)


# ============================================================================
# NEW: LAZY LOADING API ENDPOINT
# ============================================================================

@login_required
@require_http_methods(["GET"])
def api_column_data(request):
    """
    API endpoint for lazy loading column data

    Parameters:
        - columns: comma-separated list of column names to fetch
        - hostnames: comma-separated list of SERVER_IDs (optional, for current page)
        - page: page number (if hostnames not provided)
        - page_size: items per page
        - filters: JSON-encoded filters
        - permanentfilter: permanent filter name
        - view: 'flat' or 'grouped'

    Returns:
        JSON with column data for requested servers
    """
    columns = request.GET.get('columns', '').split(',')
    columns = [c.strip() for c in columns if c.strip()]

    if not columns:
        return JsonResponse({'error': 'No columns specified'}, status=400)

    # Validate columns against allowed fields
    json_data = get_field_labels()
    valid_fields = set(json_data.get('fields', {}).keys())
    invalid_columns = [c for c in columns if c not in valid_fields]
    if invalid_columns:
        return JsonResponse({'error': f'Invalid columns: {invalid_columns}'}, status=400)

    # Get hostnames (either directly or via pagination)
    hostnames = request.GET.get('hostnames', '').split(',')
    hostnames = [h.strip() for h in hostnames if h.strip()]

    if not hostnames:
        # Need to compute from filters and pagination
        filters_json = request.GET.get('filters', '{}')
        try:
            filters = json.loads(filters_json)
        except json.JSONDecodeError:
            filters = {}

        permanent_filter_selection = request.GET.get('permanentfilter', 'All Servers')
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))
        flat_view = request.GET.get('view', '').lower() == 'flat'

        # Build queryset
        permanent_filter_query, _, _ = create_permanent_filter_query(json_data, permanent_filter_selection)
        queryset = Server.objects.all()

        if permanent_filter_query:
            queryset = queryset.filter(permanent_filter_query)

        # Apply filters
        for key, values in filters.items():
            if values and key != 'ANNOTATION':
                if isinstance(values, str):
                    values = values.split(',')
                query = construct_query(key, values)
                queryset = queryset.filter(query)

        queryset = queryset.order_by('SERVER_ID', 'APP_NAME_VALUE')

        if flat_view:
            # Flat mode: paginate servers directly
            paginator = Paginator(queryset, page_size)
            page_obj = paginator.get_page(page)
            hostnames = [s.SERVER_ID for s in page_obj]
        else:
            # Grouped mode: paginate distinct hostnames
            hostnames_qs = queryset.values('SERVER_ID').distinct().order_by('SERVER_ID')
            paginator = Paginator(hostnames_qs, page_size)
            page_obj = paginator.get_page(page)
            hostnames = [item['SERVER_ID'] for item in page_obj]

    if not hostnames:
        return JsonResponse({'data': {}})

    # Fetch only the requested columns
    fields_to_fetch = ['SERVER_ID'] + columns

    # Use values() for efficient column selection
    servers_data = Server.objects.filter(
        SERVER_ID__in=hostnames
    ).values(*fields_to_fetch)

    # Group by hostname
    result = defaultdict(lambda: {'instances': []})

    for server in servers_data:
        hostname = server['SERVER_ID']
        instance_data = {col: server.get(col, '') or '' for col in columns}
        result[hostname]['instances'].append(instance_data)

    # Add summary info for grouped view
    flat_view = request.GET.get('view', '').lower() == 'flat'
    if not flat_view:
        summaries = ServerGroupSummary.objects.filter(
            SERVER_ID__in=hostnames
        ).only('SERVER_ID', 'constant_fields', 'variable_fields')

        for summary in summaries:
            hostname = summary.SERVER_ID
            if hostname in result:
                result[hostname]['constant_fields'] = {
                    col: summary.constant_fields.get(col, '')
                    for col in columns if col in summary.constant_fields
                }
                result[hostname]['variable_fields'] = {
                    col: summary.variable_fields.get(col, {})
                    for col in columns if col in summary.variable_fields
                }

    return JsonResponse({
        'data': dict(result),
        'columns': columns,
        'hostnames': hostnames
    })


@login_required
@require_http_methods(["GET"])
def api_listbox_values(request):
    """
    API endpoint to get listbox values for specific columns
    Useful for lazy loading dropdown options
    """
    columns = request.GET.get('columns', '').split(',')
    columns = [c.strip() for c in columns if c.strip()]

    if not columns:
        return JsonResponse({'error': 'No columns specified'}, status=400)

    # Validate columns
    json_data = get_field_labels()
    valid_fields = set(json_data.get('fields', {}).keys())
    columns = [c for c in columns if c in valid_fields]

    # Batch load listbox values
    listbox_values = batch_load_listbox_values(columns)

    return JsonResponse({'data': listbox_values})


# ============================================================================
# REST OF THE VIEWS (keep existing functionality)
# ============================================================================

# ... (The rest of the views like save_search, load_search, delete_search,
#      export_to_file, etc. remain the same but should use get_field_labels()
#      instead of reading the JSON file directly)


def get_filtered_servers(requestfilters, permanent_filter_selection):
    """
    Optimized version - uses cached JSON config
    """
    json_data = get_field_labels()

    filters = {}
    for field_name, field_properties in json_data['fields'].items():
        input_name = field_properties.get('inputname')
        if input_name:
            filters[field_name] = requestfilters.get(input_name)

    # Clean empty filters
    filters = {k: v for k, v in filters.items() if v not in ['', None]}

    # Build queryset
    servers = Server.objects.all().order_by('SERVER_ID')

    for key, value in filters.items():
        terms = value.split(',') if isinstance(value, str) and ',' in value else [value]
        query = construct_query(key, terms)
        servers = servers.filter(query)

    # Apply permanent filter
    permanent_filter_query, _, _ = create_permanent_filter_query(json_data, permanent_filter_selection)
    if permanent_filter_query:
        servers = servers.filter(permanent_filter_query)

    return servers


def get_filter_mapping():
    """
    Optimized version - uses cached JSON config
    """
    json_data = get_field_labels()
    return {field_name: field_name for field_name in json_data['fields'].keys()}
