import csv
import hashlib
import logging
import datetime
import django
import io
import json
import os
import time
import threading
import uuid

logger = logging.getLogger('businesscontinuity')

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import Q, F, Case, When
from django.db.models.functions import Length, Upper
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
from .models import CsvImportLog, ServerUnique, Server, ImportStatus
from .changes import HEADERS as CHANGES_HEADERS, SOURCES as CHANGES_SOURCES, TRACKED_FIELDS as CHANGES_FIELDS
from .changes import iter_change_row_chunks, iter_csv_lines
from accessrights.helpers import has_perm
from .utils import is_editor

from collections import Counter, defaultdict
from urllib.parse import urlencode, parse_qs, unquote

from .polling_job import start_job, update_job, finish_job, fail_job, get_job_response


# Confirmation token the user must type in the modal
RESET_CONFIRM_TOKEN = 'CONFIRM'

# Fields reset to 'EMPTY' regardless of mode
RESET_FIELDS_ALWAYS = [
    'priority_asset',
    'in_live_play',
    'action_during_lp',
    'annotation',
    'cluster',
    'cluster_type',
    'bc_exception',
]

# Fields cleared only when the user chose "reset history too"
RESET_FIELDS_HISTORY = [
    'action_during_lp_history',
    'annotation_history',
]

# Columns a server CSV import can update
IMPORT_FIELDS = [
    'priority_asset', 'in_live_play', 'action_during_lp',
    'annotation', 'cluster', 'cluster_type', 'bc_exception',
]
IMPORT_HEADERS = ['hostname_unique'] + IMPORT_FIELDS
IMPORT_UPPERCASE_FIELDS = {'priority_asset', 'in_live_play', 'cluster', 'bc_exception'}
IMPORT_CHOICE_VALUES = ('YES', 'NO', 'EMPTY')  # only values accepted by these fields
IMPORT_HISTORY_FIELDS = {'action_during_lp', 'annotation'}
IMPORT_LISTED_SERVERS_CAP = 2000  # servers per list sent to the review and recap pages
IMPORT_REPORTS_KEPT = 30  # latest imports keeping their detailed report
IMPORT_JOURNAL_SHOWN = 20  # lines of the journal shown on the import page

app_name=__package__.split('.')[-1]


# Function to create a Django Q object based on a list of terms for a specific field
def construct_query(key, terms):
    """
    Build the Q object of one filtered column.
    Values (plain = contains, @ = exact) are alternatives: OR. Exclusions (! = contains,
    !@ or @! = exact) apply to all of them: AND. The order of the terms does not matter.
    """
    include = Q()
    exclude = Q()
    for term in terms:
        if not term:  # "A,,B" in a URL or saved search: an empty term would match every row
            continue
        if term.startswith(('!@', '@!')):
            exclude &= ~Q(**{f'{key}__iexact': term[2:]})
        elif term.startswith('@'):
            include |= Q(**{f'{key}__iexact': term[1:]})
        elif term.startswith('!'):
            exclude &= ~Q(**{f'{key}__icontains': term[1:]})
        elif term.startswith('#'):  # Expand: keep ALL rows of the servers having at least one row matching the term
            term = term[1:]
            lookup = 'icontains'
            if term.startswith('@'):  # '#@term' = exact match on the matching row
                term = term[1:]
                lookup = 'iexact'
            if term:
                matching_ids = Server.objects.filter(**{f'{key}__{lookup}': term}).values('SERVER_ID')
                include |= Q(SERVER_ID__in=matching_ids)
        else:
            include |= Q(**{f'{key}__icontains': term})
    return include & exclude
    
    
def selection_filters(get_value, json_data):
    """
    Return {lookup: terms} for the filters present in a request.
    Single source shared by the server list, the bulk edit, Apply BC Rules and the DR reset:
    the fields come from field_labels.json, so a new or renamed field is filtered everywhere.
    get_value(input_name) returns the raw value of a filter, or an empty string.
    """
    filters = {}
    for field_key, field_info in json_data['fields'].items():
        input_name = field_info.get('inputname')
        if not input_name:
            continue
        if field_info.get('model_extra') == 'yes':
            field_key = f'server_unique__{field_key}'
        terms = (get_value(input_name) or '').split(',')
        if terms != ['']:
            filters[field_key] = terms
    return filters


