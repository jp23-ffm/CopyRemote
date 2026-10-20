"""Data-quality discrepancies pages for storage shares/objects (dashboard, list, exports)."""

import copy
import datetime
import json
import logging
import os
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode

from django.contrib.auth.decorators import login_required
from django.db.models import Exists, F, JSONField, OrderBy, OuterRef, Q, QuerySet, Subquery, TextField
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone

from accessrights.helpers import has_perm
from common.views import generate_charts
from discrepancies.models import safe_percentage_clean
from userapp.models import CustomUser, UserProfile, SavedSearch

from .discrepancy_utils import (
    ANY_ISSUE, DUPLICATE_CODE, JsonDict, ResourceSpec,
    aggregate_breakdown, check_labels, chunked, days_open_cutoff, days_open_from, discrepancy_queryset,
    duplicate_check, duplicated_q, duplicated_values, expand_region, get_config, get_spec, is_missing, is_open_since,
    missing_q, region_groups, required_fields, resource_settings, tracker_map,
)
from .exports import generate_csv, generate_excel, EXPORT_DIR
from .models import StorageAnalysisSnapshot, StorageDiscrepancy, StorageDiscrepancyTracking, StorageImportStatus
from .views import (
    _table_view, _get_filtered_queryset, construct_query, get_share_field_labels, get_object_field_labels,
)

logger = logging.getLogger(__name__)

EDIT_PERM = 'storage.annotations'
DASHBOARD_TEMPLATE = 'storage/discrepancies_dashboard.html'
LIST_TEMPLATE = 'storage/discrepancies_list.html'

# Value used in the required-field columns' listbox / filters to select missing values
MISSING_TOKEN = 'MISSING'
# Same for the duplicate-check column
DUPLICATE_TOKEN = 'DUPLICATE'
# Metric id of the "any issue" hero gauge / trend
ANY_METRIC = 'any_missing'

# Cell CSS classes (defined in storage/table-flat.html)
CSS_MISSING = 'error-missing'
CSS_DUPLICATE = 'error-duplicate'

EXPORT_FORMATS = ('xlsx', 'csv')
MAX_SEARCH_NAME = 25
BULK_PROGRESS_BATCH = 50
DEFAULT_TREND_DAYS = 30

QueryFilter = Callable[[QuerySet[Any], list[str]], QuerySet[Any]]
SortOrder = Callable[[str], OrderBy]


# ------- Resource lookup / field labels -------

def _current_user(request: HttpRequest) -> CustomUser:
    """Logged-in user of a @login_required view (narrows away AnonymousUser)."""
    user = request.user
    if not isinstance(user, CustomUser):
        raise PermissionDenied
    return user


def _resource_or_404(resource_type: str) -> tuple[ResourceSpec, JsonDict]:
    """(static spec, JSON settings) of a resource type, 404 when unknown."""
    return _spec_or_404(resource_type), resource_settings(resource_type)


def _other_type(resource_type: str) -> str:
    return 'object' if resource_type == 'share' else 'share'


def _base_field_labels(resource_type: str) -> JsonDict:
    labels: JsonDict = get_share_field_labels() if resource_type == 'share' else get_object_field_labels()
    return labels


def _required_column(code: str, label: str, base_info: JsonDict) -> JsonDict:
    """Field label entry of a required field column (listbox offering MISSING)."""
    info = dict(base_info)
    input_name = info.get('inputname', code.lower())
    info.update({
        'displayname': label, 'selectionsection': 'catdisc', 'ischecked': 'True',
        'inputname': input_name, 'listbox': 'missing', 'listboxmsg': label, 'listid': input_name,
    })
    return info


def _discrepancy_columns(resource_type: str, base_fields: JsonDict) -> JsonDict:
    """Columns shown right after the primary column: required fields, duplicate check, days open."""
    extra = {
        code: _required_column(code, label, base_fields.get(code, {}))
        for code, label in required_fields(resource_type).items()
    }
    dup = duplicate_check(resource_type)
    if dup:
        extra[DUPLICATE_CODE] = {
            'displayname': dup['label'], 'selectionsection': 'catdisc', 'ischecked': 'True',
            'inputname': 'duplicateid', 'listbox': 'duplicate', 'listboxmsg': dup['label'], 'listid': 'duplicateid',
        }
    extra['DAYS_OPEN'] = {
        'displayname': 'Days Open', 'selectionsection': 'catdisc', 'ischecked': 'True', 'inputname': 'daysopen',
    }
    return extra


