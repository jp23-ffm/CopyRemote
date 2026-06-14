import json
import os
import threading
import uuid
import socket

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.cache import cache
from django.db.models import Q, F
from django.http import FileResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from threading import Lock
from urllib.parse import parse_qs, unquote
from collections import defaultdict

from accessrights.helpers import has_perm
from common.views import generate_charts
from .exports import generate_csv, generate_excel, EXPORT_DIR
from .models import StorageShare, StorageObject, ShareAnnotation, ObjectAnnotation, StorageImportStatus
from userapp.models import UserProfile, SavedSearch

import os as _os

app_name = __package__.split('.')[-1]

# ------- Field labels cache (thread-safe, mtime-based) -------

_share_labels_cache = None
_share_labels_mtime = 0
_object_labels_cache = None
_object_labels_mtime = 0
_cache_lock = Lock()


def _load_field_labels(filename):
    global _share_labels_cache, _share_labels_mtime, _object_labels_cache, _object_labels_mtime

    is_share = 'storage_field' in filename
    cache_val = _share_labels_cache if is_share else _object_labels_cache
    cache_mtime = _share_labels_mtime if is_share else _object_labels_mtime

    json_path = _os.path.join(_os.path.dirname(__file__), filename)

    try:
        current_mtime = _os.path.getmtime(json_path)
    except OSError:
        return cache_val

    if cache_val is not None and current_mtime == cache_mtime:
        return cache_val

    with _cache_lock:
        try:
            current_mtime = _os.path.getmtime(json_path)
        except OSError:
            return cache_val
        cache_val2 = _share_labels_cache if is_share else _object_labels_cache
        cache_mtime2 = _share_labels_mtime if is_share else _object_labels_mtime
        if cache_val2 is not None and current_mtime == cache_mtime2:
            return cache_val2
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if is_share:
                _share_labels_cache = data
                _share_labels_mtime = current_mtime
            else:
                _object_labels_cache = data
                _object_labels_mtime = current_mtime
            return data
        except (OSError, json.JSONDecodeError) as e:
            print(f"[storage] Error loading {filename}: {e}")
            return cache_val


def get_share_field_labels():
    return _load_field_labels('storage_field_labels.json')


def get_object_field_labels():
    return _load_field_labels('objects_field_labels.json')


# ------- Query helpers -------

def construct_query(key, terms):
    query = Q()
    for term in terms:
        if term.startswith('@'):
            query |= Q(**{f'{key}__iexact': term[1:]})
        elif term.startswith('!'):
            query &= ~Q(**{f'{key}__icontains': term[1:]})
        else:
            query |= Q(**{f'{key}__icontains': term})
    return query


# ------- Generic filtered queryset builder (for exports and charts) -------

def _get_filtered_queryset(model_cls, annotation_cls, annotation_key_field,
                           get_field_labels_fn, requestfilters):
    json_data = get_field_labels_fn()
    queryset = model_cls.objects.all()
    combined = Q()

    for field_key, field_info in json_data['fields'].items():
        if field_key == 'ANNOTATION':
            continue
        input_name = field_info.get('inputname')
        if not input_name:
            continue
        raw = requestfilters.get(input_name, '')
        values = [v for v in (raw.split(',') if isinstance(raw, str) else raw) if v]
        if values:
            combined &= construct_query(field_key, values)

    if combined:
        queryset = queryset.filter(combined)

    sort_field = requestfilters.get('sort', 'ID')
    sort_order = requestfilters.get('order', 'asc')
    valid = set(json_data.get('fields', {}).keys()) - {'ANNOTATION'}
    if sort_field not in valid:
        sort_field = 'ID'
    order_expr = F(sort_field).asc(nulls_last=True) if sort_order == 'asc' else F(sort_field).desc(nulls_last=True)
    return queryset.order_by(order_expr)


# ------- Page wrapper (same pattern as hardware) -------

def _create_page_wrapper(object_list, source_page):
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


# ------- Generic table view -------

