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

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.cache import cache
from django.db import models, transaction
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
from functools import lru_cache
from threading import Lock


app_name=__package__.split('.')[-1]

def get_field_labels():
    # Cache with expiration of 10 minutes

    global _field_labels_cache, _field_labels_timestamp
    
    _field_labels_cache = None
    _field_labels_timestamp = 0
    _cache_lock = Lock()
    CACHE_TTL = 600  # 10 minutes    
    
    current_time = time.time()
    
    # Check if the cache is still valid
    if _field_labels_cache is not None and (current_time - _field_labels_timestamp) < CACHE_TTL:
        return _field_labels_cache
    
    # Cache expired or missing: reload
    with _cache_lock:
        # Double-check
        if _field_labels_cache is not None and (current_time - _field_labels_timestamp) < CACHE_TTL:
            return _field_labels_cache
        
        # Load the file
        json_path = os.path.join(os.path.dirname(__file__), 'field_labels.json')
        with open(json_path, 'r', encoding="utf-8") as f:
            _field_labels_cache = json.load(f)
        
        _field_labels_timestamp = current_time
        
    return _field_labels_cache

def get_latest_log_date():
    log_dir = '/var/tmp/chimera/'
    try:
        log_files = [f for f in os.listdir(log_dir) if f.startswith('insertion_log_')]  # Get all logs from the directory
        if not log_files:
            return "No log available"

        log_files.sort(key=lambda f: os.path.getmtime(os.path.join(log_dir, f)), reverse=True)  # Sort to get the most recent one
        latest_log_file = os.path.join(log_dir, log_files[0])

        with open(latest_log_file, 'r') as file:
            for line in file:
                if "Log Date and Time:" in line:
                    return line.strip().replace("Log Date and Time: ", "")  # Extract the time to display
    except Exception as e:
        print(f"Error reading log file: {e}")
        return "Error reading log"

    return "No log available"


# Function to create a Django Q object based on a list of terms for a specific field
def construct_query(key, terms):

    # Initialize an empty Q object to build the combined query
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
    
    
# Function to create a permanent filter query based on predefined filters in a JSON configuration file
def create_permanent_filter_query(json_data, selected_option):
       
    # Extract the permanent filters section from the JSON data
    json_data_permanent_filter_names=json_data.get("permanentfilters", {})
    permanent_filter = json_data.get("permanentfilters", {})
    
    # Retrieve the attributes for the selected permanent filter. If selected_option is None, permanent_filter_attributes will be None
    permanent_filter_attributes = permanent_filter.get(selected_option, {}) if selected_option else None
    
    # Prepare the filter attributes for query construction
    if permanent_filter_attributes:
        # Convert the filter attributes into a list of tuples: each tuple contains a key and a list of values (even if the value is a single string)
        dict_items = [(key, [value] if isinstance(value, str) else value) for key, value in permanent_filter_attributes.items()]
    else:
        dict_items = None

    # Initialize an empty Q object to build the combined query
    overall_query = Q() 
    if dict_items:
        for key, value in dict_items:
            # Check if the value is a list
            if isinstance(value, list):
                terms = value
            else:
                terms = [value]
            
            # Create a Q object for the current key and terms
            query = construct_query(key, terms)
            
            # Combine the new query with the overall query using the &= operator: the overall query must satisfy all individual queries
            overall_query &= query

    # Return the combined query, the names of all permanent filters, and the attributes of the selected permanent filter
    return overall_query, json_data_permanent_filter_names, permanent_filter_attributes



def get_cached_listbox(field_name):
    """
    Cache des valeurs distinctes - 1 heure
    Indépendant des filtres (listbox doit toujours montrer toutes les valeurs)
    """
    cache_key = f'listbox_{field_name}'
    
    cached_values = cache.get(cache_key)
    if cached_values is not None:
        return cached_values
    
    # Calculate from the whole table (no filter)
    values = list(
        Server.objects.values_list(field_name, flat=True)
        .distinct()
        .order_by(field_name)
    )
    
    # Check EMPTY
    if any(x is None or (isinstance(x, str) and x.upper() == "EMPTY") for x in values):
        values = [x for x in values if x and x.upper() != "EMPTY"]
        values.sort()
        values.append("EMPTY")
    
    # Cache 1 hour
    cache.set(cache_key, values, 3600)
    
    return values