def _disc_field_labels(resource_type: str) -> JsonDict:
    """
    Regular field labels, with the required fields moved right after the primary column (one
    column per checked field, like the Discrepancies servers page), then the duplicate check and DAYS_OPEN.
    """
    base = _base_field_labels(resource_type)
    primary = _primary_field(resource_type)
    required = required_fields(resource_type)
    extra = _discrepancy_columns(resource_type, base['fields'])

    fields: JsonDict = {}
    for key, val in base['fields'].items():
        if key in required:
            continue
        fields[key] = val
        if key == primary:
            fields.update(extra)
    data: JsonDict = copy.deepcopy({k: v for k, v in base.items() if k not in ('fields', 'categories')})
    data['categories'] = {'catdisc': 'Discrepancy', **base.get('categories', {})}
    data['fields'] = fields
    return data


def _primary_field(resource_type: str) -> str:
    """Primary (sticky, bold) column of a resource type."""
    spec = get_spec(resource_type)
    return spec.primary_field if spec else 'ID'


def _field_display_names(resource_type: str) -> dict[str, str]:
    return {k: v.get('displayname', k) for k, v in _base_field_labels(resource_type)['fields'].items()}


# ------- Filter terms -------

def _split_terms(raw: Any) -> list[str]:
    """Filter value from a query string (comma-separated) or a list, without empty terms."""
    terms = raw.split(',') if isinstance(raw, str) else raw
    return [t for t in terms if t]


def _is_missing_term(term: str) -> bool:
    return term.lstrip('@!').strip().upper() == MISSING_TOKEN


def _is_duplicate_term(term: str) -> bool:
    return term.lstrip('@!').strip().upper() == DUPLICATE_TOKEN


def _is_positive(term: str) -> bool:
    return not term.startswith('!')


def _selected_field_codes(resource_type: str, requestfilters: Any) -> set[str]:
    """Checks currently filtered on (MISSING / DUPLICATE) — drives context-sensitive days_open."""
    labels = _disc_field_labels(resource_type)['fields']
    selected = set()
    for code in check_labels(resource_type):
        terms = _split_terms(requestfilters.get(labels[code]['inputname'], ''))
        match = _is_duplicate_term if code == DUPLICATE_CODE else _is_missing_term
        if any(match(t) and _is_positive(t) for t in terms):
            selected.add(code)
    return selected


def _duplicate_diffs(resource_type: str, values: set[Any]) -> dict[Any, list[str]]:
    """
    {dup_value: [differing field names]} for the given duplicated values of the duplicate-check
    field (e.g. ID): a field differs when the rows sharing that value don't all hold the same content.
    """
    dup = duplicate_check(resource_type)
    spec = get_spec(resource_type)
    if not dup or not spec or not values:
        return {}
    dup_field = dup['field']
    compared = [f.name for f in spec.model._meta.concrete_fields if f.name not in ('id', dup_field)]
    seen: dict[Any, dict[str, set[Any]]] = {}
    rows = (
        row for batch in chunked(values)
        for row in spec.model.objects.filter(**{f'{dup_field}__in': batch}).values(dup_field, *compared)
    )
    for row in rows:
        per_field = seen.setdefault(row[dup_field], {f: set() for f in compared})
        for f in compared:
            per_field[f].add(row[f])
    return {v: [f for f in compared if len(per_field[f]) > 1] for v, per_field in seen.items()}


def _placeholder_filter(field_name: str, disc_field: str, placeholder: str) -> QueryFilter:
    """
    Filter for SCOPE / REGION: "No scope" / "No region" are analysis placeholders, not real values,
    so they match on the StorageDiscrepancy side; everything else on the model field as usual.
    """
    def apply(qs: QuerySet[Any], values: list[str]) -> QuerySet[Any]:
        placeholder_terms = [v for v in values if v.lstrip('@').strip().upper() == placeholder.upper()]
        other = [v for v in values if v not in placeholder_terms]
        query = construct_query(field_name, other) if other else Q()
        if placeholder_terms:
            query |= Q(**{disc_field: placeholder})
        return qs.filter(query)
    return apply


def _required_filter(field_name: str) -> QueryFilter:
    """
    Filter for a required field column: "MISSING" (optionally @/! prefixed) selects/excludes rows
    with a missing value; any other term is a regular text search on the field.
    """
    def apply(qs: QuerySet[Any], values: list[str]) -> QuerySet[Any]:
        missing_terms = [v for v in values if _is_missing_term(v)]
        other = [v for v in values if not _is_missing_term(v)]
        # _TRIM_<field> annotations come from discrepancy_queryset()
        if any(_is_positive(v) for v in missing_terms):
            qs = qs.filter(missing_q(field_name))
        if any(not _is_positive(v) for v in missing_terms):
            qs = qs.exclude(missing_q(field_name))
        if other:
            qs = qs.filter(construct_query(field_name, other))
        return qs
    return apply


def _sort_by_days_open(order: str) -> OrderBy:
    # More days open = older first_seen
    return F('FIRST_SEEN').desc(nulls_last=True) if order == 'asc' else F('FIRST_SEEN').asc(nulls_last=True)