def selection_mismatch(found, expected):
    """
    Safety for mass operations: the page sends the number of servers it showed.
    Return an error message when the operation would target another number, else None.
    """
    expected = str(expected or '').strip()
    if not expected.isdigit() or int(expected) == found:
        return None
    return (f'This operation would target {_plural(found, "server")}, but the page shows {expected}. '
            'Nothing was changed. Reload the page and check the filters before trying again.')


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

    # Filters of the URL, from field_labels.json (same helper as the mass operations)
    filters = selection_filters(request.GET.get, json_data)
    
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
            'ENVIRONMENT' : server.ENVIRONMENT if server.ENVIRONMENT else "EMPTY",
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
            'COUNTRY' : server.COUNTRY,
            'hostname_unique': server_unique.hostname,
            'priority_asset': server_unique.priority_asset if server_unique.priority_asset else "EMPTY",
            'in_live_play': server_unique.in_live_play if server_unique.in_live_play else "EMPTY",
            'action_during_lp': server_unique.action_during_lp if server_unique.action_during_lp else "EMPTY",
            'action_during_lp_history': server_unique.action_during_lp_history if server_unique.action_during_lp_history else "EMPTY",
            'annotation': server_unique.annotation if server_unique.annotation else "EMPTY",
            'annotation_history': server_unique.annotation_history if server_unique.annotation_history else "EMPTY",
            'cluster': server_unique.cluster if server_unique.cluster else "EMPTY",
            'cluster_type': server_unique.cluster_type if server_unique.cluster_type else "EMPTY",
            'bc_exception': server_unique.bc_exception if server_unique.bc_exception else "EMPTY",
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
   
    # Access rights — single source of truth via utils.is_editor()
    is_user_editor = is_editor(request)

    unique_servers_count = all_servers.values('SERVER_ID').distinct().count()
    exception_servers_count = (all_servers.filter(server_unique__bc_exception__iexact='YES')
                               .values('server_unique_id').distinct().count())

    # Rendering servers.html with the corresponding context
    
    context = {
        'servers' : servers_for_template,  # Servers with extended information of the server_unique table
        'unique_servers_count' : unique_servers_count,
        'exception_servers_count': exception_servers_count,
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
        'is_user_editor': is_user_editor, # The user is allowed to edit
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
        'annotation': 'server_unique__annotation',
        'cluster': 'server_unique__cluster',
        'cluster_type': 'server_unique__cluster_type',
        'bc_exception': 'server_unique__bc_exception',
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
            'annotation': 'server_unique__annotation',
            'cluster': 'server_unique__cluster',
            'cluster_type': 'server_unique__cluster_type',
            'bc_exception': 'server_unique__bc_exception',
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

    if not is_editor(request):
        return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)

    server_unique = get_object_or_404(ServerUnique, hostname=server_unique_id)  # Get the server_unique_id passed in the URL edit/<str:server_unique_id>/
    referrer = request.POST.get('referrer')  # Get the URL referrer, before the ?
    query = request.POST.get('query')  # Get the URL query, after the ?
    loggedonuser = request.user.username  # Author of the history entry: from the session, never from the form

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
    """
    POST: validate filters and field values, launch background update thread,
          return job_id for polling.
    """
    if request.method != "POST":
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

    if not is_editor(request):
        return JsonResponse({'status': 'error', 'message': 'Permission denied.'}, status=403)

    try:
        query_param = request.POST.get('query')
        if not query_param:
            return JsonResponse({'status': 'error', 'message': 'Query string not provided'}, status=400)

        query_param  = unquote(query_param)
        parsed_query = parse_qs(query_param)


        try:
            profile = UserProfile.objects.get(user=request.user)
        except UserProfile.DoesNotExist:
            profile = UserProfile.objects.create(user=request.user)

        json_path = os.path.join(os.path.dirname(__file__), 'field_labels.json')
        with open(json_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)
        filters = selection_filters(lambda name: parsed_query.get(name, [''])[0], json_data)

        json_data_permanentfilters = json_data.get("permanentfilters", {})
        try:
            user_options = SavedOptions.objects.get(user_profile=profile)
            permanent_filter_selection = user_options.businesscontinuity_permanentfilter
        except SavedOptions.DoesNotExist:
            permanent_filter_selection = "All Servers"

        if permanent_filter_selection != "All Servers":
            if permanent_filter_selection not in json_data_permanentfilters:
                permanent_filter_selection = "All Servers"

        servers_to_bulkedit = Server.objects.all().select_related('server_unique').order_by('SERVER_ID')
        permanent_filter_query, _, _ = create_permanent_filter_query(json_data, permanent_filter_selection)
        if permanent_filter_query:
            servers_to_bulkedit = servers_to_bulkedit.filter(permanent_filter_query)

        filters = {k: v for k, v in filters.items() if v != ['']}
        for key, value in filters.items():
            terms = value if isinstance(value, list) else [value]
            servers_to_bulkedit = servers_to_bulkedit.filter(construct_query(key, terms))

        # Collect field values to update: '-' on a select and an empty text mean unchanged
        requested = {}
        for field in IMPORT_FIELDS:
            value = (request.POST.get(field) or '').strip()
            if field in IMPORT_UPPERCASE_FIELDS:
                value = value.upper()
                if value == '-':
                    value = ''
                if value and value not in IMPORT_CHOICE_VALUES:
                    return JsonResponse({'status': 'error', 'message': f"Invalid {field} value '{value}'."}, status=400)
            if _import_too_long(field, value):
                return JsonResponse({'status': 'error', 'message': f'{field} is too long (max {_import_max_length(field)} characters).'}, status=400)
            if value:
                requested[field] = value

        now_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_str  = f"[{now_date} - {request.user.username}]"
        username = request.user.username

        updates       = list(ServerUnique.objects.filter(
            hostname__in=servers_to_bulkedit.values_list('SERVER_ID', flat=True).distinct()
        ))
        total_updates = len(updates)

        if total_updates == 0:
            return JsonResponse({'status': 'warning', 'message': 'No servers to update with the given filters'}, status=200)

        # Safety: the edit must target exactly the servers the page showed
        mismatch = selection_mismatch(total_updates, request.POST.get('expected_servers'))
        if mismatch:
            logger.warning(f"[Bulk Edit] {username} refused: {total_updates} servers selected, page showed {request.POST.get('expected_servers')}")
            return JsonResponse({'status': 'error', 'message': mismatch}, status=409)

        # Compare with the database: only real changes are written.
        # Servers in exception are ignored unless the user ticked the option.
        include_exceptions = request.POST.get('include_exceptions') == '1'
        scan = {'kind': 'bulk', 'changed': {}, 'found': {}, 'not_found': [], 'no_hostname': 0, 'invalid': [], 'skipped_exceptions': []}
        for obj in updates:
            diff = _import_diff(obj, requested)
            if diff and obj.in_exception() and not include_exceptions:
                scan['skipped_exceptions'].append(obj.hostname)
                continue
            scan['found'][obj.id] = obj.hostname
            if diff:
                scan['changed'][obj.id] = {'su': obj, 'hostname': obj.hostname, 'changes': diff, 'exception': obj.in_exception()}
        changed_entries = list(scan['changed'].values())
        unchanged_count = len(scan['found']) - len(changed_entries)
        # Identifies the exact changes: the review hands it back, and the job only starts if it still matches
        fingerprint = hashlib.sha256(json.dumps(sorted(
            [entry['hostname'], change['field'], str(change['old']), change['new']]
            for entry in changed_entries for change in entry['changes']
        )).encode()).hexdigest()

        if request.POST.get('dry_run'):
            return JsonResponse({
                'status':    'preview',
                'servers':   total_updates,
                'fingerprint': fingerprint,
                'requested': sorted(requested),
                **_import_report(scan, list(scan['changed'])),
            })

        if not changed_entries:
            skipped = len(scan['skipped_exceptions'])
            return JsonResponse({'status': 'warning', 'message': 'No server would change with these values.'
                                 + (f' {_plural(skipped, "server")} in exception ignored.' if skipped else '')}, status=200)

        reviewed = (request.POST.get('fingerprint') or '').strip()
        if reviewed and reviewed != fingerprint:
            logger.warning(f"[Bulk Edit] {username} refused: changes differ from the reviewed ones")
            return JsonResponse({'status': 'error', 'message': (
                'The changes to apply are no longer the ones you reviewed: the data changed in the meantime. '
                'Nothing was changed. Review the changes again.'
            )}, status=409)

        # Start the background job
        logger.info(f"[Bulk Edit] {request.user.username} started bulk update — {len(changed_entries)} servers")
        job_id = start_job(meta={'total': len(changed_entries)})

        def run():
            try:
                batch_size    = 50
                total_batches = (len(changed_entries) + batch_size - 1) // batch_size

                for i in range(total_batches):
                    batch = changed_entries[i * batch_size: (i + 1) * batch_size]

                    with transaction.atomic():
                        for entry in batch:
                            obj = entry['su']
                            changes = {}

                            for change in entry['changes']:
                                field, new = change['field'], change['new']
                                setattr(obj, field, new)
                                if field not in IMPORT_HISTORY_FIELDS:
                                    changes[field] = {'old': change['old'], 'new': new}
                                else:
                                    history = f'{field}_history'
                                    setattr(obj, history, f"{now_str} {new}\n" + (getattr(obj, history) or ''))
                                    changes[field] = {'info': 'Updated via Bulk Edit, check its history'}

                            obj.append_global_history(changes, username, source='Bulk Edit')

                        ServerUnique.objects.bulk_update(
                            [entry['su'] for entry in batch], [
                                'priority_asset', 'in_live_play',
                                'action_during_lp', 'action_during_lp_history',
                                'annotation', 'annotation_history',
                                'cluster', 'cluster_type', 'bc_exception', 'global_history',
                            ]
                        )

                    progress = ((i + 1) / total_batches) * 100
                    update_job(
                        job_id, progress,
                        f'Batch {i + 1}/{total_batches}',
                        log=f'✓ Batch {i + 1}/{total_batches} — {len(batch)} servers updated'
                    )

                logger.info(f"[Bulk Edit] {username} completed — {len(changed_entries)} servers updated")
                finish_job(job_id, stats={
                    'total':   len(changed_entries),
                    'message': f"Bulk update completed: {_plural(len(changed_entries), 'server')} updated, {unchanged_count} already up to date"
                               + (f", {len(scan['skipped_exceptions'])} in exception ignored." if scan['skipped_exceptions'] else '.'),
                })

            except Exception as exc:
                logger.error(f"[Bulk Edit] {username} — unexpected error: {exc}", exc_info=True)
                fail_job(job_id, error=f'Unexpected error: {exc}')

        threading.Thread(target=run, daemon=True).start()
        return JsonResponse({'job_id': job_id, 'total': len(changed_entries)})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Unexpected error: {e}'}, status=500)


