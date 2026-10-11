#    python manage.py analyze_storage_discrepancies [--type share|object|all] [--force] [--dry-run]
#
# Missing-data analysis for NAS shares / S3 objects: required fields come from
# storage/discrepancies_config.json. For each resource type, syncs:
#   - StorageDiscrepancy         — current state, 1 row per asset still missing something
#   - StorageDiscrepancyTracking — first_seen bookkeeping for days_open
#   - StorageAnalysisSnapshot    — 1 row per run (global + per region x scope counts) for gauges/trend

import datetime
import time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from storage.discrepancy_utils import (
    RESOURCES, get_config, compute_current, build_snapshot_data, sync_discrepancies, update_tracker,
)
from storage.models import StorageAnalysisSnapshot, StorageImportStatus


def write_log(message):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {message}")


class Command(BaseCommand):
    help = 'Analyze missing required fields on storage shares/objects and sync discrepancy tables'

    def add_arguments(self, parser):
        parser.add_argument('--type', choices=['share', 'object', 'all'], default='all')
        parser.add_argument('--force', action='store_true',
                            help='Bypass the safety check on population / issue count swings')
        parser.add_argument('--dry-run', action='store_true',
                            help='Compute and report without writing to the database')

    def handle(self, *args, **options):
        types = list(RESOURCES) if options['type'] == 'all' else [options['type']]
        failed = False
        for resource_type in types:
            try:
                self._analyze(resource_type, options['force'], options['dry_run'])
            except Exception as e:
                failed = True
                write_log(f"ERROR [{resource_type}]: {e}")
                if not options['dry_run']:
                    StorageImportStatus.objects.create(
                        source=f'disc-{resource_type}', success=False,
                        message=f'Error during analyze_storage_discrepancies ({resource_type}): {e}',
                    )
        if failed:
            raise SystemExit(1)

    def _analyze(self, resource_type, force, dry_run):
        start = time.monotonic()
        write_log("=" * 60)
        write_log(f"STORAGE DISCREPANCY ANALYSIS [{resource_type}]")

        current, population = compute_current(resource_type)
        data = build_snapshot_data(resource_type, current, population)
        write_log(f"Assets: {data['total_assets']}, with issues: {data['assets_with_issues']}, "
                  f"field_counts={data['field_counts']}")

        # Safety check: an empty table or a big population swing usually means a broken import,
        # not real news — abort instead of resolving every open issue.
        if not force:
            threshold = get_config().get('safety_delta_threshold', 0.10)
            previous = StorageAnalysisSnapshot.objects.filter(resource_type=resource_type).first()
            if data['total_assets'] == 0:
                raise RuntimeError("No assets found in table (empty import?) — aborted, use --force to override")
            if previous and previous.total_assets:
                delta = abs(data['total_assets'] - previous.total_assets) / previous.total_assets
                if delta > threshold:
                    raise RuntimeError(
                        f"Population changed by {delta:.0%} ({previous.total_assets} -> {data['total_assets']}), "
                        f"above {threshold:.0%} threshold — aborted, use --force to override"
                    )

        if dry_run:
            write_log("[DRY RUN] nothing written")
            for key, d in list(current.items())[:20]:
                write_log(f"  {key} | {d['region']} | {d['scope']} | missing={','.join(sorted(d['missing']))}")
            if len(current) > 20:
                write_log(f"  ... and {len(current) - 20} more")
            return

        now = timezone.now()
        with transaction.atomic():
            created, updated, deleted = sync_discrepancies(resource_type, current)
            write_log(f"StorageDiscrepancy: {created} created, {updated} updated, {deleted} removed")
            t_created, t_updated, t_deleted = update_tracker(resource_type, current, now=now)
            write_log(f"Tracker: {t_created} created, {t_updated} updated, {t_deleted} resolved")

            # One snapshot per day and type: a re-run the same day replaces the earlier one
            StorageAnalysisSnapshot.objects.filter(resource_type=resource_type, analysis_date__date=now.date()).delete()
            StorageAnalysisSnapshot.objects.create(
                resource_type=resource_type, analysis_date=now,
                duration_seconds=round(time.monotonic() - start, 2), **data,
            )

        msg = (f"Storage discrepancy analysis ({resource_type}): {data['assets_with_issues']} / "
               f"{data['total_assets']} assets with missing data")
        StorageImportStatus.objects.create(
            source=f'disc-{resource_type}', success=True, message=msg, nb_entries_created=data['assets_with_issues'],
        )
        write_log(msg)
