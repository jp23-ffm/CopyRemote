import csv
import datetime
import django
import io
import json
import math
import os
import time
import threading
import uuid
import socket

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.cache import cache
from django.db import models, transaction
from django.db.models import Q, F, Case, When, Count, OuterRef, Subquery
from django.db.models.functions import Upper
from django.http import FileResponse, JsonResponse, HttpResponse, HttpResponseRedirect, StreamingHttpResponse, QueryDict
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from accessrights.helpers import has_perm
from collections import defaultdict
from .exports import generate_csv, generate_excel, EXPORT_DIR
from urllib.parse import urlencode, parse_qs, unquote, quote_plus
from functools import lru_cache
from threading import Lock

from common.views import generate_charts
from .models import Server, Annotation, ImportStatus
from userapp.models import UserProfile, SavedSearch, SavedOptions, UserPermissions


app_name=__package__.split('.')[-1]

_field_labels_cache = None
_field_labels_file_mtime = 0
_cache_lock = Lock()


def get_field_labels():
    # Cache field_labels.json with update when the file changes, Thread-safe for Gunicorn

    global _field_labels_cache, _field_labels_file_mtime
    
    json_path = os.path.join(os.path.dirname(__file__), 'field_labels.json')
    
    try:
        current_file_mtime = os.path.getmtime(json_path)
    except OSError:
        return _field_labels_cache

    if _field_labels_cache is not None and current_file_mtime == _field_labels_file_mtime:
        return _field_labels_cache
    
    with _cache_lock:
        try:
            current_file_mtime = os.path.getmtime(json_path)
        except OSError:
            return _field_labels_cache
        
        if _field_labels_cache is not None and current_file_mtime == _field_labels_file_mtime:
            return _field_labels_cache
        
        try:
            with open(json_path, 'r', encoding="utf-8") as f:
                _field_labels_cache = json.load(f)
            
            _field_labels_file_mtime = current_file_mtime
            
            #print(f"[get_field_labels] Reloaded field_labels.json (mtime: {current_file_mtime})")
            
        except (OSError, json.JSONDecodeError) as e:
            print(f"[get_field_labels] Error loading field_labels.json: {e}")
            return _field_labels_cache
    
    return _field_labels_cache


def get_filter_mapping():

    json_path = os.path.join(os.path.dirname(__file__), 'field_labels.json')
    with open(json_path, "r", encoding="utf-8") as f:
        field_labels = json.load(f)

    # Initialize an empty dictionary to store the filter mapping
    FILTER_MAPPING = {}
    
    # Iterate over each field defined in the fields section of the JSON configuration
    for field_name, field_properties in field_labels['fields'].items():
        FILTER_MAPPING[field_name] = field_name  # Map the field to the attribute of the model

    # Return the filter mapping dictionary
    return FILTER_MAPPING
    
    
def construct_query(key, terms):
    # Creates a Django Q object based on a list of terms for a specific field
    query = Q()
    
    # Iterate over each term in the terms list
    for term in terms:
        if term.startswith('@'):  # Check if the term starts with '@' for an exact match
            term = term[1:]  # Remove the '@' character
            query |= Q(**{f'{key}__iexact': term})  # Create a Q object for an exact match (case-insensitive)
        elif term.startswith('!'):  # Check if the term starts with '!' for an exclusion
            term = term[1:]  # Remove the '!' character
            query &= ~Q(**{f'{key}__icontains': term})  # Create a Q object for an exclusion (case-insensitive containment test)
        else:  # For terms without special characters, perform a containment test
            query |= Q(**{f'{key}__icontains': term})  # Create a Q object for a containment test (case-insensitive)

    # Return the combined Q object representing the filter criteria
    return query
       

