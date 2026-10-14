"""Missing-data discrepancies pages for storage shares/objects (dashboard, list, exports)."""

import copy
import datetime
import json
import os
import threading
import uuid
from urllib.parse import parse_qs, unquote, urlencode

from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.db.models.functions import Trim, Upper
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accessrights.helpers import has_perm
from common.views import generate_charts
from discrepancies.models import safe_percentage_clean
from userapp.models import UserProfile, SavedSearch

from .discrepancy_utils import (
    resource_config, required_fields, get_config, discrepancy_queryset, tracker_map,
    days_open_cutoff, days_open_from, is_missing, region_groups, expand_region, aggregate_breakdown,
)
from .exports import generate_csv, generate_excel, EXPORT_DIR
from .models import StorageAnalysisSnapshot, StorageDiscrepancy, StorageDiscrepancyTracking, StorageImportStatus
from .views import (
    _table_view, _get_filtered_queryset, construct_query, get_share_field_labels, get_object_field_labels,
)

EDIT_PERM = 'storage.annotations'

# Value used in the required-field columns' listbox / filters to select missing values
MISSING_TOKEN = 'MISSING'


def _get_conf_or_404(resource_type):
    conf = resource_config(resource_type)
    if conf is None:
        raise Http404('Unknown resource type')
    return conf


def _base_field_labels(resource_type):
    return get_share_field_labels() if resource_type == 'share' else get_object_field_labels()


def _disc_field_labels(resource_type):
    """
    Regular field labels, with the required fields moved right after the primary column (one
    column per checked field, like the Discrepancies servers page) followed by DAYS_OPEN.
    """
    base = _base_field_labels(resource_type)
    primary = resource_config(resource_type)['primary_field']
    required = required_fields(resource_type)

    extra = {}
    for code, label in required.items():
        info = dict(base['fields'].get(code, {}))
        input_name = info.get('inputname', code.lower())
        info.update({
            'displayname': label, 'selectionsection': 'catdisc', 'ischecked': 'True',
            'inputname': input_name, 'listbox': 'missing', 'listboxmsg': label, 'listid': input_name,
        })
        extra[code] = info
    extra['DAYS_OPEN'] = {
        'displayname': 'Days Open', 'selectionsection': 'catdisc', 'ischecked': 'True', 'inputname': 'daysopen',
    }

    fields = {}
    for key, val in base['fields'].items():
        if key in required:
            continue
        fields[key] = val
        if key == primary:
            fields.update(extra)
    data = copy.deepcopy({k: v for k, v in base.items() if k not in ('fields', 'categories')})
    data['categories'] = {'catdisc': 'Discrepancy', **base.get('categories', {})}
    data['fields'] = fields
    return data


def _with_trim(qs, field):
    return qs.annotate(**{f'_TRIM_{field}': Upper(Trim(field))})


def _missing_q(field):
    """Q matching rows where `field` is null or an invalid value (trimmed, case-insensitive); needs _with_trim."""
    return Q(**{f'{field}__isnull': True}) | Q(**{f'_TRIM_{field}__in': get_config()['invalid_values']})


def _is_missing_term(term):
    return term.lstrip('@!').strip().upper() == MISSING_TOKEN


def _selected_field_codes(resource_type, requestfilters):
    """Required fields currently filtered on MISSING (drives context-sensitive days_open)."""
    labels = _disc_field_labels(resource_type)['fields']
    selected = set()
    for code in required_fields(resource_type):
        raw = requestfilters.get(labels[code]['inputname'], '')
        terms = [t for t in (raw.split(',') if isinstance(raw, str) else raw) if t]
        if any(_is_missing_term(t) and not t.startswith('!') for t in terms):
            selected.add(code)
    return selected