def bulk_update_status(request, job_id):
    """Polling endpoint for servers_bulk_update progress."""
    return get_job_response(job_id)
        

# Handles the bulk import of server data from a CSV file
def _plural(count, word):
    """Return '1 server' or '2 servers'."""
    return f"{count} {word}{'' if count == 1 else 's'}"


class ImportFileError(Exception):
    """A server CSV was refused before any import work started."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or []


def _import_value(field, row):
    """Return the value a CSV row asks for a field, None when empty (empty = unchanged)."""
    value = (row.get(field) or '').strip()
    if field in IMPORT_UPPERCASE_FIELDS:
        value = value.upper()
    return value or None


def _read_csv_rows(raw):
    """Parse raw CSV bytes. Return (fieldnames, [(line number, row)]), refusing malformed rows."""
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ImportFileError('This file is not UTF-8 encoded.')

    reader = csv.DictReader(io.StringIO(text, newline=''), delimiter=';')
    rows, errors = [], []
    try:
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            if not any(isinstance(v, str) and v.strip() for v in row.values()):
                continue
            if None in row or None in row.values():
                found = len(fieldnames) + len(row.get(None) or []) - sum(v is None for v in row.values())
                errors.append(f"Line {reader.line_num}: wrong column count (found {found}, expected {len(fieldnames)}).")
                continue
            rows.append((reader.line_num, row))
    except csv.Error as exc:
        raise ImportFileError(f'This file cannot be read as a CSV: {exc}.')

    if errors:
        raise ImportFileError(f"{_plural(len(errors), 'error')} detected.", errors[:50])
    return fieldnames, rows


def _rows_from_export(rows):
    """Reduce a full export to one row per server, refusing servers whose lines disagree."""
    by_server, first_values, errors = {}, {}, []
    for line, row in rows:
        server_id = row['SERVER_ID'].strip()
        key = server_id.upper()
        values = {field: _import_value(field, row) for field in IMPORT_FIELDS}
        if key not in by_server:
            by_server[key] = {'hostname_unique': server_id, '_line': line, '_export': True, **{field: row[field] for field in IMPORT_FIELDS}}
            first_values[key] = values
        elif values != first_values[key]:
            fields = [field for field in IMPORT_FIELDS if values[field] != first_values[key][field]]
            errors.append(f"Line {line}: {server_id} differs from its previous lines ({', '.join(fields)}).")
    if errors:
        raise ImportFileError(f"{_plural(len(errors), 'conflicting line')}: a server must have the same values on all its lines.", errors[:50])
    return list(by_server.values())


def _parse_server_csv(raw):
    """Return (rows, source line count, is_export) from a classic server CSV or a full export."""
    fieldnames, rows = _read_csv_rows(raw)
    is_export = 'SERVER_ID' in fieldnames and set(IMPORT_FIELDS) <= set(fieldnames)
    if is_export:
        return _rows_from_export(rows), len(rows), True
    if fieldnames != IMPORT_HEADERS:
        raise ImportFileError('Header incorrect.', [
            f"Header incorrect. Expected: {', '.join(IMPORT_HEADERS)}, or a full server export. "
            f"Got: {', '.join(fieldnames)}"
        ])
    return [{**row, '_line': line} for line, row in rows], len(rows), False


def _import_max_length(field):
    """Return the column size of a field, None for a text without limit."""
    return ServerUnique._meta.get_field(field).max_length


def _import_too_long(field, value):
    """SQLite ignores column sizes but PostgreSQL refuses the whole save batch: check them first."""
    limit = _import_max_length(field)
    return bool(value and limit and len(value) > limit)


def _clean_import_rows(rows):
    """
    Files can be messy: keep the usable rows and describe the others.
    A line with an invalid value is ignored as a whole. A server listed with different
    values is ignored too, as nothing tells which line is right.
    """
    usable, refused, by_host = [], [], defaultdict(list)
    for row in rows:
        hostname = (row.get('hostname_unique') or '').strip()
        bad = next(
            ((field, _import_value(field, row)) for field in IMPORT_FIELDS
             if field in IMPORT_UPPERCASE_FIELDS and _import_value(field, row) not in (None, *IMPORT_CHOICE_VALUES)),
            None,
        )
        too_long = next((field for field in IMPORT_FIELDS if _import_too_long(field, _import_value(field, row))), None)
        if bad:
            refused.append((row.get('_line', 0), f"{hostname or '(no hostname)'}: invalid {bad[0]} value '{bad[1]}' (expected YES, NO or EMPTY)."))
        elif too_long:
            refused.append((row.get('_line', 0), f"{hostname or '(no hostname)'}: {too_long} is too long (max {_import_max_length(too_long)} characters)."))
        elif hostname:
            by_host[hostname.upper()].append(row)
            usable.append(row)
        else:
            usable.append(row)

    kept = []
    conflicting = {}
    for host, host_rows in by_host.items():
        values = {tuple(_import_value(field, row) for field in IMPORT_FIELDS) for row in host_rows}
        if len(values) > 1:
            conflicting[host] = host_rows
    seen = set()
    for row in usable:
        host = (row.get('hostname_unique') or '').strip().upper()
        if host in conflicting:
            hostname = row['hostname_unique'].strip()
            refused.append((row.get('_line', 0), f'{hostname}: listed several times with different values.'))
        elif not host or host not in seen:
            seen.add(host)
            kept.append(row)
    return kept, [f'Line {line}: {text}' for line, text in sorted(refused, key=lambda item: item[0])]


def _load_import_servers(rows):
    """Bulk-fetch the ServerUnique rows referenced by a CSV, keyed by upper-case hostname."""
    hostnames_upper = {
        (row.get('hostname_unique') or '').strip().upper()
        for row in rows
        if (row.get('hostname_unique') or '').strip()
    }
    return {
        su.hostname_upper: su
        for su in ServerUnique.objects
            .annotate(hostname_upper=Upper('hostname'))
            .filter(hostname_upper__in=hostnames_upper)
    }


def _import_diff(su, row):
    """Return the real changes a CSV row asks for, as [{field, old, new}]."""
    diff = []
    for field in IMPORT_FIELDS:
        new = _import_value(field, row)
        old = getattr(su, field)
        if new is None:
            # An export is a full state: its empty cells clear the field. Elsewhere, empty = unchanged
            if row.get('_export') and old not in (None, ''):
                diff.append({'field': field, 'old': old, 'new': ''})
            continue
        # Upper-cased on import: a lower-case stored value is the same value, not a change
        same = (old or '').upper() == new if field in IMPORT_UPPERCASE_FIELDS else (old or '') == new
        if not same:
            diff.append({'field': field, 'old': old, 'new': new})
    return diff


def _apply_import_row(su, row, now_str, username):
    """Apply a CSV row to an unsaved ServerUnique, writing real changes only. Return these changes."""
    diff = _import_diff(su, row)
    changes = {}
    for change in diff:
        field, new = change['field'], change['new']
        if not new:
            changes[field] = {'old': change['old'], 'new': '(empty)'}
            setattr(su, field, None)
            continue
        if field in IMPORT_HISTORY_FIELDS:
            history = f'{field}_history'
            setattr(su, history, f"{now_str} {new}\n" + (getattr(su, history) or ''))
            changes[field] = {'info': 'Updated via CSV Import, check its history'}
        else:
            changes[field] = {'old': change['old'], 'new': new}
        setattr(su, field, new)
    su.append_global_history(changes, username=username, source='CSV Import')
    return diff


def _scan_import_rows(rows, now_str, username, on_row=None):
    """Apply every row to unsaved instances and sort the servers by outcome. Nothing is saved here."""
    rows, refused = _clean_import_rows(rows)
    server_map = _load_import_servers(rows)
    scan = {'kind': 'server', 'changed': {}, 'found': {}, 'not_found': [], 'no_hostname': 0, 'invalid': refused}
    for i, row in enumerate(rows):
        hostname = (row.get('hostname_unique') or '').strip()
        su = server_map.get(hostname.upper()) if hostname else None
        if not hostname:
            scan['no_hostname'] += 1
        elif su is None:
            scan['not_found'].append(hostname)
        else:
            scan['found'][su.id] = su.hostname
            was_exception = su.in_exception()
            diff = _apply_import_row(su, row, now_str, username)
            if diff:
                entry = scan['changed'].setdefault(su.id, {'su': su, 'hostname': su.hostname, 'changes': [], 'exception': was_exception})
                entry['changes'].extend(diff)
        if on_row:
            on_row(i)
    return scan


def _import_entries(scan, ids):
    """Return the capped, sorted list of changed servers, with their old and new values."""
    entries = sorted((scan['changed'][i] for i in ids), key=lambda e: e['hostname'])
    return [{'hostname': e['hostname'], 'changes': e['changes']} for e in entries[:IMPORT_LISTED_SERVERS_CAP]]


def _import_report(scan, changed_ids):
    """Build the counts and server lists shown on the review and recap pages."""
    unchanged = [host for id_, host in scan['found'].items() if id_ not in scan['changed']]
    field_counts = Counter(c['field'] for i in changed_ids for c in scan['changed'][i]['changes'])
    exceptions = sorted(scan['changed'][i]['hostname'] for i in changed_ids if scan['changed'][i].get('exception'))
    skipped_exceptions = sorted(scan.get('skipped_exceptions', []))
    return {
        'kind':         scan['kind'],
        'changed':      len(changed_ids),
        'unchanged':    len(unchanged),
        'not_found':    len(scan['not_found']),
        'no_hostname':  scan['no_hostname'],
        'invalid':      len(scan['invalid']),
        'exceptions':   len(exceptions),
        'skipped_exceptions': len(skipped_exceptions),
        'field_counts': {field: field_counts[field] for field in IMPORT_FIELDS if field_counts[field]},
        'lists': {
            'changed':   _import_entries(scan, changed_ids),
            'unchanged': sorted(unchanged)[:IMPORT_LISTED_SERVERS_CAP],
            'not_found': sorted(scan['not_found'])[:IMPORT_LISTED_SERVERS_CAP],
            'invalid':   scan['invalid'][:IMPORT_LISTED_SERVERS_CAP],
            'exceptions': exceptions[:IMPORT_LISTED_SERVERS_CAP],
            'skipped_exceptions': skipped_exceptions[:IMPORT_LISTED_SERVERS_CAP],
        },
    }


def _import_report_csv(scan, saved_ids):
    """Build the complete server by server report of an import, without the list caps."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['name', 'status', 'field', 'old', 'new', 'detail'])

    def write_changes(ids, status):
        for entry in sorted((scan['changed'][id_] for id_ in ids), key=lambda e: e['hostname']):
            detail = 'server in exception' if entry.get('exception') else ''
            for change in entry['changes']:
                writer.writerow([entry['hostname'], status, change['field'], change['old'] or '',
                                 change['new'] or '(empty)', '; '.join(t for t in (change.get('via', ''), detail) if t)])

    saved = set(saved_ids)
    write_changes(saved_ids, 'updated')
    write_changes([id_ for id_ in scan['changed'] if id_ not in saved], 'not saved')
    for host in sorted(host for id_, host in scan['found'].items() if id_ not in scan['changed']):
        writer.writerow([host, 'already up to date', '', '', '', ''])
    for name in sorted(scan['not_found']):
        writer.writerow([name, 'not found', '', '', '', ''])
    for text in scan['invalid']:
        writer.writerow(['', 'line ignored', '', '', '', text])
    if scan['no_hostname']:
        writer.writerow(['', 'line ignored', '', '', '', f"{_plural(scan['no_hostname'], 'line')} without an identifier"])
    return output.getvalue()


