"""Data-quality discrepancies pages for hardware assets (dashboard, list, exports)."""

import copy
import datetime
import json
import os
import socket
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Exists, F, JSONField, OrderBy, OuterRef, Q, QuerySet, Subquery, TextField
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from accessrights.helpers import has_perm
from common.views import generate_charts
from discrepancies.models import safe_percentage_clean
from userapp.models import SavedSearch, UserProfile

from . import views as hw_views
from .views import construct_query, create_page_wrapper
from .discrepancy_utils import (
    ANY_ISSUE, JsonDict, aggregate_breakdown, check_labels, checks, chunked, days_open_cutoff, days_open_from,
    discrepancy_queryset, expand_region, get_config, has_issue, is_missing, is_open_since, issue_q, issue_token,
    region_groups, tracker_map,
)
from .exports import EXPORT_DIR, generate_csv, generate_excel
from .models import Annotation, HardwareAnalysisSnapshot, HardwareDiscrepancy, HardwareDiscrepancyTracking, Server

EDIT_PERM = 'hardware.annotations'
PRIMARY_FIELD = 'SERIAL'
DASHBOARD_TEMPLATE = 'hardware/discrepancies_dashboard.html'
LIST_TEMPLATE = 'hardware/discrepancies_list.html'
SAVED_SEARCH_VIEW = 'hardware-disc'
ANY_METRIC = 'any_missing'
CSS_ISSUE = 'error-missing'
EXPORT_FORMATS = ('xlsx', 'csv')
MAX_SEARCH_NAME = 25
BULK_PROGRESS_BATCH = 50
DEFAULT_TREND_DAYS = 30


# ------- Field labels -------

def _disc_field_labels() -> JsonDict:
    """
    Hardware field labels with the checked fields moved right after SERIAL (one column per check,
    listbox offering the issue token). DAYS_OPEN comes last, in the "Status" category (can be hidden).
    """
    base = hw_views.get_field_labels()
    categories = {'catdisc': 'Discrepancy', **base.get('categories', {})}
    status_cat = next((cat for cat, title in categories.items() if title == 'Status'), 'catdisc')
    labels = check_labels()
    extra: JsonDict = {}
    for code, label in labels.items():
        info = dict(base['fields'].get(code, {}))
        input_name = info.get('inputname', code.lower())
        info.update({
            'displayname': label, 'selectionsection': 'catdisc', 'ischecked': 'True', 'inputname': input_name,
            'listbox': 'issue', 'listboxmsg': label, 'listid': input_name,
        })
        extra[code] = info

    fields: JsonDict = {}
    for key, val in base['fields'].items():
        if key in labels:
            continue
        fields[key] = val
        if key == PRIMARY_FIELD:
            fields.update(extra)
    fields['DAYS_OPEN'] = {'displayname': 'Days Open', 'selectionsection': status_cat, 'ischecked': 'True', 'inputname': 'daysopen'}
    data: JsonDict = copy.deepcopy({k: v for k, v in base.items() if k not in ('fields', 'categories')})
    data['categories'] = categories
    data['fields'] = fields
    return data


def _display_names() -> dict[str, str]:
    return {k: v.get('displayname', k) for k, v in hw_views.get_field_labels()['fields'].items()}


# ------- Filters -------

def _split_terms(raw: Any) -> list[str]:
    terms = raw.split(',') if isinstance(raw, str) else raw
    return [t for t in terms if t]


def _is_token(term: str, code: str) -> bool:
    return term.lstrip('@!').strip().upper() == issue_token(code)


def _is_positive(term: str) -> bool:
    return not term.startswith('!')


def _selected_codes(requestfilters: Any) -> set[str]:
    """Checks currently filtered on with their issue token — drives context-sensitive days_open."""
    labels = _disc_field_labels()['fields']
    return {
        code for code in checks()
        if any(_is_token(t, code) and _is_positive(t) for t in _split_terms(requestfilters.get(labels[code]['inputname'], '')))
    }


