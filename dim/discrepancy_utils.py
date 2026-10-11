"""Shared logic for storage missing-data discrepancies (analysis command + views)."""

import datetime
import json
import os
from threading import Lock

from django.db.models import CharField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce, Concat
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (
    StorageShare, StorageObject, ShareAnnotation, ObjectAnnotation,
    StorageDiscrepancy, StorageDiscrepancyTracking,
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'discrepancies_config.json')

_config_cache = None
_config_mtime = 0
_config_lock = Lock()


def get_config():
    """Load discrepancies_config.json, reloaded when the file changes."""
    global _config_cache, _config_mtime
    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except OSError:
        return _config_cache
    if _config_cache is not None and mtime == _config_mtime:
        return _config_cache
    with _config_lock:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            _config_cache = json.load(f)
        _config_mtime = mtime
    return _config_cache


def _share_key_expr():
    # DB-side equivalent of views._share_annotation_key: f"{FILER}|{SHARE_PATH}"
    return Concat(
        Coalesce('FILER', Value('')), Value('|'), Coalesce('SHARE_PATH', Value('')),
        output_field=CharField(),
    )


RESOURCES = {
    'share': {
        'model': StorageShare,
        'annotation_cls': ShareAnnotation,
        'annotation_key_field': 'share_key',
        'key_fn': lambda item: f"{item.FILER or ''}|{item.SHARE_PATH or ''}",
        'key_values_fn': lambda row: f"{row['FILER'] or ''}|{row['SHARE_PATH'] or ''}",
        'key_source_fields': ['FILER', 'SHARE_PATH'],
        'key_expr': _share_key_expr,
        'primary_field': 'SHARE_NAME',
    },
    'object': {
        'model': StorageObject,
        'annotation_cls': ObjectAnnotation,
        'annotation_key_field': 'NAME',
        'key_fn': lambda item: item.NAME or '',
        'key_values_fn': lambda row: row['NAME'] or '',
        'key_source_fields': ['NAME'],
        'key_expr': lambda: Coalesce('NAME', Value(''), output_field=CharField()),
        'primary_field': 'NAME',
    },
}


def resource_config(resource_type):
    """Merged static (RESOURCES) + JSON config for a resource type, or None if unknown."""
    if resource_type not in RESOURCES:
        return None
    conf = dict(RESOURCES[resource_type])
    conf.update(get_config()['resources'][resource_type])
    return conf


def required_fields(resource_type):
    """Ordered {field_name: label} of required fields for a resource type."""
    return get_config()['resources'][resource_type]['required_fields']


def is_missing(value):
    if value is None:
        return True
    invalid = get_config()['invalid_values']
    return str(value).strip().upper() in invalid


def normalize_scope(value):
    return get_config()['no_scope_label'] if is_missing(value) else str(value).strip()


def region_groups():
    """{group_label: [real_region, ...]} combo entries for the Region filter (e.g. "EMEA + MEAA")."""
    return get_config().get('region_groups', {})


def expand_region(region):
    """Selected region (real or group label) -> list of real regions; [] means no filter."""
    if not region:
        return []
    return list(region_groups().get(region, [region]))


def aggregate_breakdown(breakdown, regions=None, scope=''):
    """
    Sum a snapshot breakdown ({region: {scope: {...}}}) over the selected regions/scope.
    Returns {'total', 'with_issues', 'field_counts'}.
    """
    out = {'total': 0, 'with_issues': 0, 'field_counts': {}}
    for region, scopes in breakdown.items():
        if regions and region not in regions:
            continue
        for sc, data in scopes.items():
            if scope and sc != scope:
                continue
            out['total'] += data.get('total', 0)
            out['with_issues'] += data.get('with_issues', 0)
            for f, n in data.get('field_counts', {}).items():
                out['field_counts'][f] = out['field_counts'].get(f, 0) + n
    return out