# ------- List hooks (filters / sorts / cell decoration) -------

class DiscrepancyHooks:
    """filter/sort overrides + item decorator for the discrepancy columns, aware of the current filters."""

    def __init__(self, resource_type: str, requestfilters: Any) -> None:
        self.resource_type = resource_type
        self.spec = _spec_or_404(resource_type)
        self.selected_codes = _selected_field_codes(resource_type, requestfilters)
        self.codes = list(required_fields(resource_type))
        dup = duplicate_check(resource_type)
        self.dup_field = dup['field'] if dup else ''
        # Computed once per request: values of the duplicate-check field shared by several rows
        self.dup_values = duplicated_values(resource_type) if dup else set()
        self.display_names = _field_display_names(resource_type)

    # --- filters ---

    def filter_overrides(self) -> dict[str, QueryFilter]:
        """Filters replacing the default text search for the discrepancy-related columns."""
        overrides: dict[str, QueryFilter] = {code: _required_filter(code) for code in self.codes}
        overrides.update({
            'DAYS_OPEN': self.filter_days_open,
            'SCOPE': _placeholder_filter('SCOPE', 'DISC_SCOPE', get_config()['no_scope_label']),
            'REGION': _placeholder_filter('REGION', 'DISC_REGION', get_config()['no_region_label']),
        })
        if self.dup_field:
            overrides[DUPLICATE_CODE] = self.filter_duplicate
        return overrides

    def sort_overrides(self) -> dict[str, SortOrder]:
        """Sorts for the virtual columns (not plain model fields)."""
        overrides: dict[str, SortOrder] = {'DAYS_OPEN': _sort_by_days_open}
        if self.dup_field:
            overrides[DUPLICATE_CODE] = self.sort_duplicate
        return overrides

    def filter_days_open(self, qs: QuerySet[Any], values: list[str]) -> QuerySet[Any]:
        """Days open >= N: on the asset's oldest issue, or on the filtered checks' own first_seen."""
        raw = str(values[0]).lstrip('>=@ ')
        if not raw.isdigit() or int(raw) <= 0:
            return qs
        cutoff = days_open_cutoff(int(raw))
        if not self.selected_codes:
            return qs.filter(FIRST_SEEN__lte=cutoff)
        return qs.filter(Exists(self._trackers_open_since(cutoff)))

    def _trackers_open_since(self, cutoff: datetime.datetime) -> QuerySet[StorageDiscrepancyTracking]:
        """
        Tracker of the outer row's asset when one of the filtered checks is open since the cutoff.
        first_seen is an ISO string in UTC (isoformat), so a text comparison orders it like the datetime.
        """
        cutoff_str = cutoff.astimezone(datetime.timezone.utc).isoformat(timespec='microseconds')
        open_since = Q()
        for code in self.selected_codes:
            open_since |= Q(**{f'_FS_{code}__lte': cutoff_str})
        return (
            StorageDiscrepancyTracking.objects
            .filter(resource_type=self.resource_type, asset_key=OuterRef('ASSET_KEY'))
            .annotate(**{
                # Cast: plain text lookups (JSON key lookups would json-decode the cutoff)
                f'_FS_{code}': Cast(KeyTextTransform('first_seen', KeyTransform(code, 'active_issues')), TextField())
                for code in self.selected_codes
            })
            .filter(open_since)
        )

    def filter_duplicate(self, qs: QuerySet[Any], values: list[str]) -> QuerySet[Any]:
        """"DUPLICATE" keeps rows whose ID is shared with another row, "!DUPLICATE" the others."""
        terms = [v for v in values if _is_duplicate_term(v)]
        shared = duplicated_q(self.resource_type)
        if any(_is_positive(v) for v in terms):
            qs = qs.filter(shared)
        if any(not _is_positive(v) for v in terms):
            qs = qs.exclude(shared)
        return qs

    def sort_duplicate(self, order: str) -> OrderBy:
        """Sorting on the duplicate column groups rows sharing the same ID together."""
        expr = F(self.dup_field)
        return expr.asc(nulls_last=True) if order == 'asc' else expr.desc(nulls_last=True)

    # --- cell decoration ---

    def decorate(self, items: list[Any], _filters: Any = None) -> None:
        """Set MISSING_SET / CELL_CLASSES / duplicate summary / DAYS_OPEN on the page items."""
        trackers = tracker_map(self.resource_type, {self.spec.key_fn(i) for i in items})
        diffs: dict[Any, list[str]] = {}
        if self.dup_field:
            page_values = {getattr(i, self.dup_field) for i in items} & self.dup_values
            diffs = _duplicate_diffs(self.resource_type, page_values)
        now = timezone.now()
        for item in items:
            # Row-level: which required cells of THIS row are missing (rendered in red, shown as MISSING)
            item.MISSING_SET = {c for c in self.codes if is_missing(getattr(item, c, None))}
            item.CELL_CLASSES = {c: CSS_MISSING for c in item.MISSING_SET}
            if self.dup_field:
                self._decorate_duplicate(item, diffs)
            item.DAYS_OPEN = self._days_open(trackers.get(self.spec.key_fn(item)), now)

    def _decorate_duplicate(self, item: Any, diffs: dict[Any, list[str]]) -> None:
        """Differing cells in orange (missing stays red), the duplicate column summarises them."""
        differing = diffs.get(getattr(item, self.dup_field))
        if differing is None:
            setattr(item, DUPLICATE_CODE, '-')
            return
        item.CELL_CLASSES.update({f: CSS_DUPLICATE for f in differing if f not in item.MISSING_SET})
        item.CELL_CLASSES[DUPLICATE_CODE] = CSS_DUPLICATE
        summary = ', '.join(self.display_names.get(f, f) for f in differing)
        setattr(item, DUPLICATE_CODE, f'Differs: {summary}' if differing else 'Identical rows')

    def _days_open(self, tracker: StorageDiscrepancyTracking | None, now: datetime.datetime) -> int | str:
        """Asset's oldest issue, or the oldest among the filtered checks when filtering on some."""
        if tracker is None:
            return ''
        relevant = [v['first_seen'] for code, v in tracker.active_issues.items() if code in self.selected_codes]
        if relevant:
            return max(days_open_from(fs, now) for fs in relevant)
        if tracker.oldest_first_seen is None:
            return ''
        return days_open_from(tracker.oldest_first_seen, now)


