"""SCD Type 2 ingestion: Server → ServerHistory.

Run daily via cron after the main inventory import.

Algorithm per (server_key, app) pair:
  - New in inventory, absent in open history  → INSERT valid_from=today, valid_to=None
  - Present in both, attributes changed        → SET valid_to=today, INSERT new open row
  - Present in both, attributes unchanged      → skip
  - Present in open history, absent in invent  → SET valid_to=today
"""
import hashlib
import logging
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.history_query_engine import invalidate_filter_cache
from inventory.models import Server, ServerHistory, ServerHistoryImportStatus

logger = logging.getLogger(__name__)

TRACKED_FIELDS = [
    'APP_CRITICALITY', 'APP_OWNERBUSINESSLINE',
    'ENVIRONMENT', 'INFRAVERSION', 'ECOSYSTEM', 'PERIMETER',
    'OSSHORTNAME', 'OSFAMILY', 'PAMELA_PRODUCT',
    'REGION', 'SNOW_DATACENTER', 'MACHINE_TYPE', 'MANUFACTURER', 'MODEL',
    'SNOW_SUPPORTGROUP', 'SNOW_STATUS',
    'CPU', 'RAM',
]

ALIVE_STATUSES = {
    'Operational', 'Under maintenance', 'Planned',
    # Legacy values kept for backward compatibility
    'Installed', 'In Use', 'ALIVE', 'Active', 'In Stock',
    'Ready', 'Deployed', 'Running',
}


def _parse_int(val):
    if val is None:
        return None
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return None


def _normalize(val):
    if val is None:
        return None
    s = str(val)
    # Remove literal escape sequences stored as strings (e.g. "\t" = backslash+t)
    for seq in (r'\t', r'\n', r'\r'):
        s = s.replace(seq, ' ')
    s = ' '.join(s.split())  # collapse actual whitespace + trim
    if s in ('', 'MISSING', 'N/A', 'UNKNOWN', 'NULL', '-', 'null', 'None'):
        return None
    return s


def _server_to_attrs(row):
    attrs = {f: _normalize(row.get(f)) for f in TRACKED_FIELDS if f not in ('CPU', 'RAM')}
    attrs['SNOW_STATUS'] = attrs['SNOW_STATUS'] or 'OPERATIONAL'
    attrs['CPU'] = _parse_int(row.get('CPU'))
    attrs['RAM'] = _parse_int(row.get('RAM'))
    return attrs


def _hash(attrs):
    parts = [str(attrs.get(f) or '') for f in TRACKED_FIELDS]
    return hashlib.md5('|'.join(parts).encode()).hexdigest()