def _journal_import(journal, message, failed, report=None, report_csv=''):
    """Record an import in the journal. Never makes a finished import fail. Return the log id."""
    try:
        report = report or {}
        log = CsvImportLog.objects.create(
            username=journal['username'], filename=journal['filename'][:255], file_format=journal['format'],
            updated=report.get('changed', 0), unchanged=report.get('unchanged', 0),
            ignored=report.get('not_found', 0) + report.get('no_hostname', 0) + report.get('invalid', 0),
            failed=failed, message=message, report_csv=report_csv,
        )
        keep = list(CsvImportLog.objects.order_by('-id').values_list('id', flat=True)[:IMPORT_REPORTS_KEPT])
        CsvImportLog.objects.exclude(id__in=keep).exclude(report_csv='').update(report_csv='')
        return log.id
    except Exception as exc:
        logger.error(f"[CSV Import] journal error: {exc}", exc_info=True)
        return None


def _run_import_job(job_id, scan_rows, save_fields, success_message, journal):
    """Thread body shared by the imports: scan, save by batches, then publish the recap."""
    scan = None
    saved_ids = []
    try:
        update_job(job_id, 5, 'Loading servers from database...')
        scan = scan_rows()

        # Bulk save in batches of 100 \u2014 80% \u2192 100%. Each batch is atomic.
        changed_ids   = list(scan['changed'])
        total_updates = len(changed_ids)
        for i in range(0, total_updates, 100):
            batch_ids = changed_ids[i:i + 100]
            ServerUnique.objects.bulk_update([scan['changed'][id_]['su'] for id_ in batch_ids], save_fields)
            saved_ids.extend(batch_ids)
            update_job(
                job_id, 80 + (len(saved_ids) / total_updates) * 20,
                f'Saving\u2026 {len(saved_ids)}/{total_updates}',
                log=f'\u2713 Batch saved: {len(saved_ids)}/{total_updates} servers'
            )

        report = _import_report(scan, saved_ids)
        message = success_message(report)
        logger.info(f"[CSV Import] completed \u2014 {message}")
        log_id = _journal_import(journal, message, False, report, _import_report_csv(scan, saved_ids))
        finish_job(job_id, stats={'recap': True, 'failed': False, 'message': message, 'log_id': log_id, **report})

    except Exception as exc:
        logger.error(f"[CSV Import] unexpected error: {exc}", exc_info=True)
        if scan is None:
            _journal_import(journal, f'Unexpected error: {exc}', True)
            fail_job(job_id, error=f'Unexpected error: {exc}')  # nothing was saved
            return
        not_saved = [id_ for id_ in scan['changed'] if id_ not in set(saved_ids)]
        report = _import_report(scan, saved_ids)
        log_id = _journal_import(journal, str(exc), True, report, _import_report_csv(scan, saved_ids))
        finish_job(job_id, stats={
            'recap':     True,
            'failed':    True,
            'log_id':    log_id,
            'error':     str(exc),
            'total':     len(scan['changed']),
            'not_saved': {'count': len(not_saved), 'list': _import_entries(scan, not_saved)},
            **report,
        })


