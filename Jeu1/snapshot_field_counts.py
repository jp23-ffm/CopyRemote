import datetime
import json
import logging
import os
import traceback

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from inventory.models import FieldSnapshotFiltered, ImportStatus, Server, SnapshotStatus

CONFIG_PATH  = os.path.join(os.path.dirname(__file__), '..', '..', 'field_tracking.json')
DEFAULT_LOG  = r'C:\temp\snapshot_field_counts.log'
DEFAULT_TOP_N = 10

_FILTER_SENTINEL_VALUES = {'', 'UNKNOWN', 'MISSING', 'N/A', 'NULL', '-', 'null', 'None'}


def _setup_logger(log_path):
    logger = logging.getLogger('snapshot_field_counts')
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    fh = logging.FileHandler(log_path, encoding='utf-8')
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def _build_counts(qs, field_name, distinct_by):
    """Return {field_value: count} from a Server queryset."""
    if distinct_by:
        rows = qs.values(field_name).annotate(count=Count(distinct_by, distinct=True))
    else:
        rows = qs.values(field_name).annotate(count=Count(field_name))
    return {row[field_name]: row['count'] for row in rows}


def _get_top_filter_values(ff, top_n, distinct_by):
    """Return top_n values of filter field ff ranked by server count."""
    qs = (
        Server.objects
        .exclude(**{f'{ff}__isnull': True})
        .exclude(**{f'{ff}__in': _FILTER_SENTINEL_VALUES})
        .values(ff)
        .annotate(n=Count(distinct_by or 'id', distinct=bool(distinct_by)))
        .order_by('-n')
    )
    if top_n > 0:
        qs = qs[:top_n]
    return [row[ff] for row in qs]