def _placeholder_split(values: list[str], placeholder: str) -> tuple[bool, list[str]]:
    """(placeholder selected, other terms): "No region"/"No country" are analysis buckets, not field values."""
    hit = [v for v in values if v.lstrip('@').strip().upper() == placeholder.upper()]
    return bool(hit), [v for v in values if v not in hit]


def _check_filter(code: str, disc_field: str = '', placeholder: str = ''):
    """Filter of a checked column: issue token selects/excludes failing rows, other terms are text search."""
    def apply(qs: QuerySet[Any], values: list[str]) -> QuerySet[Any]:
        tokens = [v for v in values if _is_token(v, code)]
        other = [v for v in values if not _is_token(v, code)]
        if any(_is_positive(v) for v in tokens):
            qs = qs.filter(issue_q(code))
        if any(not _is_positive(v) for v in tokens):
            qs = qs.exclude(issue_q(code))
        query = Q()
        if placeholder:
            selected, other = _placeholder_split(other, placeholder)
            if selected:
                query |= Q(**{disc_field: placeholder})
        if other:
            query |= construct_query(code, other)
        return qs.filter(query) if query else qs
    return apply


def _placeholder_filter(field_name: str, disc_field: str, placeholder: str):
    """Filter of COUNTRY: the "No country" bucket matches on the discrepancy side."""
    def apply(qs: QuerySet[Any], values: list[str]) -> QuerySet[Any]:
        selected, other = _placeholder_split(values, placeholder)
        query = construct_query(field_name, other) if other else Q()
        if selected:
            query |= Q(**{disc_field: placeholder})
        return qs.filter(query)
    return apply


def _sort_by_days_open(order: str) -> OrderBy:
    # More days open = older first_seen
    return F('FIRST_SEEN').desc(nulls_last=True) if order == 'asc' else F('FIRST_SEEN').asc(nulls_last=True)


class DiscrepancyHooks:
    """filter/sort overrides + item decorator for the discrepancy columns, aware of the current filters."""

    def __init__(self, requestfilters: Any) -> None:
        self.selected_codes = _selected_codes(requestfilters)
        self.codes = list(checks())

    def filter_overrides(self) -> JsonDict:
        cfg = get_config()
        overrides: JsonDict = {code: _check_filter(code) for code in self.codes}
        if 'REGION' in overrides:
            overrides['REGION'] = _check_filter('REGION', 'DISC_REGION', cfg['no_region_label'])
        overrides['COUNTRY'] = _placeholder_filter('COUNTRY', 'DISC_COUNTRY', cfg['no_country_label'])
        overrides['DAYS_OPEN'] = self.filter_days_open
        return overrides

    @staticmethod
    def sort_overrides() -> JsonDict:
        return {'DAYS_OPEN': _sort_by_days_open}

    def filter_days_open(self, qs: QuerySet[Any], values: list[str]) -> QuerySet[Any]:
        """Days open >= N: on the serial's oldest issue, or on the filtered checks' own first_seen."""
        raw = str(values[0]).lstrip('>=@ ')
        if not raw.isdigit() or int(raw) <= 0:
            return qs
        cutoff = days_open_cutoff(int(raw))
        if not self.selected_codes:
            return qs.filter(FIRST_SEEN__lte=cutoff)
        # first_seen is an ISO string in UTC, so a text comparison orders it like the datetime
        cutoff_str = cutoff.astimezone(datetime.timezone.utc).isoformat(timespec='microseconds')
        open_since = Q()
        for code in self.selected_codes:
            open_since |= Q(**{f'_FS_{code}__lte': cutoff_str})
        trackers = (
            HardwareDiscrepancyTracking.objects.filter(SERIAL=OuterRef('SERIAL'))
            .annotate(**{
                f'_FS_{code}': Cast(KeyTextTransform('first_seen', KeyTransform(code, 'active_issues')), TextField())
                for code in self.selected_codes
            })
            .filter(open_since)
        )
        return qs.filter(Exists(trackers))

    def decorate(self, items: list[Any], _filters: Any = None) -> None:
        """Set MISSING_SET / CELL_CLASSES / DAYS_OPEN on the page items."""
        trackers = tracker_map({i.SERIAL for i in items})
        now = timezone.now()
        for item in items:
            failing = {c for c in self.codes if has_issue(c, getattr(item, c, None))}
            # Only truly missing values are displayed as MISSING; e.g. WARRANTY_ACTIVE=NO keeps its value
            item.MISSING_SET = {c for c in failing if is_missing(getattr(item, c, None))}
            item.CELL_CLASSES = {c: CSS_ISSUE for c in failing}
            item.DAYS_OPEN = self._days_open(trackers.get(item.SERIAL), now)

    def _days_open(self, tracker: HardwareDiscrepancyTracking | None, now: datetime.datetime) -> int | str:
        if tracker is None:
            return ''
        relevant = [v['first_seen'] for code, v in tracker.active_issues.items() if code in self.selected_codes]
        if relevant:
            return max(days_open_from(fs, now) for fs in relevant)
        if tracker.oldest_first_seen is None:
            return ''
        return days_open_from(tracker.oldest_first_seen, now)