def _build_hooks(resource_type, requestfilters):
    """filter/sort overrides + item decorator for the discrepancy columns, aware of the current filters."""
    selected_codes = _selected_field_codes(resource_type, requestfilters)

    def _filter_required(field):
        # "MISSING" (optionally @/! prefixed) selects/excludes rows with a missing value; any other
        # term is a regular text search on the field
        def apply(qs, values):
            missing_terms = [v for v in values if _is_missing_term(v)]
            other = [v for v in values if not _is_missing_term(v)]
            if missing_terms:
                qs = _with_trim(qs, field)
                if any(not v.startswith('!') for v in missing_terms):
                    qs = qs.filter(_missing_q(field))
                if any(v.startswith('!') for v in missing_terms):
                    qs = qs.exclude(_missing_q(field))
            if other:
                qs = qs.filter(construct_query(field, other))
            return qs
        return apply

    def filter_days_open(qs, values):
        raw = str(values[0]).lstrip('>=@ ')
        if not raw.isdigit() or int(raw) <= 0:
            return qs
        cutoff = days_open_cutoff(int(raw))
        if not selected_codes:
            return qs.filter(FIRST_SEEN__lte=cutoff)
        # Field-aware: at least one of the filtered missing fields is open for >= N days
        keys = [
            t.asset_key
            for t in StorageDiscrepancyTracking.objects.filter(resource_type=resource_type).only('asset_key', 'active_issues')
            if any(f in t.active_issues and parse_datetime(t.active_issues[f]['first_seen']) <= cutoff
                   for f in selected_codes)
        ]
        return qs.filter(ASSET_KEY__in=keys)

    def _filter_with_placeholder(field, disc_field, placeholder):
        # "No scope" / "No region" are analysis placeholders, not real values: match them on the
        # StorageDiscrepancy side, everything else on the model field as usual
        def apply(qs, values):
            placeholder_terms = [v for v in values if v.lstrip('@').strip().upper() == placeholder.upper()]
            other = [v for v in values if v not in placeholder_terms]
            query = construct_query(field, other) if other else Q()
            if placeholder_terms:
                query |= Q(**{disc_field: placeholder})
            return qs.filter(query)
        return apply

    def sort_days_open(order):
        # More days open = older first_seen
        return F('FIRST_SEEN').desc(nulls_last=True) if order == 'asc' else F('FIRST_SEEN').asc(nulls_last=True)

    codes = list(required_fields(resource_type))

    def decorate(items, filters=None):
        conf = resource_config(resource_type)
        trackers = tracker_map(resource_type, {conf['key_fn'](i) for i in items})
        now = timezone.now()
        for item in items:
            # Row-level: which required cells of THIS row are missing (rendered in red)
            item.MISSING_SET = {c for c in codes if is_missing(getattr(item, c, None))}
            tracker = trackers.get(conf['key_fn'](item))
            if not tracker:
                item.DAYS_OPEN = ''
                continue
            relevant = [v['first_seen'] for f, v in tracker.active_issues.items() if f in selected_codes]
            if relevant:
                item.DAYS_OPEN = max(days_open_from(fs, now) for fs in relevant)
            else:
                item.DAYS_OPEN = days_open_from(tracker.oldest_first_seen, now)

    filter_overrides = {code: _filter_required(code) for code in codes}
    filter_overrides.update({
        'DAYS_OPEN': filter_days_open,
        'SCOPE': _filter_with_placeholder('SCOPE', 'DISC_SCOPE', get_config()['no_scope_label']),
        'REGION': _filter_with_placeholder('REGION', 'DISC_REGION', get_config()['no_region_label']),
    })
    return {
        'filter_overrides': filter_overrides,
        'sort_overrides': {'DAYS_OPEN': sort_days_open},
        'decorate': decorate,
    }


def _filtered_items(resource_type, requestfilters):
    conf = resource_config(resource_type)
    hooks = _build_hooks(resource_type, requestfilters)
    qs = _get_filtered_queryset(
        conf['model'], conf['annotation_cls'], conf['annotation_key_field'],
        lambda: _disc_field_labels(resource_type), requestfilters,
        default_sort=conf['primary_field'], base_queryset=discrepancy_queryset(resource_type),
        filter_overrides=hooks['filter_overrides'], sort_overrides=hooks['sort_overrides'],
    )
    return qs, hooks


def _placeholder_last(values, placeholder):
    """Sorted values with the "No scope"/"No region" placeholder kept last, like EMPTY in the listboxes."""
    values = sorted(v for v in set(values) if v)
    return [v for v in values if v != placeholder] + ([placeholder] if placeholder in values else [])


def _disc_values(resource_type, field):
    return StorageDiscrepancy.objects.filter(resource_type=resource_type).values_list(field, flat=True).distinct().order_by(field)


# ------- Dashboard -------