def _spec_or_404(resource_type: str) -> ResourceSpec:
    """Static spec of a resource type, 404 when unknown."""
    spec = get_spec(resource_type)
    if spec is None:
        raise Http404('Unknown resource type')
    return spec


def _filtered_items(resource_type: str, requestfilters: Any) -> tuple[QuerySet[Any], DiscrepancyHooks]:
    """Discrepancy rows matching the list filters, plus the hooks used to decorate them."""
    spec = _spec_or_404(resource_type)
    hooks = DiscrepancyHooks(resource_type, requestfilters)
    qs = _get_filtered_queryset(
        spec.model, spec.annotation_cls, spec.annotation_key_field,
        lambda: _disc_field_labels(resource_type), requestfilters,
        default_sort=spec.primary_field, base_queryset=discrepancy_queryset(resource_type),
        filter_overrides=hooks.filter_overrides(), sort_overrides=hooks.sort_overrides(),
    )
    return qs, hooks


def _placeholder_last(values: Any, placeholder: str) -> list[str]:
    """Sorted values with the "No scope"/"No region" placeholder kept last, like EMPTY in the listboxes."""
    ordered = sorted(v for v in set(values) if v)
    return [v for v in ordered if v != placeholder] + ([placeholder] if placeholder in ordered else [])


def _disc_values(resource_type: str, field_name: str) -> list[str]:
    """Distinct values of a StorageDiscrepancy column for a resource type."""
    return list(
        StorageDiscrepancy.objects.filter(resource_type=resource_type)
        .values_list(field_name, flat=True).distinct().order_by(field_name)
    )


# ------- Dashboard -------

DashboardCounts = tuple[int, int, dict[str, int]]


def _count_all(disc_qs: QuerySet[StorageDiscrepancy], codes: list[str]) -> tuple[int, dict[str, int]]:
    """Sum the row counts of every asset."""
    field_counts = {c: 0 for c in codes}
    with_issues = 0
    for counts in disc_qs.values_list('row_counts', flat=True):
        with_issues += counts.get(ANY_ISSUE, 0)
        for c in codes:
            field_counts[c] += counts.get(c, 0)
    return with_issues, field_counts


def _count_open_since(
    disc_qs: QuerySet[StorageDiscrepancy], codes: list[str], cutoff: datetime.datetime,
) -> tuple[int, dict[str, int]]:
    """Sum the row counts of issues open since the cutoff (each check on its own first_seen)."""
    field_counts = {c: 0 for c in codes}
    with_issues = 0
    # Tracker fields joined in SQL (no asset key list sent to the database)
    track = StorageDiscrepancyTracking.objects.filter(
        resource_type=OuterRef('resource_type'), asset_key=OuterRef('asset_key'),
    )
    rows = disc_qs.annotate(
        OLDEST=Subquery(track.values('oldest_first_seen')[:1]),
        ISSUES=Subquery(track.values('active_issues')[:1], output_field=JSONField()),
    ).values_list('row_counts', 'OLDEST', 'ISSUES')
    for counts, oldest, issues in rows:
        if issues is None:
            continue
        # The "any" gauge uses the asset's oldest issue
        if oldest and oldest <= cutoff:
            with_issues += counts.get(ANY_ISSUE, 0)
        for c in codes:
            info = issues.get(c)
            if info and is_open_since(info['first_seen'], cutoff):
                field_counts[c] += counts.get(c, 0)
    return with_issues, field_counts


