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

_field_labels_cache = None
_field_labels_file_mtime = 0  # Timestamp de dernière modification du fichier
_cache_lock = Lock()


def get_field_labels():
    """
    Cache field_labels.json avec invalidation automatique quand le fichier change.
    Thread-safe pour Gunicorn.
    """
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
            
            print(f"[get_field_labels] Reloaded field_labels.json (mtime: {current_file_mtime})")
            
        except (OSError, json.JSONDecodeError) as e:
            print(f"[get_field_labels] Error loading field_labels.json: {e}")
            return _field_labels_cache
    
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
    localhostname = socket.gethostname()    

    try:
        profile = UserProfile.objects.get(user=request.user)
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    # Read and save the field_labels.json information
    json_data = get_field_labels()
     
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

    all_servers = ServerDiscrepancy.objects.all().order_by('SERVER_ID')
        
    combined_filter_query = Q()
    for key, values in filters.items():
        if not values:
            continue

        # Build the query for this field
        query = construct_query(key, values)
        combined_filter_query &= query  # Combine with AND

    if combined_filter_query:
        all_servers = all_servers.filter(combined_filter_query)
    
    # Get filtered servers
    filtered_servers = all_servers.order_by('SERVER_ID', 'APP_NAME_VALUE')
       
    # Define some pagination settings that will be passed as context
    page_size = int(request.GET.get('page_size', 50))
    page_number = request.GET.get("page")
   
    # Json part - Reading of field_labels.json to set element dynamically
    
    # Read and store the sections categories and fields of field_labels.json
    json_data_categories=json_data.get("categories", {})
    json_data_fields=json_data.get("fields", {})
    validation_errors = json_data.get('validation_errors', {})

    # Generation of the information loaded form field_labels.json to create the search boxes, the dropdown lists and populate their content
    finalfields = [(field, info) for field, info in json_data_fields.items()]  # Read all items in the json fields section
    
    table_fields=[]
    # Loop in the fields items: if some have the attribute listbox, generate the content to display it the associated drop down list in the view

    cacheset=False
    for key, val in finalfields:
        listbox_value=val.get("listbox", '')
        listempty_value=val.get("listempty", '') 
        if listbox_value:
            cache_key = f"listbox_{key}"
            listbox_evaluated = cache.get(cache_key)
            if listbox_evaluated is None:
                if listempty_value =="True":
                    listbox_evaluated = ['MISSING']
                else:
                    listbox_evaluated = ServerDiscrepancy.objects.values_list(key, flat=True).distinct().order_by(key)

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
        if cat in grouped
    ]
  
    profile = UserProfile.objects.get(user=request.user)
    #last_status = ImportStatus.objects.order_by('-date_import').first()
    visible_columns = request.GET.get("visible_columns")
    
    # Processing according to display mode
    display_servers = []
    
    # Get model fields (exclude technical fields)
    model_fields = []
    excluded_fields = {field_name for field_name in json_data['fields'].keys() 
        if field_name.endswith('_inconsistent')}

    for field_name, field_info in json_data['fields'].items():     
        if field_name not in excluded_fields:
            model_fields.append({
                'name': field_name,
                'verbose_name': field_info.get('displayname', field_name.replace('_', ' ').title()),
                'is_hostname': field_name == 'SERVER_ID'
            })

    
    paginator = Paginator(filtered_servers, page_size)
    page_obj_raw = paginator.get_page(request.GET.get('page'))

    # Convert only the current page to list
    current_page_servers = list(page_obj_raw)

    # Process servers from current page
    for server in current_page_servers:
        display_servers.append({
            'hostname': server.SERVER_ID,
            'primary_server': server
        })
    
    page_obj = create_page_wrapper(display_servers, page_obj_raw)
    total_servers_stat = paginator.count

    # Rendering servers.html with the corresponding context

    context = {
        'page_obj' : page_obj,  # Pagination object
        'table_fields' : table_fields,  # Information for the dynamic creation of table columns, input boxes and list boxes
        'category_fields' : category_fields,  # Information for the dynamic creation of the catgeory tree
        'appname' : app_name,  # Application name
        'page_size' : page_size,  # Number of objects per page
        'current_filters': filters,  # Filters defined above
        'json_data' : json.dumps(json_data),  # Json content
        'loggedonuser' : request.user,  # Logon name
        'model_fields': model_fields,
        'total_servers': total_servers_stat,
        'cacheset': cacheset,
        'localhostname': localhostname, 
        'validation_errors': validation_errors,
    }   

    return render(request, f'{app_name}/servers.html', context)



def dashboard_view(request):
    #  Main dashboard view displaying data quality metrics.
    
    # Load dashboard configuration from JSON
    #config_path = os.path.join(settings.BASE_DIR, 'config', 'discrepancies_dashboard.json')
    config_path = os.path.join(os.path.dirname(__file__), 'discrepancies_dashboard.json' )
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
    

