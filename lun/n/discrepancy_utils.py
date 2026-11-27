"""Shared logic for hardware data-quality discrepancies (analysis command + views)."""

import datetime
import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, TypedDict

from django.db import connection
from django.db.models import OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Trim, Upper
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Server, HardwareDiscrepancy, HardwareDiscrepancyTracking

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'discrepancies_config.json')

# Key of row_counts holding the number of rows failing at least one check
ANY_ISSUE = '_any'
BULK_BATCH_SIZE = 1000

JsonDict = dict[str, Any]
# {(region, country): number of rows}
Population = dict[tuple[str, str], int]


class CurrentEntry(TypedDict):
    """Analysis result for one serial with at least one failing check."""

    region: str
    country: str
    missing: set[str]
    row_counts: dict[str, int]


# {SERIAL: CurrentEntry}
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


def checks() -> dict[str, JsonDict]:
    """Ordered {field_name: check settings} ({'label', optional 'valid_values', 'gauge_title'})."""
    result: dict[str, JsonDict] = get_config()['checks']
    return result


def check_labels() -> dict[str, str]:
    """Ordered {field_name: label} of every check — one gauge / one list column each."""
    return {code: c['label'] for code, c in checks().items()}


def valid_values(code: str) -> list[str] | None:
    """Accepted values (upper-cased) of a value check, None for a presence check."""
    values = checks()[code].get('valid_values')
    return [str(v).strip().upper() for v in values] if values else None


def issue_token(code: str) -> str:
    """Listbox / filter token selecting rows failing a check: MISSING, or NOT <valid values>."""
    accepted = valid_values(code)
    return f"NOT {'/'.join(accepted)}" if accepted else 'MISSING'


def is_missing(value: Any) -> bool:
    """True when a value is null or one of the configured invalid values (trimmed, case-insensitive)."""
    if value is None:
        return True
    return str(value).strip().upper() in get_config()['invalid_values']


def has_issue(code: str, value: Any) -> bool:
    """True when a value fails the check: missing (presence check) or not an accepted value (value check)."""
    accepted = valid_values(code)
    if accepted is None:
        return is_missing(value)
    return value is None or str(value).strip().upper() not in accepted


def region_groups() -> dict[str, list[str]]:
    """{group_label: [real_region, ...]} combo entries for the Region filter."""
    groups: dict[str, list[str]] = get_config().get('region_groups', {})
    return groups


def expand_region(region: str) -> list[str]:
    """Selected region (real or group label) -> list of real regions; [] means no filter."""
    if not region:
        return []
    return list(region_groups().get(region, [region]))


def aggregate_breakdown(breakdown: JsonDict, regions: list[str] | None = None, country: str = '') -> JsonDict:
    """
    Sum a snapshot breakdown ({region: {country: {...}}}) over the selected regions/country.
    Returns {'total', 'with_issues', 'field_counts'}.
    """
    out: JsonDict = {'total': 0, 'with_issues': 0, 'field_counts': {}}
    cells = (
        data
        for region, countries in breakdown.items() if not regions or region in regions
        for ctry, data in countries.items() if not country or ctry == country
    )
    for data in cells:
        out['total'] += data.get('total', 0)
        out['with_issues'] += data.get('with_issues', 0)
        for code, n in data.get('field_counts', {}).items():
            out['field_counts'][code] = out['field_counts'].get(code, 0) + n
    return out