# ------- Filtering / table engine -------

VIRTUAL_FIELDS = {'ANNOTATION', 'DAYS_OPEN'}  # not model fields: no plain text filter / F() sort


def _apply_filters(queryset: QuerySet[Any], json_data: JsonDict, requestfilters: Any,
                   overrides: JsonDict) -> tuple[QuerySet[Any], dict[str, list[str]]]:
    """
    Apply the column filters of the query string: date range (<input>_from / <input>_to) for
    fieldtype "date" (same as the main hardware view), overrides for the discrepancy columns,
    annotation comment for ANNOTATION, construct_query otherwise.
    Returns (queryset, {field: terms}).
    """
    combined = Q()
    filters: dict[str, list[str]] = {}
    for field_key, field_info in json_data['fields'].items():
        input_name = field_info.get('inputname')
        if not input_name:
            continue
        if field_info.get('fieldtype') == 'date':
            date_from = str(requestfilters.get(f'{input_name}_from', '')).strip()
            date_to = str(requestfilters.get(f'{input_name}_to', '')).strip()
            if date_from:
                combined &= Q(**{f'{field_key}__gte': date_from})
            if date_to:
                combined &= Q(**{f'{field_key}__lte': date_to})
            filters[field_key] = [v for v in (date_from, date_to) if v]
            continue
        values = _split_terms(requestfilters.get(input_name, ''))
        filters[field_key] = values
        if not values:
            continue
        if field_key in overrides:
            queryset = overrides[field_key](queryset, values)
        elif field_key == 'ANNOTATION':
            serials = Annotation.objects.filter(construct_query('comment', values)).values_list('SERIAL', flat=True)
            queryset = queryset.filter(SERIAL__in=serials)
        elif field_key not in VIRTUAL_FIELDS:
            combined &= construct_query(field_key, values)
    if combined:
        queryset = queryset.filter(combined)
    return queryset, filters


def _apply_sort(queryset: QuerySet[Any], json_data: JsonDict, requestfilters: Any,
                overrides: JsonDict) -> tuple[QuerySet[Any], str, str]:
    """Sort on a known column (override for virtual ones), SERIAL by default."""
    sort_field = requestfilters.get('sort', PRIMARY_FIELD)
    sort_order = requestfilters.get('order', 'asc')
    if sort_field not in json_data['fields'] or (sort_field in VIRTUAL_FIELDS and sort_field not in overrides):
        sort_field = PRIMARY_FIELD
    if sort_field in overrides:
        order_expr = overrides[sort_field](sort_order)
    else:
        order_expr = F(sort_field).asc(nulls_last=True) if sort_order == 'asc' else F(sort_field).desc(nulls_last=True)
    return queryset.order_by(order_expr), sort_field, sort_order


def _filtered_items(requestfilters: Any) -> tuple[QuerySet[Any], DiscrepancyHooks]:
    """Discrepancy rows matching the list filters (sorted), plus the hooks used to decorate them."""
    hooks = DiscrepancyHooks(requestfilters)
    json_data = _disc_field_labels()
    qs, _ = _apply_filters(discrepancy_queryset(), json_data, requestfilters, hooks.filter_overrides())
    qs, _, _ = _apply_sort(qs, json_data, requestfilters, hooks.sort_overrides())
    return qs, hooks


