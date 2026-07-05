import json
import os
import socket
import threading
import uuid

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.cache import cache
from django.db.models import Q, F
from django.http import FileResponse, JsonResponse
from django.shortcuts import render, redirect
from urllib.parse import urlencode, parse_qs, unquote
from collections import defaultdict
from threading import Lock

from common.views import generate_charts
from .exports import generate_csv, generate_excel, EXPORT_DIR
from .models import Application, ImportStatus
from userapp.models import UserProfile, SavedSearch


app_name = __package__.split('.')[-1]

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

        except (OSError, json.JSONDecodeError) as e:
            print(f"[get_field_labels] Error loading field_labels.json: {e}")
            return _field_labels_cache

    return _field_labels_cache


def construct_query(key, terms):
    # Creates a Django Q object based on a list of terms for a specific field
    query = Q()

    for term in terms:
        if term.startswith('@'):
            term = term[1:]
            query |= Q(**{f'{key}__iexact': term})
        elif term.startswith('!'):
            term = term[1:]
            query &= ~Q(**{f'{key}__icontains': term})
        else:
            query |= Q(**{f'{key}__icontains': term})

    return query


# View to display the application information - Main View
@login_required
def application_view(request):

    localhostname = socket.gethostname()

    try:
        profile = UserProfile.objects.get(user=request.user)
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    json_data = get_field_labels()

    # Initialize the filters dictionary
    filters = {}

    for field_key, field_info in json_data['fields'].items():
        input_name = field_info.get('inputname')
        if not input_name:
            continue
        filter_value = request.GET.get(input_name, '').split(',')
        filters[field_key] = [v for v in filter_value if v]

    all_applications = Application.objects.all()

    combined_filter_query = Q()
    for key, values in filters.items():
        if not values:
            continue
        query = construct_query(key, values)
        combined_filter_query &= query

    if combined_filter_query:
        all_applications = all_applications.filter(combined_filter_query)

    sort_field = request.GET.get('sort', 'APPLICATION_AUID')
    sort_order = request.GET.get('order', 'asc')

    valid_sort_fields = {f_key for f_key in json_data.get('fields', {}).keys()}
    if sort_field not in valid_sort_fields:
        sort_field = 'APPLICATION_AUID'
    order_expr = F(sort_field).asc(nulls_last=True) if sort_order == 'asc' else F(sort_field).desc(nulls_last=True)

    filtered_applications = all_applications.order_by(order_expr)

    page_size = int(request.GET.get('page_size', 50))

    json_data_categories = json_data.get("categories", {})
    json_data_fields = json_data.get("fields", {})

    finalfields = [(field, info) for field, info in json_data_fields.items()]

    table_fields = []
    cacheset = False
    for key, val in finalfields:
        listbox_value = val.get("listbox", '')
        if listbox_value:
            cache_key = f"listbox_applications_{key}"
            listbox_evaluated = cache.get(cache_key)
            if not listbox_evaluated:
                listbox_evaluated = Application.objects.values_list(key, flat=True).distinct().order_by(key)

                if listbox_evaluated:
                    listbox_evaluated = list(listbox_evaluated)
                    if any(x is None or x.upper() == "EMPTY" for x in listbox_evaluated):
                        has_na = any(isinstance(x, str) and x.upper() == "EMPTY" for x in listbox_evaluated)
                        listbox_evaluated = [
                            x for x in listbox_evaluated if x is not None and x != "" and x.upper() != "EMPTY"
                        ]
                        listbox_evaluated.sort()
                        if has_na:
                            listbox_evaluated.append("EMPTY")

                cache.set(cache_key, listbox_evaluated, timeout=300)
                cacheset = True
        else:
            listbox_evaluated = ''

        table_fields.append({
            "name": key,
            "displayname": val.get("displayname", key),
            "inputname": val.get("inputname", key),
            "listbox": listbox_evaluated,
            "listboxmsg": val.get("listboxmsg", 'Select an option'),
            "listid": val.get("listid", 'missingid'),
            "selectionsection": val.get("selectionsection", 'cat0'),
            "fieldtype": val.get("fieldtype", ''),
        })

    grouped = defaultdict(list)
    for key, value in json_data_fields.items():
        section = value.get('selectionsection', '').strip()
        displayname = value.get('displayname', '').strip() or key
        ischecked = bool(value.get('ischecked') == "True")
        ischeckeddisabled = bool(value.get('ischeckeddisabled') == "True")

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
        if cat in grouped and cat != 'cat0'
    ]

    last_status = ImportStatus.objects.order_by('-date_import').first()

    model_fields = []
    for field_name, field_info in json_data['fields'].items():
        model_fields.append({
            'name': field_name,
            'verbose_name': field_info.get('displayname', field_name.replace('_', ' ').title()),
            'is_hostname': field_name == 'APPLICATION_AUID'
        })

    paginator = Paginator(filtered_applications, page_size)
    page_obj_raw = paginator.get_page(request.GET.get('page'))

    current_page_applications = list(page_obj_raw)

    display_applications = []
    for application in current_page_applications:
        display_applications.append({
            'hostname': application.APPLICATION_AUID,
            'primary_server': application,
        })

    page_obj = create_page_wrapper(display_applications, page_obj_raw)
    total_applications_stat = paginator.count

    saved_searches = SavedSearch.objects.filter(
        user_profile__user=request.user, view=app_name
    ).order_by('name')

    context = {
        'page_obj': page_obj,
        'table_fields': table_fields,
        'category_fields': category_fields,
        'appname': app_name,
        'page_size': page_size,
        'current_filters': filters,
        'json_data': json.dumps(json_data),
        'last_status': last_status,
        'loggedonuser': request.user,
        'model_fields': model_fields,
        'total_applications': total_applications_stat,
        'cacheset': cacheset,
        'sort_field': sort_field,
        'sort_order': sort_order,
        'localhostname': localhostname,
        'saved_searches': saved_searches,
    }

    return render(request, f'{app_name}/applications.html', context)


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


