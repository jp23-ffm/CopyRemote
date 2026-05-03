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

        # Check last import was successful
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

        # Load config
        if not os.path.exists(CONFIG_PATH):
            self.log(f"Config file not found: {CONFIG_PATH}", 'error')
            raise CommandError(f"Config file not found: {CONFIG_PATH}")

        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            self.log(f"Failed to read config: {e}", 'error')
            raise CommandError(f"Failed to read config: {e}")

        # Resolve snapshot date
        if options['date']:
            try:
                snapshot_date = datetime.date.fromisoformat(options['date'])
            except ValueError:
                raise CommandError("Invalid date format, expected YYYY-MM-DD")
        else:
            snapshot_date = datetime.date.today()

        self.log(f"Snapshotting {snapshot_date} — {len(config)} field(s) configured")

        # Process each field
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

            label         = field_conf.get('label', field_name)
            distinct_by   = field_conf.get('distinct_by')
            exclude_values = set(field_conf.get('exclude_values', []))

            try:
                if options['overwrite']:
                    deleted, _ = FieldSnapshot.objects.filter(
                        date=snapshot_date, field_name=field_name
                    ).delete()
                    if deleted:
                        self.log(f"  {label}: deleted {deleted} existing row(s)")
                elif FieldSnapshot.objects.filter(date=snapshot_date, field_name=field_name).exists():
                    self.log(f"  {label}: already exists for {snapshot_date}, skipping (--overwrite to force)")
                    continue

                qs = Server.objects.exclude(**{f'{field_name}__isnull': True})
                if exclude_values:
                    qs = qs.exclude(**{f'{field_name}__in': exclude_values})

                if distinct_by:
                    rows = list(qs.values(field_name).annotate(count=Count(distinct_by, distinct=True)))
                else:
                    rows = list(qs.values(field_name).annotate(count=Count(field_name)))

                snapshots = [
                    FieldSnapshot(
                        date=snapshot_date,
                        field_name=field_name,
                        field_value=row[field_name],
                        count=row['count'],
                    )
                    for row in rows
                ]

                FieldSnapshot.objects.bulk_create(snapshots)
                total_saved += len(snapshots)
                mode = f"distinct {distinct_by}" if distinct_by else "all rows"
                self.log(f"  {label}: {len(snapshots)} value(s) saved ({mode})")

            except Exception as e:
                errors += 1
                self.log(f"  {label}: ERROR — {e}", 'error')
                self.log(traceback.format_exc(), 'debug')

        # Summary
        summary = f"Done — {total_saved} row(s) inserted for {snapshot_date}"
        if errors:
            summary += f", {errors} field(s) failed"
            self.log(summary, 'warning')
        else:
            self.log(self.style.SUCCESS(summary))

        self.log("=== snapshot_field_counts finished ===")