def _listbox_values(key: str, val: JsonDict, overrides: dict[str, list[str]]) -> Any:
    """Listbox options of a column: override, or distinct model values (cached 1h, EMPTY kept last)."""
    if key in overrides:
        return overrides[key]
    if not val.get('listbox'):
        return ''
    cache_key = f'listbox_hardware_disc_{key}'
    values = cache.get(cache_key)
    if values is not None:
        return values
    if val.get('listempty') == 'True':
        values = ['MISSING']
    else:
        raw = list(Server.objects.values_list(key, flat=True).distinct().order_by(key))
        has_empty = any(isinstance(x, str) and x.upper() == 'EMPTY' for x in raw)
        values = sorted(x for x in raw if x not in (None, '') and not (isinstance(x, str) and x.upper() == 'EMPTY'))
        if has_empty:
            values.append('EMPTY')
    cache.set(cache_key, values, timeout=3600)
    return values


def _sidebar_categories(json_data: JsonDict) -> list[JsonDict]:
    """Show/Hide columns sidebar: fields grouped by category."""
    categories = json_data.get('categories', {})
    grouped: dict[str, list[JsonDict]] = defaultdict(list)
    for key, value in json_data['fields'].items():
        section = value.get('selectionsection', '').strip()
        if section in categories:
            grouped[section].append({
                'key': key, 'displayname': value.get('displayname', '').strip() or key,
                'ischecked': value.get('ischecked') == 'True',
                'ischeckeddisabled': value.get('ischeckeddisabled') == 'True',
            })
    return [
        {'category': cat, 'title': categories[cat], 'fields': grouped[cat]}
        for cat in categories if cat in grouped and cat != 'cat0'
    ]


def _table_context(request: HttpRequest, hooks: DiscrepancyHooks) -> JsonDict:
    """List page context: filtered + sorted + paginated rows, columns, sidebar, annotations."""
    edit_mode = has_perm(request.user, EDIT_PERM)
    UserProfile.objects.get_or_create(user=request.user)
    json_data = _disc_field_labels()

    qs, filters = _apply_filters(discrepancy_queryset(), json_data, request.GET, hooks.filter_overrides())
    qs, sort_field, sort_order = _apply_sort(qs, json_data, request.GET, hooks.sort_overrides())

    fields = {k: v for k, v in json_data['fields'].items() if edit_mode or k != 'ANNOTATION'}
    overrides = _listbox_overrides()
    table_fields = [{
        'name': key, 'displayname': val.get('displayname', key), 'inputname': val.get('inputname', key),
        'listbox': _listbox_values(key, val, overrides), 'listboxmsg': val.get('listboxmsg', 'Select an option'),
        'listid': val.get('listid', 'missingid'), 'selectionsection': val.get('selectionsection', 'cat0'),
        'fieldtype': val.get('fieldtype', ''),
    } for key, val in fields.items()]
    model_fields = [{
        'name': name, 'verbose_name': info.get('displayname', name.replace('_', ' ').title()),
        'is_hostname': name == PRIMARY_FIELD,
    } for name, info in json_data['fields'].items()]

    page_size = int(request.GET.get('page_size', 50))
    paginator = Paginator(qs, page_size)
    page_raw = paginator.get_page(request.GET.get('page'))
    items = list(page_raw)
    hooks.decorate(items)
    annotations = {a.SERIAL: a for a in Annotation.objects.filter(SERIAL__in=[i.SERIAL for i in items])}
    display_items = [
        {'hostname': i.SERIAL, 'primary_server': i, 'annotation': annotations.get(i.SERIAL)} for i in items
    ]
    return {
        'page_obj': create_page_wrapper(display_items, page_raw),
        'table_fields': table_fields,
        'category_fields': _sidebar_categories({**json_data, 'fields': fields}),
        'model_fields': model_fields,
        'json_data': json.dumps(json_data),
        'edit_mode': edit_mode,
        'page_size': page_size,
        'current_filters': filters,
        'total_count': paginator.count,
        'sort_field': sort_field,
        'sort_order': sort_order,
        'localhostname': socket.gethostname(),
        'loggedonuser': request.user,
        'primary_field_name': PRIMARY_FIELD,
        'saved_searches': SavedSearch.objects.filter(
            user_profile__user=request.user, view=SAVED_SEARCH_VIEW).order_by('name'),
    }