# View to display the server information - Main View
@login_required
def server_view(request):

    # Get the user's profile if it already exists in the table userapp_userprofile
    localhostname = socket.gethostname()    

    # Access rights
    edit_mode = has_perm(request.user, 'hardware.annotations')

    try:
        profile = UserProfile.objects.get(user=request.user)
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    # Read and save the field_labels.json information
    json_data = get_field_labels()
     
    # Initialize the filters dictionary
    filters = {}

    # Create the filter using the parameter passed in the URL with request.GET.get
    for field_key, field_info in json_data['fields'].items():
        input_name = field_info.get('inputname')
        if not input_name:
            continue
        if field_info.get('fieldtype') == 'date':
            date_from = request.GET.get(f'{input_name}_from', '').strip()
            date_to = request.GET.get(f'{input_name}_to', '').strip()
            if date_from:
                filters[f'{field_key}__gte'] = [date_from]
            if date_to:
                filters[f'{field_key}__lte'] = [date_to]
        else:
            filter_value = request.GET.get(input_name, '').split(',')
            filters[field_key] = [v for v in filter_value if v]

    # Build the query based on the filters values extracted earlier
    all_servers = Server.objects.all()

    combined_filter_query = Q()
    for key, values in filters.items():
        if not values:
            continue
        if key in ('ANNOTATION'):
            continue
            
        # Handle date range lookups (__gte and __lte)
        if key.endswith('__gte') or key.endswith('__lte'):
            field_name, lookup = key.rsplit('__', 1)
            combined_filter_query &= Q(**{f'{field_name}__{lookup}': values[0]})
        else:
            # Build the query for this field
            query = construct_query(key, values)
            combined_filter_query &= query  # Combine with AND            

    if combined_filter_query:
        all_servers = all_servers.filter(combined_filter_query)

    # Handle ANNOTATION filter: filter servers by annotation comment
    annotation_terms = [v for v in filters.get('ANNOTATION', []) if v]
    if annotation_terms:
        matching_ids = Annotation.objects.filter(
            construct_query('comment', annotation_terms)
        ).values_list('SERIAL', flat=True)
        all_servers = all_servers.filter(SERIAL__in=matching_ids)

    # Get filtered and sorted servers
    sort_field = request.GET.get('sort', 'SERIAL')
    sort_order = request.GET.get('order', 'asc')

    # Validate sort_field against known fields to prevent injection
    valid_sort_fields = {f_key for f_key in json_data.get('fields', {}).keys()}
    if sort_field not in valid_sort_fields:
        sort_field = 'SERIAL'
    order_expr = F(sort_field).asc(nulls_last=True) if sort_order == 'asc' else F(sort_field).desc(nulls_last=True)

    filtered_servers = all_servers.order_by(order_expr)
   
    # Define some pagination settings that will be passed as context
    page_size = int(request.GET.get('page_size', 50))
    page_number = request.GET.get("page")
   
    # Json part - Reading of field_labels.json to set element dynamically
    
    # Read and store the sections categories and fields of field_labels.json
    json_data_categories=json_data.get("categories", {})
    json_data_fields=json_data.get("fields", {})
    validation_errors = json_data.get('validation_errors', {})

    if 'ANNOTATION' in json_data_fields and not edit_mode:
        json_data_fields = {k: v for k, v in json_data_fields.items() if k != 'ANNOTATION'}

    # Generation of the information loaded form field_labels.json to create the search boxes, the dropdown lists and populate their content
    finalfields = [(field, info) for field, info in json_data_fields.items()]  # Read all items in the json fields section
    
    table_fields=[]
    # Loop in the fields items: if some have the attribute listbox, generate the content to display it the associated drop down list in the view

    cacheset=False
    for key, val in finalfields:
        listbox_value=val.get("listbox", '')
        listempty_value=val.get("listempty", '') 
        if listbox_value:
            cache_key = f"listbox_disc_{key}"
            listbox_evaluated_disc = cache.get(cache_key)
            if listbox_evaluated_disc is None:
                if listempty_value =="True":
                    listbox_evaluated_disc = ['MISSING']
                else:
                    listbox_evaluated_disc = Server.objects.values_list(key, flat=True).distinct().order_by(key)

                if listbox_evaluated_disc:  # Sort the entry to put "EMPTY" at the end
                    listbox_evaluated_disc = list(listbox_evaluated_disc)
                    if any(x is None or x.upper() == "EMPTY" for x in listbox_evaluated_disc):
                        has_na = any(isinstance(x, str) and x.upper() == "EMPTY" for x in listbox_evaluated_disc)  #"EMPTY" in listbox_evaluated_disc
                        listbox_evaluated_disc = [
                            x for x in listbox_evaluated_disc if x is not None and x != "" and x.upper() != "EMPTY"
                        ]

                        listbox_evaluated_disc.sort()
                        if has_na:
                            listbox_evaluated_disc.append("EMPTY")
                   
                cache.set(cache_key, listbox_evaluated_disc, timeout=3600)  # Cache for 1 hour
                cacheset=True
        else:
            listbox_evaluated_disc = '' 
          
        # Create a table_fields item with information from the json: this information will be used for the HTML creation
        table_fields.append({
            "name":key,
            "displayname":val.get("displayname", key),
            "inputname":val.get("inputname", key),
            "listbox":listbox_evaluated_disc,
            "listboxmsg":val.get("listboxmsg", 'Select an option'),
            "listid":val.get("listid", 'missingid'),
            "selectionsection":val.get("selectionsection", 'cat0'),
            "fieldtype":val.get("fieldtype", ''),
        })
        
    # Generation of the information loaded form field_labels.json to create the category tree and its sub-categories
    grouped=defaultdict(list)
    for key, value in json_data_fields.items():
        if (isinstance(value, dict)):
            section=value.get('selectionsection', '').strip()
            displayname=value.get('displayname', '').strip()
            ischecked=bool(value.get('ischecked') == "True")
            ischeckeddisabled=bool(value.get('ischeckeddisabled') == "True")
            
            if not displayname:
               displayname=key

            if section in json_data_categories:
                grouped[section].append({
                    'key':key,
                    'displayname':displayname,
                    'ischecked':ischecked,
                    'ischeckeddisabled':ischeckeddisabled
                })
                
    category_fields = [
        {
            'category':cat,
            'title':json_data_categories[cat],
            'fields': grouped[cat]
        }
        for cat in json_data_categories
        if cat in grouped and cat != 'cat0'
    ]
    
    profile = UserProfile.objects.get(user=request.user)
    last_status = ImportStatus.objects.order_by('-date_import').first()
    visible_columns = request.GET.get("visible_columns")
    
    # Processing according to display mode
    display_servers = []
    
    model_fields = []
    for field_name, field_info in json_data['fields'].items():     
        model_fields.append({
            'name': field_name,
            'verbose_name': field_info.get('displayname', field_name.replace('_', ' ').title()),
            'is_hostname': field_name == 'SERIAL'
        })

    
    paginator = Paginator(filtered_servers, page_size)
    page_obj_raw = paginator.get_page(request.GET.get('page'))

    # Convert only the current page to list
    current_page_servers = list(page_obj_raw)

    # Process servers from current page
    for server in current_page_servers:
        display_servers.append({
            'hostname': server.SERIAL,
            'primary_server': server
        })

    # Load annotations for current page servers
    hostnames_in_page = [s['hostname'] for s in display_servers]
    annotations = Annotation.objects.filter(SERIAL__in=hostnames_in_page)
    annotations_dict = {ann.SERIAL: ann for ann in annotations}
    for server_item in display_servers:
        server_item['annotation'] = annotations_dict.get(server_item['hostname'])

    page_obj = create_page_wrapper(display_servers, page_obj_raw)
    total_servers_stat = paginator.count

    # Load saved searches for this user/app
    saved_searches = SavedSearch.objects.filter(
        user_profile__user=request.user, view=app_name
    ).order_by('name')

    # Rendering servers.html with the corresponding context

    context = {
        'page_obj' : page_obj,  # Pagination object
        'table_fields' : table_fields,  # Information for the dynamic creation of table columns, input boxes and list boxes
        'category_fields' : category_fields,  # Information for the dynamic creation of the catgeory tree
        'appname' : app_name,  # Application name
        'edit_mode': edit_mode,
        'page_size' : page_size,  # Number of objects per page
        'current_filters': filters,  # Filters defined above
        'json_data' : json.dumps(json_data),  # Json content
        'last_status' : last_status,  # Last import state
        'loggedonuser' : request.user,  # Logon name
        'model_fields': model_fields,
        'total_servers': total_servers_stat,
        'cacheset': cacheset,
        'sort_field': sort_field,
        'sort_order': sort_order,        
        'localhostname': localhostname, 
        'validation_errors': validation_errors,
        'saved_searches': saved_searches,
    }   

    return render(request, f'{app_name}/servers.html', context)