def _dashboard_counts(resource_type: str, region: str = '', scope: str = '', days_open: int = 0) -> DashboardCounts:
    """
    (population, rows_with_issues, {check: rows}) for the gauges, region/scope and days-open aware.
    Everything is counted in rows (StorageDiscrepancy.row_counts), like the list page.
    """
    snapshot = StorageAnalysisSnapshot.objects.filter(resource_type=resource_type).first()
    if snapshot is None:
        return 0, 0, {}
    regions = expand_region(region)
    population = int(aggregate_breakdown(snapshot.breakdown, regions, scope)['total'])

    disc_qs = StorageDiscrepancy.objects.filter(resource_type=resource_type)
    if regions:
        disc_qs = disc_qs.filter(region__in=regions)
    if scope:
        disc_qs = disc_qs.filter(scope=scope)
    codes = list(check_labels(resource_type))

    if days_open:
        with_issues, field_counts = _count_open_since(disc_qs, codes, days_open_cutoff(days_open))
    else:
        with_issues, field_counts = _count_all(disc_qs, codes)
    return population, with_issues, field_counts


def _parse_filters(request: HttpRequest) -> tuple[str, str, int]:
    """(region, scope, days_open) from the dashboard query string."""
    region = request.GET.get('region', '').strip()
    scope = request.GET.get('scope', '').strip()
    days = request.GET.get('days_open', '').strip()
    return region, scope, int(days) if days.isdigit() else 0


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
    """Template context of one gauge (percentage of clean rows over the population)."""
    clean = max(0, population - spec.issues)
    pct = safe_percentage_clean(clean, population)
    return {
        'id': spec.widget_id, 'title': spec.title, 'size': spec.size, 'info': spec.info,
        'base_link': list_url + ('?' + urlencode(spec.link_params) if spec.link_params else ''),
        'value': pct, 'display_value': f'{pct}%',
        'issues': spec.issues, 'clean': clean, 'total': population,
        'thresholds': json.dumps(settings['thresholds']), 'colors': json.dumps(settings['colors']),
    }


def _gauge_specs(
    resource_type: str, settings: JsonDict, with_issues: int, field_counts: dict[str, int],
) -> list[GaugeSpec]:
    """Hero gauge (any issue) + one small gauge per check."""
    labels = check_labels(resource_type)
    disc_fields = _disc_field_labels(resource_type)['fields']
    item_label = settings['item_label']
    specs = [GaugeSpec(
        ANY_METRIC, f'Data Quality\n({item_label})', with_issues, 'large', {},
        f"{item_label} passing every check ({', '.join(labels.values())})",
    )]
    for code, label in labels.items():
        input_name = disc_fields[code]['inputname']
        count = field_counts.get(code, 0)
        if code == DUPLICATE_CODE:
            dup = duplicate_check(resource_type) or {}
            # Sorted on the duplicate column so rows sharing an ID are listed together
            specs.append(GaugeSpec(
                code, label, count, 'small', {input_name: DUPLICATE_TOKEN, 'sort': DUPLICATE_CODE},
                f"{item_label} whose {dup.get('field', 'ID')} is shared by several rows",
            ))
        else:
            specs.append(GaugeSpec(
                code, f'Missing {label}', count, 'small', {input_name: MISSING_TOKEN},
                f"{item_label} with '{label}' missing or invalid",
            ))
    return specs


def _trend_metrics(resource_type: str, settings: JsonDict) -> list[JsonDict]:
    """Options of the trend metric selector (any issue + one per check)."""
    colors = settings.get('trend_colors', {})
    metrics = [{'metric': ANY_METRIC, 'label': 'Any issue', 'color': colors.get(ANY_METRIC, '#A0826D')}]
    metrics += [
        {'metric': code, 'label': label if code == DUPLICATE_CODE else f'Missing {label}',
         'color': colors.get(code, '#6c757d')}
        for code, label in check_labels(resource_type).items()
    ]
    return metrics


def _filter_choices(snapshot: StorageAnalysisSnapshot) -> JsonDict:
    """Region / scope dropdown choices: real values from the snapshot, region groups from config."""
    snapshot_scopes = [sc for scopes in snapshot.breakdown.values() for sc in scopes]
    return {
        'all_regions': _placeholder_last(snapshot.breakdown.keys(), get_config()['no_region_label']),
        'region_group_names': list(region_groups()),
        'region_groups_json': json.dumps(region_groups()),
        'all_scopes': _placeholder_last(snapshot_scopes, get_config()['no_scope_label']),
    }