# View to display the server information - Main View
@login_required
def server_view(request):

    # Get the user's profile if it already exists in the table userapp_userprofile
    start_time = time.time()
    start1_time = time.time()
    localhostname = socket.gethostname()    

    print(f"[TIMING] View start")

    try:
        profile = UserProfile.objects.get(user=request.user)
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    try:
        user_permissions = UserPermissions.objects.get(user_profile=profile)
        edit_mode = user_permissions.inventory_allowedit
    except UserPermissions.DoesNotExist:
        edit_mode = False
    edit_mode = True ### to remove

    # Read and save the field_labels.json information
    print(f"[TIMING] Read json: {time.time()}s")
    #json_path=os.path.join(os.path.dirname(__file__), 'field_labels.json')
    #with open(json_path, "r", encoding="utf-8") as f:
    #    json_data=json.load(f)
    json_data = get_field_labels()

    # Read the permanentfilters section from field_labels.json and the last permanent filter chosen by the user for this view
    json_data_permanentfilters=json_data.get("permanentfilters", {})
    try:
        user_options = SavedOptions.objects.get(user_profile=profile)
        permanent_filter_selection = user_options.inventory_permanentfilter
    except SavedOptions.DoesNotExist:
        permanent_filter_selection = "All Servers"
                    
    # If the last permanent filter entry doesn't match with any filter defined in field_labels.json, switch back to "All Servers"
    if permanent_filter_selection != "All Servers":
        if permanent_filter_selection not in json_data_permanentfilters:
            permanent_filter_selection = "All Servers"

    print(f"[TIMING] Parameters retrieved: {time.time() - start_time:.3f}s")
    start_time = time.time()
    print(f"[TIMING] Permanent Filter start")
        
    # Call create_permanent_filter_query to create the query associated to the permanent filter parameters
    permanent_filter_query, permanent_filter_names, permanent_filter_attributes = create_permanent_filter_query(json_data, permanent_filter_selection)
    
    print(f"[TIMING] End of permanent filter: {time.time() - start_time:.3f}s")
    # Initialize the filters dictionary
    filters = {}

    # Create the filter using the parameter passed in the URL with request.GET.get 
    # Iterate over the fields section to search for potential matches and construct the filters dictionary
    for field_key, field_info in json_data['fields'].items():
        # Retrieve the input name for the current field
        input_name = field_info.get('inputname')
        if input_name:
            # Retrieve the filter value from the request's GET parameters, if any, and split the value by commas to handle multiple filter values
            # Example: businesscontinuity/?server=EURV%2CMAD&visible_columns... -> filters['server']=['EURV','MAD']
            filter_value = request.GET.get(input_name, '').split(',')
            filters[field_key] = [v for v in filter_value if v]
    
    latest_log_date = get_latest_log_date()
 
    # Remove all [''] added during the filters creation
    #filters = { k: v for k, v in filters.items() if v != [''] }

    # Build the query based on the filters values extracted earlier
    print(f"[TIMING] Create the query: {time.time()}s")

    query_time = time.time()
    all_servers = Server.objects.all().order_by('SERVER_ID')
    
    # Apply permanent filter
    if permanent_filter_query:
        all_servers = all_servers.filter(permanent_filter_query)
        
    combined_filter_query = Q()
    for key, values in filters.items():
        if not values:
            continue
        if key == "ANNOTATION":
            continue

        # Build the query for this field
        query = construct_query(key, values)
        combined_filter_query &= query  # Combine with AND

    # Special case Annotation
    filter_value = request.GET.get("annotation")
    if filter_value:
        filter_value=filter_value.split(',')
        query = construct_query("notes", filter_value)
        server_ids = ServerAnnotation.objects.filter(query).values_list('SERVER_ID', flat=True)
        combined_filter_query &= Q(SERVER_ID__in=server_ids)

    if combined_filter_query:
        all_servers = all_servers.filter(combined_filter_query)
    
    # Get filtered servers
    filtered_servers = all_servers.order_by('SERVER_ID', 'APP_NAME_VALUE')

    # Fetch only the necessary data upfront
    start_time = time.time()
    print(f"[TIMING] Getting all servers")
    
    #filtered_servers = Server.objects.filter(query).order_by('SERVER_ID')#, 'APP_NAME_VALUE')
    print(f"[TIMING] All servers retrieved: {time.time() - start_time:.3f}s")
        
    # Define some pagination settings that will be passed as context
    page_size = int(request.GET.get('page_size', 50))
    #paginator = Paginator(filtered_servers, page_size)
    page_number = request.GET.get("page")
    #page_obj = paginator.get_page(page_number)
   
    # Json part - Reading of field_labels.json to set element dynamically
    
    # Read and store the sections categories and fields of field_labels.json
    json_data_categories=json_data.get("categories", {})
    json_data_fields=json_data.get("fields", {})
    if 'ANNOTATION' in json_data_fields and edit_mode == False:
        del json_data_fields['ANNOTATION']
    
    # Generation of the information loaded form field_labels.json to create the search boxes, the dropdown lists and populate their content
    finalfields = [(field, info) for field, info in json_data_fields.items()]  # Read all items in the json fields section
    
    table_fields=[]
    # Loop in the fields items: if some have the attribute listbox, generate the content to display it the associated drop down list in the view
    print(f"[TIMING] Creating listboxes")
    start_time = time.time()
    cacheset=False
    for key, val in finalfields:
        listbox_value=val.get("listbox", '')
        if listbox_value:
            cache_key = f"listbox_{key}"
            listbox_evaluated = cache.get(cache_key)
            if listbox_evaluated is None:
                if permanent_filter_attributes is not None and key in permanent_filter_attributes:  # A permanent filter is defined for this entry: display its attributes
                    #listbox_evaluated = permanent_filter_attributes[key]
                    listbox_evaluated = Server.objects.values_list(key, flat=True).distinct().order_by(key)
                else:  # A listbox must be displayed: list the unique values
                    listbox_evaluated = Server.objects.values_list(key, flat=True).distinct().order_by(key)
                    #print(key)

                if listbox_evaluated:  # Sort the entry to put "EMPTY" at the end
                    listbox_evaluated = list(listbox_evaluated)
                    if any(x is None or x.upper() == "EMPTY" for x in listbox_evaluated):
                        has_na = any(isinstance(x, str) and x.upper() == "EMPTY" for x in listbox_evaluated)  #"EMPTY" in listbox_evaluated
                        listbox_evaluated = [
                            x for x in listbox_evaluated if x is not None and x != "" and x.upper() != "EMPTY"
                        ]

                        listbox_evaluated.sort()
                        if has_na:
                            listbox_evaluated.append("EMPTY")
                   
                cache.set(cache_key, listbox_evaluated, timeout=3600)  # Cache for 1 hour
                cacheset=True
        else:
            listbox_evaluated = ''
          
        # Create a table_fields item with information from the json: this information will be used for the HTML creation
        table_fields.append({
    		"name":key,
    	  	"displayname":val.get("displayname", key),
    	  	"inputname":val.get("inputname", key),
    		"listbox":listbox_evaluated,
    	  	"listboxmsg":val.get("listboxmsg", 'Select an option'),
    	  	"listid":val.get("listid", 'missingid')
        })
        
    print(f"[TIMING] Listboxes evaluated: {time.time() - start_time:.3f}s")

    # Generation of the information loaded form field_labels.json to create the category tree and its sub-categories
    print(f"[TIMING] Categories and fields")
    start_time = time.time()
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
        if cat in grouped
    ]
  
    profile = UserProfile.objects.get(user=request.user)
    saved_searches = profile.savedsearch_set.filter(view=app_name)
    last_status = ImportStatus.objects.order_by('-date_import').first()
    visible_columns = request.GET.get("visible_columns")
    
    print(f"[TIMING] End of pre-rendering: {time.time() - start1_time:.3f}s")
    
    ###############################################

    # Processing according to display mode
    display_servers = []
        
    start_time = time.time()
    print(f"[TIMING] View start")

    # Display mode parameters
       
    print(f"[TIMING] Parameters retrieved: {time.time() - start_time:.3f}s")
    filter_start = time.time()
    
    print(f"[TIMING] Filters applied: {time.time() - filter_start:.3f}s")
    
    fields_start = time.time()
    
    # Get model fields (exclude technical fields)
    model_fields = []
    excluded_fields = set()

    for field_name, field_info in json_data['fields'].items():
        if field_name not in excluded_fields:
            model_fields.append({
                'name': field_name,
                'verbose_name': field_info.get('displayname', field_name.replace('_', ' ').title()),
                'is_hostname': field_name == 'SERVER_ID'
            })

    print(f"[TIMING] Model fields: {time.time() - fields_start:.3f}s")    
    
    
    else: # Grouped View
    
    print(f"[TIMING] Grouped mode selected")
    processing_start = time.time()
    grouping_start = time.time()
    filtered_hostnames_qs = (filtered_servers
        .values('SERVER_ID')
        .distinct()
        .order_by('SERVER_ID')
    )
    
    print(f"[TIMING] Filtered hostnames query prepared")
    
    # Paginate hostnames
    pagination_start = time.time()
    hostnames_paginator = Paginator(filtered_hostnames_qs, page_size)
    print(f"[TIMING] Hostnames paginator: {time.time() - pagination_start:.3f}s")
    pagination_start = time.time()
    hostnames_page = hostnames_paginator.get_page(request.GET.get('page'))
    print(f"[TIMING] Hostnames page: {time.time() - pagination_start:.3f}s")
    
    # Get servers only for hostnames in current page
    servers_start = time.time()
    hostnames_in_page = [item['SERVER_ID'] for item in hostnames_page]
    servers_for_page = filtered_servers.filter(SERVER_ID__in=hostnames_in_page)
    
    # Now convert to list (much smaller dataset)
    servers_list = list(servers_for_page)
    print(f"[TIMING] Servers for page conversion ({len(servers_list)} servers for {len(hostnames_in_page)} hostnames): {time.time() - servers_start:.3f}s")
    
    # Group servers by hostname
    grouping_start = time.time()
    server_groups = defaultdict(list)
    for server in servers_list:
        server_groups[server.SERVER_ID].append(server)
    print(f"[TIMING] Grouping by hostname ({len(server_groups)} groups): {time.time() - grouping_start:.3f}s")
    
    # Get pre-calculated summaries
    summaries_start = time.time()

    if hostnames_in_page:
        summaries_queryset = ServerGroupSummary.objects.filter(SERVER_ID__in=hostnames_in_page).only('SERVER_ID', 'total_instances', 'constant_fields', 'variable_fields')
        print(f"[TIMING] Summaries retrieved (summaries_queryset): {time.time() - summaries_start:.3f}s")
        summaries_dict = {summary.SERVER_ID: summary for summary in summaries_queryset}
        print(f"[TIMING] Summaries retrieved (dict {len(summaries_dict)} summaries): {time.time() - summaries_start:.3f}s")
    else:
        summaries_dict = {}
        print(f"[TIMING] No summaries to retrieve: {time.time() - summaries_start:.3f}s")
    
    # Create display objects for grouping
    analysis_start = time.time()
    grouped_servers = []

    for SERVER_ID in hostnames_in_page:  # Maintain page order
        server_list = server_groups.get(SERVER_ID, [])
        if not server_list:
            continue
        
        # Get pre-calculated summary
        summary = summaries_dict.get(SERVER_ID)
        
        if summary:
            visible_count = len(server_list)
            total_count = summary.total_instances
            hidden_count = max(0, total_count - visible_count)
            
            # Only occurrence visible: print the real data
            if visible_count == 1:
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
                })
            else:
                # Default logic for several occurrences
                display_servers.append({
                    'hostname': SERVER_ID,
                    'count': visible_count,
                    'total_count': total_count,
                    'hidden_count': hidden_count,
                    'has_hidden': hidden_count > 0,
                    'constant_fields': summary.constant_fields,
                    'variable_fields': summary.variable_fields,
                    'all_instances': server_list,
                    'instances_json': json.dumps([{
                        'constant_fields': {field_name: str(getattr(s, field_name, '')) for field_name in summary.constant_fields.keys()},
                        'variable_fields': {field_name: str(getattr(s, field_name, '')) for field_name in summary.variable_fields.keys()},
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
            })
    
    print(f"[TIMING] Group analysis: {time.time() - analysis_start:.3f}s")

    if edit_mode:
        annotations_start = time.time()

        annotations_dict = {}
        if hostnames_in_page:
            annotations = ServerAnnotation.objects.filter(SERVER_ID__in=hostnames_in_page)
            annotations_dict = {ann.SERVER_ID: ann for ann in annotations}
            
        # Add annotations to display servers
        for server_group in display_servers:
            server_group['annotation'] = annotations_dict.get(server_group['hostname'])
        
        print(f"[TIMING] Annotations for current page ({len(annotations_dict)} annotations): {time.time() - annotations_start:.3f}s")

    page_obj = create_page_wrapper(display_servers, hostnames_page)

    # Statistics for grouped mode
    stats_start = time.time()
    if not filters:
        # Without filters: get true global statistics
        total_servers_stat = hostnames_paginator.count
        total_instances_stat = filtered_servers.count()
    else:
        # With filters: use current filtered results
        total_servers_stat = len(grouped_servers)
        total_instances_stat = sum(group['count'] for group in grouped_servers)
        
    print(f"[TIMING] Statistics calculation: {time.time() - stats_start:.3f}s")
    print(f"[TIMING] Total grouped mode: {time.time() - processing_start:.3f}s")
    

    # Rendering servers.html with the corresponding context

    context = {
        'page_obj' : page_obj,  # Pagination object
        'table_fields' : table_fields,  # Information for the dynamic creation of table columns, input boxes and list boxes
        'category_fields' : category_fields,  # Information for the dynamic creation of the catgeory tree
        'permanent_filters_fields' : permanent_filter_names,  # Names from the section "permanentfilters" in the json file
        'appname' : app_name,  # Application name
        'page_size' : page_size,  # Number of objects per page
        'saved_searches' : saved_searches,  # Last Searches saved
        'last_status' : last_status,  # Last import state
        'current_filters': filters,  # Filters defined above
        'json_data' : json.dumps(json_data),  # Json content
        'loggedonuser' : request.user,  # Logon name
        'permanent_filter_selection' : permanent_filter_selection,  # Permanent filter name
        'model_fields': model_fields,
        'total_servers': total_servers_stat,
        'total_instances': total_instances_stat,
        'flat_view': false,
        'edit_mode': edit_mode,
        'cacheset': cacheset,
        'localhostname': localhostname,
        'visible_columns': visible_columns
    }   

    return render(request, f'{app_name}/servers.html', context)


# View to save a user's search criteria
@login_required
def save_search(request):

    # filters, tags, referrer, query and search_name are passed through saveSearchForm
    if request.method == 'POST':
    
        search_name = request.POST['search_name']  # Retrieve the search name from the POST data
        if len(search_name) > 25:  # Validate the name length
            return JsonResponse({'success': False, 'message': 'Search name must be 25 characters or fewer.'})

        profile = UserProfile.objects.get(user=request.user)  # Get the user's profile
        # Check if a search with the same name already exists for the user
        if SavedSearch.objects.filter(user_profile=profile, name=search_name).exists():
            return JsonResponse({'success': False, 'message': 'A search with this name already exists.'})

        # Retrieve the filters from the POST data        
        filters = request.POST.get('filters', None)
        if not filters:
            return JsonResponse({'success': False, 'message': 'Filters cannot be empty.'})

        try:
            search_params = json.loads(filters)  # Parse the filters data, passed as JSON
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': 'Invalid filter data.'})

        tags = json.loads(request.POST.get('tags', '[]'))  # Retrieve the tags from the POST data, if any
        # Create a new SavedSearch entry with the provided data        
        saved_search = SavedSearch.objects.create(user_profile=profile, name=search_name, filters=search_params, tags=tags, view=app_name)

        # Redirect back to the previous page after saving the search
        return redirect(request.META.get('HTTP_REFERER', '/'))
        
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})

"""
@login_required
def chart_view(request):
    json_data = get_field_labels()

    selected_fields = request.GET.getlist('fields')  # Ex: ['SERVER_ID', 'APP_NAME_VALUE']
    chart_types = request.GET.getlist('types')       # Ex: ['bar', 'pie']
    permanent_filter_selection = request.GET.get('permanentfilter')
    
    requestfilters = {}
    
    # Retrieve the filters based on the url
    for key, value in request.GET.items():
        requestfilters[key] = value

    servers = get_filtered_servers(requestfilters, permanent_filter_selection)

    if "ANNOTATION" in selected_fields:
        hostnames = (servers.values('SERVER_ID').distinct().order_by('SERVER_ID'))
        hostname_list = [item['SERVER_ID'] for item in hostnames]
        annotations_dict = {}
        if hostname_list:
            annotations = ServerAnnotation.objects.filter(SERVER_ID__in=hostname_list)
            servers = annotations.values('SERVER_ID').distinct()

    else: # No Annotation
        fields_to_keep = ['SERVER_ID'] + selected_fields
        servers = servers.values(*fields_to_keep).distinct()

    return generate_charts(request, servers, json_data)
    
  
@login_required
def chart_view(request):
    json_data = get_field_labels()
    
    selected_fields = request.GET.getlist('fields')
    chart_types = request.GET.getlist('types')
    permanent_filter_selection = request.GET.get('permanentfilter')
    
    requestfilters = {}
    
    # Retrieve the filters based on the url
    for key, value in request.GET.items():
        requestfilters[key] = value
    
    servers = get_filtered_servers(requestfilters, permanent_filter_selection)
    server_ids = list(servers.values_list('SERVER_ID', flat=True).distinct())
    
    if "ANNOTATION" in selected_fields:
        annotations = ServerAnnotation.objects.filter(SERVER_ID__in=server_ids)
        annotation_map = {ann.SERVER_ID: ann.notes for ann in annotations}
        
        fields_to_extract = ['SERVER_ID'] + [f for f in selected_fields if f != 'ANNOTATION']
        server_data = list(servers.values(*fields_to_extract).distinct())

        for server in server_data:
            server['ANNOTATION'] = annotation_map.get(server['SERVER_ID'], '')

    else:
        fields_to_extract = ['SERVER_ID'] + selected_fields
        server_data = list(servers.values(*fields_to_extract).distinct())
    
    return generate_charts(request, server_data, json_data, selected_fields, chart_types)
"""

@login_required
def chart_view(request):
    json_data = get_field_labels()
    
    selected_fields = request.GET.getlist('fields')
    chart_types = request.GET.getlist('types')
    permanent_filter_selection = request.GET.get('permanentfilter')
    
    requestfilters = {}
    for key, value in request.GET.items():
        requestfilters[key] = value
    
    servers = get_filtered_servers(requestfilters, permanent_filter_selection)
    
    if "ANNOTATION" in selected_fields:
        server_ids = list(servers.values_list('SERVER_ID', flat=True).distinct())
        annotations = ServerAnnotation.objects.filter(SERVER_ID__in=server_ids)
        annotation_map = {ann.SERVER_ID: ann.notes for ann in annotations}
        
        fields_to_extract = ['SERVER_ID'] + [f for f in selected_fields if f != 'ANNOTATION']
        server_data = list(servers.values(*fields_to_extract).distinct())
        
        for server in server_data:
            server['ANNOTATION'] = annotation_map.get(server['SERVER_ID'], '')
    else:
        fields_to_extract = ['SERVER_ID'] + selected_fields
        server_data = list(servers.values(*fields_to_extract).distinct())
    
    # Pre-calculate the fields total here
    field_totals = {}
    for field in selected_fields:
       
        # Count the unique combos (SERVER_ID, valeur)
        unique_combos = set()
        for server in server_data:
            server_id = server.get('SERVER_ID')
            value = server.get(field, 'Unknown')
            if value is None or value == '':
                value = 'Unknown'
            unique_combos.add((server_id, str(value)))
        
        field_totals[field] = len(unique_combos)
    
    return generate_charts(request, server_data, json_data, selected_fields, chart_types, field_totals)                  

# View to load a saved search and redirect to the search results page
@login_required        
def load_search(request, search_id):

    # Retrieve the saved search object for the given search_id and user
    saved_search = SavedSearch.objects.get(id=search_id, user_profile__user=request.user)
    
    # Get the filters from the saved search
    filters = saved_search.filters
    
    # Convert the filters dictionary to a query string
    query_string = urlencode(filters, doseq=True)

    return redirect(f"/{app_name}/?{query_string}")


# View to delete a saved search
@login_required
def delete_search(request, search_id):

    # Retrieve the saved search object for the given search_id and user
    saved_search = SavedSearch.objects.get(id=search_id, user_profile__user=request.user)

    # Delete the saved search object
    saved_search.delete()

    # Redirect back to the previous page after deleting the search
    return redirect(request.META.get('HTTP_REFERER', '/'))


# Display the logs_imports.html with the last 100 logs entries
def log_imports(request):

    # Get and sort the last entries of the table inventory_importstatus
    logs = ImportStatus.objects.order_by('-date_import')[:100]

    return render(request, f"{app_name}/logs_imports.html", {
        "logs": logs
    })
    

#  Generate a mapping of field names to their corresponding model attributes based on the JSON configuration and return a dictionary mapping field names to model attributes
def get_filter_mapping():

    """
      Example: returns
      {
        'SERVER_ID': 'SERVER_ID',
        'priority_asset': 'server_unique.priority_asset',
        ...
      }
    """
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


# Filters servers based on the provided criteria and applies a permanent filter if selected
def get_filtered_servers(requestfilters, permanent_filter_selection):

    json_path = os.path.join(os.path.dirname(__file__), 'field_labels.json')
    with open(json_path, "r", encoding="utf-8") as f:
        field_labels = json.load(f)

    # Initialize filters dictionary
    filters = {}

    # Populate filters dictionary for the fields
    for field_name, field_properties in field_labels['fields'].items():
        input_name = field_properties.get('inputname')
        if input_name:
            filters[field_name] = requestfilters.get(input_name, None)

    # Get all servers and apply filters
    servers = Server.objects.all().order_by('SERVER_ID')
    # Remove all [''] added during the filters creation
    filters = { k: v for k, v in filters.items() if v not in ['', None] }

    for key, value in filters.items():
        if isinstance(value, str) and ',' in value:
            terms = value.split(',')
        else:
            terms = [value]
        query = construct_query(key, terms)        
        servers = servers.filter(query)
    
    # Apply the permanent filter, if selected
    json_path=os.path.join(os.path.dirname(__file__), 'field_labels.json')
    with open(json_path, "r", encoding="utf-8") as f:
        json_data=json.load(f)        

    permanent_filter_query, permanent_filter_names, permanent_filter_attributes = create_permanent_filter_query(json_data, permanent_filter_selection)
    if permanent_filter_query:
        servers = servers.filter(permanent_filter_query)
    
    return servers


# Handles the export of server data to a specified file format (CSV or XLSX)
def export_to_file(request, filetype):

    # filters, columns and permanentfilterselection are passed as data content
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not authorized'}, status=405)
        
    # Verify that the file type is allowed
    filetype = filetype.lower()
    if filetype not in ['xlsx', 'csv']:
        return JsonResponse({'error': 'Invalid format type'}, status=400)

    # Get the data passed as content
    data = json.loads(request.body)
    requestfilters = data['filters']
    columns = data['columns']
    permanent_filter_selection = data['permanentfilterselection']
    exportnotes = data['exportnotes']
    
    # Filter the servers based on the filters and permanent filter
    servers = get_filtered_servers(requestfilters, permanent_filter_selection)
    
    hostnames = (servers.values('SERVER_ID').distinct().order_by('SERVER_ID'))
    hostname_list = [item['SERVER_ID'] for item in hostnames]
    
    annotations_dict = {}
    if exportnotes:
        if hostname_list:
            annotations = ServerAnnotation.objects.filter(SERVER_ID__in=hostname_list)
            annotations_dict = {ann.SERVER_ID: ann for ann in annotations}    
      
    # Generate the filter mapping
    FILTER_MAPPING=get_filter_mapping()
    job_id = str(uuid.uuid4())  # Generate a unique identifier
    filepath = os.path.join(EXPORT_DIR, f"{job_id}.{filetype}")
    
    # Generate the export file using generate_excel from the exports.py module
    def background_export():
        try:
            if filetype == 'xlsx':
                generate_excel(filepath, servers, annotations_dict, columns, FILTER_MAPPING, exportnotes)
            else:
                generate_csv(filepath, servers, annotations_dict, columns, FILTER_MAPPING, exportnotes)
        except Exception as e:
            print(f"Error during the export : {e}")

    # Execute the fucntion background_export as a separated thread
    threading.Thread(target=background_export).start()

    # Return the job id back in order for the js function startExport to wait for its completion
    return JsonResponse({'job_id': job_id})


# Handles the export of grouped server data to a specified file format (CSV or XLSX)
def export_to_file_grouped(request, filetype):

    # filters, columns and permanentfilterselection are passed as data content
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not authorized'}, status=405)
        
    # Verify that the file type is allowed
    filetype = filetype.lower()
    if filetype not in ['xlsx', 'csv']:
        return JsonResponse({'error': 'Invalid format type'}, status=400)

    # Get the data passed as content
    data = json.loads(request.body)
    requestfilters = data['filters']
    columns = data['columns']
    permanent_filter_selection = data['permanentfilterselection']
    exportnotes = data['exportnotes']
    
    # Filter the servers based on the filters and permanent filter
    servers = get_filtered_servers(requestfilters, permanent_filter_selection)
    
    hostnames = (servers.values('SERVER_ID').distinct().order_by('SERVER_ID'))
    server_groups = defaultdict(list)
    for server in servers.order_by('SERVER_ID'):
        server_groups[server.SERVER_ID].append(server)
    
    hostname_list = [item['SERVER_ID'] for item in hostnames]
    summaries_dict = {}
    if hostname_list:
        summaries = ServerGroupSummary.objects.filter(SERVER_ID__in=hostname_list)
        summaries_dict = {s.SERVER_ID: s for s in summaries}
        
    annotations_dict = {}
    if exportnotes:
        if hostname_list:
            annotations = ServerAnnotation.objects.filter(SERVER_ID__in=hostname_list)
            annotations_dict = {ann.SERVER_ID: ann for ann in annotations}
    
    # Generate the filter mapping
    job_id = str(uuid.uuid4())  # Generate a unique identifier
    filepath = os.path.join(EXPORT_DIR, f"{job_id}.{filetype}")
    
    # Generate the export file using generate_excel from the exports.py module
    def background_export():
        try:
            if filetype == 'xlsx':
                generate_excel_grouped(filepath, hostnames, server_groups, summaries_dict, annotations_dict, columns, exportnotes)
            else:
                generate_csv_grouped(filepath, hostnames, server_groups, summaries_dict, annotations_dict, columns, exportnotes)
        except Exception as e:
            print(f"Error during the export : {e}")

    # Execute the fucntion background_export as a separated thread
    threading.Thread(target=background_export).start()

    # Return the job id back in order for the js function startExport to wait for its completion
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
        


# Update and save the permanent filter field for the authenticated user
@csrf_exempt
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


@login_required
@require_http_methods(["GET", "POST"])
def edit_annotation(request, hostname):
    annotation = ServerAnnotation.objects.filter(SERVER_ID=hostname).first()

    if request.method == 'GET':
        form = AnnotationForm(instance=annotation)

        return JsonResponse({
            'hostname': hostname,
            'notes': annotation.notes if annotation else '',
            'type': annotation.type if annotation else '',
            'servicenow': annotation.servicenow if annotation else '',
            'history': annotation.get_history_display() if annotation else [],
            'form_html': form.as_p()
        })

    elif request.method == 'POST':
        form = AnnotationForm(request.POST, instance=annotation)

        if form.is_valid():
            notes_text = form.cleaned_data['notes'].strip()
            annotation_type = form.cleaned_data['type']
            custom_type = form.cleaned_data.get('custom_type', '').strip()
            servicenow = form.cleaned_data['servicenow'].strip()

            # Use custom type if "CUSTOM" is selected
            if annotation_type == 'CUSTOM':
                annotation_type = custom_type

            """if not notes_text:  # For a complete removal
                if annotation:
                    annotation.delete()
                return JsonResponse({
                    'success': True,
                    'message': 'Annotation removed',
                    'notes': '',
                    'history': []
                })"""
                               
            if not annotation:
                annotation = ServerAnnotation(SERVER_ID=hostname)

            annotation.notes = notes_text  # Check here for the history
            annotation.type = annotation_type
            annotation.servicenow = servicenow

            # Add entry to history
            annotation.add_entry(notes_text, request.user, annotation_type, servicenow)
            annotation.save()

            return JsonResponse({
                'success': True,
                'message': 'Annotation saved successfully',
                'notes': annotation.notes,
                'type': annotation.type,
                'servicenow': annotation.servicenow,
                'history': annotation.get_history_display(),
                'updated_by': request.user.username,
                'updated_at': annotation.updated_at.strftime('%d/%m/%Y %H:%M')
            })
        
        
# Handles the bulk import of server data from a CSV file
@require_http_methods(["GET", "POST"])
def bulk_import_csv(request):
    if request.method == 'POST':
        form = CsvUploadForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES['csv_file']

            if not csv_file.name.endswith('.csv'):
                return JsonResponse({'error': "This file must be a CSV."}, status=400)

            decoded_file = csv_file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file, delimiter=';')

            expected_headers = ['hostname', 'type', 'servicenow', 'notes']

            errors = []
            if reader.fieldnames != expected_headers:
                errors.append(
                    f"The Header is incorrect. Fields expected: {', '.join(expected_headers)}. "
                    f"Received: {', '.join(reader.fieldnames or [])}"
                )
                return JsonResponse({'error': 'Header incorrect.', 'detailed_errors': errors}, status=400)

            header_len = len(expected_headers)
            for idx, line in enumerate(decoded_file[1:], start=2):
                if line.count(';') + 1 != header_len:
                    errors.append(
                        f"Line {idx}: number of columns is incorrect "
                        f"(Found: {line.count(';') + 1}, expected: {header_len})."
                    )

            if errors:
                return JsonResponse({'error': f"{len(errors)} errors detected.", 'detailed_errors': errors[:50]}, status=400)

            updated_count = 0
            ignored_count = 0
            lines_processed = 0
            total_lines = len(decoded_file) - 1
            errors = []
            instances_to_update = []
            now_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            now_usr = request.user.username
            now_str = f"[{now_date} - {now_usr}]"

            def process_import():
                nonlocal updated_count, ignored_count, lines_processed, total_lines, errors
                yield f"data: {json.dumps({'progress': 0, 'message': 'Reading CSV file...'})}\n\n"

                for row in reader:
                    hostname = row.get('hostname')

                    if not hostname:
                        ignored_count += 1
                        errors.append(f"Line ignored: 'hostname' is missing. Line content: {row}")
                        continue

                    if not Server.objects.filter(SERVER_ID=hostname).exists():
                        ignored_count += 1
                        errors.append(f"Line ignored: 'hostname'={hostname} does not exist as a server.")
                        continue

                    try:
                        annotation, created = ServerAnnotation.objects.get_or_create(SERVER_ID=hostname)
                    except ServerAnnotation.DoesNotExist:
                        # This should never happen, since we're using get_or_create
                        errors.append(f"Line ignored: unable to retrieve or create 'hostname'={hostname}.")
                        continue

                    notes = row.get('notes', "") or None
                    xtype = row.get('type', "").upper() or None
                    servicenow = row.get('servicenow', "") or None

                    if notes is not None:
                        annotation.notes = notes

                    if xtype is not None:
                        annotation.type = xtype

                    if servicenow is not None:
                        annotation.servicenow = servicenow

                    # Add entry to history
                    annotation.add_entry(notes, request.user, xtype, servicenow)
                    instances_to_update.append(annotation)

                    lines_processed += 1
                    progress = (lines_processed / total_lines) * 100
                    yield f"data: {json.dumps({'progress': progress, 'message': 'Reading CSV file...'})}\n\n"

                total_updates = len(instances_to_update)
                yield f"data: {json.dumps({'progress': 0, 'message': 'Importing data...'})}\n\n"
                for i in range(0, total_updates, 100):
                    ServerAnnotation.objects.bulk_update(
                        instances_to_update[i:i+100],
                        ['notes', 'type', 'servicenow', 'history']
                    )
                    updated_count += len(instances_to_update[i:i+100])
                    progress = (updated_count / total_updates) * 100
                    yield f"data: {json.dumps({'progress': progress, 'message': 'Importing data...'})}\n\n"

                success_msg = f"Import successful: {updated_count} servers updated. {ignored_count} servers ignored."
                yield f"data: {json.dumps({'success': success_msg})}\n\n"

                if errors:
                    warning_msg = f"{len(errors)} warnings detected."
                    yield f"data: {json.dumps({'warning': warning_msg, 'detailed_errors': errors[:50]})}\n\n"

            response = StreamingHttpResponse(process_import(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache'
            return response

        error_msg = "Form validation failed or file is incorrect."
        return JsonResponse({'error': error_msg}, status=400)

    elif request.method == 'GET':
        form = CsvUploadForm()
        return render(request, f"{app_name}/bulk_import.html", {'form': form})

    return JsonResponse({'error': 'Invalid request method'}, status=405)
    

# View to handle bulk update of servers and providing progress updates
def servers_bulk_update(request):
    if request.method == "POST":
        try:
            # Retrieve the filters from the POST data
            query_param = request.POST.get('query')

            # Check if the query_param exists
            if not query_param:
                return JsonResponse({'status': 'error', 'message': 'Query string not provided'}, status=400)

            # Decode and parse the query string
            query_param = unquote(query_param)
            parsed_query = parse_qs(query_param)

            # Get the user's profile
            profile = UserProfile.objects.get(user=request.user)

            # Read and save the field_labels.json information
            json_path = os.path.join(os.path.dirname(__file__), 'field_labels.json')
            with open(json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)

            # Get the permanent filter choice from the POST data
            permanent_filter_selection = request.POST.get("permanentfilter_choice")

            # Define servers_to_bulkedit to first get all objects
            servers_to_bulkedit = Server.objects.all().order_by('SERVER_ID')

            # Call create_permanent_filter_query to create the query associated to the permanent filter parameters
            permanent_filter_query, permanent_filter_names, permanent_filter_attributes = create_permanent_filter_query(json_data, permanent_filter_selection)
            if permanent_filter_query:
                servers_to_bulkedit = servers_to_bulkedit.filter(permanent_filter_query)

            # Initialize the filters dictionary
            filters = {}

            # Create the filter using the parameter passed in the URL with request.GET.get
            # Iterate over the fields section to search for potential matches and construct the filters dictionary
            for field_key, field_info in json_data['fields'].items():
                if 'inputname' in field_info:
                    filters[field_key] = parsed_query.get(field_info['inputname'], [''])[0].split(',')

            # Remove all [''] added during the filters creation
            filters = {k: v for k, v in filters.items() if v != ['']}

            # Build the query based on the filters values extracted earlier
            for key, value in filters.items():
                if isinstance(value, list):
                    terms = value
                else:
                    terms = [value]
                query = construct_query(key, terms)
                servers_to_bulkedit = servers_to_bulkedit.filter(query)

            # Retrieve the servers to update: get the unique server hostnames on the objects filtered with filters
            total_updates = servers_to_bulkedit.count()

            if total_updates == 0:
                return JsonResponse({'status': 'warning', 'message': 'No servers to update with the given filters'}, status=200)

            # Collect input data for updates and convert to uppercase if needed
            bulk_type = request.POST.get('bulk_type', '')
            bulk_custom_type = request.POST.get('bulk_custom_type', '')
            bulk_servicenow = request.POST.get('bulk_servicenow', '')
            bulk_notes = request.POST.get('bulk_notes', '')
            if bulk_type == "CUSTOM":
                bulk_type = bulk_custom_type

            # Function to handle the bulk update of server records in a way that provides progress updates
            def update_with_progress():
                batch_size = 50
                total_batches = (total_updates + batch_size - 1) // batch_size

                # Iterate over each batch
                for i in range(total_batches):
                    batch_start = i * batch_size
                    batch_end = min((i + 1) * batch_size, total_updates)
                    batch = servers_to_bulkedit[batch_start:batch_end]

                    # Get the corresponding ServerAnnotation instances
                    annotations = []
                    for server in batch:
                        annotation, created = ServerAnnotation.objects.get_or_create(SERVER_ID=server.SERVER_ID)
                        annotations.append(annotation)

                    # Update the annotations
                    for annotation in annotations:
                        # Add entry to history
                        annotation.add_entry(bulk_notes, request.user, bulk_type, bulk_servicenow)
                        annotation.notes = bulk_notes
                        annotation.type = bulk_type
                        annotation.servicenow = bulk_servicenow

                    # Perform a bulk update on the current batch of records
                    ServerAnnotation.objects.bulk_update(annotations, ['notes', 'type', 'servicenow', 'history'])

                    progress = ((i + 1) / total_batches) * 100
                    yield f"data: progress:{progress}|batch:{i + 1}\n\n"

            response = StreamingHttpResponse(update_with_progress(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache'
            return response

        except Exception as e:
            # Log unexpected errors and return a meaningful message
            return JsonResponse({'status': 'error', 'message': f"An unexpected error occurred: {e}"}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid Request Method'}, status=400)
    