class Command(BaseCommand):
    help = 'SCD2 ingestion of the current inventory into server_history.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would change without writing to the database.',
        )
        parser.add_argument(
            '--all-statuses', action='store_true',
            help='Include all SNOW_STATUS values (default: ALIVE statuses only).',
        )
        parser.add_argument(
            '--clear', action='store_true',
            help='Delete all existing ServerHistory rows before importing.',
        )
        parser.add_argument(
            '--date',
            help='Override valid_from date (YYYY-MM-DD). Default: today.',
        )
        parser.add_argument(
            '--diff-file', default=None, metavar='PATH',
            help='Diff report path (default: /tmp/scd2_diff_YYYY-MM-DD.txt).',
        )
        parser.add_argument(
            '--no-diff-file', action='store_true',
            help='Disable diff report.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = date.fromisoformat(options['date']) if options.get('date') else date.today()

        state = {
            'success': False,
            'message': 'Run did not complete',
            'import_date': today,
            'dry_run': dry_run,
            'nb_new': 0,
            'nb_changed': 0,
            'nb_disappeared': 0,
            'nb_closed': 0,
            'nb_inserted': 0,
        }

        logger.info('import_server_history started — date=%s dry_run=%s', today, dry_run)

        try:
            self._run(options, today, dry_run, state)
        except Exception as e:
            state['message'] = str(e)
            logger.error('import_server_history failed: %s', e)
            raise
        finally:
            if not dry_run:
                try:
                    ServerHistoryImportStatus.objects.create(
                        success        = state['success'],
                        message        = state['message'],
                        import_date    = state['import_date'],
                        dry_run        = state['dry_run'],
                        nb_new         = state['nb_new'],
                        nb_changed     = state['nb_changed'],
                        nb_disappeared = state['nb_disappeared'],
                        nb_closed      = state['nb_closed'],
                        nb_inserted    = state['nb_inserted'],
                    )
                except Exception as exc:
                    logger.error('Could not write ServerHistoryImportStatus: %s', exc)

    def _run(self, options, today, dry_run, state):
        """Main ingestion logic. Updates state dict with run results."""
        # Resolve diff file path (on by default, --no-diff-file disables)
        if options.get('no_diff_file'):
            diff_path = None
        else:
            diff_path = options.get('diff_file') or f'/tmp/scd2_diff_{today}.txt'

        if options.get('clear') and not dry_run:
            deleted, _ = ServerHistory.objects.all().delete()
            self.stdout.write(f'Cleared {deleted:,} existing rows.')
            logger.info('Cleared %d existing ServerHistory rows', deleted)

        self.stdout.write(f'Running SCD2 ingestion for {today} (dry_run={dry_run})')

        # ── 1. Load current inventory ──────────────────────────────────────
        fields = [
            'SERVER_ID', 'APP_NAME_VALUE',
            'APP_CRITICALITY', 'APP_OWNERBUSINESSLINE',
            'ENVIRONMENT', 'INFRAVERSION', 'ECOSYSTEM', 'PERIMETER',
            'OSSHORTNAME', 'OSFAMILY', 'PAMELA_PRODUCT',
            'REGION', 'SNOW_DATACENTER', 'MACHINE_TYPE', 'MANUFACTURER', 'MODEL',
            'SNOW_SUPPORTGROUP', 'SNOW_STATUS', 'CPU', 'RAM',
        ]
        qs = Server.objects.values(*fields)
        if not options['all_statuses']:
            qs = qs.filter(SNOW_STATUS__in=ALIVE_STATUSES)

        current = {}
        for row in qs.iterator(chunk_size=5000):
            key = (row['SERVER_ID'], row['APP_NAME_VALUE'] or '')
            if key not in current:
                current[key] = row
        self.stdout.write(f'  Current inventory: {len(current):,} (server, app) pairs')
        logger.info('Current inventory: %d (server, app) pairs', len(current))

        # ── 2. Load open history rows ──────────────────────────────────────
        open_qs = ServerHistory.objects.filter(
            valid_to__isnull=True
        ).values('id', 'SERVER_ID', 'APP_NAME_VALUE', *TRACKED_FIELDS)

        open_versions = {}
        for row in open_qs.iterator(chunk_size=5000):
            key = (row['SERVER_ID'], row['APP_NAME_VALUE'])
            open_versions[key] = row
        self.stdout.write(f'  Open history rows: {len(open_versions):,}')
        logger.info('Open history rows: %d', len(open_versions))

        # ── 3. Diff ────────────────────────────────────────────────────────
        ids_to_close = []
        rows_to_insert = []

        current_keys = set(current.keys())
        open_keys = set(open_versions.keys())

        n_new         = len(current_keys - open_keys)
        n_changed     = 0
        n_disappeared = len(open_keys - current_keys)

        new_list         = []  # [(sid, app)]
        changed_list     = []  # [(sid, app, [(field, old, new)])]
        disappeared_list = []  # [(sid, app)]

        for key in sorted(current_keys - open_keys):
            sid, app = key
            new_list.append((sid, app))
            rows_to_insert.append(ServerHistory(
                SERVER_ID=sid, APP_NAME_VALUE=app,
                valid_from=today, valid_to=None,
                **_server_to_attrs(current[key]),
            ))

        for key in sorted(current_keys & open_keys):
            attrs = _server_to_attrs(current[key])
            existing_attrs = {f: open_versions[key][f] for f in TRACKED_FIELDS}
            if _hash(attrs) != _hash(existing_attrs):
                n_changed += 1
                ids_to_close.append(open_versions[key]['id'])
                sid, app = key
                field_diffs = [
                    (f, existing_attrs[f], attrs[f])
                    for f in TRACKED_FIELDS
                    if existing_attrs[f] != attrs[f]
                ]
                changed_list.append((sid, app, field_diffs))
                rows_to_insert.append(ServerHistory(
                    SERVER_ID=sid, APP_NAME_VALUE=app,
                    valid_from=today, valid_to=None,
                    **attrs,
                ))

        for key in sorted(open_keys - current_keys):
            ids_to_close.append(open_versions[key]['id'])
            disappeared_list.append(key)

        self.stdout.write(
            f'  New: {n_new:,}  '
            f'Changed: {n_changed:,}  '
            f'Disappeared: {n_disappeared:,}'
        )
        logger.info('Diff — new: %d  changed: %d  disappeared: %d', n_new, n_changed, n_disappeared)

        state.update({
            'nb_new': n_new,
            'nb_changed': n_changed,
            'nb_disappeared': n_disappeared,
            'nb_closed': len(ids_to_close),
            'nb_inserted': len(rows_to_insert),
        })

        if dry_run:
            msg = (
                f'DRY RUN — would close {len(ids_to_close)} rows '
                f'and insert {len(rows_to_insert)} rows.'
            )
            self.stdout.write(self.style.WARNING(msg))
            logger.info(msg)
            state['success'] = True
            state['message'] = msg
            self._write_diff(diff_path, today, new_list, changed_list, disappeared_list)
            return

        # ── 4. Apply in a single transaction ──────────────────────────────
        with transaction.atomic():
            if ids_to_close:
                ServerHistory.objects.filter(id__in=ids_to_close).update(valid_to=today)
            if rows_to_insert:
                total = len(rows_to_insert)
                inserted = 0
                batch_size = 2000
                for i in range(0, total, batch_size):
                    ServerHistory.objects.bulk_create(rows_to_insert[i:i + batch_size])
                    inserted += min(batch_size, total - i)
                    if inserted % 10000 == 0:
                        print(f'  {inserted:,}/{total:,} rows inserted...')

        invalidate_filter_cache()

        summary = (
            f'Done — closed {len(ids_to_close)} rows, '
            f'inserted {len(rows_to_insert)} rows.'
        )
        self.stdout.write(self.style.SUCCESS(summary))
        logger.info(summary)

        state['success'] = True
        state['message'] = summary
        self._write_diff(diff_path, today, new_list, changed_list, disappeared_list)

    def _write_diff(self, diff_path, today, new_list, changed_list, disappeared_list):
        """Write diff report to diff_path; no-op if diff_path is None."""
        if not diff_path:
            return
        try:
            _write_diff_file(diff_path, today, new_list, changed_list, disappeared_list)
            self.stdout.write(f'Diff written to {diff_path}')
            logger.info('Diff written to %s', diff_path)
        except Exception as exc:
            self.stderr.write(f'Could not write diff file: {exc}')
            logger.error('Could not write diff file %s: %s', diff_path, exc)


def _write_diff_file(path, run_date, new_list, changed_list, disappeared_list):
    """Write a human-readable diff report to path, one line per server."""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'=== SCD2 Diff — {run_date} ===\n\n')

        f.write(f'NEW ({len(new_list)})\n')
        for sid, app in new_list:
            f.write(f'  NEW  {sid:<30}  {app}\n')

        f.write(f'\nCHANGED ({len(changed_list)})\n')
        for sid, app, diffs in changed_list:
            changes = '  |  '.join(
                f'{field}: {old if old is not None else "(null)"}→{new if new is not None else "(null)"}'
                for field, old, new in diffs
            )
            f.write(f'  CHG  {sid:<30}  {app:<30}  {changes}\n')

        f.write(f'\nDISAPPEARED ({len(disappeared_list)})\n')
        for sid, app in disappeared_list:
            f.write(f'  DEL  {sid:<30}  {app}\n')