def _placeholder_last(values: Any, placeholder: str) -> list[str]:
    ordered = sorted(v for v in set(values) if v)
    return [v for v in ordered if v != placeholder] + ([placeholder] if placeholder in ordered else [])


# ------- Dashboard -------

def _parse_filters(request: HttpRequest) -> tuple[str, str, int]:
    """(region, country, days_open) from the dashboard query string."""
    days = request.GET.get('days_open', '').strip()
    return request.GET.get('region', '').strip(), request.GET.get('country', '').strip(), int(days) if days.isdigit() else 0


def _dashboard_counts(region: str = '', country: str = '', days_open: int = 0) -> tuple[int, int, dict[str, int]]:
    """(population, rows_with_issues, {check: rows}) for the gauges, region/country and days-open aware."""
    snapshot = HardwareAnalysisSnapshot.objects.first()
    if snapshot is None:
        return 0, 0, {}
    regions = expand_region(region)
    population = int(aggregate_breakdown(snapshot.breakdown, regions, country)['total'])
    disc_qs = HardwareDiscrepancy.objects.all()
    if regions:
        disc_qs = disc_qs.filter(region__in=regions)
    if country:
        disc_qs = disc_qs.filter(country=country)
    codes = list(checks())
    field_counts = {c: 0 for c in codes}
    with_issues = 0

    if not days_open:
        for counts in disc_qs.values_list('row_counts', flat=True):
            with_issues += counts.get(ANY_ISSUE, 0)
            for c in codes:
                field_counts[c] += counts.get(c, 0)
        return population, with_issues, field_counts

    cutoff = days_open_cutoff(days_open)
    track = HardwareDiscrepancyTracking.objects.filter(SERIAL=OuterRef('SERIAL'))
    rows = disc_qs.annotate(
        OLDEST=Subquery(track.values('oldest_first_seen')[:1]),
        ISSUES=Subquery(track.values('active_issues')[:1], output_field=JSONField()),
    ).values_list('row_counts', 'OLDEST', 'ISSUES')
    for counts, oldest, issues in rows:
        if issues is None:
            continue
        if oldest and oldest <= cutoff:
            with_issues += counts.get(ANY_ISSUE, 0)
        for c in codes:
            info = issues.get(c)
            if info and is_open_since(info['first_seen'], cutoff):
                field_counts[c] += counts.get(c, 0)
    return population, with_issues, field_counts


@dataclass(frozen=True)
class GaugeSpec:
    """One dashboard gauge: what it counts and where it links to."""

    widget_id: str
    title: str
    issues: int
    size: str
    link_params: dict[str, str]
    info: str


def _gauge(spec: GaugeSpec, population: int, settings: JsonDict, list_url: str) -> JsonDict:
    clean = max(0, population - spec.issues)
    pct = safe_percentage_clean(clean, population)
    return {
        'id': spec.widget_id, 'title': spec.title, 'size': spec.size, 'info': spec.info,
        'base_link': list_url + ('?' + urlencode(spec.link_params) if spec.link_params else ''),
        'value': pct, 'display_value': f'{pct}%', 'issues': spec.issues, 'clean': clean, 'total': population,
        'thresholds': json.dumps(settings['thresholds']), 'colors': json.dumps(settings['colors']),
    }


def _gauge_title(code: str) -> str:
    check = checks()[code]
    return check.get('gauge_title') or f"Missing {check['label']}"


