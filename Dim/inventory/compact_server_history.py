"""
Compact ServerHistory by reducing row density in older time zones.

Zone definitions (hardcoded):
  Daily   : [today-30d,  today]       → never touched
  Weekly  : [today-70d,  today-30d)   → one row per (server, app) per Sunday
  Monthly : [oldest,     today-70d)   → one row per (server, app) per 1st of month

Algorithm per (SERVER_ID, APP_NAME_VALUE) per zone:
  1. Take a snapshot at each reference date (Sunday / 1st).
  2. Collapse consecutive identical snapshots into a single row.
  3. Delete closed rows completely contained in the zone.
  4. Trim any pre-zone row whose valid_to falls inside the zone.
  5. Insert the new compacted rows.

Rows that span a zone boundary are never split.
Open rows (valid_to IS NULL) are only deleted when the last compacted row
is also open (i.e., the server is still alive and we're taking over).
"""
import hashlib
import logging
from collections import defaultdict
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Min, Q

from inventory.models import ServerHistory

logger_w = logging.getLogger('compact.weekly')
logger_m = logging.getLogger('compact.monthly')

# ── Hardcoded thresholds ──────────────────────────────────────────────────────
DAILY_KEEP  = 30   # days kept at full (daily) resolution
WEEKLY_KEEP = 70   # days = 10 weeks; older than this goes to monthly

TRACKED_FIELDS = [
    'APP_CRITICALITY', 'APP_OWNERBUSINESSLINE',
    'ENVIRONMENT', 'INFRAVERSION', 'ECOSYSTEM', 'PERIMETER',
    'OSSHORTNAME', 'OSFAMILY', 'PAMELA_PRODUCT',
    'REGION', 'SNOW_DATACENTER', 'MACHINE_TYPE', 'MANUFACTURER', 'MODEL',
    'SNOW_SUPPORTGROUP', 'SNOW_STATUS',
    'CPU', 'RAM',
]
_ROW_FIELDS = ('id', 'SERVER_ID', 'APP_NAME_VALUE', 'valid_from', 'valid_to', *TRACKED_FIELDS)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _attrs_hash(attrs):
    parts = [str(attrs.get(f) or '') for f in TRACKED_FIELDS]
    return hashlib.md5('|'.join(parts).encode()).hexdigest()


def _sundays_between(start, end):
    """All Sundays S with start <= S < end."""
    days_ahead = (6 - start.weekday()) % 7
    d = start + timedelta(days=days_ahead)
    result = []
    while d < end:
        result.append(d)
        d += timedelta(weeks=1)
    return result


def _firsts_between(start, end):
    """All 1st-of-month dates d with start <= d < end."""
    if start.day == 1:
        d = start
    else:
        m = start.month % 12 + 1
        y = start.year + (1 if start.month == 12 else 0)
        d = date(y, m, 1)
    result = []
    while d < end:
        result.append(d)
        m = d.month % 12 + 1
        y = d.year + (1 if d.month == 12 else 0)
        d = date(y, m, 1)
    return result


def _state_at(rows_sorted, ref_date):
    """Return attrs dict valid at ref_date, or None if server didn't exist."""
    for row in reversed(rows_sorted):
        if row['valid_from'] <= ref_date:
            if row['valid_to'] is None or row['valid_to'] > ref_date:
                return {f: row[f] for f in TRACKED_FIELDS}
    return None


def _build_after_zone_map(zone_end):
    """
    One query: for every (SERVER_ID, APP_NAME_VALUE), the earliest valid_from
    that falls at or after zone_end (i.e. in the daily zone).
    Returns {(sid, app): date}.
    """
    rows = (
        ServerHistory.objects
        .filter(valid_from__gte=zone_end)
        .values('SERVER_ID', 'APP_NAME_VALUE')
        .annotate(first_after=Min('valid_from'))
    )
    return {(r['SERVER_ID'], r['APP_NAME_VALUE']): r['first_after'] for r in rows}


