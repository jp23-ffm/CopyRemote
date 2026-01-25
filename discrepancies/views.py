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

from collections import defaultdict
from urllib.parse import urlencode, parse_qs, unquote
from functools import lru_cache
from threading import Lock

from .models import AnalysisSnapshot, ServerDiscrepancy
from .utils import get_trend_data
from userapp.models import UserProfile, SavedSearch, SavedOptions, UserPermissions


app_name=__package__.split('.')[-1]

def get_field_labels():
    """
    Cache avec expiration de 10 minutes
    Thread-safe pour Gunicorn
    """
    global _field_labels_cache, _field_labels_timestamp
    
    _field_labels_cache = None
    _field_labels_timestamp = 0
    _cache_lock = Lock()
    CACHE_TTL = 600  # 10 minutes    
    
    current_time = time.time()
    
    # Vérifier si le cache est encore valide
    if _field_labels_cache is not None and (current_time - _field_labels_timestamp) < CACHE_TTL:
        return _field_labels_cache
    
    # Cache expiré ou inexistant → recharger
    with _cache_lock:
        # Double-check après avoir acquis le lock
        if _field_labels_cache is not None and (current_time - _field_labels_timestamp) < CACHE_TTL:
            return _field_labels_cache
        
        # Charger le fichier
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
        ServerDiscrepancy.objects.values_list(field_name, flat=True)
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
    all_servers = ServerDiscrepancy.objects.all().order_by('SERVER_ID')
    
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
                    listbox_evaluated = ServerDiscrepancy.objects.values_list(key, flat=True).distinct().order_by(key)
                else:  # A listbox must be displayed: list the unique values
                    listbox_evaluated = ServerDiscrepancy.objects.values_list(key, flat=True).distinct().order_by(key)
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
    #last_status = ImportStatus.objects.order_by('-date_import').first()
    visible_columns = request.GET.get("visible_columns")
    
    print(f"[TIMING] End of pre-rendering: {time.time() - start1_time:.3f}s")
    
    ###############################################

    # Processing according to display mode
    display_servers = []
        
    start_time = time.time()
    print(f"[TIMING] View start")

    # Display mode parameters
    flat_view = False
    if 'view' in request.GET:  # ?view=flat&... 
        if request.GET['view'].lower() == 'flat':
            flat_view = True
       
    print(f"[TIMING] Parameters retrieved: {time.time() - start_time:.3f}s")
    filter_start = time.time()
    
    # Get filtered servers
    #filtered_servers = filtered_servers.order_by('SERVER_ID', 'APP_NAME_VALUE')
    
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
    
    if (flat_view): # Flat view
    
        print(f"[TIMING] Flat mode selected")
        processing_start = time.time()
        
        # FLAT MODE - Direct server pagination
        pagination_start = time.time()
        
        paginator = Paginator(filtered_servers, page_size)
        page_obj_raw = paginator.get_page(request.GET.get('page'))
        
        print(f"[TIMING] Server pagination created: {time.time() - pagination_start:.3f}s")
        
        # Convert only the current page to list
        conversion_start = time.time()
        current_page_servers = list(page_obj_raw)
        print(f"[TIMING] Current page conversion ({len(current_page_servers)} elements): {time.time() - conversion_start:.3f}s")
        
        if edit_mode:
            # Get annotations only for current page
            annotations_start = time.time()
            annotations_dict = {}
            hostnames_in_page = [server.SERVER_ID for server in current_page_servers]
            if hostnames_in_page:
                annotations = ServerAnnotation.objects.filter(SERVER_ID__in=hostnames_in_page)
                annotations_dict = {ann.SERVER_ID: ann for ann in annotations}
            print(f"[TIMING] Annotations for current page ({len(annotations_dict)} annotations): {time.time() - annotations_start:.3f}s")

        # Process servers from current page
        transform_start = time.time()
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
        print(f"[TIMING] Data transformation for flat mode: {time.time() - transform_start:.3f}s")
        
        page_obj = create_page_wrapper(display_servers, page_obj_raw)
        
        print(f"[TIMING] Flat mode processed: {time.time() - processing_start:.3f}s")
        
        # Statistics for flat mode
        total_servers_stat = paginator.count
        total_instances_stat = total_servers_stat        
    
    
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
    
    ###############################################
    

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
        'flat_view': flat_view,
        'edit_mode': edit_mode,
        'cacheset': cacheset,
        'localhostname': localhostname,
        'visible_columns': visible_columns
    }   

    return render(request, f'{app_name}/servers.html', context)