def create_page_wrapper(object_list, source_page):
    # Create a unified page object wrapper
    
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


def update_permanentfilter_field(request):
    if request.method == "POST":
        
        # Get the permanent filter choice from the POST data, passed as input permanentfilter_choice
        permanentfilter_choice = request.POST.get("permanentfilter_choice")

        if request.user.is_authenticated:
            # Get the user's profile
            profile = UserProfile.objects.get(user=request.user)

            # Update or create the SavedOptions entry for the user
            permanentfilter, created = SavedOptions.objects.update_or_create(  # Update or create the SavedOptions entry for the user
                user_profile=profile,
                defaults={f'{app_name}_permanentfilter': permanentfilter_choice}
            )
            # Redirect back to the referring page after submission
            return redirect(request.META.get('HTTP_REFERER', '/'))  # Redirect back to the same page after submission
        else:
            # The user is not authenticated
            return JsonResponse({"status": "error", "message": "User is not authenticated."}, status=401)

    # Return an error message if the request method is invalid
    return JsonResponse({"status": "error", "message": "Invalid request method."}, status=400)


@login_required
def edit_annotation(request, hostname):
    annotation = Annotation.objects.filter(SERIAL=hostname).first()

    if request.method == 'GET':
        return JsonResponse({
            'hostname': hostname,
            'comment': annotation.comment if annotation else '',
            'assigned_to': annotation.assigned_to if annotation else '',
            'history': annotation.get_history_display() if annotation else [],
        })

    elif request.method == 'POST':
        comment = request.POST.get('comment', '').strip()
        assigned_to = request.POST.get('assigned_to', '').strip()

        if not annotation:
            annotation = Annotation(SERIAL=hostname)

        annotation.add_entry(comment, assigned_to, request.user)

        return JsonResponse({
            'success': True,
            'message': 'Annotation saved successfully',
            'comment': annotation.comment,
            'assigned_to': annotation.assigned_to,
            'history': annotation.get_history_display(),
            'updated_by': request.user.username,
            'updated_at': annotation.updated_at.strftime('%d/%m/%Y %H:%M')
        })

    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)