def _load_pairs(zone_start, zone_end):
    """
    Load rows in and around [zone_start, zone_end), grouped by
    (SERVER_ID, APP_NAME_VALUE).  Includes:
      - rows starting before zone_start that extend into the zone
      - rows starting inside the zone
    """
    qs = (
        ServerHistory.objects
        .filter(
            Q(valid_from__lt=zone_start, valid_to__gt=zone_start)   # spanning into zone
            | Q(valid_from__gte=zone_start, valid_from__lt=zone_end)  # inside zone
        )
        .values(*_ROW_FIELDS)
        .order_by('SERVER_ID', 'APP_NAME_VALUE', 'valid_from')
    )

    pairs = defaultdict(list)
    for row in qs.iterator(chunk_size=5000):
        pairs[(row['SERVER_ID'], row['APP_NAME_VALUE'])].append(row)

    # Keep only pairs that actually have rows starting inside the zone
    # (pre-zone-only rows would mean the server state spans the whole zone → nothing to do)
    return {
        key: rows for key, rows in pairs.items()
        if any(zone_start <= r['valid_from'] < zone_end for r in rows)
    }


# ── Core compaction ───────────────────────────────────────────────────────────

def _compact_zone(pairs, zone_start, zone_end, ref_dates, after_zone_map, dry_run, logger):
    """
    Compact all (SERVER_ID, APP_NAME_VALUE) pairs for a zone.
    Returns (total_deleted, total_inserted).
    """
    n_del = n_ins = n_skip = 0

    for (sid, app), rows in pairs.items():
        rows_sorted = sorted(rows, key=lambda r: r['valid_from'])

        # If a single row spans the entire zone, state didn't change → skip
        if any(
            r['valid_from'] < zone_start and (r['valid_to'] is None or r['valid_to'] >= zone_end)
            for r in rows_sorted
        ):
            n_skip += 1
            continue

        # Snapshots at each reference date (None = server didn't exist yet)
        snapshots = [(d, _state_at(rows_sorted, d)) for d in ref_dates]
        snapshots = [(d, s) for d, s in snapshots if s is not None]
        if not snapshots:
            n_skip += 1
            continue

        # Collapse consecutive identical states
        groups = []
        for ref_date, attrs in snapshots:
            if groups and _attrs_hash(groups[-1]['attrs']) == _attrs_hash(attrs):
                pass  # same state — current group naturally extends to this date
            else:
                groups.append({'valid_from': ref_date, 'attrs': attrs, 'valid_to': None})

        # valid_to for each group except the last
        for i in range(len(groups) - 1):
            groups[i]['valid_to'] = groups[i + 1]['valid_from']

        # Last group valid_to: first row at or after zone_end (pre-fetched map)
        groups[-1]['valid_to'] = after_zone_map.get((sid, app))

        # Pre-zone row whose valid_to falls inside the zone (spanning_into)
        # → will be trimmed to zone_start so no overlap with our new rows
        spanning_into = next(
            (r for r in rows_sorted
             if r['valid_from'] < zone_start
             and r['valid_to'] is not None
             and zone_start < r['valid_to'] <= zone_end),
            None,
        )
        if spanning_into:
            # Our first compacted row must start at zone_start to avoid a gap
            groups[0]['valid_from'] = zone_start

        # IDs to delete: closed rows completely inside the zone
        del_ids = [
            r['id'] for r in rows_sorted
            if zone_start <= r['valid_from'] < zone_end
            and r['valid_to'] is not None
            and r['valid_to'] <= zone_end
        ]
        # Open rows starting in zone: delete only if last compacted row is also open
        if groups[-1]['valid_to'] is None:
            del_ids += [
                r['id'] for r in rows_sorted
                if zone_start <= r['valid_from'] < zone_end and r['valid_to'] is None
            ]

        pair_del = len(del_ids)
        pair_ins = len(groups)
        logger.debug('%s / %s  del=%d ins=%d', sid, app or '—', pair_del, pair_ins)

        if not dry_run:
            with transaction.atomic():
                if spanning_into:
                    ServerHistory.objects.filter(id=spanning_into['id']).update(valid_to=zone_start)
                if del_ids:
                    ServerHistory.objects.filter(id__in=del_ids).delete()
                ServerHistory.objects.bulk_create([
                    ServerHistory(
                        SERVER_ID=sid,
                        APP_NAME_VALUE=app,
                        valid_from=g['valid_from'],
                        valid_to=g['valid_to'],
                        **g['attrs'],
                    )
                    for g in groups
                ])

        n_del += pair_del
        n_ins += pair_ins

    logger.info(
        'zone [%s → %s)  pairs=%d  skipped=%d  deleted=%d  inserted=%d%s',
        zone_start, zone_end, len(pairs), n_skip, n_del, n_ins,
        '  [DRY RUN]' if dry_run else '',
    )
    return n_del, n_ins