def compute_current(resource_type):
    """
    Scan the whole table and return (current, population):
      current    = {asset_key: {'region': str, 'scope': str, 'missing': {field, ...}}} — only assets with issues
      population = {(region, scope): number of distinct assets}
    An asset can span several rows (same key): a field counts as missing if it is missing on any row.
    """
    conf = RESOURCES[resource_type]
    fields = list(required_fields(resource_type))
    columns = list(dict.fromkeys(conf['key_source_fields'] + ['REGION', 'SCOPE'] + fields))

    assets = {}
    for row in conf['model'].objects.values(*columns).iterator(chunk_size=5000):
        key = conf['key_values_fn'](row)
        entry = assets.setdefault(key, {'region': None, 'scope': None, 'missing': set()})
        if entry['region'] is None and not is_missing(row['REGION']):
            entry['region'] = str(row['REGION']).strip()
        if entry['scope'] is None and not is_missing(row['SCOPE']):
            entry['scope'] = str(row['SCOPE']).strip()
        for f in fields:
            if is_missing(row[f]):
                entry['missing'].add(f)

    no_scope = get_config()['no_scope_label']
    no_region = get_config()['no_region_label']
    population = {}
    current = {}
    for key, entry in assets.items():
        region = entry['region'] or no_region
        scope = entry['scope'] or no_scope
        population[(region, scope)] = population.get((region, scope), 0) + 1
        if entry['missing']:
            current[key] = {'region': region, 'scope': scope, 'missing': entry['missing']}
    return current, population


def build_snapshot_data(resource_type, current, population):
    """Aggregate counts for StorageAnalysisSnapshot (global + per region x scope)."""
    fields = list(required_fields(resource_type))
    field_counts = {f: 0 for f in fields}
    breakdown = {}
    for (region, scope), total in population.items():
        breakdown.setdefault(region, {})[scope] = {
            'total': total, 'with_issues': 0, 'field_counts': {f: 0 for f in fields},
        }
    for data in current.values():
        b = breakdown[data['region']][data['scope']]
        b['with_issues'] += 1
        for f in data['missing']:
            field_counts[f] += 1
            b['field_counts'][f] += 1
    return {
        'total_assets': sum(population.values()),
        'assets_with_issues': len(current),
        'field_counts': field_counts,
        'breakdown': breakdown,
    }


def sync_discrepancies(resource_type, current):
    """Replace StorageDiscrepancy current state for a resource type. Returns (created, updated, deleted)."""
    existing = {d.asset_key: d for d in StorageDiscrepancy.objects.filter(resource_type=resource_type)}
    to_create, to_update = [], []
    for key, data in current.items():
        missing_fields = ','.join(sorted(data['missing']))
        obj = existing.get(key)
        if obj:
            if (obj.region, obj.scope, obj.missing_fields) != (data['region'], data['scope'], missing_fields):
                obj.region = data['region']
                obj.scope = data['scope']
                obj.missing_fields = missing_fields
                to_update.append(obj)
        else:
            to_create.append(StorageDiscrepancy(
                resource_type=resource_type, asset_key=key,
                region=data['region'], scope=data['scope'], missing_fields=missing_fields,
            ))
    to_delete = [obj.pk for key, obj in existing.items() if key not in current]

    if to_create:
        StorageDiscrepancy.objects.bulk_create(to_create, batch_size=1000)
    if to_update:
        StorageDiscrepancy.objects.bulk_update(to_update, ['region', 'scope', 'missing_fields'], batch_size=1000)
    if to_delete:
        StorageDiscrepancy.objects.filter(pk__in=to_delete).delete()
    return len(to_create), len(to_update), len(to_delete)


