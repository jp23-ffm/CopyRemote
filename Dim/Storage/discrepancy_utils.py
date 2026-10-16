"""Shared logic for storage missing-data discrepancies (analysis command + views)."""

import datetime
import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, TypedDict

from django.db.models import CharField, Count, Expression, OuterRef, Q, QuerySet, Subquery, Value
from django.db.models.functions import Coalesce, Concat, Trim, Upper
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (
    StorageShare, StorageObject, ShareAnnotation, ObjectAnnotation,
    StorageDiscrepancy, StorageDiscrepancyTracking,
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'discrepancies_config.json')

# Issue code stored alongside missing field names when several rows share the same ID
DUPLICATE_CODE = 'DUPLICATE_ID'
# Key of row_counts holding the number of rows having at least one issue
ANY_ISSUE = '_any'
BULK_BATCH_SIZE = 1000

JsonDict = dict[str, Any]
# {(region, scope): number of rows}
Population = dict[tuple[str, str], int]


class CurrentEntry(TypedDict):
    """Analysis result for one asset with at least one issue."""

    region: str
    scope: str
    missing: set[str]
    row_counts: dict[str, int]


# {asset_key: CurrentEntry}
Current = dict[str, CurrentEntry]


# ------- Configuration -------

class _JsonConfigCache:
    """Thread-safe JSON file cache, reloaded when the file modification time changes."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._data: JsonDict = {}
        self._mtime = 0.0
        self._lock = Lock()

    def get(self) -> JsonDict:
        """Return the parsed file, re-reading it only when it changed on disk."""
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            return self._data
        if self._data and mtime == self._mtime:
            return self._data
        with self._lock:
            with open(self._path, 'r', encoding='utf-8') as f:
                self._data = json.load(f)
            self._mtime = mtime
        return self._data


_config = _JsonConfigCache(CONFIG_PATH)


def get_config() -> JsonDict:
    """Load discrepancies_config.json, reloaded when the file changes."""
    return _config.get()


# ------- Resource types (share / object) -------

StorageModel = type[StorageShare] | type[StorageObject]
AnnotationModel = type[ShareAnnotation] | type[ObjectAnnotation]


@dataclass(frozen=True)
class AssetKey:
    """How to build the asset key (same key as the annotations): from an instance, a values() row, in SQL."""

    from_item: Callable[[Any], str]
    from_values: Callable[[JsonDict], str]
    expression: Callable[[], Expression]
    source_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResourceSpec:
    """Static description of a resource type: model, asset key and annotation wiring."""

    model: StorageModel
    annotation_cls: AnnotationModel
    annotation_key_field: str
    asset_key: AssetKey
    primary_field: str = 'ID'

    def key_fn(self, item: Any) -> str:
        """Asset key of a model instance."""
        return self.asset_key.from_item(item)


def _share_key_expr() -> Expression:
    """DB-side equivalent of views._share_annotation_key: f"{FILER}|{SHARE_PATH}"."""
    return Concat(
        Coalesce('FILER', Value('')), Value('|'), Coalesce('SHARE_PATH', Value('')),
        output_field=CharField(),
    )


def _object_key_expr() -> Expression:
    return Coalesce('NAME', Value(''), output_field=CharField())


RESOURCES: dict[str, ResourceSpec] = {
    'share': ResourceSpec(
        model=StorageShare,
        annotation_cls=ShareAnnotation,
        annotation_key_field='share_key',
        asset_key=AssetKey(
            from_item=lambda item: f"{item.FILER or ''}|{item.SHARE_PATH or ''}",
            from_values=lambda row: f"{row['FILER'] or ''}|{row['SHARE_PATH'] or ''}",
            expression=_share_key_expr,
            source_fields=['FILER', 'SHARE_PATH'],
        ),
        primary_field='SHARE_NAME',
    ),
    'object': ResourceSpec(
        model=StorageObject,
        annotation_cls=ObjectAnnotation,
        annotation_key_field='NAME',
        asset_key=AssetKey(
            from_item=lambda item: item.NAME or '',
            from_values=lambda row: row['NAME'] or '',
            expression=_object_key_expr,
            source_fields=['NAME'],
        ),
        primary_field='NAME',
    ),
}


def get_spec(resource_type: str) -> ResourceSpec | None:
    """Static spec of a resource type, or None if unknown."""
    return RESOURCES.get(resource_type)


def resource_settings(resource_type: str) -> JsonDict:
    """JSON settings of a resource type (title, item_label, required_fields, thresholds...)."""
    settings: JsonDict = get_config()['resources'][resource_type]
    return settings


def required_fields(resource_type: str) -> dict[str, str]:
    """Ordered {field_name: label} of required fields for a resource type."""
    fields: dict[str, str] = resource_settings(resource_type)['required_fields']
    return fields


def duplicate_check(resource_type: str) -> dict[str, str] | None:
    """{'field': ..., 'label': ...} if the duplicate check is enabled for this resource type, else None."""
    check: dict[str, str] | None = resource_settings(resource_type).get('duplicate_check')
    return check


def check_labels(resource_type: str) -> dict[str, str]:
    """Ordered {issue_code: label} of every check (required fields + duplicate check) — one gauge each."""
    labels = dict(required_fields(resource_type))
    dup = duplicate_check(resource_type)
    if dup:
        labels[DUPLICATE_CODE] = dup['label']
    return labels


def duplicated_values(resource_type: str) -> set[Any]:
    """Set of values of the duplicate-check field (e.g. ID) that appear on more than one row."""
    dup = duplicate_check(resource_type)
    if not dup:
        return set()
    dup_field = dup['field']
    return set(
        RESOURCES[resource_type].model.objects.values(dup_field)
        .annotate(n=Count('pk')).filter(n__gt=1).values_list(dup_field, flat=True)
    )


def is_missing(value: Any) -> bool:
    """True when a value is null or one of the configured invalid values (trimmed, case-insensitive)."""
    if value is None:
        return True
    return str(value).strip().upper() in get_config()['invalid_values']


def region_groups() -> dict[str, list[str]]:
    """{group_label: [real_region, ...]} combo entries for the Region filter (e.g. "EMEA + MEAA")."""
    groups: dict[str, list[str]] = get_config().get('region_groups', {})
    return groups


def expand_region(region: str) -> list[str]:
    """Selected region (real or group label) -> list of real regions; [] means no filter."""
    if not region:
        return []
    return list(region_groups().get(region, [region]))


def aggregate_breakdown(breakdown: JsonDict, regions: list[str] | None = None, scope: str = '') -> JsonDict:
    """
    Sum a snapshot breakdown ({region: {scope: {...}}}) over the selected regions/scope.
    Returns {'total', 'with_issues', 'field_counts'}.
    """
    out: JsonDict = {'total': 0, 'with_issues': 0, 'field_counts': {}}
    cells = (
        data
        for region, scopes in breakdown.items() if not regions or region in regions
        for sc, data in scopes.items() if not scope or sc == scope
    )
    for data in cells:
        out['total'] += data.get('total', 0)
        out['with_issues'] += data.get('with_issues', 0)
        for code, n in data.get('field_counts', {}).items():
            out['field_counts'][code] = out['field_counts'].get(code, 0) + n
    return out


# ------- Analysis -------

@dataclass
class _AssetAccumulator:
    """Per-asset state while scanning rows: first valid region/scope, issues and per-issue row counts."""

    region: str | None = None
    scope: str | None = None
    rows: int = 0
    missing: set[str] = field(default_factory=set)
    row_counts: dict[str, int] = field(default_factory=dict)

    def add_row(self, row: JsonDict, issues: set[str]) -> None:
        """Account for one row of the asset and the issues found on it."""
        if self.region is None and not is_missing(row['REGION']):
            self.region = str(row['REGION']).strip()
        if self.scope is None and not is_missing(row['SCOPE']):
            self.scope = str(row['SCOPE']).strip()
        self.rows += 1
        self.missing |= issues
        counted = issues | {ANY_ISSUE} if issues else set()
        for code in counted:
            self.row_counts[code] = self.row_counts.get(code, 0) + 1


def _row_issues(row: JsonDict, fields: list[str], dup_field: str | None, dup_values: set[Any]) -> set[str]:
    """Issue codes of a single row: missing required fields + DUPLICATE_CODE if its ID is shared."""
    issues = {f for f in fields if is_missing(row[f])}
    if dup_field and row[dup_field] in dup_values:
        issues.add(DUPLICATE_CODE)
    return issues


def _scan_assets(resource_type: str) -> dict[str, _AssetAccumulator]:
    """One pass over the whole table, grouping rows by asset key."""
    spec = RESOURCES[resource_type]
    fields = list(required_fields(resource_type))
    dup = duplicate_check(resource_type)
    dup_field = dup['field'] if dup else None
    dup_values = duplicated_values(resource_type)
    columns = list(dict.fromkeys(
        spec.asset_key.source_fields + ['REGION', 'SCOPE'] + fields + ([dup_field] if dup_field else [])
    ))

    assets: dict[str, _AssetAccumulator] = {}
    for row in spec.model.objects.values(*columns).iterator(chunk_size=5000):
        acc = assets.setdefault(spec.asset_key.from_values(row), _AssetAccumulator())
        acc.add_row(row, _row_issues(row, fields, dup_field, dup_values))
    return assets


def compute_current(resource_type: str) -> tuple[Current, Population]:
    """
    Scan the whole table and return (current, population):
      current    = {asset_key: CurrentEntry} — only assets with issues
      population = {(region, scope): number of rows}
    Issues are tracked per asset (days_open), but counted per row: an asset can span several rows
    (same key), row_counts says how many of its rows have each issue — so dashboard figures match
    the number of rows shown in the list. 'missing' also holds DUPLICATE_CODE when one of the
    asset's rows shares its ID with another row.
    """
    no_scope = get_config()['no_scope_label']
    no_region = get_config()['no_region_label']
    population: Population = {}
    current: Current = {}
    for key, acc in _scan_assets(resource_type).items():
        region = acc.region or no_region
        scope = acc.scope or no_scope
        population[(region, scope)] = population.get((region, scope), 0) + acc.rows
        if acc.missing:
            current[key] = {'region': region, 'scope': scope, 'missing': acc.missing, 'row_counts': acc.row_counts}
    return current, population


def build_snapshot_data(resource_type: str, current: Current, population: Population) -> JsonDict:
    """
    Aggregate row counts for StorageAnalysisSnapshot (global + per region x scope).
    total_assets / assets_with_issues hold ROW counts (field names kept from the first version).
    """
    codes = list(check_labels(resource_type))
    field_counts = {code: 0 for code in codes}
    breakdown: JsonDict = {}
    for (region, scope), total in population.items():
        breakdown.setdefault(region, {})[scope] = {
            'total': total, 'with_issues': 0, 'field_counts': {code: 0 for code in codes},
        }
    rows_with_issues = 0
    for data in current.values():
        cell = breakdown[data['region']][data['scope']]
        counts = data['row_counts']
        cell['with_issues'] += counts.get(ANY_ISSUE, 0)
        rows_with_issues += counts.get(ANY_ISSUE, 0)
        for code in data['missing']:
            field_counts[code] += counts.get(code, 0)
            cell['field_counts'][code] += counts.get(code, 0)
    return {
        'total_assets': sum(population.values()),
        'assets_with_issues': rows_with_issues,
        'field_counts': field_counts,
        'breakdown': breakdown,
    }


def sync_discrepancies(resource_type: str, current: Current) -> tuple[int, int, int]:
    """Replace StorageDiscrepancy current state for a resource type. Returns (created, updated, deleted)."""
    existing = {d.asset_key: d for d in StorageDiscrepancy.objects.filter(resource_type=resource_type)}
    to_create: list[StorageDiscrepancy] = []
    to_update: list[StorageDiscrepancy] = []
    for key, data in current.items():
        missing_fields = ','.join(sorted(data['missing']))
        new_values = (data['region'], data['scope'], missing_fields, data['row_counts'])
        obj = existing.get(key)
        if obj is None:
            to_create.append(StorageDiscrepancy(
                resource_type=resource_type, asset_key=key, region=data['region'], scope=data['scope'],
                missing_fields=missing_fields, row_counts=data['row_counts'],
            ))
        elif (obj.region, obj.scope, obj.missing_fields, obj.row_counts) != new_values:
            obj.region, obj.scope, obj.missing_fields, obj.row_counts = new_values
            to_update.append(obj)
    to_delete = [obj.pk for key, obj in existing.items() if key not in current]

    StorageDiscrepancy.objects.bulk_create(to_create, batch_size=BULK_BATCH_SIZE)
    StorageDiscrepancy.objects.bulk_update(
        to_update, ['region', 'scope', 'missing_fields', 'row_counts'], batch_size=BULK_BATCH_SIZE,
    )
    StorageDiscrepancy.objects.filter(pk__in=to_delete).delete()
    return len(to_create), len(to_update), len(to_delete)


def _parse_dt(value: str) -> datetime.datetime:
    """Parse an ISO datetime stored in active_issues (always written by isoformat())."""
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f'Invalid datetime in tracker: {value!r}')
    return parsed


def _refresh_tracker(tracker: StorageDiscrepancyTracking, issues_now: set[str], now_str: str) -> bool:
    """
    Keep first_seen of still-open issues, add new ones, drop fixed ones.
    Returns True when the tracker changed (False also when nothing is left: caller deletes it).
    """
    active = {code: v for code, v in tracker.active_issues.items() if code in issues_now}
    for code in issues_now:
        active.setdefault(code, {'first_seen': now_str})
    if not active or active == tracker.active_issues:
        return False
    tracker.active_issues = active
    tracker.oldest_first_seen = min(_parse_dt(v['first_seen']) for v in active.values())
    return True


def update_tracker(
    resource_type: str, current: Current, now: datetime.datetime | None = None,
) -> tuple[int, int, int]:
    """
    Advance StorageDiscrepancyTracking: new issue -> first_seen=now, still open -> kept,
    fixed -> removed, nothing left -> row deleted. Returns (created, updated, deleted).
    """
    now = now or timezone.now()
    now_str = now.isoformat()
    existing = {t.asset_key: t for t in StorageDiscrepancyTracking.objects.filter(resource_type=resource_type)}

    to_create: list[StorageDiscrepancyTracking] = []
    to_update: list[StorageDiscrepancyTracking] = []
    to_delete: list[int] = []
    for key in set(current) | set(existing):
        issues_now = current[key]['missing'] if key in current else set()
        tracker = existing.get(key)
        if tracker is None:
            to_create.append(StorageDiscrepancyTracking(
                resource_type=resource_type, asset_key=key,
                active_issues={code: {'first_seen': now_str} for code in issues_now},
                oldest_first_seen=now,
            ))
        elif not issues_now:
            to_delete.append(tracker.pk)
        elif _refresh_tracker(tracker, issues_now, now_str):
            to_update.append(tracker)

    StorageDiscrepancyTracking.objects.bulk_create(to_create, batch_size=BULK_BATCH_SIZE)
    StorageDiscrepancyTracking.objects.bulk_update(
        to_update, ['active_issues', 'oldest_first_seen'], batch_size=BULK_BATCH_SIZE,
    )
    StorageDiscrepancyTracking.objects.filter(pk__in=to_delete).delete()
    return len(to_create), len(to_update), len(to_delete)


# ------- Query helpers for views -------

def days_open_cutoff(days: int) -> datetime.datetime:
    """An issue is at least `days` days open when first_seen <= cutoff (days_open = elapsed days + 1)."""
    return timezone.now() - datetime.timedelta(days=days - 1)


def days_open_from(first_seen: datetime.datetime | str, now: datetime.datetime | None = None) -> int:
    """Days open (elapsed days + 1) for a first_seen datetime or ISO string."""
    start = _parse_dt(first_seen) if isinstance(first_seen, str) else first_seen
    return ((now or timezone.now()) - start).days + 1


def is_open_since(first_seen: str, cutoff: datetime.datetime) -> bool:
    """True when an active issue's first_seen (ISO string) is at or before the cutoff."""
    return _parse_dt(first_seen) <= cutoff