def _table_view(request, model_cls, annotation_cls, annotation_key_field,
                get_field_labels_fn, template_name, perm_code, resource_type,
                view_display_name, item_display_name, saved_search_view):

    localhostname = socket.gethostname()
    edit_mode = has_perm(request.user, perm_code)

    try:
        profile = UserProfile.objects.get(user=request.user)
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    json_data = get_field_labels_fn()

    # Build filters from URL params
    filters = {}
    for field_key, field_info in json_data['fields'].items():
        input_name = field_info.get('inputname')
        if not input_name:
            continue
        filter_value = request.GET.get(input_name, '').split(',')
        filters[field_key] = [v for v in filter_value if v]

    # Apply filters to queryset
    queryset = model_cls.objects.all()
    combined_filter_query = Q()
    for key, values in filters.items():
        if not values or key == 'ANNOTATION':
            continue
        combined_filter_query &= construct_query(key, values)

    if combined_filter_query:
        queryset = queryset.filter(combined_filter_query)

    # ANNOTATION filter
    annotation_terms = [v for v in filters.get('ANNOTATION', []) if v]
    if annotation_terms:
        matching_ids = annotation_cls.objects.filter(
            construct_query('comment', annotation_terms)
        ).values_list(annotation_key_field, flat=True)
        queryset = queryset.filter(ID__in=matching_ids)

    # Sort
    sort_field = request.GET.get('sort', 'ID')
    sort_order = request.GET.get('order', 'asc')
    valid_sort_fields = set(json_data.get('fields', {}).keys())
    if sort_field not in valid_sort_fields:
        sort_field = 'ID'
    order_expr = F(sort_field).asc(nulls_last=True) if sort_order == 'asc' else F(sort_field).desc(nulls_last=True)
    queryset = queryset.order_by(order_expr)

    # Pagination
    page_size = int(request.GET.get('page_size', 50))

    # Build fields config for sidebar and table headers
    json_data_categories = json_data.get('categories', {})
    json_data_fields = dict(json_data.get('fields', {}))

    if 'ANNOTATION' in json_data_fields and not edit_mode:
        json_data_fields = {k: v for k, v in json_data_fields.items() if k != 'ANNOTATION'}

    table_fields = []
    cacheset = False
    for key, val in json_data_fields.items():
        listbox_value = val.get('listbox', '')
        listempty_value = val.get('listempty', '')
        if listbox_value:
            cache_key = f'listbox_storage_{resource_type}_{key}'
            listbox_evaluated = cache.get(cache_key)
            if listbox_evaluated is None:
                if listempty_value == 'True':
                    listbox_evaluated = ['MISSING']
                else:
                    listbox_evaluated = list(
                        model_cls.objects.values_list(key, flat=True).distinct().order_by(key)
                    )
                if listbox_evaluated:
                    has_empty = any(isinstance(x, str) and x.upper() == 'EMPTY' for x in listbox_evaluated)
                    listbox_evaluated = [
                        x for x in listbox_evaluated
                        if x is not None and x != '' and not (isinstance(x, str) and x.upper() == 'EMPTY')
                    ]
                    listbox_evaluated.sort()
                    if has_empty:
                        listbox_evaluated.append('EMPTY')
                cache.set(cache_key, listbox_evaluated, timeout=3600)
                cacheset = True
        else:
            listbox_evaluated = ''

        table_fields.append({
            'name': key,
            'displayname': val.get('displayname', key),
            'inputname': val.get('inputname', key),
            'listbox': listbox_evaluated,
            'listboxmsg': val.get('listboxmsg', 'Select an option'),
            'listid': val.get('listid', 'missingid'),
            'selectionsection': val.get('selectionsection', 'cat0'),
            'fieldtype': val.get('fieldtype', ''),
        })

    # Category sidebar
    grouped = defaultdict(list)
    for key, value in json_data_fields.items():
        if isinstance(value, dict):
            section = value.get('selectionsection', '').strip()
            displayname = value.get('displayname', '').strip() or key
            ischecked = value.get('ischecked') == 'True'
            ischeckeddisabled = value.get('ischeckeddisabled') == 'True'
            if section in json_data_categories:
                grouped[section].append({
                    'key': key,
                    'displayname': displayname,
                    'ischecked': ischecked,
                    'ischeckeddisabled': ischeckeddisabled,
                })

    category_fields = [
        {'category': cat, 'title': json_data_categories[cat], 'fields': grouped[cat]}
        for cat in json_data_categories
        if cat in grouped and cat != 'cat0'
    ]

    last_status = StorageImportStatus.objects.filter(source=resource_type).order_by('-date_import').first()

    model_fields = []
    for field_name, field_info in json_data['fields'].items():
        model_fields.append({
            'name': field_name,
            'verbose_name': field_info.get('displayname', field_name.replace('_', ' ').title()),
            'is_hostname': field_name == 'ID',
        })

    # Paginate
    paginator = Paginator(queryset, page_size)
    page_obj_raw = paginator.get_page(request.GET.get('page'))
    current_page_items = list(page_obj_raw)

    display_items = [{'hostname': item.ID, 'primary_server': item} for item in current_page_items]

    ids_in_page = [s['hostname'] for s in display_items]
    annotations = annotation_cls.objects.filter(**{f'{annotation_key_field}__in': ids_in_page})
    annotations_dict = {getattr(ann, annotation_key_field): ann for ann in annotations}
    for item in display_items:
        item['annotation'] = annotations_dict.get(item['hostname'])

    page_obj = _create_page_wrapper(display_items, page_obj_raw)

    saved_searches = SavedSearch.objects.filter(
        user_profile__user=request.user, view=saved_search_view
    ).order_by('name')

    context = {
        'page_obj': page_obj,
        'table_fields': table_fields,
        'category_fields': category_fields,
        'appname': app_name,
        'resource_type': resource_type,
        'edit_mode': edit_mode,
        'page_size': page_size,
        'current_filters': filters,
        'json_data': json.dumps(json_data),
        'last_status': last_status,
        'loggedonuser': request.user,
        'model_fields': model_fields,
        'total_count': paginator.count,
        'cacheset': cacheset,
        'sort_field': sort_field,
        'sort_order': sort_order,
        'localhostname': localhostname,
        'saved_searches': saved_searches,
        'view_display_name': view_display_name,
        'item_display_name': item_display_name,
        'annotation_url_base': f'/storage/annotation/{resource_type}/',
        'bulk_annotation_url': f'/storage/bulk-annotation/{resource_type}/',
        'export_url_base': f'/storage/export/{resource_type}/',
        'export_status_url_base': '/storage/export-status/',
        'export_download_url_base': '/storage/export-download/',
        'save_search_url': reverse('storage:save_search', args=[resource_type]),
        'load_search_url_pattern': f'/storage/load-search/{resource_type}/SEARCH_ID/',
        'delete_search_url_pattern': f'/storage/delete-search/{resource_type}/SEARCH_ID/',
        'logs_imports_url': reverse('storage:logs_imports'),
        'charts_url': f'/storage/charts/{resource_type}/',
        'app_base_url': f'/storage/{"objects/" if resource_type == "object" else ""}',
        'validation_errors': {},
    }

    return render(request, template_name, context)


