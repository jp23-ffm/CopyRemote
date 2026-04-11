import csv
import datetime
import django
import io
import json
import os
import time
import threading
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import Q, F, Case, When
from django.db.models.functions import Upper
from django.http import FileResponse, JsonResponse, HttpResponse, HttpResponseRedirect, StreamingHttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from common.views import generate_charts
from userapp.models import UserProfile, SavedSearch, SavedOptions, UserPermissions, SavedChart
from .exports import generate_csv, generate_excel, EXPORT_DIR
from .forms import BusinessContinuityInformationForm, CsvUploadForm
from .models import ServerUnique, Server, ImportStatus

from collections import defaultdict
from urllib.parse import urlencode, parse_qs, unquote


app_name=__package__.split('.')[-1]


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


# View to display the server information - Main View
@login_required
def server_view(request):

    # Get the user's profile if it already exists in the table userapp_userprofile
    try:
        profile = UserProfile.objects.get(user=request.user)
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    # Read and save the field_labels.json information
    json_path=os.path.join(os.path.dirname(__file__), 'field_labels.json')
    with open(json_path, "r", encoding="utf-8") as f:
        json_data=json.load(f)

    # Read the permanentfilters section from field_labels.json and the last permanent filter chosen by the user for this view
    json_data_permanentfilters=json_data.get("permanentfilters", {})
    try:
        user_options = SavedOptions.objects.get(user_profile=profile)
        permanent_filter_selection = user_options.businesscontinuity_permanentfilter
    except SavedOptions.DoesNotExist:
        permanent_filter_selection = "All Servers"

    # If the last permanent filter entry doesn't match with any filter defined in field_labels.json, switch back to "All Servers"
    if permanent_filter_selection != "All Servers":
        if permanent_filter_selection not in json_data_permanentfilters:
            permanent_filter_selection = "All Servers"

    # Call create_permanent_filter_query to create the query associated to the permanent filter parameters
    permanent_filter_query, permanent_filter_names, permanent_filter_attributes = create_permanent_filter_query(json_data, permanent_filter_selection)

    # Initialize the filters dictionary
    filters = {}

    # Create the filter using the parameter passed in the URL with request.GET.get
    # Iterate over the fields section to search for potential matches and construct the filters dictionary
    for field_key, field_info in json_data['fields'].items():
        # Retrieve the input name for the current field
        input_name = field_info.get('inputname')
        if input_name:
            # Check if the field has the model_extra parameter
            if field_info.get('model_extra') == 'yes':
                # model_extra is 'yes': modify the field_key to include the 'server_unique__' prefix, to access the values of the businesscontinuity_serverunique table
                field_key = f'server_unique__{field_key}'
            # Retrieve the filter value from the request's GET parameters, if any, and split the value by commas to handle multiple filter values
            # Example: businesscontinuity/?server=EURV%2CMAD&visible_columns... -> filters['server']=['EURV','MAD']
            filters[field_key] = request.GET.get(input_name, '').split(',')

    # Create a variable containing all servers with their server_unique related values
    all_servers = Server.objects.all().select_related('server_unique').order_by('SERVER_ID')

    # if a permanent filter has been defined earlier, apply it
    if permanent_filter_query:
        all_servers = all_servers.filter(permanent_filter_query)

    # Remove all [''] added during the filters creation
    filters = { k: v for k, v in filters.items() if v != [''] }

    # Build the query based on the filters values extracted earlier
    for key, value in filters.items():  # Loop in every filters item
        if isinstance(value, list):
            terms = value
        else:
            terms = [value]
        # Call the construct_query to get a filter
        query = construct_query(key, terms)
        # Filter the servers with this query
        all_servers = all_servers.filter(query)

    servers_for_template = []

    # Define some pagination settings that will be passed as context
    page_size = int(request.GET.get('page_size', 50))
    paginator = Paginator(all_servers, page_size)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)


    # Recreate the page content and pass it with extended server_unique information as context
    # By default, server_unique information are not displayed. The servers of the page passed in the context are here extended with these values
    for server in page_obj:  # Loop for all servers in the page
        server_unique = server.server_unique

        current_server_data = {  # Recreate an extended server object
            'SERVER_ID' : server.SERVER_ID,
            'ITCONTINUITY_LEVEL' : server.ITCONTINUITY_LEVEL,
            'DAP_NAME' : server.DAP_NAME,
            'DAP_AUID' : server.DAP_AUID,
            'DATACENTER' : server.DATACENTER,
            'TECH_FAMILY' : server.TECH_FAMILY,
            'MACHINE_TYPE' : server.MACHINE_TYPE,
            'VM_TYPE' : server.VM_TYPE,
            'AFFINITY' : server.AFFINITY,
            'VITAL_LEVEL' : server.VITAL_LEVEL,
            'DATABASE_TECHNO' : server.DATABASE_TECHNO,
            'DATABASE_DB_CI' : server.DATABASE_DB_CI,
            'SUPPORT_GROUP' : server.SUPPORT_GROUP,
            'APPLICATION_SUPPORT_GROUP' : server.APPLICATION_SUPPORT_GROUP,
            'IT_CLUSTER' : server.IT_CLUSTER,
            'hostname_unique': server_unique.hostname,
            'priority_asset': server_unique.priority_asset if server_unique.priority_asset else "EMPTY",
            'in_live_play': server_unique.in_live_play if server_unique.in_live_play else "EMPTY",
            'action_during_lp': server_unique.action_during_lp if server_unique.action_during_lp else "EMPTY",
            'action_during_lp_history': server_unique.action_during_lp_history if server_unique.action_during_lp_history else "EMPTY",
            'original_action_during_lp': server_unique.original_action_during_lp if server_unique.original_action_during_lp else "EMPTY",
            'original_action_during_lp_history': server_unique.original_action_during_lp_history if server_unique.original_action_during_lp_history else "EMPTY",
            'cluster': server_unique.cluster if server_unique.cluster else "EMPTY",
            'cluster_type': server_unique.cluster_type if server_unique.cluster_type else "EMPTY",
        }

        # Add the new object to  servers_for_template
        servers_for_template.append(current_server_data)

    # Json part - Reading of field_labels.json to set element dynamically

    # Read and store the sections categories and fields of field_labels.json
    json_data_categories=json_data.get("categories", {})
    json_data_fields=json_data.get("fields", {})

    # Generation of the information loaded form field_labels.json to create the search boxes, the dropdown lists and populate their content
    finalfields = [(field, info) for field, info in json_data_fields.items()]  # Read all items in the json fields section

    table_fields=[]
    # Loop in the fields items: if some have the attribute listbox, generate the content to display it the associated drop down list in the view
    for key, val in finalfields:
        listbox_value=val.get("listbox", '')
        if listbox_value:
            if permanent_filter_attributes is not None and key in permanent_filter_attributes:  # A permanent filter is defined for this entry: display its attributes
                listbox_evaluated = permanent_filter_attributes[key]
            elif "model_extra" in val and val["model_extra"] == "yes":  # A listbox for a server_unique attribute must be displayed: list the unique values
                listbox_evaluated = Server.objects.values_list(f'server_unique__{key}', flat=True).distinct().order_by(f'server_unique__{key}')
            else:  # A listbox must be displayed: list the unique values
                listbox_evaluated = Server.objects.values_list(key, flat=True).distinct().order_by(key)

            if listbox_evaluated:  # Sort the entry to put "EMPTY" at the end
                listbox_evaluated = list(listbox_evaluated)
                if any(x is None or x.upper() == "EMPTY" for x in listbox_evaluated):
                    has_na = any(isinstance(x, str) and x.upper() == "EMPTY" for x in listbox_evaluated)  # "EMPTY" in listbox_evaluated
                    listbox_evaluated = [
                        x for x in listbox_evaluated if x is not None and x != "" and x.upper() != "EMPTY"
                    ]

                    listbox_evaluated.sort()
                    if has_na:
                        listbox_evaluated.append("EMPTY")
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

    saved_searches = profile.savedsearch_set.filter(view=app_name)
    last_status = ImportStatus.objects.order_by('-date_import').first()
    bc_liveplay_form = BusinessContinuityInformationForm()

    try:
        user_permissions = UserPermissions.objects.get(user_profile=profile)
        is_user_editor = user_permissions.businesscontinuity_allowedit
    except UserPermissions.DoesNotExist:
        is_user_editor = False

    unique_servers_count = all_servers.values('SERVER_ID').distinct().count()

    # Rendering servers.html with the corresponding context

    context = {
        'servers' : servers_for_template,  # Servers with extended information of the server_unique table
        'unique_servers_count' : unique_servers_count,
        'page_obj' : page_obj,  # Pagination object
        'bc_liveplay_form' : bc_liveplay_form,  # Form used fo the Edit window
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
        'is_user_editor' : True, #is_user_editor, # The user is allowed to edit
        'permanent_filter_selection' : permanent_filter_selection  # Permanent filter name
    }

    return render(request, f'{app_name}/servers.html', context)