def missing_q(field_name: str) -> Q:
    """
    Q matching rows where `field_name` is null or an invalid value (trimmed, case-insensitive).
    Relies on the _TRIM_<field> annotations added by discrepancy_queryset().
    """
    return (
        Q(**{f'{field_name}__isnull': True})
        | Q(**{f'_TRIM_{field_name}__in': get_config()['invalid_values']})
    )


def discrepancy_queryset(resource_type: str) -> QuerySet[Any]:
    """
    Model rows that themselves have an issue (a missing required field or a duplicated ID) and
    belong to an asset currently in StorageDiscrepancy — row-level, so the list shows exactly the
    rows counted by the dashboard. Annotated with ASSET_KEY, MISSING_FIELDS, DISC_REGION,
    DISC_SCOPE, FIRST_SEEN (oldest active issue) and _TRIM_<field> for filtering/sorting.
    """
    spec = RESOURCES[resource_type]
    fields = list(required_fields(resource_type))
    disc = StorageDiscrepancy.objects.filter(resource_type=resource_type, asset_key=OuterRef('ASSET_KEY'))
    track = StorageDiscrepancyTracking.objects.filter(resource_type=resource_type, asset_key=OuterRef('ASSET_KEY'))

    row_has_issue = Q()
    for f in fields:
        row_has_issue |= missing_q(f)
    dup = duplicate_check(resource_type)
    if dup:
        row_has_issue |= Q(**{f"{dup['field']}__in": duplicated_values(resource_type)})

    queryset: QuerySet[Any] = (
        spec.model.objects
        .annotate(ASSET_KEY=spec.asset_key.expression())
        .annotate(**{f'_TRIM_{f}': Upper(Trim(f)) for f in fields})
        .annotate(
            MISSING_FIELDS=Subquery(disc.values('missing_fields')[:1]),
            DISC_REGION=Subquery(disc.values('region')[:1]),
            DISC_SCOPE=Subquery(disc.values('scope')[:1]),
            FIRST_SEEN=Subquery(track.values('oldest_first_seen')[:1]),
        )
        .filter(MISSING_FIELDS__isnull=False)
        .filter(row_has_issue)
    )
    return queryset


def tracker_map(resource_type: str, keys: Iterable[str]) -> dict[str, StorageDiscrepancyTracking]:
    """{asset_key: tracker} for the given asset keys."""
    return {
        t.asset_key: t
        for t in StorageDiscrepancyTracking.objects.filter(resource_type=resource_type, asset_key__in=list(keys))
    }