# ------- Main views -------

@login_required
def storage_view(request):
    return _table_view(
        request,
        model_cls=StorageShare,
        annotation_cls=ShareAnnotation,
        annotation_key_field='SHARE_ID',
        get_field_labels_fn=get_share_field_labels,
        template_name='storage/storage.html',
        perm_code='storage.annotations',
        resource_type='share',
        view_display_name='Storage',
        item_display_name='NAS Shares',
        saved_search_view='storage-share',
    )


@login_required
def objects_view(request):
    return _table_view(
        request,
        model_cls=StorageObject,
        annotation_cls=ObjectAnnotation,
        annotation_key_field='OBJECT_ID',
        get_field_labels_fn=get_object_field_labels,
        template_name='storage/objects.html',
        perm_code='storage.annotations',
        resource_type='object',
        view_display_name='Storage - Objects',
        item_display_name='S3 Objects',
        saved_search_view='storage-object',
    )


# ------- Annotation views -------

@login_required
def edit_annotation(request, resource_type, resource_id):
    if resource_type == 'share':
        annotation_cls, key_field = ShareAnnotation, 'SHARE_ID'
    elif resource_type == 'object':
        annotation_cls, key_field = ObjectAnnotation, 'OBJECT_ID'
    else:
        return JsonResponse({'success': False, 'message': 'Invalid resource type'}, status=400)

    annotation = annotation_cls.objects.filter(**{key_field: resource_id}).first()

    if request.method == 'GET':
        return JsonResponse({
            'hostname': resource_id,
            'comment': annotation.comment if annotation else '',
            'assigned_to': annotation.assigned_to if annotation else '',
            'history': annotation.get_history_display() if annotation else [],
        })

    if request.method == 'POST':
        comment = request.POST.get('comment', '').strip()
        assigned_to = request.POST.get('assigned_to', '').strip()
        if not annotation:
            annotation = annotation_cls(**{key_field: resource_id})
        annotation.add_entry(comment, assigned_to, request.user)
        return JsonResponse({
            'success': True,
            'message': 'Annotation saved successfully',
            'comment': annotation.comment,
            'assigned_to': annotation.assigned_to,
            'history': annotation.get_history_display(),
            'updated_by': request.user.username,
            'updated_at': annotation.updated_at.strftime('%d/%m/%Y %H:%M'),
        })

    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)