def _in_chunk_size() -> int | None:
    """Values per "IN (...)" clause: half the backend's SQL parameter limit, None when unlimited."""
    limit = connection.features.max_query_params
    return max(limit // 2, 1) if limit else None


def chunked(values: Iterable[Any]) -> Iterator[list[Any]]:
    """Split values into lists fitting the backend's parameter limit (a single list when unlimited)."""
    items = list(values)
    size = _in_chunk_size() or max(len(items), 1)
    for i in range(0, len(items), size):
        yield items[i:i + size]


# ------- Analysis -------

@dataclass
class _AssetAccumulator:
    """Per-serial state while scanning rows: first valid region/country, issues and per-issue row counts."""

    region: str | None = None
    country: str | None = None
    rows: int = 0
    missing: set[str] = field(default_factory=set)
    row_counts: dict[str, int] = field(default_factory=dict)

    def add_row(self, row: JsonDict, issues: set[str]) -> None:
        """Account for one row of the serial and the checks it fails."""
        if self.region is None and not is_missing(row['REGION']):
            self.region = str(row['REGION']).strip()
        if self.country is None and not is_missing(row['COUNTRY']):
            self.country = str(row['COUNTRY']).strip()
        self.rows += 1
        self.missing |= issues
        counted = issues | {ANY_ISSUE} if issues else set()
        for code in counted:
            self.row_counts[code] = self.row_counts.get(code, 0) + 1


def compute_current() -> tuple[Current, Population]:
    """
    Scan the whole table and return (current, population):
      current    = {SERIAL: CurrentEntry} — only serials failing at least one check
      population = {(region, country): number of rows}
    Issues are tracked per serial (days_open) but counted per row, like the list page.
    """
    codes = list(checks())
    no_region = get_config()['no_region_label']
    no_country = get_config()['no_country_label']
    columns = list(dict.fromkeys(['SERIAL', 'REGION', 'COUNTRY'] + codes))

    assets: dict[str, _AssetAccumulator] = {}
    for row in Server.objects.values(*columns).iterator(chunk_size=5000):
        issues = {c for c in codes if has_issue(c, row[c])}
        assets.setdefault(row['SERIAL'] or '', _AssetAccumulator()).add_row(row, issues)

    population: Population = {}
    current: Current = {}
    for key, acc in assets.items():
        region = acc.region or no_region
        country = acc.country or no_country
        population[(region, country)] = population.get((region, country), 0) + acc.rows
        if acc.missing:
            current[key] = {'region': region, 'country': country, 'missing': acc.missing, 'row_counts': acc.row_counts}
    return current, population


def build_snapshot_data(current: Current, population: Population) -> JsonDict:
    """Aggregate row counts for HardwareAnalysisSnapshot (global + per region x country)."""
    codes = list(checks())
    field_counts = {code: 0 for code in codes}
    breakdown: JsonDict = {}
    for (region, country), total in population.items():
        breakdown.setdefault(region, {})[country] = {
            'total': total, 'with_issues': 0, 'field_counts': {code: 0 for code in codes},
        }
    rows_with_issues = 0
    for data in current.values():
        cell = breakdown[data['region']][data['country']]
        counts = data['row_counts']
        cell['with_issues'] += counts.get(ANY_ISSUE, 0)
        rows_with_issues += counts.get(ANY_ISSUE, 0)
        for code in data['missing']:
            field_counts[code] += counts.get(code, 0)
            cell['field_counts'][code] += counts.get(code, 0)
    return {
        'total_rows': sum(population.values()),
        'rows_with_issues': rows_with_issues,
        'field_counts': field_counts,
        'breakdown': breakdown,
    }


def sync_discrepancies(current: Current) -> tuple[int, int, int]:
    """Replace HardwareDiscrepancy current state. Returns (created, updated, deleted)."""
    existing = {d.SERIAL: d for d in HardwareDiscrepancy.objects.all()}
    to_create: list[HardwareDiscrepancy] = []
    to_update: list[HardwareDiscrepancy] = []
    for key, data in current.items():
        missing_fields = ','.join(sorted(data['missing']))
        new_values = (data['region'], data['country'], missing_fields, data['row_counts'])
        obj = existing.get(key)
        if obj is None:
            to_create.append(HardwareDiscrepancy(
                SERIAL=key, region=data['region'], country=data['country'],
                missing_fields=missing_fields, row_counts=data['row_counts'],
            ))
        elif (obj.region, obj.country, obj.missing_fields, obj.row_counts) != new_values:
            obj.region, obj.country, obj.missing_fields, obj.row_counts = new_values
            to_update.append(obj)
    to_delete = [obj.pk for key, obj in existing.items() if key not in current]

    HardwareDiscrepancy.objects.bulk_create(to_create, batch_size=BULK_BATCH_SIZE)
    HardwareDiscrepancy.objects.bulk_update(
        to_update, ['region', 'country', 'missing_fields', 'row_counts'], batch_size=BULK_BATCH_SIZE,
    )
    for pks in chunked(to_delete):
        HardwareDiscrepancy.objects.filter(pk__in=pks).delete()
    return len(to_create), len(to_update), len(to_delete)


def _parse_dt(value: str) -> datetime.datetime:
    """Parse an ISO datetime stored in active_issues (always written by isoformat())."""
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f'Invalid datetime in tracker: {value!r}')
    return parsed


