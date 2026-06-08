"""Query engine for ServerHistory (SCD2 temporal table).

All field names are validated against server_history_meta.json before reaching
the ORM — never interpolate user input directly into queries.

Dedup logic for SUM aggregation:
  relation_in_play = any relation-grain field (APP_NAME_VALUE, APP_CRITICALITY, APP_OWNERBUSINESSLINE) in group_by OR filters
  True  → attributed path  : direct SUM (multi-app rows are intentional)
  False → deduped path     : DISTINCT SERVER_ID before SUM (each machine counted once)

COUNT DISTINCT never needs dedup — COUNT(DISTINCT x) is always correct.
"""
import json
import os
from collections import defaultdict
from datetime import date, timedelta

from django.core.cache import cache
from django.db.models import Count, Q, Sum

from inventory.models import ServerHistory

# ── Metadata ──────────────────────────────────────────────────────────────────

_META = None


def get_meta():
    global _META
    if _META is None:
        path = os.path.join(os.path.dirname(__file__), 'server_history_meta.json')
        with open(path, encoding='utf-8') as f:
            _META = json.load(f)
    return _META


RELATION_FIELDS = frozenset({'APP_NAME_VALUE', 'APP_CRITICALITY', 'APP_OWNERBUSINESSLINE'})

# ── Date axis helpers ─────────────────────────────────────────────────────────


def _next_date(d, step):
    if step == 'day':
        return d + timedelta(days=1)
    if step == 'week':
        return d + timedelta(weeks=1)
    # month: always land on the 1st
    month = d.month % 12 + 1
    year = d.year + (1 if d.month == 12 else 0)
    return d.replace(year=year, month=month, day=1)


def generate_dates(start, end, step):
    dates, d = [], start
    while d <= end:
        dates.append(d)
        d = _next_date(d, step)
    return dates


# ── Query helpers ─────────────────────────────────────────────────────────────


def _base_qs_at(T):
    """All history rows valid at date T."""
    return ServerHistory.objects.filter(
        valid_from__lte=T,
    ).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gt=T)
    )


def _apply_filters(qs, filters):
    """Apply validated filter conditions to a queryset.

    Same-field eq  filters are combined with OR  (union).
    Same-field neq filters are combined with AND (exclusion).
    Other ops (is_null, in, not_in) are applied individually with AND.
    """
    # Group by field to enable same-field OR/AND merging
    grouped = {}
    order = []
    for f in filters:
        field = f['field']
        if field not in grouped:
            grouped[field] = {'eq': [], 'neq': [], 'others': []}
            order.append(field)
        op = f['op']
        val = f.get('value', '')
        if op == 'eq':
            grouped[field]['eq'].append(val)
        elif op == 'neq':
            grouped[field]['neq'].append(val)
        else:
            grouped[field]['others'].append((op, val))

    for field in order:
        g = grouped[field]
        if g['eq']:
            # Multiple values on same field → OR (field = A OR field = B)
            qs = qs.filter(**{field + '__in': g['eq']})
        if g['neq']:
            # Multiple exclusions on same field → NOT IN (field != A AND field != B)
            qs = qs.exclude(**{field + '__in': g['neq']})
        for op, value in g['others']:
            if op == 'in':
                vals = value if isinstance(value, list) else [v.strip() for v in value.split(',')]
                qs = qs.filter(**{field + '__in': vals})
            elif op == 'not_in':
                vals = value if isinstance(value, list) else [v.strip() for v in value.split(',')]
                qs = qs.exclude(**{field + '__in': vals})
            elif op == 'is_null':
                qs = qs.filter(**{field + '__isnull': True})
            elif op == 'is_not_null':
                qs = qs.filter(**{field + '__isnull': False})
    return qs


def _query_point(T, measure_field, measure_agg, group_by, filters, relation_grain):
    """Return {key_tuple: value} for a single date point T."""
    qs = _base_qs_at(T)
    qs = _apply_filters(qs, filters)
    gb = list(group_by)

    if measure_agg == 'count_distinct':
        # COUNT(DISTINCT measure_field) — correct with no dedup needed
        if gb:
            rows = qs.values(*gb).annotate(value=Count(measure_field, distinct=True))
            return {tuple(r.get(g) for g in gb): r['value'] for r in rows}
        return {('Total',): qs.aggregate(v=Count(measure_field, distinct=True))['v'] or 0}

    # measure_agg == 'sum'
    if not relation_grain:
        # Dedup: collapse to one row per (SERVER_ID, *group_dims) before summing
        distinct_rows = list(qs.values('SERVER_ID', *gb, measure_field).distinct())
        agg = defaultdict(int)
        for row in distinct_rows:
            key = tuple(row.get(g) for g in gb) if gb else ('Total',)
            agg[key] += row.get(measure_field) or 0
        return dict(agg)

    # Attributed path: direct SUM
    if gb:
        rows = qs.values(*gb).annotate(value=Sum(measure_field))
        return {tuple(r.get(g) for g in gb): r['value'] or 0 for r in rows}
    val = qs.aggregate(v=Sum(measure_field))['v'] or 0
    return {('Total',): val}


# ── Public API ────────────────────────────────────────────────────────────────


MAX_DATE_POINTS = 120  # hard ceiling — protects Gunicorn workers from long-running loops