def _scan_application_rows(rows, username):
    """
    Resolve servers from DAP_AUID and sort them by outcome. Nothing is saved here.
    The file is the source: a YES on an application wins over NO lines of that application,
    and a server goes to YES as soon as one of its applications of the file is YES.
    Applications absent from the file have no influence.
    """
    scan = {'kind': 'application', 'changed': {}, 'found': {}, 'not_found': [], 'no_hostname': 0, 'invalid': []}
    app_values = {}
    for line, row in rows:
        app_id = (row.get('application_id') or '').strip().upper()
        value  = (row.get('in_live_play') or '').strip().upper()
        if not app_id:
            scan['no_hostname'] += 1
        elif value not in ('YES', 'NO'):
            scan['invalid'].append(f"Line {line}: {app_id}: invalid in_live_play value '{value}' (expected YES or NO).")
        elif app_id not in app_values or value == 'YES':
            app_values[app_id] = value
    scan['apps'] = len(app_values)

    server_apps = defaultdict(dict)
    server_rows = (
        Server.objects
        .annotate(dap_upper=Upper('DAP_AUID'))
        .filter(dap_upper__in=app_values.keys())
        .values('server_unique_id', 'dap_upper')
    )
    for entry in server_rows:
        server_apps[entry['server_unique_id']][entry['dap_upper']] = app_values[entry['dap_upper']]

    apps_found = {app for apps in server_apps.values() for app in apps}
    scan['not_found'] = [app for app in app_values if app not in apps_found]

    for su in ServerUnique.objects.filter(id__in=server_apps.keys()):
        apps = server_apps[su.id]
        new = 'YES' if 'YES' in apps.values() else 'NO'
        scan['found'][su.id] = su.hostname
        if (su.in_live_play or '').upper() == new:
            continue
        via = ', '.join(f'{app}={value}' for app, value in sorted(apps.items()))
        change = {'field': 'in_live_play', 'old': su.in_live_play, 'new': new, 'via': via}
        was_exception = su.in_exception()
        su.append_global_history({'in_live_play': {'old': su.in_live_play, 'new': new}},
                                 username=username, source='Application CSV Import')
        su.in_live_play = new
        scan['changed'][su.id] = {'su': su, 'hostname': su.hostname, 'changes': [change], 'exception': was_exception}
    return scan