@login_required
def disc_dashboard_view(request: HttpRequest, resource_type: str) -> HttpResponse:
    """Gauges (any issue + one per check) and quality trend, filterable by region / scope / days open."""
    _, settings = _resource_or_404(resource_type)
    snapshot = StorageAnalysisSnapshot.objects.filter(resource_type=resource_type).first()
    list_url = reverse('storage:disc_list', args=[resource_type])
    context: JsonDict = {
        'title': settings['title'],
        'resource_type': resource_type,
        'item_label': settings['item_label'],
        'no_data': snapshot is None,
        'list_url': list_url,
        'other_type': _other_type(resource_type),
        'other_label': resource_settings(_other_type(resource_type))['item_label'],
    }
    if snapshot is None:
        return render(request, DASHBOARD_TEMPLATE, context)

    region, scope, days_open = _parse_filters(request)
    population, with_issues, field_counts = _dashboard_counts(resource_type, region, scope, days_open)
    gauges = _gauge_specs(resource_type, settings, with_issues, field_counts)

    context.update({
        'snapshot': snapshot,
        'widgets': [_gauge(g, population, settings, list_url) for g in gauges],
        'region': region,
        'scope': scope,
        'days_open': days_open or '',
        'trend_metrics': _trend_metrics(resource_type, settings),
        'trend_data_json': json.dumps(_trend_data(resource_type, ANY_METRIC, DEFAULT_TREND_DAYS, region, scope)),
        'fields_json': json.dumps(check_labels(resource_type)),
        **_filter_choices(snapshot),
    })
    return render(request, DASHBOARD_TEMPLATE, context)


@login_required
def disc_dashboard_filter_api(request: HttpRequest, resource_type: str) -> JsonResponse:
    """Gauge figures for the region / scope / days open currently selected on the dashboard."""
    _resource_or_404(resource_type)
    region, scope, days_open = _parse_filters(request)
    population, with_issues, field_counts = _dashboard_counts(resource_type, region, scope, days_open)
    return JsonResponse({'population': population, 'any_missing': with_issues, 'field_counts': field_counts})


def _snapshot_point(snap: StorageAnalysisSnapshot, metric: str, regions: list[str], scope: str) -> tuple[int, int]:
    """(issue count, population) of one snapshot for a metric, region/scope aware."""
    if regions or scope:
        data = aggregate_breakdown(snap.breakdown, regions, scope)
        value = data['with_issues'] if metric == ANY_METRIC else data['field_counts'].get(metric, 0)
        return int(value), int(data['total'])
    value = snap.assets_with_issues if metric == ANY_METRIC else snap.field_counts.get(metric, 0)
    return int(value), snap.total_assets


def _trend_data(resource_type: str, metric: str, days: int | None, region: str = '', scope: str = '') -> JsonDict:
    """One point per analysis run: issue count and population for the metric (region/scope aware)."""
    snapshots = StorageAnalysisSnapshot.objects.filter(resource_type=resource_type).order_by('analysis_date')
    if days:
        snapshots = snapshots.filter(analysis_date__gte=timezone.now() - datetime.timedelta(days=days))
    regions = expand_region(region)
    labels, values, totals = [], [], []
    for snap in snapshots:
        value, total = _snapshot_point(snap, metric, regions, scope)
        labels.append(timezone.localtime(snap.analysis_date).strftime('%d %b'))
        values.append(value)
        totals.append(total)
    return {'labels': labels, 'values': values, 'totals': totals}


@login_required
def disc_trend_api(request: HttpRequest, resource_type: str) -> JsonResponse:
    """Trend points for a metric / period / region / scope."""
    _resource_or_404(resource_type)
    metric = request.GET.get('metric', ANY_METRIC)
    if metric != ANY_METRIC and metric not in check_labels(resource_type):
        return JsonResponse({'error': 'invalid metric'}, status=400)
    days_param = request.GET.get('days', str(DEFAULT_TREND_DAYS))
    days = None if days_param == 'all' else (int(days_param) if days_param.isdigit() else DEFAULT_TREND_DAYS)
    data = _trend_data(
        resource_type, metric, days, request.GET.get('region', '').strip(), request.GET.get('scope', '').strip(),
    )
    data['metric'] = metric
    return JsonResponse(data)


# ------- List page -------

def _list_urls(resource_type: str) -> JsonDict:
    """URLs used by the list template (exports, charts, saved searches...)."""
    base = f'/storage/discrepancies/{resource_type}/'
    return {
        'dashboard_url': reverse('storage:disc_dashboard', args=[resource_type]),
        'bulk_annotation_url': base + 'bulk-annotation/',
        'export_url_base': base + 'export/',
        'charts_url': base + 'charts/',
        'save_search_url': reverse('storage:disc_save_search', args=[resource_type]),
        'load_search_url_pattern': base + 'load-search/SEARCH_ID/',
        'delete_search_url_pattern': f'/storage/delete-search/{resource_type}/SEARCH_ID/',
        'app_base_url': base + 'list/',
    }