def _dashboard_counts(resource_type, region='', scope='', days_open=0):
    """(population, assets_with_issues, {field: count}) for the gauges, region/scope and days-open aware."""
    snapshot = StorageAnalysisSnapshot.objects.filter(resource_type=resource_type).first()
    if snapshot is None:
        return 0, 0, {}
    regions = expand_region(region)
    population = aggregate_breakdown(snapshot.breakdown, regions, scope)['total']

    disc_qs = StorageDiscrepancy.objects.filter(resource_type=resource_type)
    if regions:
        disc_qs = disc_qs.filter(region__in=regions)
    if scope:
        disc_qs = disc_qs.filter(scope=scope)
    rows = list(disc_qs.values_list('asset_key', 'missing_fields'))
    fields = list(required_fields(resource_type))
    field_counts = {f: 0 for f in fields}
    with_issues = 0

    if not days_open:
        for _, missing in rows:
            codes = [c for c in missing.split(',') if c]
            if codes:
                with_issues += 1
            for c in codes:
                if c in field_counts:
                    field_counts[c] += 1
        return population, with_issues, field_counts

    # Each gauge checks its own field's first_seen; the "any" gauge uses the oldest issue
    cutoff = days_open_cutoff(days_open)
    trackers = tracker_map(resource_type, [k for k, _ in rows])
    for key, missing in rows:
        tracker = trackers.get(key)
        if not tracker:
            continue
        if tracker.oldest_first_seen and tracker.oldest_first_seen <= cutoff:
            with_issues += 1
        for c in missing.split(','):
            info = tracker.active_issues.get(c)
            if c in field_counts and info and parse_datetime(info['first_seen']) <= cutoff:
                field_counts[c] += 1
    return population, with_issues, field_counts


def _parse_filters(request):
    """(region, scope, days_open) from the dashboard query string."""
    region = request.GET.get('region', '').strip()
    scope = request.GET.get('scope', '').strip()
    days = request.GET.get('days_open', '').strip()
    return region, scope, int(days) if days.isdigit() else 0


@login_required
def disc_dashboard_view(request, resource_type):
    conf = _get_conf_or_404(resource_type)
    snapshot = StorageAnalysisSnapshot.objects.filter(resource_type=resource_type).first()
    list_url = reverse('storage:disc_list', args=[resource_type])
    context = {
        'title': conf['title'],
        'resource_type': resource_type,
        'item_label': conf['item_label'],
        'no_data': snapshot is None,
        'list_url': list_url,
        'other_type': 'object' if resource_type == 'share' else 'share',
        'other_label': resource_config('object' if resource_type == 'share' else 'share')['item_label'],
    }
    if snapshot is None:
        return render(request, 'storage/discrepancies_dashboard.html', context)

    region, scope, days_open = _parse_filters(request)
    population, with_issues, field_counts = _dashboard_counts(resource_type, region, scope, days_open)

    def gauge(widget_id, title, issues, size, link_params, info):
        clean = max(0, population - issues)
        pct = safe_percentage_clean(clean, population)
        return {
            'id': widget_id, 'title': title, 'size': size, 'info': info,
            'base_link': list_url + ('?' + urlencode(link_params) if link_params else ''),
            'value': pct, 'display_value': f'{pct}%',
            'issues': issues, 'clean': clean, 'total': population,
            'thresholds': json.dumps(conf['thresholds']), 'colors': json.dumps(conf['colors']),
        }

    labels = required_fields(resource_type)
    widgets = [gauge(
        'any_missing', f"Missing Data\n({conf['item_label']})", with_issues, 'large', {},
        f"{conf['item_label']} with all required fields filled ({', '.join(labels.values())})",
    )]
    disc_fields = _disc_field_labels(resource_type)['fields']
    for code, label in labels.items():
        widgets.append(gauge(
            code, label, field_counts.get(code, 0), 'small', {disc_fields[code]['inputname']: MISSING_TOKEN},
            f"{conf['item_label']} with '{label}' missing or invalid",
        ))

    trend_colors = conf.get('trend_colors', {})
    trend_metrics = [{'metric': 'any_missing', 'label': 'Any field missing', 'color': trend_colors.get('any_missing', '#A0826D')}]
    trend_metrics += [
        {'metric': code, 'label': f'Missing {label}', 'color': trend_colors.get(code, '#6c757d')}
        for code, label in labels.items()
    ]
    trend_data = _trend_data(resource_type, 'any_missing', 30, region, scope)

    # Real regions/scopes come from the snapshot, region groups (e.g. "EMEA + MEAA") from config
    snapshot_scopes = [sc for scopes in snapshot.breakdown.values() for sc in scopes]

    context.update({
        'snapshot': snapshot,
        'widgets': widgets,
        'region': region,
        'scope': scope,
        'days_open': days_open or '',
        'all_regions': _placeholder_last(snapshot.breakdown.keys(), get_config()['no_region_label']),
        'region_group_names': list(region_groups()),
        'region_groups_json': json.dumps(region_groups()),
        'all_scopes': _placeholder_last(snapshot_scopes, get_config()['no_scope_label']),
        'trend_metrics': trend_metrics,
        'trend_data_json': json.dumps(trend_data),
        'fields_json': json.dumps(labels),
    })
    return render(request, 'storage/discrepancies_dashboard.html', context)