def _import_applications_csv(request, csv_file):
    """Application import: same dry run and job as a server import, on the in_live_play field."""
    try:
        fieldnames, rows = _read_csv_rows(csv_file.read())
        expected = ['application_id', 'in_live_play']
        if fieldnames != expected:
            raise ImportFileError('Header incorrect.', [f"Expected: {', '.join(expected)}. Got: {', '.join(fieldnames)}"])
    except ImportFileError as exc:
        return JsonResponse({'error': exc.message, 'detailed_errors': exc.details}, status=400)

    username = request.user.username
    if request.POST.get('dry_run'):
        scan = _scan_application_rows(rows, username)  # instances are thrown away
        return JsonResponse({
            'lines': len(rows),
            'apps':  scan['apps'],
            **_import_report(scan, list(scan['changed'])),
        })

    logger.info(f"[App CSV Import] {username} started import \u2014 {len(rows)} lines")
    job_id = start_job(meta={'total_rows': len(rows), 'type': 'application'})

    def success_message(report):
        ignored = report['not_found'] + report['no_hostname'] + report['invalid']
        return (
            f"Application import successful: {_plural(report['changed'], 'server')} updated, "
            f"{report['unchanged']} unchanged, {ignored} ignored."
        )

    threading.Thread(
        target=_run_import_job,
        args=(job_id, lambda: _scan_application_rows(rows, username), ['in_live_play', 'global_history'], success_message,
              {'username': username, 'filename': csv_file.name, 'format': 'Application Import'}),
        daemon=True,
    ).start()
    return JsonResponse({'job_id': job_id, 'total_rows': len(rows)})


@require_http_methods(["GET", "POST"])
def bulk_import_csv(request):
    """
    GET:  render bulk_import.html.
    POST: validate CSV, launch background import thread, return job_id.
          With dry_run, return what a server import would do without saving anything.
    """
    if request.method == 'GET':
        if not is_editor(request):
            from django.shortcuts import redirect
            return redirect('businesscontinuity:server_view')
        form = CsvUploadForm()
        recent_imports = list(
            CsvImportLog.objects.order_by('-id').defer('report_csv')
            .annotate(report_size=Length('report_csv'))[:IMPORT_JOURNAL_SHOWN]
        )
        for log in recent_imports:
            log.local_date = log.date.astimezone().strftime('%Y-%m-%d %H:%M:%S')  # same clock as the histories
        return render(request, f"{app_name}/bulk_import.html", {'form': form, 'appname': app_name, 'recent_imports': recent_imports})

    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    if not is_editor(request):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    form = CsvUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({'error': 'Form validation failed or file is incorrect.'}, status=400)

    csv_file = request.FILES['csv_file']
    if not csv_file.name.endswith('.csv'):
        return JsonResponse({'error': 'This file must be a CSV.'}, status=400)

    import_type = request.POST.get('import_type', 'server')
    if import_type == 'application':
        return _import_applications_csv(request, csv_file)

    # Validate the file before launching the thread
    try:
        rows_data, line_count, is_export = _parse_server_csv(csv_file.read())
    except ImportFileError as exc:
        return JsonResponse({'error': exc.message, 'detailed_errors': exc.details}, status=400)

    username = request.user.username
    if request.POST.get('dry_run'):
        scan = _scan_import_rows(rows_data, '', username)  # instances are thrown away
        return JsonResponse({
            'is_export': is_export,
            'lines':     line_count,
            'servers':   len(rows_data),
            **_import_report(scan, list(scan['changed'])),
        })

    # Snapshot data needed by the thread before the request context is gone
    total_lines = len(rows_data)
    now_str     = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {username}]"

    logger.info(f"[CSV Import] {username} started import \u2014 {total_lines} servers from {line_count} lines (export: {is_export})")
    job_id = start_job(meta={'total_lines': total_lines})

    def scan_rows():
        last_progress = [time.monotonic()]

        def on_row(i):
            now = time.monotonic()
            if now - last_progress[0] >= 0.5 or i == total_lines - 1:
                update_job(job_id, 5 + ((i + 1) / total_lines) * 75, f'Reading CSV\u2026 {i + 1}/{total_lines}')  # 5% \u2192 80%
                last_progress[0] = now

        return _scan_import_rows(rows_data, now_str, username, on_row)

    def success_message(report):
        ignored = report['not_found'] + report['no_hostname'] + report['invalid']
        return (
            f"Import successful: {_plural(report['changed'], 'server')} updated, "
            f"{report['unchanged']} unchanged, {ignored} ignored."
        )

    save_fields = [
        'priority_asset', 'in_live_play',
        'action_during_lp', 'action_during_lp_history',
        'annotation', 'annotation_history',
        'cluster', 'cluster_type', 'bc_exception', 'global_history',
    ]
    threading.Thread(
        target=_run_import_job,
        args=(job_id, scan_rows, save_fields, success_message,
              {'username': username, 'filename': csv_file.name, 'format': 'Server Export' if is_export else 'Server Import'}),
        daemon=True,
    ).start()
    return JsonResponse({'job_id': job_id, 'total_lines': total_lines})