def _gauge_specs(with_issues: int, field_counts: dict[str, int]) -> list[GaugeSpec]:
    """Hero gauge (any issue) + one small gauge per check."""
    labels = check_labels()
    item_label = get_config()['item_label']
    disc_fields = _disc_field_labels()['fields']
    specs = [GaugeSpec(
        ANY_METRIC, f'Data Quality\n({item_label})', with_issues, 'large', {},
        f"{item_label} passing every check ({', '.join(labels.values())})",
    )]
    for code, label in labels.items():
        accepted = checks()[code].get('valid_values')
        info = (f"{item_label} whose '{label}' is not {'/'.join(accepted)}" if accepted
                else f"{item_label} with '{label}' missing or invalid")
        specs.append(GaugeSpec(
            code, _gauge_title(code), field_counts.get(code, 0), 'small',
            {disc_fields[code]['inputname']: issue_token(code)}, info,
        ))
    return specs


def _trend_data(metric: str, days: int | None, region: str = '', country: str = '') -> JsonDict:
    """One point per analysis run: issue count and population for the metric (region/country aware)."""
    snapshots = HardwareAnalysisSnapshot.objects.order_by('analysis_date')
    if days:
        snapshots = snapshots.filter(analysis_date__gte=timezone.now() - datetime.timedelta(days=days))
    regions = expand_region(region)
    labels, values, totals = [], [], []
    for snap in snapshots:
        if regions or country:
            data = aggregate_breakdown(snap.breakdown, regions, country)
            value = data['with_issues'] if metric == ANY_METRIC else data['field_counts'].get(metric, 0)
            total = data['total']
        else:
            value = snap.rows_with_issues if metric == ANY_METRIC else snap.field_counts.get(metric, 0)
            total = snap.total_rows
        labels.append(timezone.localtime(snap.analysis_date).strftime('%d %b'))
        values.append(int(value))
        totals.append(int(total))
    return {'labels': labels, 'values': values, 'totals': totals}


@login_required
def disc_dashboard_view(request: HttpRequest) -> HttpResponse:
    """Gauges (any issue + one per check) and quality trend, filterable by region / country / days open."""
    settings = get_config()
    snapshot = HardwareAnalysisSnapshot.objects.first()
    list_url = reverse('hardware:disc_list')
    context: JsonDict = {
        'title': settings['title'], 'item_label': settings['item_label'],
        'no_data': snapshot is None, 'list_url': list_url,
    }
    if snapshot is None:
        return render(request, DASHBOARD_TEMPLATE, context)

    region, country, days_open = _parse_filters(request)
    population, with_issues, field_counts = _dashboard_counts(region, country, days_open)
    colors = settings.get('trend_colors', {})
    countries = [c for ctrs in snapshot.breakdown.values() for c in ctrs]
    context.update({
        'snapshot': snapshot,
        'widgets': [_gauge(g, population, settings, list_url) for g in _gauge_specs(with_issues, field_counts)],
        'region': region, 'country': country, 'days_open': days_open or '',
        'trend_metrics': [{'metric': ANY_METRIC, 'label': 'Any issue', 'color': colors.get(ANY_METRIC, '#A0826D')}] + [
            {'metric': code, 'label': _gauge_title(code), 'color': colors.get(code, '#6c757d')} for code in checks()
        ],
        'trend_data_json': json.dumps(_trend_data(ANY_METRIC, DEFAULT_TREND_DAYS, region, country)),
        'all_regions': _placeholder_last(snapshot.breakdown.keys(), settings['no_region_label']),
        'region_group_names': list(region_groups()),
        'region_groups_json': json.dumps(region_groups()),
        'all_countries': _placeholder_last(countries, settings['no_country_label']),
    })
    return render(request, DASHBOARD_TEMPLATE, context)


@login_required
def disc_dashboard_filter_api(request: HttpRequest) -> JsonResponse:
    """Gauge figures for the region / country / days open currently selected on the dashboard."""
    population, with_issues, field_counts = _dashboard_counts(*_parse_filters(request))
    return JsonResponse({'population': population, 'any_missing': with_issues, 'field_counts': field_counts})


