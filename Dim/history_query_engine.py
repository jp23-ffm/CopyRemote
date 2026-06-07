"""Query engine for ServerHistory (SCD2 temporal table).

All field names are validated against server_history_meta.json before reaching
the ORM — never interpolate user input directly into queries.

Dedup logic for SUM aggregation:
  relation_in_play = any relation-grain field (APP_NAME_VALUE, APP_CRITICALITY) in group_by OR filters
  True  → attributed path  : direct SUM (multi-app rows are intentional)
  False → deduped path     : DISTINCT SERVER_ID before SUM (each machine counted once)

COUNT DISTINCT never needs dedup — COUNT(DISTINCT x) is always correct.
"""
import json
import os
from collections import defaultdict
from datetime import date, timedelta

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


RELATION_FIELDS = frozenset({'APP_NAME_VALUE', 'APP_CRITICALITY'})

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
    """Apply validated filter conditions to a queryset."""
    for f in filters:
        field, op = f['field'], f['op']
        value = f.get('value', '')
        if op == 'eq':
            qs = qs.filter(**{field: value})
        elif op == 'in':
            vals = value if isinstance(value, list) else [v.strip() for v in value.split(',')]
            qs = qs.filter(**{field + '__in': vals})
        elif op == 'neq':
            qs = qs.exclude(**{field: value})
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
    }


def get_filter_values(field, limit=60):
    """Distinct non-null values for a filterable field (current open rows only)."""
    return sorted(
        v for v in
        ServerHistory.objects.filter(valid_to__isnull=True)
        .values_list(field, flat=True).distinct()
        if v is not None and v != ''
    )[:limit]