@login_required
def chart_view(request):
    json_path = os.path.join(os.path.dirname(__file__), 'field_labels.json')
    with open(json_path, 'r', encoding="utf-8") as f:
        json_data = json.load(f)

    selected_fields = request.GET.getlist('fields')
    chart_types = request.GET.getlist('types')
    permanent_filter_selection = request.GET.get('permanentfilter')

    requestfilters = {}
    for key, value in request.GET.items():
        requestfilters[key] = value

    servers = get_filtered_servers(requestfilters, permanent_filter_selection)

    alias_map = {
        'priority_asset': 'server_unique__priority_asset',
        'in_live_play': 'server_unique__in_live_play',
        'action_during_lp': 'server_unique__action_during_lp',
        'original_action_during_lp': 'server_unique__original_action_during_lp',
        'cluster': 'server_unique__cluster',
        'cluster_type': 'server_unique__cluster_type'
    }

    real_fields = [alias_map.get(alias, alias) for alias in selected_fields]
    fields_to_keep = ['SERVER_ID'] + real_fields
    server_data = list(servers.values(*fields_to_keep).distinct())

    # Pre-calculate the fields total here
    field_totals = {}
    for field in selected_fields:
        alias_map = {
            'priority_asset': 'server_unique__priority_asset',
            'in_live_play': 'server_unique__in_live_play',
            'action_during_lp': 'server_unique__action_during_lp',
            'original_action_during_lp': 'server_unique__original_action_during_lp',
            'cluster': 'server_unique__cluster',
            'cluster_type': 'server_unique__cluster_type',
        }
        data_field = alias_map.get(field, field)

        # Count the unique combos (SERVER_ID, valeur)
        unique_combos = set()
        for server in server_data:
            server_id = server.get('SERVER_ID')
            value = server.get(data_field, 'Unknown')
            if value is None or value == '':
                value = 'Unknown'
            unique_combos.add((server_id, str(value)))

        field_totals[field] = len(unique_combos)

    return generate_charts(request, server_data, json_data, selected_fields, chart_types, field_totals)