@login_required
def bulk_annotation(request):
    if request.method == "POST":
        try:
            query_param = request.POST.get('query')
            if not query_param:
                return JsonResponse({'status': 'error', 'message': 'Query string not provided'}, status=400)

            query_param = unquote(query_param)
            parsed_query = parse_qs(query_param)

            json_data = get_field_labels()

            # Build filter query from URL params
            servers_to_update = Server.objects.all()
            filters = {}
            for field_key, field_info in json_data['fields'].items():
                if 'inputname' in field_info:
                    filters[field_key] = parsed_query.get(field_info['inputname'], [''])[0].split(',')
            filters = {k: v for k, v in filters.items() if v != ['']}

            for key, value in filters.items():
                terms = value if isinstance(value, list) else [value]
                query = construct_query(key, terms)
                servers_to_update = servers_to_update.filter(query)

            total_updates = servers_to_update.count()
            if total_updates == 0:
                return JsonResponse({'status': 'warning', 'message': 'No servers to update with the given filters'}, status=200)

            bulk_comment = request.POST.get('bulk_comment', '')
            bulk_assigned_to = request.POST.get('bulk_assigned_to', '')

            def update_with_progress():
                batch_size = 50
                total_batches = (total_updates + batch_size - 1) // batch_size

                for i in range(total_batches):
                    batch_start = i * batch_size
                    batch_end = min((i + 1) * batch_size, total_updates)
                    batch = servers_to_update[batch_start:batch_end]

                    annotations = []
                    for server in batch:
                        annotation, created = Annotation.objects.get_or_create(SERIAL=server.SERIAL)
                        annotations.append(annotation)

                    for annotation in annotations:
                        annotation.add_entry(bulk_comment, bulk_assigned_to, request.user)

                    progress = ((i + 1) / total_batches) * 100
                    yield f"data: progress:{progress}|batch:{i + 1}\n\n"

            response = StreamingHttpResponse(update_with_progress(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache'
            return response

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f"An unexpected error occurred: {e}"}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid Request Method'}, status=400)
    

@login_required
def chart_view(request):
    # Generate charts based on the filtered data
    
    json_data = get_field_labels()
    
    selected_fields = request.GET.getlist('fields')
    chart_types = request.GET.getlist('types')
    permanent_filter_selection = request.GET.get('permanentfilter')
    
    requestfilters = {}
    for key, value in request.GET.items():
        requestfilters[key] = value
    
    #servers = get_filtered_servers(requestfilters, permanent_filter_selection)
    servers = _get_filtered_servers_for_export(requestfilters)

    if "ANNOTATION" in selected_fields:
        serial_ids = list(servers.values_list('SERIAL', flat=True).distinct())
        annotations = Annotation.objects.filter(SERIAL__in=serial_ids)
        annotation_map = {ann.SERIAL: ann.comment for ann in annotations}
        
        fields_to_extract = ['SERIAL'] + [f for f in selected_fields if f != 'ANNOTATION']
        server_data = list(servers.values(*fields_to_extract).distinct())
        
        for server in server_data:
            server['ANNOTATION'] = annotation_map.get(server['SERIAL'], '')
    else:
        fields_to_extract = ['SERIAL'] + selected_fields
        server_data = list(servers.values(*fields_to_extract).distinct())

    # Pre-calculate the fields total here
    field_totals = {}
    for field in selected_fields:
       
        # Count the unique combos (SERIAL, valeur)
        unique_combos = set()
        for server in server_data:
            serial_id = server.get('SERIAL')
            value = server.get(field, 'Unknown')
            if value is None or value == '':
                value = 'Unknown'
            unique_combos.add((serial_id, str(value)))
        
        field_totals[field] = len(unique_combos)
    
    return generate_charts(request, server_data, json_data, selected_fields, chart_types, field_totals, default_keyfield='SERIAL')   
    

def _get_filtered_servers_for_export(requestfilters):
    # Build a filtered queryset from URL params dict (inputname → value)
    json_data = get_field_labels()
    all_servers = Server.objects.all()
    combined_filter_query = Q()

    for field_key, field_info in json_data['fields'].items():
        if field_key in ('ANNOTATION'):
            continue
        input_name = field_info.get('inputname')
        if not input_name:
            continue
        
        # Handle date range lookups (__gte and __lte) similar to server_view
        if field_info.get('fieldtype') == 'date':
            date_from = requestfilters.get(f'{input_name}_from', '').strip()
            date_to = requestfilters.get(f'{input_name}_to', '').strip()
            if date_from:
                combined_filter_query &= Q(**{f'{field_key}__gte': date_from})
            if date_to:
                combined_filter_query &= Q(**{f'{field_key}__lte': date_to})
        else:
            # Non-date field: extract values from request
            raw = requestfilters.get(input_name, '')
            values = [v for v in (raw.split(',') if isinstance(raw, str) else raw) if v]
            if values:
                # For annotation field, we need to handle it specially
                if field_key == 'ANNOTATION':
                    # Get matching SERIALs from Annotation model
                    matching_ids = Annotation.objects.filter(
                        construct_query('comment', values)
                    ).values_list('SERIAL', flat=True)
                    all_servers = all_servers.filter(SERIAL__in=matching_ids)
                else:
                    # Build the query for this field
                    query = construct_query(field_key, values)
                    combined_filter_query &= query

    if combined_filter_query:
        all_servers = all_servers.filter(combined_filter_query)
        
    # Apply sort order from URL params (same logic as server_view)
    sort_field = requestfilters.get('sort', 'SERIAL')
    sort_order = requestfilters.get('order', 'asc')

    if sort_field == 'ANNOTATION':
        order_expr = F('SERIAL').asc(nulls_last=True)
    else:
        valid_sort_fields = {k for k in json_data.get('fields', {}) if k not in ('ANNOTATION')}
        if sort_field not in valid_sort_fields:
            sort_field = 'SERIAL'
        order_expr = F(sort_field).asc(nulls_last=True) if sort_order == 'asc' else F(sort_field).desc(nulls_last=True)

    return all_servers.order_by(order_expr)
    

# Handles the export of server data to a specified file format (CSV or XLSX)
@login_required
def export_to_file(request, filetype):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not authorized'}, status=405)

    filetype = filetype.lower()
    if filetype not in ['xlsx', 'csv']:
        return JsonResponse({'error': 'Invalid format type'}, status=400)

    data = json.loads(request.body)
    requestfilters = data.get('filters', {})
    columns = data.get('columns', [])

    servers = _get_filtered_servers_for_export(requestfilters)
    hostname_list = list(servers.values_list('SERIAL', flat=True))

    # Annotations
    annotations_dict = {}
    if hostname_list:
        annotations = Annotation.objects.filter(SERIAL__in=hostname_list)
        annotations_dict = {ann.SERIAL: ann for ann in annotations}

    os.makedirs(EXPORT_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    filepath = os.path.join(EXPORT_DIR, f"{job_id}.{filetype}")

    def background_export():
        try:
            if filetype == 'xlsx':
                generate_excel(filepath, servers, annotations_dict, columns)
            else:
                generate_csv(filepath, servers, annotations_dict, columns)
        except Exception as e:
            print(f"Error during export: {e}")

    threading.Thread(target=background_export).start()
    return JsonResponse({'job_id': job_id})


# Check the state of the file to export 
def export_status(request, job_id, filetype):

    extension = filetype.lower()
    if extension not in ['xlsx', 'csv']:
        return JsonResponse({'Error': 'Invalid filetype'}, status=400)

    # Create the full file name based on the job_id and extension passed in the URL from the s function startExport
    filename=f'{job_id}.{extension}'
    filepath = os.path.join(EXPORT_DIR, filename)
    
    # Return "ready" id the file is present, and "pending" if not. During its creation, the file as an additional .tmp extension to not trigger a "ready" too early
    if os.path.exists(filepath):
        return JsonResponse({'status': 'ready'})
    return JsonResponse({'status': 'pending'})


# Trigger the automatic downlaod when the export file is fully created
def download_export(request, job_id, filetype):

    from django.http import Http404
    extension = filetype.lower()
    if extension not in ['xlsx', 'csv']:
        return JsonResponse({'Error': 'Invalid filetype'}, status=400)
        
    # Create the full file name based on the job_id and extension passed in the URL from the s function startExport
    filename=f'{job_id}.{extension}'
    filepath = os.path.join(EXPORT_DIR, filename)
    
    # Raise an error if the file doesn't exist
    if not os.path.exists(filepath):
        raise Http404("File not found")

    # Initiate the automatic download
    response = FileResponse(open(filepath, 'rb'), as_attachment=True, filename=f'export_{app_name}.{extension}')

    def delete_file_after_close(resp):
        try:
            os.remove(filepath)
        except Exception as e:
            print(f"Error during the removing of the file : {e}")

    # Close and delete the generated file once downloaded
    response.close = lambda *args, **kwargs: delete_file_after_close(response)
    return response
        

@login_required
def save_search(request):
    if request.method == 'POST':
        search_name = request.POST.get('search_name', '').strip()
        if len(search_name) > 25:
            return JsonResponse({'success': False, 'message': 'Search name must be 25 characters or fewer.'})
        profile = UserProfile.objects.get(user=request.user)
        if SavedSearch.objects.filter(user_profile=profile, name=search_name).exists():
            return JsonResponse({'success': False, 'message': 'A search with this name already exists.'})
        filters = request.POST.get('filters')
        if not filters:
            return JsonResponse({'success': False, 'message': 'Filters cannot be empty.'})
        try:
            search_params = json.loads(filters)
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': 'Invalid filter data.'})
        tags = json.loads(request.POST.get('tags', '[]'))
        SavedSearch.objects.create(
            user_profile=profile, name=search_name,
            filters=search_params, tags=tags, view=app_name
        )
        return redirect(request.META.get('HTTP_REFERER', '/'))
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})


@login_required
def load_search(request, search_id):
    saved_search = SavedSearch.objects.get(id=search_id, user_profile__user=request.user)
    query_string = urlencode(saved_search.filters, doseq=True)
    return redirect(f'/{app_name}/?{query_string}')


@login_required
def delete_search(request, search_id):
    saved_search = SavedSearch.objects.get(id=search_id, user_profile__user=request.user)
    saved_search.delete()
    return redirect(request.META.get('HTTP_REFERER', '/'))


# Display the logs_imports.html with the last 100 logs entries
def log_imports(request):
    # Get and sort the last entries of the table hardware_importstatus
    logs = ImportStatus.objects.order_by('-date_import')[:100]

    return render(request, f"{app_name}/logs_imports.html", {
        "logs": logs
    })