def import_csv_report(request, log_id):
    """Download the server by server report of an import."""
    if not is_editor(request):
        return JsonResponse({'error': 'Permission denied.'}, status=403)
    log = get_object_or_404(CsvImportLog, id=log_id)
    if not log.report_csv:
        return JsonResponse({'error': 'This report is no longer available.'}, status=404)
    response = HttpResponse(log.report_csv, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="bc_import_{log.id}_{log.date.astimezone():%Y%m%d_%H%M%S}.csv"'
    return response


def import_csv_status(request, job_id):
    """Polling endpoint for bulk_import_csv progress."""
    return get_job_response(job_id)


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
        

# Display the logs_imports.html with the last 100 logs entries
def log_imports(request):

    # Get and sort the last entries of the table businesscontinuity_importstatus
    logs = ImportStatus.objects.order_by('-date_import')[:100]

    return render(request, f'{app_name}/logs_imports.html', {
        'logs': logs
    })
    

# Update and save the permanent filter field for the authenticated user
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


# Changes summary: on-screen range is capped, CSV export is streamed in chunks without range limit
CHANGES_MAX_VIEW_DAYS = 31
CHANGES_MAX_DISPLAY_ROWS = 2000


def _parse_changes_filters(request):
    """Read changes summary filters from GET. Returns (filters, error)."""
    today = datetime.date.today()
    raw_from = request.GET.get('date_from', '').strip()
    raw_to = request.GET.get('date_to', '').strip()
    filters = {
        'hostname': request.GET.get('hostname', '').strip(),
        'user':     request.GET.get('user', '').strip(),
        'source':   request.GET.get('source', '').strip(),
    }
    try:
        d_from = datetime.date.fromisoformat(raw_from) if raw_from else today
        d_to = datetime.date.fromisoformat(raw_to) if raw_to else d_from
    except ValueError:
        return {**filters, 'date_from': today, 'date_to': today}, 'Invalid date, expected YYYY-MM-DD.'
    if filters['source'] not in CHANGES_SOURCES:
        filters['source'] = ''
    filters.update(date_from=d_from, date_to=d_to)
    if d_to < d_from:
        return filters, '"To" date must be on or after "From" date.'
    return filters, None


def _changes_row_chunks(filters):
    """Chunked change rows for the given filters."""
    return iter_change_row_chunks(
        filters['date_from'], filters['date_to'],
        hostname=filters['hostname'], user=filters['user'], source=filters['source'],
    )


@login_required
def changes_summary(request):
    """Display ServerUnique changes for a date range (default: today)."""
    filters, error = _parse_changes_filters(request)
    rows, total = [], 0

    if not error and (filters['date_to'] - filters['date_from']).days + 1 > CHANGES_MAX_VIEW_DAYS:
        error = (f'On-screen range is limited to {CHANGES_MAX_VIEW_DAYS} days. '
                 f'Use "Export CSV" for larger ranges.')

    if not error:
        for chunk in _changes_row_chunks(filters):
            rows.extend(chunk)
        rows.sort(key=lambda r: (r['date'], r['hostname']), reverse=True)
        total = len(rows)
        rows = rows[:CHANGES_MAX_DISPLAY_ROWS]

    labels = {f: ServerUnique._meta.get_field(f).verbose_name for f in CHANGES_FIELDS}
    labels.update(date='Date', user='User', source='Source', hostname='Hostname', other_changes='Other changes')

    return render(request, 'businesscontinuity/changes_summary.html', {
        'appname':      'businesscontinuity',
        'filters':      filters,
        'error':        error,
        'sources':      CHANGES_SOURCES,
        'headers':      [labels[h] for h in CHANGES_HEADERS],
        'rows':         [[r[h] for h in CHANGES_HEADERS] for r in rows],
        'total':        total,
        'truncated':    total > CHANGES_MAX_DISPLAY_ROWS,
        'max_rows':     CHANGES_MAX_DISPLAY_ROWS,
        'query_string': request.GET.urlencode(),
    })


@login_required
def changes_summary_export(request):
    """Stream the changes summary as CSV, reading servers in chunks."""
    filters, error = _parse_changes_filters(request)
    if error:
        return HttpResponse(error, status=400, content_type='text/plain')

    filename = f"bc_changes_{filters['date_from']}_{filters['date_to']}.csv"
    response = StreamingHttpResponse(
        iter_csv_lines(_changes_row_chunks(filters)),
        content_type='text/csv; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _build_filtered_queryset(request, query_param_raw):
    """
    Build a filtered Server queryset from a URL query string.
    Same filters as the server list and the bulk edit (selection_filters).
    Returns (queryset, is_filtered) where is_filtered=True means at least
    one active filter was applied beyond the permanent filter.
    """
    # The query string may be double-encoded when passed via JS encodeURIComponent
    # Decode once — parse_qs handles the rest
    try:
        raw = unquote(query_param_raw) if query_param_raw else ''
        parsed_query = parse_qs(raw, keep_blank_values=False)
    except Exception:
        parsed_query = {}


    json_path = os.path.join(os.path.dirname(__file__), 'field_labels.json')
    with open(json_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    active_filters = selection_filters(lambda name: parsed_query.get(name, [''])[0], json_data)

    try:
        profile = UserProfile.objects.get(user=request.user)
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    try:
        user_options = SavedOptions.objects.get(user_profile=profile)
        permanent_filter_selection = user_options.businesscontinuity_permanentfilter
    except SavedOptions.DoesNotExist:
        permanent_filter_selection = 'All Servers'

    if permanent_filter_selection not in json_data.get('permanentfilters', {}):
        permanent_filter_selection = 'All Servers'

    qs = Server.objects.all().select_related('server_unique').order_by('SERVER_ID')
    pf_result = create_permanent_filter_query(json_data, permanent_filter_selection)
    if not isinstance(pf_result, tuple) or len(pf_result) != 3:
        logger.error(f"[_build_filtered_queryset] create_permanent_filter_query returned unexpected value: {pf_result!r}")
        return qs, bool(active_filters)
    permanent_filter_query, _, _ = pf_result
    if permanent_filter_query:
        qs = qs.filter(permanent_filter_query)

    for key, value in active_filters.items():
        qs = qs.filter(construct_query(key, value if isinstance(value, list) else [value]))

    return qs, bool(active_filters)


def reset_dr_preview(request):
    """
    GET: return count of servers/occurrences that would be affected by reset,
    given the current filters.
    Called by the reset modal JS before the user confirms.
    """
    if not is_editor(request):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    query_param = request.GET.get('query', '')
    try:
        result = _build_filtered_queryset(request, query_param)
        qs, is_filtered = result
        count_unique = qs.values('server_unique_id').distinct().count()
        count_total  = qs.count()
    except Exception as e:
        logger.error(f"[DR Reset Preview] error building queryset: {e}", exc_info=True)
        return JsonResponse({'error': f'Error computing scope: {e}'}, status=500)

    mismatch = selection_mismatch(count_unique, request.GET.get('expected_servers'))
    if mismatch:
        return JsonResponse({'error': mismatch}, status=409)

    return JsonResponse({
        'count_unique': count_unique,
        'count_total':  count_total,
        'is_filtered':  is_filtered,
    })


def reset_dr(request):
    """
    Start a background DR reset job.

    Request body (form-encoded):
        confirm_token : must equal RESET_CONFIRM_TOKEN ('CONFIRM')
        keep_history  : '1' to keep _history fields, '0' to wipe them too

    Returns:
        JsonResponse { job_id, total } on success
        JsonResponse { error }         on validation failure
    """
    if not is_editor(request):
        return JsonResponse({'error': 'Permission denied. Editor role required.'}, status=403)

    confirm_token = (request.POST.get('confirm_token') or '').strip().upper()
    if confirm_token != RESET_CONFIRM_TOKEN:
        return JsonResponse(
            {'error': f'Invalid confirmation token. Please type "{RESET_CONFIRM_TOKEN}" to proceed.'},
            status=400
        )

    keep_history = request.POST.get('keep_history', '1') == '1'
    username     = request.user.username

    # Parse and validate selected fields
    fields_raw = (request.POST.get('fields') or '').strip()
    selected_fields = [
        f.strip() for f in fields_raw.split(',')
        if f.strip() in RESET_FIELDS_ALWAYS
    ]
    if not selected_fields:
        return JsonResponse(
            {'error': 'Please select at least one field to reset.'},
            status=400
        )

    # Build filtered queryset — get distinct ServerUnique ids
    query_param = request.POST.get('query', '')
    qs, is_filtered = _build_filtered_queryset(request, query_param)
    server_unique_ids = list(
        qs.values_list('server_unique_id', flat=True).distinct()
    )
    total = len(server_unique_ids)

    if total == 0:
        return JsonResponse({'error': 'No servers match the current filters.'}, status=404)

    mismatch = selection_mismatch(total, request.POST.get('expected_servers'))
    if mismatch:
        logger.warning(f"[DR Reset] {request.user.username} refused: {total} servers selected, page showed {request.POST.get('expected_servers')}")
        return JsonResponse({'error': mismatch}, status=409)

    logger.info(
        f"[DR Reset] {username} started reset — {total} servers, "
        f"filtered={is_filtered}, fields={selected_fields}, keep_history={keep_history}"
    )
    job_id = start_job(meta={
        'total':           total,
        'keep_history':    keep_history,
        'selected_fields': selected_fields,
        'is_filtered':     is_filtered,
        'username':        username,
    })

    threading.Thread(
        target=_run_reset_job,
        args=(job_id, server_unique_ids, selected_fields, keep_history, username),
        daemon=True,
    ).start()

    return JsonResponse({'job_id': str(job_id), 'total': total})


def _run_reset_job(
    job_id: str,
    server_unique_ids: list,
    selected_fields: list,
    keep_history: bool,
    username: str,
) -> None:
    """
    Background thread: reset selected ServerUnique BC fields in batches.
    Only processes the pre-filtered list of ServerUnique ids.
    """
    import datetime

    BATCH_SIZE = 200

    def upd(progress, message, log_line=None):
        update_job(job_id, progress, message, log_line)

    try:
        upd(5, 'Loading servers...')

        all_ids = server_unique_ids
        total   = len(all_ids)

        upd(10, f'{total} servers to reset.',
            f'DR Reset by {username} — fields={selected_fields}, keep_history={keep_history}')

        reset_count  = 0

        # Fields to pass to bulk_update: selected fields + history if wiping
        fields_to_update = list(selected_fields)
        if not keep_history:
            # Only wipe _history fields that correspond to selected fields
            for f in RESET_FIELDS_HISTORY:
                base = f.replace('_history', '')
                if base in selected_fields:
                    fields_to_update.append(f)
            fields_to_update.append('global_history')
        else:
            fields_to_update.append('global_history')

        for i in range(0, total, BATCH_SIZE):
            batch_ids  = all_ids[i:i + BATCH_SIZE]
            batch_objs = list(ServerUnique.objects.filter(id__in=batch_ids))

            for su in batch_objs:
                # Build change record for global_history
                changes = {
                    field: {'old': getattr(su, field), 'new': 'EMPTY'}
                    for field in selected_fields
                    if getattr(su, field) not in ('EMPTY', None, '')
                }

                # Reset selected fields to EMPTY
                for field in selected_fields:
                    setattr(su, field, 'EMPTY')

                # Handle history
                if not keep_history:
                    for f in RESET_FIELDS_HISTORY:
                        base = f.replace('_history', '')
                        if base in selected_fields:
                            setattr(su, f, None)
                    su.global_history = []
                    # The wipe itself stays traced: who, when, and what was reset
                    su.append_global_history(
                        changes={**changes, 'history_wiped': {'info': 'Change history wiped by DR Reset'}},
                        username=username,
                        source='DR Reset',
                    )
                else:
                    if changes:
                        su.append_global_history(
                            changes=changes,
                            username=username,
                            source='DR Reset',
                        )

            from django.db import transaction
            with transaction.atomic():
                ServerUnique.objects.bulk_update(batch_objs, fields_to_update)

            reset_count += len(batch_objs)
            progress = 10 + (reset_count / total) * 88
            upd(
                progress,
                f'Resetting… {reset_count}/{total}',
                log_line=(
                    f'✓ Batch {i // BATCH_SIZE + 1} — {len(batch_objs)} servers reset'
                    if (i // BATCH_SIZE) % 5 == 0 else None
                ),
            )

        fields_str = ', '.join(selected_fields)
        upd(99, 'Finalizing...',
            f'✓ {reset_count} servers reset — fields: {fields_str}')

        logger.info(
            f"[DR Reset] {username} completed — {reset_count} servers reset, "
            f"fields={selected_fields}, keep_history={keep_history}"
        )
        finish_job(job_id, stats={
            'total':           reset_count,
            'fields':          selected_fields,
            'keep_history':    keep_history,
            'message': (
                f'DR Reset complete: {reset_count} servers reset '
                f'({fields_str}). '
                + ('History preserved.' if keep_history else 'History wiped.')
            ),
        })

    except Exception as exc:
        logger.error(f"[DR Reset] {username} — unexpected error: {exc}", exc_info=True)
        fail_job(job_id, error=f'Unexpected error: {exc}')


@login_required
@require_http_methods(["GET"])
def reset_dr_status(request, job_id):
    """Polling endpoint for reset_dr progress."""
    return get_job_response(job_id)
 