# View to edit server information
def edit_server_info(request, server_unique_id):

    server_unique = get_object_or_404(ServerUnique, hostname=server_unique_id)  # Get the server_unique_id passed in the URL edit/<str:server_unique_id>/
    referrer = request.POST.get('referrer')  # Get the URL referrer, before the ?
    query = request.POST.get('query')  # Get the URL query, after the ?
    loggedonuser = request.POST.get('loggedonuser')  # Retreve the user logged on for historic logging

    if request.method == 'POST':

        # Display the Edit form with the needed paramters
        form = BusinessContinuityInformationForm(request.POST, instance=server_unique, loggedonuser=loggedonuser)
        if form.is_valid():
            form.save()
            # Save and go back to the original URL
            return HttpResponseRedirect(f"{referrer}?{query}")
        else:
            # Go back to the original URL without saving
            return HttpResponseRedirect(f"{referrer}?{query}")

    return HttpResponseRedirect(f"{referrer}?{query}")


# View to handle bulk update of servers and providing progress updates
def servers_bulk_update(request):

    if request.method == "POST":
        try:
            query_param = request.POST.get('query')  # Extract the query parameter from the request data

            # Check if the query_param exists
            if not query_param:
                return JsonResponse({'status': 'error', 'message': 'Query string not provided'}, status=400)

            # Decode and parse the query string
            query_param = unquote(query_param)  # Convert percent-encoded characters to human readable ones. Example: 1%2C -> ,
            parsed_query = parse_qs(query_param)  # Convert query_param to a dictionary mapping each key to a list of values

            # Build a filters dictionary by extracting and processing the specific query parameters from parsed_query
            filters = {
                'SERVER_ID': parsed_query.get('server', [''])[0].split(','),
                'ITCONTINUITY_LEVEL': parsed_query.get('itcontinuitylvl', [''])[0].split(','),
                'DAP_NAME': parsed_query.get('dapname', [''])[0].split(','),
                'DAP_AUID': parsed_query.get('dapauid', [''])[0].split(','),
                'DATACENTER': parsed_query.get('datacenter', [''])[0].split(','),
                'TECH_FAMILY': parsed_query.get('techfamily', [''])[0].split(','),
                'MACHINE_TYPE': parsed_query.get('machinetype', [''])[0].split(','),
                'VM_TYPE': parsed_query.get('vmtype', [''])[0].split(','),
                'AFFINITY': parsed_query.get('affinity', [''])[0].split(','),
                'VITAL_LEVEL': parsed_query.get('vitallevel', [''])[0].split(','),
                'DATABASE_TECHNO': parsed_query.get('dbtechno', [''])[0].split(','),
                'DATABASE_DB_CI': parsed_query.get('dbci', [''])[0].split(','),
                'SUPPORT_GROUP': parsed_query.get('supportgroup', [''])[0].split(','),
                'APPLICATION_SUPPORT_GROUP': parsed_query.get('appsupportgroup', [''])[0].split(','),
                'IT_CLUSTER': parsed_query.get('itcluster', [''])[0].split(','),
                'server_unique__priority_asset': parsed_query.get('priorityasset', [''])[0].split(','),
                'server_unique__in_live_play': parsed_query.get('inliveplay', [''])[0].split(','),
                'server_unique__action_during_lp': parsed_query.get('actionduringlp', [''])[0].split(','),
                'server_unique__original_action_during_lp': parsed_query.get('originalactionduringlp', [''])[0].split(','),
                'server_unique__cluster': parsed_query.get('cluster', [''])[0].split(','),
                'server_unique__cluster_type': parsed_query.get('clustertype', [''])[0].split(','),
            }

            try:
                profile = UserProfile.objects.get(user=request.user)
            except UserProfile.DoesNotExist:
                profile = UserProfile.objects.create(user=request.user)

            # Read and save the field_labels.json information
            json_path=os.path.join(os.path.dirname(__file__), 'field_labels.json')
            with open(json_path, "r", encoding="utf-8") as f:
                json_data=json.load(f)

            # Read the permanentfilters section from field_labels.json and the last permanent filter chosen by the user for this view
            json_data_permanentfilters=json_data.get("permanentfilters", {})
            try:
                user_options = SavedOptions.objects.get(user_profile=profile)
                permanent_filter_selection = user_options.businesscontinuity_permanentfilter
            except SavedOptions.DoesNotExist:
                permanent_filter_selection = "All Servers"

            # If the last permanent filter entry doesn't match with any filter defined in field_labels.json, switch back to "All Servers"
            if permanent_filter_selection != "All Servers":
                if permanent_filter_selection not in json_data_permanentfilters:
                    permanent_filter_selection = "All Servers"

            # Define servers_to_bulkedit to first get all objects
            servers_to_bulkedit = Server.objects.all().select_related('server_unique').order_by('SERVER_ID')

            # Call create_permanent_filter_query to create the query associated to the permanent filter parameters
            permanent_filter_query, permanent_filter_names, permanent_filter_attributes = create_permanent_filter_query(json_data, permanent_filter_selection)
            if permanent_filter_query:
                servers_to_bulkedit = servers_to_bulkedit.filter(permanent_filter_query)

            # Remove all [''] added during the filters creation
            filters = { k: v for k, v in filters.items() if v != [''] }

            # Build the query based on the filters values extracted earlier
            for key, value in filters.items():
                if isinstance(value, list):
                    terms = value
                else:
                    terms = [value]
                # Call the construct_query to get a filter
                query = construct_query(key, terms)
                # Filter the servers with this query
                servers_to_bulkedit = servers_to_bulkedit.filter(query)


            # Collect input data for updates and convert to uppercase if needed
            priority_asset = request.POST.get('priority_asset', '')
            priority_asset = priority_asset.upper() if priority_asset else "EMPTY"
            in_live_play = request.POST.get('in_live_play', '')
            in_live_play = in_live_play.upper() if in_live_play else "EMPTY"
            action_during_lp = request.POST.get('action_during_lp', '')
            original_action_during_lp = request.POST.get('original_action_during_lp', '')
            cluster = request.POST.get('cluster', '')
            cluster = cluster.upper() if cluster else "EMPTY"
            cluster_type = request.POST.get('cluster_type', '')

            # Prepare for update records
            now_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            now_usr = request.user.username
            now_str = f"[{now_date} - {now_usr}]"

            # Retrieve the servers to update: get the unique server hostnames on the objects filtered with filters
            updates = list(ServerUnique.objects.filter(hostname__in=servers_to_bulkedit.values_list('SERVER_ID', flat=True).distinct()))
            total_updates = len(updates)

            if total_updates == 0:
                return JsonResponse({'status': 'warning', 'message': 'No servers to update with the given filters'}, status=200)

            # Function to handle the bulk update of server records in a way that provides progress updates
            def update_with_progress():
                batch_size = 50  # Define the batch size for updating records
                total_batches = (total_updates + batch_size - 1) // batch_size  # Calculate the total number of batches required to update all records

                # Iterate over each batch
                for i in range(total_batches):
                    batch_start = i * batch_size  # Calculate the starting index of the current batch
                    batch_end = min((i + 1) * batch_size, total_updates)  # Calculate the ending index of the current batch, ensuring it does not exceed total_updates
                    batch = updates[batch_start:batch_end]  # Get the current batch of records to update

                    # Perform the updates within a transaction to ensure atomicity
                    with transaction.atomic():
                        for obj in batch:
                            if priority_asset != '-':
                                obj.priority_asset = priority_asset

                            if in_live_play != '-':
                                obj.in_live_play = in_live_play

                            if action_during_lp:
                                obj.action_during_lp = action_during_lp
                                if action_during_lp != "EMPTY":
                                    obj.action_during_lp_history = f"{now_str} {action_during_lp}\n" + (
                                        obj.action_during_lp_history if obj.action_during_lp_history else '')

                            if original_action_during_lp:
                                obj.original_action_during_lp = original_action_during_lp
                                if original_action_during_lp != "EMPTY":
                                    obj.original_action_during_lp_history = f"{now_str} {original_action_during_lp}\n" + (
                                        obj.original_action_during_lp_history if obj.original_action_during_lp_history else '')

                            if cluster != '-':
                                obj.cluster = cluster

                            if cluster_type:
                                obj.cluster_type = cluster_type

                        # Perform a bulk update on the current batch of records
                        ServerUnique.objects.bulk_update(batch, ['priority_asset', 'in_live_play', 'action_during_lp', 'action_during_lp_history',
                            'original_action_during_lp', 'original_action_during_lp_history', 'cluster', 'cluster_type'])


                    progress = ((i + 1) / total_batches) * 100
                    # Yield a progress update message understandable by the js function startBulkUpdate
                    yield f"data: progress:{progress}|batch:{i + 1}\n\n"

            # Send back the progress
            response = StreamingHttpResponse(update_with_progress(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response

        except Exception as e:
            # Log unexpected errors and return a meaningful message
            return JsonResponse({'status': 'error', 'message': f"An unexpected error occurred: {e}"}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid Request Method'}, status=400)


# Handles the bulk import of server data from a CSV file
def _import_applications_csv(request, csv_file):
    """Application import: resolves servers from DAP_NAME and sets in_live_play. YES wins over NO."""

    decoded_file = csv_file.read().decode('utf-8').splitlines()
    reader = csv.DictReader(decoded_file, delimiter=';')

    expected_headers = ['application_id', 'in_live_play']
    if reader.fieldnames != expected_headers:
        errors = [
            f"Header incorrect. Expected: {', '.join(expected_headers)}. "
            f"Got: {', '.join(reader.fieldnames or [])}"
        ]
        return JsonResponse({'error': 'Header incorrect.', 'detailed_errors': errors}, status=400)

    errors = []
    for idx, line in enumerate(decoded_file[1:], start=2):
        if not line.strip():
            continue
        if line.count(';') + 1 != 2:
            errors.append(f"Line {idx}: incorrect column count (found {line.count(';') + 1}, expected 2).")
    if errors:
        return JsonResponse({'error': f"{len(errors)} errors detected.", 'detailed_errors': errors[:50]}, status=400)

    now_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_usr = request.user.username
    total_rows = len(decoded_file) - 1

    def process_import():
        yield f"data: {json.dumps({'progress': 5, 'message': 'Parsing CSV...'})}\n\n"

        app_lp_map = {}  # app_id (uppercased) → 'YES' | 'NO'
        parse_errors = []

        for i, row in enumerate(reader):
            app_id = (row.get('application_id') or '').strip().upper()
            in_live_play = (row.get('in_live_play') or '').strip().upper()

            if not app_id:
                parse_errors.append(f"Line {i + 2}: 'application_id' is empty, line ignored.")
                continue
            if in_live_play not in ('YES', 'NO'):
                parse_errors.append(
                    f"Line {i + 2}: invalid 'in_live_play' value '{in_live_play}' "
                    f"(expected YES or NO), line ignored."
                )
                continue

            # YES wins: once an app is set to YES, keep YES even if another row says NO
            if app_id not in app_lp_map or in_live_play == 'YES':
                app_lp_map[app_id] = in_live_play

        yield f"data: {json.dumps({'progress': 20, 'message': 'Resolving servers from applications...'})}\n\n"

        if not app_lp_map:
            yield f"data: {json.dumps({'error': 'No valid application entries found in CSV.'})}\n\n"
            if parse_errors:
                yield f"data: {json.dumps({'warning': f'{len(parse_errors)} warnings.', 'detailed_errors': parse_errors[:50]})}\n\n"
            return

        # Fetch all Server rows whose DAP_NAME matches one of our app IDs (case-insensitive)
        server_rows = (
            Server.objects
            .annotate(dap_upper=Upper('DAP_NAME'))
            .filter(dap_upper__in=app_lp_map.keys())
            .values('server_unique_id', 'dap_upper')
        )

        yield f"data: {json.dumps({'progress': 40, 'message': 'Computing Live Play values per server...'})}\n\n"

        # For each ServerUnique, collect values from all its matching apps — YES wins
        server_lp = {}  # server_unique_id → 'YES' | 'NO'
        apps_found = set()

        for entry in server_rows:
            su_id = entry['server_unique_id']
            dap = entry['dap_upper'] or ''
            apps_found.add(dap)
            value = app_lp_map.get(dap, '')
            if not value:
                continue
            if su_id not in server_lp or value == 'YES':
                server_lp[su_id] = value

        for app_id in app_lp_map:
            if app_id not in apps_found:
                parse_errors.append(f"Application '{app_id}': no server found with this DAP_NAME.")

        if not server_lp:
            yield f"data: {json.dumps({'error': 'No matching servers found for the provided application IDs.'})}\n\n"
            if parse_errors:
                yield f"data: {json.dumps({'warning': f'{len(parse_errors)} warnings.', 'detailed_errors': parse_errors[:50]})}\n\n"
            return

        yield f"data: {json.dumps({'progress': 50, 'message': f'Updating {len(server_lp)} servers...'})}\n\n"

        # Fetch ServerUnique instances, apply in_live_play
        server_unique_qs = {
            su.id: su
            for su in ServerUnique.objects.filter(id__in=server_lp.keys())
        }

        instances_to_update = []
        for su_id, new_lp in server_lp.items():
            su = server_unique_qs.get(su_id)
            if su is None:
                continue
            su.in_live_play = new_lp
            instances_to_update.append(su)

        # Bulk update in batches of 100 — progress 50% → 100%
        updated_count = 0
        total_updates = len(instances_to_update)
        for i in range(0, total_updates, 100):
            batch = instances_to_update[i:i + 100]
            ServerUnique.objects.bulk_update(batch, ['in_live_play'])
            updated_count += len(batch)
            progress = 50 + (updated_count / total_updates) * 50
            yield f"data: {json.dumps({'progress': progress, 'message': 'Saving...'})}\n\n"

        ignored_count = total_rows - len(app_lp_map)
        success_msg = (
            f"Application import successful: {len(app_lp_map)} applications processed, "
            f"{updated_count} servers updated, {ignored_count} rows ignored."
        )
        yield f"data: {json.dumps({'success': success_msg})}\n\n"

        if parse_errors:
            yield f"data: {json.dumps({'warning': f'{len(parse_errors)} warnings.', 'detailed_errors': parse_errors[:50]})}\n\n"

    response = StreamingHttpResponse(process_import(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@require_http_methods(["GET", "POST"])
def bulk_import_csv(request):

    if request.method == 'POST':  # Treat the data after the csv file has been selected

        form = CsvUploadForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES['csv_file']

            if not csv_file.name.endswith('.csv'):
                return JsonResponse({'error': "This file must be a CSV."}, status=400)

            import_type = request.POST.get('import_type', 'server')
            if import_type == 'application':
                return _import_applications_csv(request, csv_file)

            # Read the content of the csv
            decoded_file = csv_file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file, delimiter=';')

            expected_headers = [
                'hostname_unique', 'priority_asset', 'in_live_play', 'action_during_lp',
                'original_action_during_lp', 'cluster', 'cluster_type',
            ]

            # Check for header or formatting errors
            errors = []
            if reader.fieldnames != expected_headers:
                errors.append(
                    f"The Header is incorrect. Fields expected: {', '.join(expected_headers)}. "
                    f"Received: {', '.join(reader.fieldnames or [])}"
                )
                return JsonResponse({'error': 'Header incorrect.', 'detailed_errors': errors}, status=400)

            header_len = len(expected_headers)
            for idx, line in enumerate(decoded_file[1:], start=2):
                if not line.strip():  # Check if the line is empty
                    continue  # Skip to the next iteration if the line is empty

                if line.count(';') + 1 != header_len:
                    errors.append(
                        f"Line {idx}: number of columns is incorrect "
                        f"(Found: {line.count(';') + 1}, expected: {header_len})."
                    )

            # Returns an error formatted to be understood by the reader.onload event in bulk_import.html
            if errors:
                return JsonResponse({'error': f"{len(errors)} errors detected.", 'detailed_errors': errors[:50]}, status=400)

            updated_count = 0
            ignored_count = 0
            lines_processed = 0
            total_lines = len(decoded_file) - 1  # Exclude header
            errors = []
            instances_to_update = {}  # keyed by server_unique.id — prevents duplicate saves if hostname appears twice
            now_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            now_usr = request.user.username
            # Create a string with the time and the name of the current user to inject in the history fields
            now_str = f"[{now_date} - {now_usr}]"

            def process_import():
                nonlocal updated_count, ignored_count, lines_processed, total_lines, errors
                yield f"data: {json.dumps({'progress': 0, 'message': 'Reading CSV file...'})}\n\n"

                # Consume the reader into a list to allow two passes
                rows_data = list(reader)

                # Collect all non-empty hostnames (uppercased) for a single bulk DB query
                hostnames_upper = {
                    (row.get('hostname_unique') or '').strip().upper()
                    for row in rows_data
                    if (row.get('hostname_unique') or '').strip()
                }

                # Single query to fetch all matching ServerUnique rows at once (replaces N individual .get() calls)
                yield f"data: {json.dumps({'progress': 5, 'message': 'Loading servers from database...'})}\n\n"
                server_map = {
                    su.hostname_upper: su
                    for su in ServerUnique.objects
                        .annotate(hostname_upper=Upper('hostname'))
                        .filter(hostname_upper__in=hostnames_upper)
                }

                # Process each CSV row in memory using the pre-fetched server_map
                for i, row in enumerate(rows_data):
                    hostname = (row.get('hostname_unique') or '').strip()

                    if not hostname:
                        ignored_count += 1
                        errors.append(f"Line ignored: 'hostname_unique' is missing. Line content: {row}")
                        continue

                    server_unique = server_map.get(hostname.upper())
                    if server_unique is None:
                        ignored_count += 1
                        errors.append(f"Line ignored: 'hostname_unique'={hostname} does not exist. Line content: {row}")
                        continue

                    # Read all values
                    priority_asset = row.get('priority_asset', "").upper() or None
                    in_live_play = row.get('in_live_play', "").upper() or None
                    action_during_lp = row.get('action_during_lp', "") or None
                    original_action_during_lp = row.get('original_action_during_lp', "") or None
                    cluster = row.get('cluster', "").upper() or None
                    cluster_type = row.get('cluster_type', "") or None

                    # Update the properties set in the csv file. If some properties are left empty, the old values of the server_unique are kept
                    if priority_asset is not None:
                        server_unique.priority_asset = priority_asset

                    if in_live_play is not None:
                        server_unique.in_live_play = in_live_play

                    if action_during_lp is not None:
                        server_unique.action_during_lp = action_during_lp
                        server_unique.action_during_lp_history = f"{now_str} {action_during_lp}\n{server_unique.action_during_lp_history or ''}"

                    if original_action_during_lp is not None:
                        server_unique.original_action_during_lp = original_action_during_lp
                        server_unique.original_action_during_lp_history = f"{now_str} {original_action_during_lp}\n{server_unique.original_action_during_lp_history or ''}"

                    if cluster is not None:
                        server_unique.cluster = cluster

                    if cluster_type is not None:
                        server_unique.cluster_type = cluster_type

                    instances_to_update[server_unique.id] = server_unique

                    lines_processed += 1
                    progress = 5 + (lines_processed / total_lines) * 75  # reading phase: 5% → 80%
                    yield f"data: {json.dumps({'progress': progress, 'message': 'Reading CSV file...'})}\n\n"

                # Perform the bulk update in chunks of 100 — saving phase: 80% → 100%
                instances_list = list(instances_to_update.values())
                total_updates = len(instances_list)
                for i in range(0, total_updates, 100):
                    batch = instances_list[i:i + 100]
                    ServerUnique.objects.bulk_update(
                        batch, [
                            'priority_asset', 'in_live_play', 'action_during_lp', 'action_during_lp_history',
                            'original_action_during_lp', 'original_action_during_lp_history', 'cluster', 'cluster_type'
                        ]
                    )
                    updated_count += len(batch)
                    progress = 80 + (updated_count / total_updates) * 20
                    yield f"data: {json.dumps({'progress': progress, 'message': 'Saving...'})}\n\n"

                # Return the final status with data formatted to be understood by the reader.onload event in bulk_import.html
                success_msg = f"Import successful: {updated_count} servers updated. {ignored_count} servers ignored."
                yield f"data: {json.dumps({'success': success_msg})}\n\n"

                # If errors were detected, return the related data formatted to be understood by the reader.onload event in bulk_import.html and displayed in the error field
                if errors:
                    warning_msg = f"{len(errors)} warnings detected."
                    yield f"data: {json.dumps({'warning': warning_msg, 'detailed_errors': errors[:50]})}\n\n"

            response = StreamingHttpResponse(process_import(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response

        # Return an error message formatted to be understood by the reader.onload event in bulk_import.html
        error_msg = "Form validation failed or file is incorrect."
        return JsonResponse({'error': error_msg}, status=400)

    elif request.method == 'GET':  # Open the bulk_import.html
        form = CsvUploadForm()
        return render(request, f"{app_name}/bulk_import.html", {'form': form})

    return JsonResponse({'error': 'Invalid request method'}, status=405)


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
        if 'model_extra' in field_properties:  # Check if the field has the model_extra property
            FILTER_MAPPING[field_name] = f'server_unique.{field_name}'  # Map the field to the nested attribute within server_unique
        else:
            FILTER_MAPPING[field_name] = field_name  # No model_extra field: map the field to the direct attribute of the main model

    # Return the filter mapping dictionary
    return FILTER_MAPPING


# Filters servers based on the provided criteria and applies a permanent filter if selected
def get_filtered_servers(requestfilters, permanent_filter_selection):

    json_path = os.path.join(os.path.dirname(__file__), 'field_labels.json')
    with open(json_path, "r", encoding="utf-8") as f:
        field_labels = json.load(f)

    # Initialize filters dictionary
    filters = {}

    # Map input names to model field names for fields with 'model_extra'
    input_to_model_field = {}
    for field_name, field_properties in field_labels['fields'].items():
        if 'model_extra' in field_properties:
            input_name = field_properties.get('inputname')
            if input_name:
                input_to_model_field[input_name] = field_name

    # Populate filters dictionary for fields without 'model_extra'
    for field_name, field_properties in field_labels['fields'].items():
        if 'model_extra' not in field_properties:
            input_name = field_properties.get('inputname')
            if input_name:
                filters[field_name] = requestfilters.get(input_name, None)

    # Populate filters dictionary for fields with 'model_extra'
    for input_name, model_field_name in input_to_model_field.items():
        filters[f'server_unique__{model_field_name}'] = requestfilters.get(input_name, None)

    # Get all servers and apply filters
    servers = Server.objects.all().select_related('server_unique').order_by('SERVER_ID')

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

    # Filter the servers based on the filters and permanent filter
    servers = get_filtered_servers(requestfilters, permanent_filter_selection)

    # Generate the filter mapping
    FILTER_MAPPING=get_filter_mapping()
    job_id = str(uuid.uuid4())  # Generate a unique identifier
    filepath = os.path.join(EXPORT_DIR, f"{job_id}.{filetype}")

    # Generate the export file using generate_excel from the exports.py module
    def background_export():
        try:
            if filetype == 'xlsx':
                generate_excel(filepath, servers, columns, FILTER_MAPPING)
            else:
                generate_csv(filepath, servers, columns, FILTER_MAPPING)
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

    # Raise an Http404 if the filepath doesn't exist
    if not os.path.exists(filepath):
        raise Http404(f"File not found")

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


# Display the logs_imports.html with the last 100 logs entries
def log_imports(request):
    # Get and sort the last entries of the table businesscontinuity_importstatus
    logs = ImportStatus.objects.order_by('-date_import')[:100]

    return render(request, f'{app_name}/logs_imports.html', {
        'logs': logs
    })


# Update and save the permanent filter field for the authenticated user
@csrf_exempt
def update_permanentfilter_field(request):
    if request.method == 'POST':

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
            return JsonResponse({'status': 'error', 'message': 'User is not authenticated.'}, status=401)

    # Return an error message if the request method is invalid
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=400)


def get_server_history(request):
    server_id = request.GET.get('server_id')
    server = ServerUnique.objects.get(hostname=server_id)
    history = server.global_history
    return JsonResponse(history, safe=False)    