class Command(BaseCommand):
    help = 'Take a daily snapshot of field value counts for tracked fields.'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help='Date to snapshot (YYYY-MM-DD), defaults to today')
        parser.add_argument('--overwrite', action='store_true', help='Delete existing snapshot for this date before re-running')
        parser.add_argument('--skip-import-check', action='store_true', help='Skip the last-import success check')
        parser.add_argument('--log', type=str, default=DEFAULT_LOG, help=f'Log file path (default: {DEFAULT_LOG})')
        parser.add_argument('--status', action='store_true', help='Show snapshot coverage summary and exit')

    def log(self, msg, level='info'):
        getattr(self._logger, level)(msg)
        writer = self.stderr if level in ('warning', 'error', 'critical') else self.stdout
        writer.write(msg)

    def handle(self, *args, **options):
        if options['status']:
            self._show_status()
            return

        self._logger = _setup_logger(options['log'])
        self.log("=== snapshot_field_counts started ===")

        state = {
            'success': False, 'message': 'Run did not complete',
            'snapshot_date': None, 'total_saved': 0, 'errors': 0, 'nb_fields': 0,
        }

        try:
            self._run(options, state)
        except CommandError as e:
            state['message'] = str(e)
            raise
        except Exception as e:
            state['message'] = str(e)
            raise
        finally:
            try:
                SnapshotStatus.objects.create(
                    success          = state['success'],
                    message          = state['message'],
                    snapshot_date    = state['snapshot_date'],
                    nb_rows_inserted = state['total_saved'],
                    nb_fields        = state['nb_fields'],
                    nb_errors        = state['errors'],
                )
            except Exception:
                pass

    def _run(self, options, state):
        """Main snapshot logic. Updates state dict with run results."""
        if not options['skip_import_check']:
            try:
                last_import = ImportStatus.objects.order_by('-date_import').first()
                if last_import is None:
                    self.log("No import record found — run dbimport_inventory_csv first", 'error')
                    raise CommandError("Aborted: no import record found.")
                if not last_import.success:
                    self.log(
                        f"Last import ({last_import.date_import:%Y-%m-%d %H:%M}) failed — "
                        f"snapshot aborted. Use --skip-import-check to force.",
                        'error',
                    )
                    raise CommandError("Aborted: last import was not successful.")
                self.log(f"Last import OK ({last_import.date_import:%Y-%m-%d %H:%M})")
            except CommandError:
                raise
            except Exception as e:
                self.log(f"Could not check ImportStatus: {e}", 'error')
                raise CommandError(f"Aborted: {e}")

        if not os.path.exists(CONFIG_PATH):
            raise CommandError(f"Config file not found: {CONFIG_PATH}")

        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            raise CommandError(f"Failed to read config: {e}")

        if options['date']:
            try:
                snapshot_date = datetime.date.fromisoformat(options['date'])
            except ValueError:
                raise CommandError("Invalid date format, expected YYYY-MM-DD")
        else:
            snapshot_date = datetime.date.today()

        state['snapshot_date'] = snapshot_date
        state['nb_fields']    = len(config)
        self.log(f"Snapshotting {snapshot_date} — {len(config)} field(s) configured")

        server_fields = {f.name for f in Server._meta.get_fields()}
        total_saved   = 0
        errors        = 0

        for field_conf in config:
            field_name = field_conf.get('field')
            if not field_name:
                self.log("Entry without 'field' key, skipped", 'warning')
                continue
            if field_name not in server_fields:
                self.log(f"{field_name}: not found on Server model, skipped", 'warning')
                continue

            label          = field_conf.get('label', field_name)
            distinct_by    = field_conf.get('distinct_by')
            exclude_values = set(field_conf.get('exclude_values', []))
            filters_conf   = field_conf.get('filters', [])
            combos_conf    = field_conf.get('filter_combinations', [])

            try:
                base_qs = Server.objects.exclude(**{f'{field_name}__isnull': True})
                if exclude_values:
                    base_qs = base_qs.exclude(**{f'{field_name}__in': exclude_values})

                # ── Global (no filter) ────────────────────────────────────────────
                saved = self._save_snapshot(
                    snapshot_date, field_name, '', '', '', '',
                    base_qs, distinct_by, options['overwrite'],
                    label=label,
                )
                total_saved += saved

                # ── Single-filter snapshots ───────────────────────────────────────
                for fconf in filters_conf:
                    ff = fconf.get('field')
                    if not ff or ff not in server_fields:
                        self.log(f"  {label} × {ff}: not on Server model, skipped", 'warning')
                        continue

                    top_n = fconf.get('top_n', DEFAULT_TOP_N)
                    filter_values = _get_top_filter_values(ff, top_n, distinct_by)

                    if options['overwrite']:
                        FieldSnapshotFiltered.objects.filter(
                            date=snapshot_date, field_name=field_name,
                            filter_field=ff, filter_field2='',
                        ).delete()
                    elif FieldSnapshotFiltered.objects.filter(
                        date=snapshot_date, field_name=field_name,
                        filter_field=ff, filter_field2='',
                    ).exists():
                        self.log(f"  {label} × {ff}: already exists, skipping")
                        continue

                    snaps = []
                    for fv in filter_values:
                        counts = _build_counts(base_qs.filter(**{ff: fv}), field_name, distinct_by)
                        if counts:
                            snaps.append(FieldSnapshotFiltered(
                                date=snapshot_date, field_name=field_name,
                                filter_field=ff, filter_value=fv,
                                filter_field2='', filter_value2='',
                                counts=counts,
                            ))
                    FieldSnapshotFiltered.objects.bulk_create(snaps)
                    total_saved += len(snaps)
                    self.log(f"  {label} × {ff}: {len(snaps)}/{top_n} filter value(s) saved")

                # ── Combination snapshots ─────────────────────────────────────────
                for combo in combos_conf:
                    fields = combo.get('fields', [])
                    if len(fields) not in (2, 3):
                        self.log(f"  {label}: combination must have 2 or 3 fields, skipped", 'warning')
                        continue
                    if any(f not in server_fields for f in fields):
                        self.log(f"  {label}: combo field(s) not on Server model, skipped", 'warning')
                        continue

                    top_n  = combo.get('top_n', DEFAULT_TOP_N)
                    label_combo = '+'.join(fields)
                    ff1    = fields[0]
                    ff2    = fields[1]
                    ff3    = fields[2] if len(fields) == 3 else ''

                    if options['overwrite']:
                        FieldSnapshotFiltered.objects.filter(
                            date=snapshot_date, field_name=field_name,
                            filter_field=ff1, filter_field2=ff2, filter_field3=ff3,
                        ).delete()
                    elif FieldSnapshotFiltered.objects.filter(
                        date=snapshot_date, field_name=field_name,
                        filter_field=ff1, filter_field2=ff2, filter_field3=ff3,
                    ).exists():
                        self.log(f"  {label} × {label_combo}: already exists, skipping")
                        continue

                    values1 = _get_top_filter_values(ff1, top_n, distinct_by)
                    values2 = _get_top_filter_values(ff2, top_n, distinct_by)
                    values3 = _get_top_filter_values(ff3, top_n, distinct_by) if ff3 else ['']

                    snaps = []
                    for fv1 in values1:
                        for fv2 in values2:
                            for fv3 in values3:
                                scoped = base_qs.filter(**{ff1: fv1, ff2: fv2})
                                if ff3 and fv3:
                                    scoped = scoped.filter(**{ff3: fv3})
                                counts = _build_counts(scoped, field_name, distinct_by)
                                if counts:
                                    snaps.append(FieldSnapshotFiltered(
                                        date=snapshot_date, field_name=field_name,
                                        filter_field=ff1, filter_value=fv1,
                                        filter_field2=ff2, filter_value2=fv2,
                                        filter_field3=ff3, filter_value3=fv3 if ff3 else '',
                                        counts=counts,
                                    ))
                    FieldSnapshotFiltered.objects.bulk_create(snaps)
                    total_saved += len(snaps)
                    max_combos = len(values1) * len(values2) * (len(values3) if ff3 else 1)
                    self.log(f"  {label} × {label_combo}: {len(snaps)}/{max_combos} combination(s) saved")

            except Exception as e:
                errors += 1
                self.log(f"  {label}: ERROR — {e}", 'error')
                self.log(traceback.format_exc(), 'debug')

        summary = f"Done — {total_saved} row(s) inserted for {snapshot_date}"
        if errors:
            summary += f", {errors} field(s) failed"
            self.log(summary, 'warning')
        else:
            self.log(self.style.SUCCESS(summary))
        self.log("=== snapshot_field_counts finished ===")

        state['success']     = (errors == 0)
        state['message']     = summary
        state['total_saved'] = total_saved
        state['errors']      = errors

    def _save_snapshot(self, date, field_name, ff, fv, ff2, fv2, base_qs, distinct_by, overwrite, label=''):
        """Save a single global snapshot row. Returns 1 if saved, 0 if skipped."""
        if overwrite:
            deleted, _ = FieldSnapshotFiltered.objects.filter(
                date=date, field_name=field_name,
                filter_field=ff, filter_value=fv,
                filter_field2=ff2, filter_value2=fv2,
            ).delete()
            if deleted:
                self.log(f"  {label}: deleted existing global row")
        elif FieldSnapshotFiltered.objects.filter(
            date=date, field_name=field_name,
            filter_field=ff, filter_value=fv,
            filter_field2=ff2, filter_value2=fv2,
        ).exists():
            self.log(f"  {label}: already exists for {date}, skipping (--overwrite to force)")
            return 0

        counts = _build_counts(base_qs, field_name, distinct_by)
        FieldSnapshotFiltered.objects.create(
            date=date, field_name=field_name,
            filter_field=ff, filter_value=fv,
            filter_field2=ff2, filter_value2=fv2,
            counts=counts,
        )
        mode = f"distinct {distinct_by}" if distinct_by else "all rows"
        self.log(f"  {label}: {len(counts)} value(s) saved ({mode})")
        return 1

    def _show_status(self):
        """Print snapshot coverage per field and filter combination."""
        from django.db.models import Min, Max, Count as DCount

        rows = list(
            FieldSnapshotFiltered.objects
            .values('field_name', 'filter_field', 'filter_field2', 'filter_field3')
            .annotate(
                n_days=DCount('date', distinct=True),
                first_date=Min('date'),
                last_date=Max('date'),
            )
            .order_by('field_name', 'filter_field', 'filter_field2', 'filter_field3')
        )

        if not rows:
            self.stdout.write("No snapshot data found.")
            return

        current_field = None
        for r in rows:
            if r['field_name'] != current_field:
                current_field = r['field_name']
                self.stdout.write(f"\n{self.style.SUCCESS(current_field)}")
            filters = [f for f in [r['filter_field'], r['filter_field2'], r['filter_field3']] if f]
            filter_str = ' + '.join(filters) if filters else '(global)'
            self.stdout.write(
                f"  {filter_str:<45}  {r['n_days']:>4} day(s)   "
                f"{r['first_date']:%Y-%m-%d} -> {r['last_date']:%Y-%m-%d}"
            )
        self.stdout.write('')