def _refresh_tracker(tracker: HardwareDiscrepancyTracking, issues_now: set[str], now_str: str) -> bool:
    """Keep first_seen of still-open issues, add new ones, drop fixed ones. True when changed."""
    active = {code: v for code, v in tracker.active_issues.items() if code in issues_now}
    for code in issues_now:
        active.setdefault(code, {'first_seen': now_str})
    if not active or active == tracker.active_issues:
        return False
    tracker.active_issues = active
    tracker.oldest_first_seen = min(_parse_dt(v['first_seen']) for v in active.values())
    return True


def update_tracker(current: Current, now: datetime.datetime | None = None) -> tuple[int, int, int]:
    """
    Advance HardwareDiscrepancyTracking: new issue -> first_seen=now, still open -> kept,
    fixed -> removed, nothing left -> row deleted. Returns (created, updated, deleted).
    """
    now = now or timezone.now()
    now_str = now.isoformat()
    existing = {t.SERIAL: t for t in HardwareDiscrepancyTracking.objects.all()}

    to_create: list[HardwareDiscrepancyTracking] = []
    to_update: list[HardwareDiscrepancyTracking] = []
    to_delete: list[int] = []
    for key in set(current) | set(existing):
        issues_now = current[key]['missing'] if key in current else set()
        tracker = existing.get(key)
        if tracker is None:
            to_create.append(HardwareDiscrepancyTracking(
                SERIAL=key, active_issues={code: {'first_seen': now_str} for code in issues_now},
                oldest_first_seen=now,
            ))
        elif not issues_now:
            to_delete.append(tracker.pk)
        elif _refresh_tracker(tracker, issues_now, now_str):
            to_update.append(tracker)

    HardwareDiscrepancyTracking.objects.bulk_create(to_create, batch_size=BULK_BATCH_SIZE)
    HardwareDiscrepancyTracking.objects.bulk_update(
        to_update, ['active_issues', 'oldest_first_seen'], batch_size=BULK_BATCH_SIZE,
    )
    for pks in chunked(to_delete):
        HardwareDiscrepancyTracking.objects.filter(pk__in=pks).delete()
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


def issue_q(code: str) -> Q:
    """
    Q matching rows failing a check (null, invalid value, or not an accepted value).
    Relies on the _TRIM_<field> annotations added by discrepancy_queryset().
    """
    accepted = valid_values(code)
    if accepted is None:
        return Q(**{f'{code}__isnull': True}) | Q(**{f'_TRIM_{code}__in': get_config()['invalid_values']})
    return Q(**{f'{code}__isnull': True}) | ~Q(**{f'_TRIM_{code}__in': accepted})


def discrepancy_queryset() -> QuerySet[Server]:
    """
    Server rows that themselves fail a check and whose SERIAL is currently in HardwareDiscrepancy —
    row-level, so the list shows exactly the rows counted by the dashboard. Annotated with
    MISSING_FIELDS, DISC_REGION, DISC_COUNTRY, FIRST_SEEN and _TRIM_<field>.
    """
    codes = list(checks())
    disc = HardwareDiscrepancy.objects.filter(SERIAL=OuterRef('SERIAL'))
    track = HardwareDiscrepancyTracking.objects.filter(SERIAL=OuterRef('SERIAL'))
    row_has_issue = Q()
    for code in codes:
        row_has_issue |= issue_q(code)
    return (
        Server.objects
        .annotate(**{f'_TRIM_{c}': Upper(Trim(c)) for c in codes})
        .annotate(
            MISSING_FIELDS=Subquery(disc.values('missing_fields')[:1]),
            DISC_REGION=Subquery(disc.values('region')[:1]),
            DISC_COUNTRY=Subquery(disc.values('country')[:1]),
            FIRST_SEEN=Subquery(track.values('oldest_first_seen')[:1]),
        )
        .filter(MISSING_FIELDS__isnull=False)
        .filter(row_has_issue)
    )


def tracker_map(keys: Iterable[str]) -> dict[str, HardwareDiscrepancyTracking]:
    """{SERIAL: tracker} for the given serials (queried in chunks)."""
    return {
        t.SERIAL: t
        for batch in chunked(set(keys))
        for t in HardwareDiscrepancyTracking.objects.filter(SERIAL__in=batch)
    }