@login_required
def disc_dashboard_filter_api(request, resource_type):
    _get_conf_or_404(resource_type)
    region, scope, days_open = _parse_filters(request)
    population, with_issues, field_counts = _dashboard_counts(resource_type, region, scope, days_open)
    return JsonResponse({'population': population, 'any_missing': with_issues, 'field_counts': field_counts})


def _trend_data(resource_type, metric, days, region='', scope=''):
    """One point per analysis run: issue count and population for the metric (region/scope aware)."""
    snapshots = StorageAnalysisSnapshot.objects.filter(resource_type=resource_type).order_by('analysis_date')
    if days:
        snapshots = snapshots.filter(analysis_date__gte=timezone.now() - datetime.timedelta(days=days))
    regions = expand_region(region)
    labels, values, totals = [], [], []
    for snap in snapshots:
        if regions or scope:
            data = aggregate_breakdown(snap.breakdown, regions, scope)
            total = data['total']
            value = data['with_issues'] if metric == 'any_missing' else data['field_counts'].get(metric, 0)
        else:
            total = snap.total_assets
            value = snap.assets_with_issues if metric == 'any_missing' else snap.field_counts.get(metric, 0)
        labels.append(timezone.localtime(snap.analysis_date).strftime('%d %b'))
        values.append(value)
        totals.append(total)
    return {'labels': labels, 'values': values, 'totals': totals}


@login_required
def disc_trend_api(request, resource_type):
    _get_conf_or_404(resource_type)
    metric = request.GET.get('metric', 'any_missing')
    if metric != 'any_missing' and metric not in required_fields(resource_type):
        return JsonResponse({'error': 'invalid metric'}, status=400)
    days_param = request.GET.get('days', '30')
    days = None if days_param == 'all' else (int(days_param) if days_param.isdigit() else 30)
    data = _trend_data(
        resource_type, metric, days, request.GET.get('region', '').strip(), request.GET.get('scope', '').strip(),
    )
    data['metric'] = metric
    return JsonResponse(data)


# ------- List page -------

@login_required
def disc_list_view(request, resource_type):
    conf = _get_conf_or_404(resource_type)
    hooks = _build_hooks(resource_type, request.GET)
    base = f'/storage/discrepancies/{resource_type}/'
    scopes = _placeholder_last(_disc_values(resource_type, 'scope'), get_config()['no_scope_label'])
    regions = _placeholder_last(_disc_values(resource_type, 'region'), get_config()['no_region_label'])

    return _table_view(
        request,
        model_cls=conf['model'],
        annotation_cls=conf['annotation_cls'],
        annotation_key_field=conf['annotation_key_field'],
        get_field_labels_fn=lambda: _disc_field_labels(resource_type),
        template_name='storage/discrepancies_list.html',
        perm_code=EDIT_PERM,
        resource_type=resource_type,
        view_display_name=f"Storage - {conf['item_label']} Missing Data",
        item_display_name=conf['item_label'],
        saved_search_view=f'storage-{resource_type}-disc',
        primary_field=conf['primary_field'],
        annotation_key_fn=conf['key_fn'],
        base_queryset=discrepancy_queryset(resource_type),
        filter_overrides=hooks['filter_overrides'],
        sort_overrides=hooks['sort_overrides'],
        listbox_overrides={
            **{code: [MISSING_TOKEN] for code in required_fields(resource_type)},
            'SCOPE': scopes, 'REGION': regions,
        },
        decorate_items_fn=hooks['decorate'],
        extra_context={
            'last_status': StorageImportStatus.objects.filter(source=f'disc-{resource_type}').order_by('-date_import').first(),
            'dashboard_url': reverse('storage:disc_dashboard', args=[resource_type]),
            'bulk_annotation_url': base + 'bulk-annotation/',
            'export_url_base': base + 'export/',
            'charts_url': base + 'charts/',
            'save_search_url': reverse('storage:disc_save_search', args=[resource_type]),
            'load_search_url_pattern': base + 'load-search/SEARCH_ID/',
            'delete_search_url_pattern': f'/storage/delete-search/{resource_type}/SEARCH_ID/',
            'app_base_url': base + 'list/',
        },
    )


# ------- Exports / charts / bulk annotation -------