def update_tracker(resource_type, current, now=None):
    """
    Advance StorageDiscrepancyTracking: new missing field -> first_seen=now, still missing -> kept,
    fixed -> removed, nothing left -> row deleted. Returns (created, updated, deleted).
    """
    now = now or timezone.now()
    now_str = now.isoformat()
    existing = {t.asset_key: t for t in StorageDiscrepancyTracking.objects.filter(resource_type=resource_type)}

    to_create, to_update, to_delete = [], [], []
    for key in set(current) | set(existing):
        fields_now = current.get(key, {}).get('missing', set())
        tracker = existing.get(key)
        if tracker:
            active = {f: v for f, v in tracker.active_issues.items() if f in fields_now}
            for f in fields_now:
                active.setdefault(f, {'first_seen': now_str})
            if not active:
                to_delete.append(tracker.pk)
            elif active != tracker.active_issues:
                tracker.active_issues = active
                tracker.oldest_first_seen = min(parse_datetime(v['first_seen']) for v in active.values())
                to_update.append(tracker)
        elif fields_now:
            to_create.append(StorageDiscrepancyTracking(
                resource_type=resource_type, asset_key=key,
                active_issues={f: {'first_seen': now_str} for f in fields_now},
                oldest_first_seen=now,
            ))

    if to_create:
        StorageDiscrepancyTracking.objects.bulk_create(to_create, batch_size=1000)
    if to_update:
        StorageDiscrepancyTracking.objects.bulk_update(to_update, ['active_issues', 'oldest_first_seen'], batch_size=1000)
    if to_delete:
        StorageDiscrepancyTracking.objects.filter(pk__in=to_delete).delete()
    return len(to_create), len(to_update), len(to_delete)


# ------- Query helpers for views -------

def days_open_cutoff(days):
    """An issue is at least `days` days open when first_seen <= cutoff (days_open = elapsed days + 1)."""
    return timezone.now() - datetime.timedelta(days=days - 1)


def days_open_from(first_seen, now=None):
    if not first_seen:
        return ''
    if isinstance(first_seen, str):
        first_seen = parse_datetime(first_seen)
    return ((now or timezone.now()) - first_seen).days + 1


def discrepancy_queryset(resource_type):
    """
    Model queryset restricted to assets currently in StorageDiscrepancy, annotated with
    ASSET_KEY, MISSING_FIELDS, DISC_REGION, DISC_SCOPE and FIRST_SEEN (oldest active issue) for filtering/sorting.
    """
    conf = RESOURCES[resource_type]
    disc = StorageDiscrepancy.objects.filter(resource_type=resource_type, asset_key=OuterRef('ASSET_KEY'))
    track = StorageDiscrepancyTracking.objects.filter(resource_type=resource_type, asset_key=OuterRef('ASSET_KEY'))
    return (
        conf['model'].objects
        .annotate(ASSET_KEY=conf['key_expr']())
        .annotate(
            MISSING_FIELDS=Subquery(disc.values('missing_fields')[:1]),
            DISC_REGION=Subquery(disc.values('region')[:1]),
            DISC_SCOPE=Subquery(disc.values('scope')[:1]),
            FIRST_SEEN=Subquery(track.values('oldest_first_seen')[:1]),
        )
        .filter(MISSING_FIELDS__isnull=False)
    )


def tracker_map(resource_type, keys):
    return {
        t.asset_key: t
        for t in StorageDiscrepancyTracking.objects.filter(resource_type=resource_type, asset_key__in=list(keys))
    }


def decorate_items(resource_type, items, filtered_fields=None):
    """
    Set DAYS_OPEN on each item (context-sensitive: when filtering on specific missing fields,
    days_open is the oldest among those fields only). Also sets tracker_json for tooltips.
    """
    conf = RESOURCES[resource_type]
    trackers = tracker_map(resource_type, {conf['key_fn'](i) for i in items})
    now = timezone.now()
    for item in items:
        tracker = trackers.get(conf['key_fn'](item))
        if not tracker:
            item.DAYS_OPEN = ''
            continue
        issues = tracker.active_issues
        if filtered_fields:
            relevant = [v['first_seen'] for f, v in issues.items() if f in filtered_fields]
            if relevant:
                item.DAYS_OPEN = max(days_open_from(fs, now) for fs in relevant)
                continue
        item.DAYS_OPEN = days_open_from(tracker.oldest_first_seen, now)