@login_required
def bulk_annotation(request, resource_type):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid Request Method'}, status=400)

    if resource_type == 'share':
        model_cls, annotation_cls, key_field = StorageShare, ShareAnnotation, 'SHARE_ID'
        get_labels = get_share_field_labels
    elif resource_type == 'object':
        model_cls, annotation_cls, key_field = StorageObject, ObjectAnnotation, 'OBJECT_ID'
        get_labels = get_object_field_labels
    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid resource type'}, status=400)

    try:
        query_param = request.POST.get('query')
        if not query_param:
            return JsonResponse({'status': 'error', 'message': 'Query string not provided'}, status=400)

        query_param = unquote(query_param)
        parsed_query = parse_qs(query_param)
        json_data = get_labels()

        items_to_update = model_cls.objects.all()
        filters = {}
        for field_key, field_info in json_data['fields'].items():
            if 'inputname' in field_info:
                filters[field_key] = parsed_query.get(field_info['inputname'], [''])[0].split(',')
        filters = {k: v for k, v in filters.items() if v != ['']}

        for key, value in filters.items():
            if key == 'ANNOTATION':
                continue
            terms = value if isinstance(value, list) else [value]
            items_to_update = items_to_update.filter(construct_query(key, terms))

        total_updates = items_to_update.count()
        if total_updates == 0:
            return JsonResponse({'status': 'warning', 'message': 'No records to update'}, status=200)

        bulk_comment = request.POST.get('bulk_comment', '')
        bulk_assigned_to = request.POST.get('bulk_assigned_to', '')

        def update_with_progress():
            batch_size = 50
            total_batches = (total_updates + batch_size - 1) // batch_size
            for i in range(total_batches):
                batch = items_to_update[i * batch_size:(i + 1) * batch_size]
                for item in batch:
                    ann, _ = annotation_cls.objects.get_or_create(**{key_field: item.ID})
                    ann.add_entry(bulk_comment, bulk_assigned_to, request.user)
                progress = ((i + 1) / total_batches) * 100
                yield f'data: progress:{progress}|batch:{i + 1}\n\n'

        response = StreamingHttpResponse(update_with_progress(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        return response

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Unexpected error: {e}'}, status=500)


# ------- Chart view -------

@login_required
def chart_view(request, resource_type):
    if resource_type == 'share':
        model_cls, annotation_cls, key_field = StorageShare, ShareAnnotation, 'SHARE_ID'
        get_labels = get_share_field_labels
    elif resource_type == 'object':
        model_cls, annotation_cls, key_field = StorageObject, ObjectAnnotation, 'OBJECT_ID'
        get_labels = get_object_field_labels
    else:
        return JsonResponse({'error': 'Invalid resource type'}, status=400)

    json_data = get_labels()
    selected_fields = request.GET.getlist('fields')
    chart_types = request.GET.getlist('types')
    requestfilters = dict(request.GET.items())

    items = _get_filtered_queryset(model_cls, annotation_cls, key_field, get_labels, requestfilters)
    fields_to_extract = ['ID'] + [f for f in selected_fields if f != 'ANNOTATION']
    item_data = list(items.values(*fields_to_extract).distinct())

    field_totals = {}
    for field in selected_fields:
        unique_combos = set()
        for row in item_data:
            val = row.get(field, 'Unknown') or 'Unknown'
            unique_combos.add((row.get('ID'), str(val)))
        field_totals[field] = len(unique_combos)

    return generate_charts(request, item_data, json_data, selected_fields, chart_types, field_totals, default_keyfield='ID')


# ------- Export views -------

@login_required
def export_to_file(request, resource_type, filetype):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not authorized'}, status=405)

    filetype = filetype.lower()
    if filetype not in ['xlsx', 'csv']:
        return JsonResponse({'error': 'Invalid format type'}, status=400)

    if resource_type == 'share':
        model_cls, annotation_cls, key_field = StorageShare, ShareAnnotation, 'SHARE_ID'
        get_labels = get_share_field_labels
    elif resource_type == 'object':
        model_cls, annotation_cls, key_field = StorageObject, ObjectAnnotation, 'OBJECT_ID'
        get_labels = get_object_field_labels
    else:
        return JsonResponse({'error': 'Invalid resource type'}, status=400)

    import json as _json
    data = _json.loads(request.body)
    requestfilters = data.get('filters', {})
    columns = data.get('columns', [])

    items = _get_filtered_queryset(model_cls, annotation_cls, key_field, get_labels, requestfilters)
    id_list = list(items.values_list('ID', flat=True))
    annotations_dict = {}
    if id_list:
        anns = annotation_cls.objects.filter(**{f'{key_field}__in': id_list})
        annotations_dict = {getattr(a, key_field): a for a in anns}

    import os as _os2
    _os2.makedirs(EXPORT_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    filepath = _os2.path.join(EXPORT_DIR, f'{job_id}.{filetype}')

    def background_export():
        try:
            if filetype == 'xlsx':
                generate_excel(filepath, items, annotations_dict, columns)
            else:
                generate_csv(filepath, items, annotations_dict, columns)
        except Exception as e:
            print(f'[storage] Export error: {e}')

    threading.Thread(target=background_export).start()
    return JsonResponse({'job_id': job_id})


def export_status(request, job_id, filetype):
    extension = filetype.lower()
    if extension not in ['xlsx', 'csv']:
        return JsonResponse({'error': 'Invalid filetype'}, status=400)
    import os as _os3
    filepath = _os3.path.join(EXPORT_DIR, f'{job_id}.{extension}')
    if _os3.path.exists(filepath):
        return JsonResponse({'status': 'ready'})
    return JsonResponse({'status': 'pending'})


def download_export(request, job_id, filetype):
    from django.http import Http404
    import os as _os4
    extension = filetype.lower()
    if extension not in ['xlsx', 'csv']:
        return JsonResponse({'error': 'Invalid filetype'}, status=400)
    filepath = _os4.path.join(EXPORT_DIR, f'{job_id}.{extension}')
    if not _os4.path.exists(filepath):
        raise Http404('File not found')
    response = FileResponse(open(filepath, 'rb'), as_attachment=True, filename=f'export_storage.{extension}')

    def delete_after(resp):
        try:
            _os4.remove(filepath)
        except Exception:
            pass

    response.close = lambda *a, **kw: delete_after(response)
    return response


# ------- Saved search views -------

@login_required
def save_search(request, resource_type):
    if resource_type == 'share':
        view_key = 'storage-share'
    elif resource_type == 'object':
        view_key = 'storage-object'
    else:
        return JsonResponse({'success': False, 'message': 'Invalid resource type'})

    if request.method == 'POST':
        search_name = request.POST.get('search_name', '').strip()
        if len(search_name) > 25:
            return JsonResponse({'success': False, 'message': 'Search name must be 25 characters or fewer.'})
        profile = UserProfile.objects.get(user=request.user)
        if SavedSearch.objects.filter(user_profile=profile, name=search_name, view=view_key).exists():
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
            filters=search_params, tags=tags, view=view_key,
        )
        return redirect(request.META.get('HTTP_REFERER', '/'))
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})


@login_required
def load_search(request, resource_type, search_id):
    if resource_type == 'share':
        redirect_url = '/storage/'
    else:
        redirect_url = '/storage/objects/'
    from urllib.parse import urlencode
    saved_search = SavedSearch.objects.get(id=search_id, user_profile__user=request.user)
    query_string = urlencode(saved_search.filters, doseq=True)
    return redirect(f'{redirect_url}?{query_string}')


@login_required
def delete_search(request, resource_type, search_id):
    saved_search = SavedSearch.objects.get(id=search_id, user_profile__user=request.user)
    saved_search.delete()
    return redirect(request.META.get('HTTP_REFERER', '/'))


# ------- Import logs -------

def log_imports(request):
    logs = StorageImportStatus.objects.order_by('-date_import')[:100]
    return render(request, 'storage/logs_imports.html', {'logs': logs})