@login_required
def disc_export_to_file(request, resource_type, filetype):
    conf = _get_conf_or_404(resource_type)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not authorized'}, status=405)
    filetype = filetype.lower()
    if filetype not in ('xlsx', 'csv'):
        return JsonResponse({'error': 'Invalid format type'}, status=400)

    data = json.loads(request.body)
    requestfilters = data.get('filters', {})
    columns = data.get('columns', [])

    qs, hooks = _filtered_items(resource_type, requestfilters)
    items = list(qs)
    hooks['decorate'](items)
    # Export shows MISSING for missing required fields, like the screen (in-memory only, never saved)
    for item in items:
        for code in item.MISSING_SET:
            setattr(item, code, MISSING_TOKEN)
    key_fn = conf['key_fn']
    key_field = conf['annotation_key_field']
    keys = [key_fn(i) for i in items]
    annotations = {getattr(a, key_field): a for a in conf['annotation_cls'].objects.filter(**{f'{key_field}__in': keys})} if keys else {}

    os.makedirs(EXPORT_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    filepath = os.path.join(EXPORT_DIR, f'{job_id}.{filetype}')

    def background_export():
        try:
            fn = generate_excel if filetype == 'xlsx' else generate_csv
            fn(filepath, items, annotations, columns, annotation_key_fn=key_fn)
        except Exception as e:
            print(f'[storage] Discrepancy export error: {e}')

    threading.Thread(target=background_export).start()
    return JsonResponse({'job_id': job_id})


@login_required
def disc_chart_view(request, resource_type):
    _get_conf_or_404(resource_type)
    json_data = _disc_field_labels(resource_type)
    selected_fields = [f for f in request.GET.getlist('fields') if f not in ('ANNOTATION', 'DAYS_OPEN')]
    chart_types = request.GET.getlist('types')

    qs, hooks = _filtered_items(resource_type, dict(request.GET.items()))
    items = list(qs)
    hooks['decorate'](items)
    item_data = [{'ID': i.ID, **{f: getattr(i, f, '') for f in selected_fields}} for i in items]

    field_totals = {}
    for field in selected_fields:
        field_totals[field] = len({(row['ID'], str(row.get(field) or 'Unknown')) for row in item_data})

    return generate_charts(request, item_data, json_data, selected_fields, chart_types, field_totals, default_keyfield='ID')


@login_required
def disc_bulk_annotation(request, resource_type):
    conf = _get_conf_or_404(resource_type)
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid Request Method'}, status=400)
    if not has_perm(request.user, EDIT_PERM):
        return JsonResponse({'status': 'error', 'message': 'Forbidden'}, status=403)

    query_param = request.POST.get('query')
    if not query_param:
        return JsonResponse({'status': 'error', 'message': 'Query string not provided'}, status=400)
    parsed = parse_qs(unquote(query_param))
    requestfilters = {k: v[0] for k, v in parsed.items()}

    qs, _ = _filtered_items(resource_type, requestfilters)
    # One annotation per asset key (an asset can span several rows)
    keys = list(dict.fromkeys(conf['key_fn'](i) for i in qs))
    if not keys:
        return JsonResponse({'status': 'warning', 'message': 'No records to update'}, status=200)

    bulk_comment = request.POST.get('bulk_comment', '')
    bulk_assigned_to = request.POST.get('bulk_assigned_to', '')
    annotation_cls, key_field = conf['annotation_cls'], conf['annotation_key_field']

    def update_with_progress():
        batch_size = 50
        total_batches = (len(keys) + batch_size - 1) // batch_size
        for i in range(total_batches):
            for key in keys[i * batch_size:(i + 1) * batch_size]:
                ann, _ = annotation_cls.objects.get_or_create(**{key_field: key})
                ann.add_entry(bulk_comment, bulk_assigned_to, request.user)
            yield f'data: progress:{((i + 1) / total_batches) * 100}|batch:{i + 1}\n\n'

    response = StreamingHttpResponse(update_with_progress(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    return response


# ------- Saved searches -------

@login_required
def disc_save_search(request, resource_type):
    _get_conf_or_404(resource_type)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method.'})
    view_key = f'storage-{resource_type}-disc'
    search_name = request.POST.get('search_name', '').strip()
    if len(search_name) > 25:
        return JsonResponse({'success': False, 'message': 'Search name must be 25 characters or fewer.'})
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if SavedSearch.objects.filter(user_profile=profile, name=search_name, view=view_key).exists():
        return JsonResponse({'success': False, 'message': 'A search with this name already exists.'})
    try:
        search_params = json.loads(request.POST.get('filters') or '')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid filter data.'})
    tags = json.loads(request.POST.get('tags', '[]'))
    SavedSearch.objects.create(user_profile=profile, name=search_name, filters=search_params, tags=tags, view=view_key)
    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def disc_load_search(request, resource_type, search_id):
    _get_conf_or_404(resource_type)
    saved = SavedSearch.objects.get(id=search_id, user_profile__user=request.user)
    return redirect(f"{reverse('storage:disc_list', args=[resource_type])}?{urlencode(saved.filters, doseq=True)}")