def dashboard_view(request):
    """
    Main dashboard view displaying data quality metrics.
    Renders gauges for overall quality and per-field issues.
    """
    
    # Load dashboard configuration from JSON
    #config_path = os.path.join(settings.BASE_DIR, 'config', 'discrepancies_dashboard.json')
    config_path = "C:\\Temp\\Django\\chimera\\discrepancies\\discrepancies_dashboard.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # Get the latest analysis snapshot
    try:
        latest_snapshot = AnalysisSnapshot.objects.latest('analysis_date')
    except AnalysisSnapshot.DoesNotExist:
        # No analysis has been run yet
        context = {
            'no_data': True,
            'message': 'No analysis has been run yet. Please run the discrepancy analysis first.'
        }
        return render(request, 'discrepancies/dashboard.html', context)
    
    # Prepare widget data
    widgets_data = []
    
    for widget in config['dashboard']['widgets']:
        widget_data = {
            'id': widget['id'],
            'type': widget['type'],
            'size': widget.get('size', 'small'),
            'title': widget['title'],
            'icon': widget.get('icon', ''),
            'link': widget.get('link', '#'),
        }
        
        # Retrieve metric value from snapshot
        metric_name = widget['metric']
        metric_value = getattr(latest_snapshot, metric_name, 0)
        
        if widget['type'] == 'gauge':
            if widget['size'] == 'large':
                # Large gauge: displays percentage directly
                widget_data['value'] = metric_value
                widget_data['display_value'] = f"{metric_value}%"
            else:
                # Small gauge: calculate percentage of servers OK for this field
                # metric_value = number of servers with issues in this field
                total = latest_snapshot.total_servers_analyzed
                servers_ok = total - metric_value
                percentage_ok = round((servers_ok / total) * 100, 1) if total > 0 else 100
                
                widget_data['value'] = percentage_ok
                widget_data['count'] = metric_value
                widget_data['display_value'] = f"{percentage_ok}%"
                widget_data['detail'] = f"{metric_value} issues"
            
            # Thresholds and colors for gauge coloring
            widget_data['thresholds'] = widget.get('thresholds', {
                'critical': 80,
                'warning': 95,
                'good': 100
            })
            widget_data['colors'] = widget.get('colors', {
                'critical': '#dc3545',
                'warning': '#ffc107',
                'good': '#28a744'
            })
        
        widgets_data.append(widget_data)
    
    # Prepare historical trend data (default metric)
    historic_config = config['dashboard'].get('historic_section', {})
    
    if historic_config.get('enabled', False):
        default_metric = historic_config.get('default_metric', 'servers_with_issues')
        days = historic_config.get('days', 30)
        trend_data = get_trend_data(default_metric, days)
    else:
        historic_config = None
        trend_data = None
    
    context = {
        'title': config['dashboard']['title'],
        'widgets': widgets_data,
        'snapshot': latest_snapshot,
        'no_data': False,
        'historic_config': historic_config,
        'trend_data': trend_data,
    }
    
    return render(request, 'discrepancies/dashboard.html', context)


def trend_api_view(request):
    """
    API endpoint for retrieving trend data for a specific metric.
    Called via AJAX when user changes the metric selector.
    
    Query params:
        - metric: Field name from AnalysisSnapshot
        - days: Number of days to look back (default: 30)
    
    Returns:
        JSON with dates (labels) and values
    """
    
    metric = request.GET.get('metric', 'servers_with_issues')
    days = int(request.GET.get('days', 30))
    
    data = get_trend_data(metric, days)
    
    return JsonResponse({
        'labels': data['dates'],
        'values': data['values'],
        'metric': metric
    })