def _listbox_overrides(resource_type: str) -> dict[str, list[str]]:
    """Listbox options of the discrepancy columns, scope and region."""
    return {
        **{code: [MISSING_TOKEN] for code in required_fields(resource_type)},
        DUPLICATE_CODE: [DUPLICATE_TOKEN],
        'SCOPE': _placeholder_last(_disc_values(resource_type, 'scope'), get_config()['no_scope_label']),
        'REGION': _placeholder_last(_disc_values(resource_type, 'region'), get_config()['no_region_label']),
    }


@login_required
def disc_list_view(request: HttpRequest, resource_type: str) -> HttpResponse:
    """Rows with at least one issue, one column per check (red = missing, orange = duplicate diff)."""
    spec, settings = _resource_or_404(resource_type)
    hooks = DiscrepancyHooks(resource_type, request.GET)
    last_status = StorageImportStatus.objects.filter(source=f'disc-{resource_type}').order_by('-date_import').first()
    response: HttpResponse = _table_view(
        request,
        model_cls=spec.model,
        annotation_cls=spec.annotation_cls,
        annotation_key_field=spec.annotation_key_field,
        get_field_labels_fn=lambda: _disc_field_labels(resource_type),
        template_name=LIST_TEMPLATE,
        perm_code=EDIT_PERM,
        resource_type=resource_type,
        view_display_name=f"Storage - {settings['item_label']} Data Quality",
        item_display_name=settings['item_label'],
        saved_search_view=f'storage-{resource_type}-disc',
        primary_field=spec.primary_field,
        annotation_key_fn=spec.key_fn,
        base_queryset=discrepancy_queryset(resource_type),
        filter_overrides=hooks.filter_overrides(),
        sort_overrides=hooks.sort_overrides(),
        listbox_overrides=_listbox_overrides(resource_type),
        decorate_items_fn=hooks.decorate,
        extra_context={'last_status': last_status, **_list_urls(resource_type)},
    )
    return response


# ------- Exports / charts / bulk annotation -------

def _export_items(resource_type: str, requestfilters: JsonDict) -> tuple[list[Any], dict[str, Any]]:
    """Filtered + decorated rows to export, and their annotations by asset key."""
    spec = _spec_or_404(resource_type)
    qs, hooks = _filtered_items(resource_type, requestfilters)
    items = list(qs)
    hooks.decorate(items)
    # Export shows MISSING for missing required fields, like the screen (in-memory only, never saved)
    for item in items:
        for code in item.MISSING_SET:
            setattr(item, code, MISSING_TOKEN)
    keys = [spec.key_fn(i) for i in items]
    if not keys:
        return items, {}
    key_field = spec.annotation_key_field
    annotations = {
        getattr(a, key_field): a
        for batch in chunked(set(keys))
        for a in spec.annotation_cls.objects.filter(**{f'{key_field}__in': batch})
    }
    return items, annotations


@dataclass(frozen=True)
class ExportJob:
    """Everything the background export thread needs."""

    filepath: str
    filetype: str
    items: list[Any]
    annotations: dict[str, Any]
    columns: list[str]
    key_fn: Callable[[Any], str]


def _write_export(job: ExportJob) -> None:
    """Background export job: the file appears in EXPORT_DIR once written (polled by export_status)."""
    writer = generate_excel if job.filetype == 'xlsx' else generate_csv
    try:
        writer(job.filepath, job.items, job.annotations, job.columns, annotation_key_fn=job.key_fn)
    except Exception:  # pylint: disable=broad-exception-caught  # any failure must be logged, thread has no caller
        logger.exception('Storage discrepancy export failed: %s', job.filepath)