@login_required
def disc_trend_api(request: HttpRequest) -> JsonResponse:
    """Trend points for a metric / period / region / country."""
    metric = request.GET.get('metric', ANY_METRIC)
    if metric != ANY_METRIC and metric not in checks():
        return JsonResponse({'error': 'invalid metric'}, status=400)
    days_param = request.GET.get('days', str(DEFAULT_TREND_DAYS))
    days = None if days_param == 'all' else (int(days_param) if days_param.isdigit() else DEFAULT_TREND_DAYS)
    data = _trend_data(metric, days, request.GET.get('region', '').strip(), request.GET.get('country', '').strip())
    data['metric'] = metric
    return JsonResponse(data)


# ------- List page -------

def _listbox_overrides() -> dict[str, list[str]]:
    """Listbox options of the checked columns (issue token) and of REGION / COUNTRY."""
    cfg = get_config()
    overrides = {code: [issue_token(code)] for code in checks()}
    regions = HardwareDiscrepancy.objects.values_list('region', flat=True).distinct()
    countries = HardwareDiscrepancy.objects.values_list('country', flat=True).distinct()
    if 'REGION' in overrides:
        overrides['REGION'] = [issue_token('REGION')] + _placeholder_last(regions, cfg['no_region_label'])
    overrides['COUNTRY'] = _placeholder_last(countries, cfg['no_country_label'])
    return overrides


class _LastAnalysis:
    """Stand-in for an import status in the list sidebar ("Last analysis: <date>")."""

    success = True

    def __init__(self, date: datetime.datetime) -> None:
        self.date_import = timezone.localtime(date).strftime('%d.%m.%Y %H:%M')


@login_required
def disc_list_view(request: HttpRequest) -> HttpResponse:
    """Rows failing at least one check, one column per check (red = failing)."""
    hooks = DiscrepancyHooks(request.GET)
    snapshot = HardwareAnalysisSnapshot.objects.first()
    base = '/hardware/discrepancies/'
    context = _table_context(request, hooks)
    context.update({
        'appname': 'hardware',
        'view_display_name': 'Hardware - Data Quality',
        'item_display_name': get_config()['item_label'],
        'last_status': _LastAnalysis(snapshot.analysis_date) if snapshot else None,
        'dashboard_url': reverse('hardware:disc_dashboard'),
        'logs_imports_url': reverse('hardware:disc_dashboard'),
        'bulk_annotation_url': base + 'bulk-annotation/',
        'export_url_base': base + 'export/',
        'export_status_url_base': '/hardware/export/status/',
        'export_download_url_base': '/hardware/export/download/',
        'charts_url': base + 'charts/',
        'save_search_url': reverse('hardware:disc_save_search'),
        'load_search_url_pattern': base + 'load-search/SEARCH_ID/',
        'delete_search_url_pattern': '/hardware/delete_search/SEARCH_ID/',
        'app_base_url': base + 'list/',
    })
    return render(request, LIST_TEMPLATE, context)


# ------- Exports / charts / bulk annotation -------

def _export_job(filepath: str, filetype: str, items: list[Any], annotations: dict[str, Any], columns: list[str]) -> None:
    """Background export job: the file appears in EXPORT_DIR once written (polled by export_status)."""
    writer = generate_excel if filetype == 'xlsx' else generate_csv
    try:
        writer(filepath, items, annotations, columns)
    except Exception as e:  # pylint: disable=broad-exception-caught  # thread has no caller
        print(f'[hardware] discrepancy export failed: {e}')


