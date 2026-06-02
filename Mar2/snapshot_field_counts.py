import datetime
import json
import logging
import os
import traceback

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from inventory.models import FieldSnapshot, ImportStatus, Server

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'field_tracking.json')
DEFAULT_LOG  = r'C:\temp\snapshot_field_counts.log'

# Values considered invalid for filter fields (REGION, etc.)
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


class Command(BaseCommand):
    help = 'Take a daily snapshot of field value counts for tracked fields.'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help='Date to snapshot (YYYY-MM-DD), defaults to today')
        parser.add_argument('--overwrite', action='store_true', help='Delete existing snapshot for this date before re-running')
        parser.add_argument('--skip-import-check', action='store_true', help='Skip the last-import success check')
        parser.add_argument('--log', type=str, default=DEFAULT_LOG, help=f'Log file path (default: {DEFAULT_LOG})')

    def log(self, msg, level='info'):
        getattr(self._logger, level)(msg)
        writer = self.stderr if level in ('warning', 'error', 'critical') else self.stdout
        writer.write(msg)

    def handle(self, *args, **options):
        self._logger = _setup_logger(options['log'])
        self.log(f"=== snapshot_field_counts started ===")

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
            self.log(f"Config file not found: {CONFIG_PATH}", 'error')
            raise CommandError(f"Config file not found: {CONFIG_PATH}")

        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            self.log(f"Failed to read config: {e}", 'error')
            raise CommandError(f"Failed to read config: {e}")

        if options['date']:
            try:
                snapshot_date = datetime.date.fromisoformat(options['date'])
            except ValueError:
                raise CommandError("Invalid date format, expected YYYY-MM-DD")
        else:
            snapshot_date = datetime.date.today()

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

            try:
                # ── Global snapshot (filter_field='', filter_value='') ──────────────
                if options['overwrite']:
                    deleted, _ = FieldSnapshot.objects.filter(
                        date=snapshot_date, field_name=field_name, filter_field='', filter_value=''
                    ).delete()
                    if deleted:
                        self.log(f"  {label}: deleted existing global row")
                elif FieldSnapshot.objects.filter(
                    date=snapshot_date, field_name=field_name, filter_field='', filter_value=''
                ).exists():
                    self.log(f"  {label}: already exists for {snapshot_date}, skipping (--overwrite to force)")
                    continue

                base_qs = Server.objects.exclude(**{f'{field_name}__isnull': True})
                if exclude_values:
                    base_qs = base_qs.exclude(**{f'{field_name}__in': exclude_values})

                counts = _build_counts(base_qs, field_name, distinct_by)

                FieldSnapshot.objects.create(
                    date=snapshot_date,
                    field_name=field_name,
                    filter_field='',
                    filter_value='',
                    counts=counts,
                )
                total_saved += 1
                mode = f"distinct {distinct_by}" if distinct_by else "all rows"
                self.log(f"  {label}: {len(counts)} value(s) saved ({mode})")

                # ── Per-filter snapshots ──────────────────────────────────────────
                for fconf in filters_conf:
                    ff = fconf.get('field')
                    if not ff:
                        continue
                    if ff not in server_fields:
                        self.log(f"  {label} × {ff}: filter field not on Server model, skipped", 'warning')
                        continue

                    if options['overwrite']:
                        FieldSnapshot.objects.filter(
                            date=snapshot_date, field_name=field_name, filter_field=ff
                        ).delete()
                    elif FieldSnapshot.objects.filter(
                        date=snapshot_date, field_name=field_name, filter_field=ff
                    ).exists():
                        self.log(f"  {label} × {ff}: already exists, skipping")
                        continue

                    filter_values = list(
                        Server.objects
                        .exclude(**{f'{ff}__isnull': True})
                        .exclude(**{f'{ff}__in': _FILTER_SENTINEL_VALUES})
                        .values_list(ff, flat=True)
                        .distinct()
                        .order_by(ff)
                    )

                    filter_snaps = []
                    for fv in filter_values:
                        scoped_qs = base_qs.filter(**{ff: fv})
                        fv_counts = _build_counts(scoped_qs, field_name, distinct_by)
                        if fv_counts:
                            filter_snaps.append(FieldSnapshot(
                                date=snapshot_date,
                                field_name=field_name,
                                filter_field=ff,
                                filter_value=fv,
                                counts=fv_counts,
                            ))

                    FieldSnapshot.objects.bulk_create(filter_snaps)
                    total_saved += len(filter_snaps)
                    self.log(f"  {label} × {ff}: {len(filter_snaps)} filter value(s) saved")

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


def _build_counts(qs, field_name, distinct_by):
    """Return {field_value: count} dict from a Server queryset."""
    if distinct_by:
        rows = qs.values(field_name).annotate(count=Count(distinct_by, distinct=True))
    else:
        rows = qs.values(field_name).annotate(count=Count(field_name))
    return {row[field_name]: row['count'] for row in rows}