@login_required
def disc_export_to_file(request: HttpRequest, resource_type: str, filetype: str) -> JsonResponse:
    """Start an asynchronous CSV / Excel export of the filtered rows; returns the job id."""
    spec = _spec_or_404(resource_type)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not authorized'}, status=405)
    filetype = filetype.lower()
    if filetype not in EXPORT_FORMATS:
        return JsonResponse({'error': 'Invalid format type'}, status=400)

    data = json.loads(request.body)
    items, annotations = _export_items(resource_type, data.get('filters', {}))

    os.makedirs(EXPORT_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    job = ExportJob(
        filepath=os.path.join(EXPORT_DIR, f'{job_id}.{filetype}'), filetype=filetype,
        items=items, annotations=annotations, columns=data.get('columns', []), key_fn=spec.key_fn,
    )
    threading.Thread(target=_write_export, args=(job,)).start()
    return JsonResponse({'job_id': job_id})


@login_required
def disc_chart_view(request: HttpRequest, resource_type: str) -> HttpResponse:
    """Charts of the filtered rows (same chart modal as the regular storage pages)."""
    _resource_or_404(resource_type)
    selected_fields = [f for f in request.GET.getlist('fields') if f not in ('ANNOTATION', 'DAYS_OPEN')]
    qs, hooks = _filtered_items(resource_type, dict(request.GET.items()))
    items = list(qs)
    hooks.decorate(items)
    item_data = [{'ID': i.ID, **{f: getattr(i, f, '') for f in selected_fields}} for i in items]
    field_totals = {
        f: len({(row['ID'], str(row.get(f) or 'Unknown')) for row in item_data})
        for f in selected_fields
    }
    response: HttpResponse = generate_charts(
        request, item_data, _disc_field_labels(resource_type), selected_fields,
        request.GET.getlist('types'), field_totals, default_keyfield='ID',
    )
    return response


def _bulk_annotate_stream(
    spec: ResourceSpec, keys: list[str], comment: str, assigned_to: str, user: Any,
) -> Iterator[str]:
    """Annotate the assets by batches, yielding server-sent progress events."""
    total_batches = (len(keys) + BULK_PROGRESS_BATCH - 1) // BULK_PROGRESS_BATCH
    for i in range(total_batches):
        for key in keys[i * BULK_PROGRESS_BATCH:(i + 1) * BULK_PROGRESS_BATCH]:
            lookup: dict[str, Any] = {spec.annotation_key_field: key}
            ann, _ = spec.annotation_cls.objects.get_or_create(**lookup)
            ann.add_entry(comment, assigned_to, user)
        yield f'data: progress:{((i + 1) / total_batches) * 100}|batch:{i + 1}\n\n'


@login_required
def disc_bulk_annotation(request: HttpRequest, resource_type: str) -> HttpResponseBase:
    """Annotate every asset of the filtered rows (streams progress)."""
    spec, _ = _resource_or_404(resource_type)
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid Request Method'}, status=400)
    if not has_perm(request.user, EDIT_PERM):
        return JsonResponse({'status': 'error', 'message': 'Forbidden'}, status=403)

    query_param = request.POST.get('query')
    if not query_param:
        return JsonResponse({'status': 'error', 'message': 'Query string not provided'}, status=400)
    requestfilters = {k: v[0] for k, v in parse_qs(unquote(query_param)).items()}

    qs, _ = _filtered_items(resource_type, requestfilters)
    # One annotation per asset key (an asset can span several rows)
    keys = list(dict.fromkeys(spec.key_fn(i) for i in qs))
    if not keys:
        return JsonResponse({'status': 'warning', 'message': 'No records to update'}, status=200)

    stream = _bulk_annotate_stream(
        spec, keys, request.POST.get('bulk_comment', ''), request.POST.get('bulk_assigned_to', ''),
        _current_user(request),
    )
    response = StreamingHttpResponse(stream, content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    return response


# ------- Saved searches -------

def _json_error(message: str) -> JsonResponse:
    return JsonResponse({'success': False, 'message': message})


@login_required
def disc_save_search(request: HttpRequest, resource_type: str) -> HttpResponse:
    """Save the current list filters under a name (separate from the regular storage pages' searches)."""
    _resource_or_404(resource_type)
    if request.method != 'POST':
        return _json_error('Invalid request method.')
    view_key = f'storage-{resource_type}-disc'
    search_name = request.POST.get('search_name', '').strip()
    if len(search_name) > MAX_SEARCH_NAME:
        return _json_error(f'Search name must be {MAX_SEARCH_NAME} characters or fewer.')
    profile, _ = UserProfile.objects.get_or_create(user=_current_user(request))
    if SavedSearch.objects.filter(user_profile=profile, name=search_name, view=view_key).exists():
        return _json_error('A search with this name already exists.')
    try:
        search_params = json.loads(request.POST.get('filters') or '')
    except json.JSONDecodeError:
        return _json_error('Invalid filter data.')
    tags = json.loads(request.POST.get('tags', '[]'))
    SavedSearch.objects.create(user_profile=profile, name=search_name, filters=search_params, tags=tags, view=view_key)
    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def disc_load_search(request: HttpRequest, resource_type: str, search_id: int) -> HttpResponse:
    """Open the list page with a saved search's filters."""
    _resource_or_404(resource_type)
    saved = SavedSearch.objects.get(id=search_id, user_profile__user=_current_user(request))
    return redirect(f"{reverse('storage:disc_list', args=[resource_type])}?{urlencode(saved.filters, doseq=True)}")