@login_required
def disc_export_to_file(request: HttpRequest, filetype: str) -> JsonResponse:
    """Start an asynchronous CSV / Excel export of the filtered rows; returns the job id."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not authorized'}, status=405)
    filetype = filetype.lower()
    if filetype not in EXPORT_FORMATS:
        return JsonResponse({'error': 'Invalid format type'}, status=400)

    data = json.loads(request.body)
    qs, hooks = _filtered_items(data.get('filters', {}))
    items = list(qs)
    hooks.decorate(items)
    # Export shows MISSING for missing values, like the screen (in-memory only, never saved)
    for item in items:
        for code in item.MISSING_SET:
            setattr(item, code, 'MISSING')
    annotations = {
        a.SERIAL: a for batch in chunked({i.SERIAL for i in items})
        for a in Annotation.objects.filter(SERIAL__in=batch)
    }
    columns = data.get('columns', [])

    os.makedirs(EXPORT_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    filepath = os.path.join(EXPORT_DIR, f'{job_id}.{filetype}')
    threading.Thread(target=_export_job, args=(filepath, filetype, items, annotations, columns)).start()
    return JsonResponse({'job_id': job_id})


@login_required
def disc_chart_view(request: HttpRequest) -> HttpResponse:
    """Charts of the filtered rows (same chart modal as the regular pages)."""
    labels = _disc_field_labels()
    selected = [f for f in request.GET.getlist('fields') if f not in ('ANNOTATION', 'DAYS_OPEN')]
    qs, hooks = _filtered_items(dict(request.GET.items()))
    items = list(qs)
    hooks.decorate(items)
    item_data = [{'SERIAL': i.SERIAL, **{f: getattr(i, f, '') for f in selected}} for i in items]
    field_totals = {f: len({(row['SERIAL'], str(row.get(f) or 'Unknown')) for row in item_data}) for f in selected}
    response: HttpResponse = generate_charts(
        request, item_data, labels, selected, request.GET.getlist('types'), field_totals, default_keyfield='SERIAL',
    )
    return response


@login_required
def disc_bulk_annotation(request: HttpRequest) -> HttpResponseBase:
    """Annotate every serial of the filtered rows (streams progress)."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid Request Method'}, status=400)
    if not has_perm(request.user, EDIT_PERM):
        return JsonResponse({'status': 'error', 'message': 'Forbidden'}, status=403)
    query_param = request.POST.get('query')
    if not query_param:
        return JsonResponse({'status': 'error', 'message': 'Query string not provided'}, status=400)
    requestfilters = {k: v[0] for k, v in parse_qs(unquote(query_param)).items()}

    qs, _ = _filtered_items(requestfilters)
    keys = list(dict.fromkeys(qs.values_list('SERIAL', flat=True)))
    if not keys:
        return JsonResponse({'status': 'warning', 'message': 'No records to update'}, status=200)
    comment = request.POST.get('bulk_comment', '')
    assigned_to = request.POST.get('bulk_assigned_to', '')
    user = request.user

    def stream():
        total_batches = (len(keys) + BULK_PROGRESS_BATCH - 1) // BULK_PROGRESS_BATCH
        for i in range(total_batches):
            for key in keys[i * BULK_PROGRESS_BATCH:(i + 1) * BULK_PROGRESS_BATCH]:
                ann, _ = Annotation.objects.get_or_create(SERIAL=key)
                ann.add_entry(comment, assigned_to, user)
            yield f'data: progress:{((i + 1) / total_batches) * 100}|batch:{i + 1}\n\n'

    response = StreamingHttpResponse(stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    return response


# ------- Saved searches -------

@login_required
def disc_save_search(request: HttpRequest) -> HttpResponse:
    """Save the current list filters under a name (separate from the main hardware page's searches)."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method.'})
    search_name = request.POST.get('search_name', '').strip()
    if len(search_name) > MAX_SEARCH_NAME:
        return JsonResponse({'success': False, 'message': f'Search name must be {MAX_SEARCH_NAME} characters or fewer.'})
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if SavedSearch.objects.filter(user_profile=profile, name=search_name, view=SAVED_SEARCH_VIEW).exists():
        return JsonResponse({'success': False, 'message': 'A search with this name already exists.'})
    try:
        search_params = json.loads(request.POST.get('filters') or '')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid filter data.'})
    tags = json.loads(request.POST.get('tags', '[]'))
    SavedSearch.objects.create(user_profile=profile, name=search_name, filters=search_params, tags=tags, view=SAVED_SEARCH_VIEW)
    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def disc_load_search(request: HttpRequest, search_id: int) -> HttpResponse:
    """Open the list page with a saved search's filters."""
    saved = SavedSearch.objects.get(id=search_id, user_profile__user=request.user)
    return redirect(f"{reverse('hardware:disc_list')}?{urlencode(saved.filters, doseq=True)}")