# ── Management command ────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = 'Compact ServerHistory: reduce row density in weekly and monthly zones.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would change without writing to the database.',
        )
        parser.add_argument(
            '--zone', choices=['weekly', 'monthly', 'all'], default='all',
            help='Which zone to compact (default: all).',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        zone    = options['zone']
        today   = date.today()

        daily_cutoff  = today - timedelta(days=DAILY_KEEP)
        weekly_cutoff = today - timedelta(days=WEEKLY_KEEP)

        if zone in ('weekly', 'all'):
            self._compact_weekly(daily_cutoff, weekly_cutoff, dry_run)

        if zone in ('monthly', 'all'):
            self._compact_monthly(weekly_cutoff, dry_run)

    # ── Weekly ────────────────────────────────────────────────────────────────

    def _compact_weekly(self, zone_end, zone_start, dry_run):
        ref_dates = _sundays_between(zone_start, zone_end)
        logger_w.info(
            'Starting — zone [%s → %s)  Sundays=%d  dry_run=%s',
            zone_start, zone_end, len(ref_dates), dry_run,
        )
        self.stdout.write(f'Weekly [{zone_start} → {zone_end})  {len(ref_dates)} Sundays')

        if not ref_dates:
            logger_w.info('No Sundays in zone — nothing to do.')
            return

        pairs = _load_pairs(zone_start, zone_end)
        after_zone_map = _build_after_zone_map(zone_end)
        logger_w.info('Pairs to process: %d', len(pairs))
        self.stdout.write(f'  {len(pairs):,} pairs')

        n_del, n_ins = _compact_zone(pairs, zone_start, zone_end, ref_dates, after_zone_map, dry_run, logger_w)

        msg = f'Weekly done — deleted {n_del:,}, inserted {n_ins:,}'
        if dry_run:
            msg += '  [DRY RUN]'
            self.stdout.write(self.style.WARNING(msg))
        else:
            self.stdout.write(self.style.SUCCESS(msg))

    # ── Monthly ───────────────────────────────────────────────────────────────

    def _compact_monthly(self, zone_end, dry_run):
        oldest = (
            ServerHistory.objects
            .order_by('valid_from')
            .values_list('valid_from', flat=True)
            .first()
        )
        if not oldest:
            logger_m.info('No ServerHistory data — skipping.')
            return

        zone_start = oldest
        ref_dates  = _firsts_between(zone_start, zone_end)
        logger_m.info(
            'Starting — zone [%s → %s)  1sts=%d  dry_run=%s',
            zone_start, zone_end, len(ref_dates), dry_run,
        )
        self.stdout.write(f'Monthly [{zone_start} → {zone_end})  {len(ref_dates)} 1sts')

        if not ref_dates:
            logger_m.info('No 1sts-of-month in zone — nothing to do.')
            return

        pairs = _load_pairs(zone_start, zone_end)
        after_zone_map = _build_after_zone_map(zone_end)
        logger_m.info('Pairs to process: %d', len(pairs))
        self.stdout.write(f'  {len(pairs):,} pairs')

        n_del, n_ins = _compact_zone(pairs, zone_start, zone_end, ref_dates, after_zone_map, dry_run, logger_m)

        msg = f'Monthly done — deleted {n_del:,}, inserted {n_ins:,}'
        if dry_run:
            msg += '  [DRY RUN]'
            self.stdout.write(self.style.WARNING(msg))
        else:
            self.stdout.write(self.style.SUCCESS(msg))