def run_query(spec, chart_limit=10):
    """Execute a history query and return Chart.js-compatible data.

    spec = {
        measure_field : str,           # key from meta['fields']
        measure_agg   : str,           # 'count_distinct' | 'sum'
        group_by      : [str, ...],    # 0-2 dimension keys, groupable=True
        filters       : [{field, op, value}, ...],
        start         : date,
        end           : date,
        step          : 'day'|'week'|'month',
    }

    Returns all series sorted by total descending, plus chart_limit so the
    frontend can cap the chart while showing everything in the table.

    Returns {
        labels      : [str, ...],
        datasets    : [{label: str, data: [int, ...]}, ...],   # all series
        chart_limit : int,
        truncated   : bool,   # True if date axis was capped at MAX_DATE_POINTS
        true_totals : [int, ...] | None,
            # Per-date ungrouped COUNT DISTINCT, returned only when
            # measure_agg=='count_distinct' and group_by is non-empty.
            # The sum-of-groups inflates the total (same value counted once per
            # group it appears in); true_totals gives the real distinct count.
    }
    """
    measure_field = spec['measure_field']
    measure_agg = spec.get('measure_agg', 'count_distinct')
    group_by = spec.get('group_by', [])[:2]
    filters = spec.get('filters', [])
    start, end = spec['start'], spec['end']
    step = spec.get('step', 'month')

    relation_grain = (
        any(f in RELATION_FIELDS for f in group_by) or
        any(f['field'] in RELATION_FIELDS for f in filters)
    )

    dates = generate_dates(start, end, step)
    truncated = len(dates) > MAX_DATE_POINTS
    if truncated:
        # Keep last MAX_DATE_POINTS so the most recent data is always visible
        dates = dates[-MAX_DATE_POINTS:]

    date_data = [
        _query_point(T, measure_field, measure_agg, group_by, filters, relation_grain)
        for T in dates
    ]

    # Rank keys by total across all dates
    all_keys: set = set()
    for d in date_data:
        all_keys.update(d.keys())

    key_totals = {k: sum(d.get(k) or 0 for d in date_data) for k in all_keys}
    sorted_keys = sorted(key_totals, key=lambda k: -key_totals[k])

    def _label(k):
        if k == ('Total',) or not group_by:
            return 'Total'
        return ' / '.join(str(v) if v is not None else '—' for v in k) or '—'

    # True ungrouped total — only meaningful for count_distinct with a group_by.
    # For sum, sum-of-groups IS the correct total (additive measure).
    true_totals = None
    if measure_agg == 'count_distinct' and group_by:
        true_totals = [
            _query_point(T, measure_field, 'count_distinct', [], filters, False)[('Total',)]
            for T in dates
        ]

    return {
        'labels': [str(d) for d in dates],
        'truncated': truncated,
        'datasets': [
            {
                'label': _label(k),
                'data': [date_data[i].get(k) or 0 for i in range(len(dates))],
                'total': key_totals[k],
            }
            for k in sorted_keys
        ],
        'chart_limit': chart_limit,
        'true_totals': true_totals,
    }


_FILTER_CACHE_KEY = 'history_filter_values'
_FILTER_CACHE_TTL = 3600  # 1 hour


def get_all_filter_values():
    """Return {field: [values]} for all filterable fields, cached for 1 hour.

    Runs one DB query per filterable field on first call, then serves from cache.
    Call invalidate_filter_cache() after an import to force a refresh.
    """
    cached = cache.get(_FILTER_CACHE_KEY)
    if cached is not None:
        return cached

    meta = get_meta()
    filterable = [k for k, v in meta['fields'].items() if v.get('filterable')]
    open_qs = ServerHistory.objects.filter(valid_to__isnull=True)

    result = {}
    for field in filterable:
        vals = sorted(
            v for v in open_qs.values_list(field, flat=True).distinct()
            if v is not None and v != ''
        )
        if vals:
            result[field] = vals

    cache.set(_FILTER_CACHE_KEY, result, _FILTER_CACHE_TTL)
    return result


def invalidate_filter_cache():
    """Force filter values to be recomputed on next page load."""
    cache.delete(_FILTER_CACHE_KEY)


_DRILLDOWN_LIMIT = 200


def _drilldown_fields(group_by, measure_field, measure_agg):
    """Fields to return per row: SERVER_ID + group dims + measure if sum."""
    seen = {'SERVER_ID'}
    fields = ['SERVER_ID']
    for f in group_by:
        if f not in seen:
            seen.add(f)
            fields.append(f)
    if measure_agg == 'sum' and measure_field not in seen:
        fields.append(measure_field)
    return fields


def drilldown_servers(point_date, group_by, group_values, filters,
                      measure_field='SERVER_ID', measure_agg='count_distinct'):
    """Return server rows valid at point_date matching the given group values.

    group_by    : list of field names (0-2)
    group_values: parallel list of values (same length as group_by)
    Returns {servers: [...], total: int, shown: int, fields: [...]}
    """
    qs = _base_qs_at(point_date)
    qs = _apply_filters(qs, filters)

    for field, value in zip(group_by, group_values):
        if value in ('—', 'None', '', None):
            qs = qs.filter(**{field + '__isnull': True})
        else:
            qs = qs.filter(**{field: value})

    fields = _drilldown_fields(group_by, measure_field, measure_agg)
    total = qs.values('SERVER_ID').distinct().count()
    rows = list(
        qs.values(*fields)
        .order_by('SERVER_ID')[:_DRILLDOWN_LIMIT]
    )
    return {'servers': rows, 'total': total, 'shown': len(rows), 'fields': fields}