@login_required
def chart_view(request):
    # Generate charts based on the filtered data

    json_data = get_field_labels()

    selected_fields = request.GET.getlist('fields')
    chart_types = request.GET.getlist('types')

    requestfilters = {}
    for key, value in request.GET.items():
        requestfilters[key] = value

    applications = _get_filtered_applications_for_export(requestfilters)

    fields_to_extract = ['APPLICATION_AUID'] + selected_fields
    application_data = list(applications.values(*fields_to_extract).distinct())

    field_totals = {}
    for field in selected_fields:
        unique_combos = set()
        for application in application_data:
            auid = application.get('APPLICATION_AUID')
            value = application.get(field, 'Unknown')
            if value is None or value == '':
                value = 'Unknown'
            unique_combos.add((auid, str(value)))
        field_totals[field] = len(unique_combos)

    return generate_charts(request, application_data, json_data, selected_fields, chart_types, field_totals, default_keyfield='APPLICATION_AUID')


def _get_filtered_applications_for_export(requestfilters):
    # Build a filtered queryset from URL params dict (inputname -> value)
    json_data = get_field_labels()
    all_applications = Application.objects.all()
    combined_filter_query = Q()

    for field_key, field_info in json_data['fields'].items():
        input_name = field_info.get('inputname')
        if not input_name:
            continue

        raw = requestfilters.get(input_name, '')
        values = [v for v in (raw.split(',') if isinstance(raw, str) else raw) if v]
        if values:
            query = construct_query(field_key, values)
            combined_filter_query &= query

    if combined_filter_query:
        all_applications = all_applications.filter(combined_filter_query)

    sort_field = requestfilters.get('sort', 'APPLICATION_AUID')
    sort_order = requestfilters.get('order', 'asc')

    valid_sort_fields = set(json_data.get('fields', {}).keys())
    if sort_field not in valid_sort_fields:
        sort_field = 'APPLICATION_AUID'
    order_expr = F(sort_field).asc(nulls_last=True) if sort_order == 'asc' else F(sort_field).desc(nulls_last=True)

    return all_applications.order_by(order_expr)


# Handles the export of application data to a specified file format (CSV or XLSX)
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

    applications = _get_filtered_applications_for_export(requestfilters)

    os.makedirs(EXPORT_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    filepath = os.path.join(EXPORT_DIR, f"{job_id}.{filetype}")

    def background_export():
        try:
            if filetype == 'xlsx':
                generate_excel(filepath, applications, columns)
            else:
                generate_csv(filepath, applications, columns)
        except Exception as e:
            print(f"Error during export: {e}")

    threading.Thread(target=background_export).start()
    return JsonResponse({'job_id': job_id})


# Check the state of the file to export
def export_status(request, job_id, filetype):

    extension = filetype.lower()
    if extension not in ['xlsx', 'csv']:
        return JsonResponse({'Error': 'Invalid filetype'}, status=400)

    filename = f'{job_id}.{extension}'
    filepath = os.path.join(EXPORT_DIR, filename)

    if os.path.exists(filepath):
        return JsonResponse({'status': 'ready'})
    return JsonResponse({'status': 'pending'})


# Trigger the automatic download when the export file is fully created
def download_export(request, job_id, filetype):

    from django.http import Http404
    extension = filetype.lower()
    if extension not in ['xlsx', 'csv']:
        return JsonResponse({'Error': 'Invalid filetype'}, status=400)

    filename = f'{job_id}.{extension}'
    filepath = os.path.join(EXPORT_DIR, filename)

    if not os.path.exists(filepath):
        raise Http404("File not found")

    response = FileResponse(open(filepath, 'rb'), as_attachment=True, filename=f'export_{app_name}.{extension}')

    def delete_file_after_close(resp):
        try:
            os.remove(filepath)
        except Exception as e:
            print(f"Error during the removing of the file : {e}")

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
    logs = ImportStatus.objects.order_by('-date_import')[:100]

    return render(request, f"{app_name}/logs_imports.html", {
        "logs": logs
    })
