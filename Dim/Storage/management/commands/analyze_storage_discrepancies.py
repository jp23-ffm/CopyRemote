#    python manage.py analyze_storage_discrepancies [--type share|object|all] [--force] [--dry-run]
#
# Data-quality analysis for NAS shares / S3 objects: required fields and the duplicate check come
# from storage/discrepancies_config.json. For each resource type, syncs:
#   - StorageDiscrepancy         — current state, 1 row per asset with at least one issue
#   - StorageDiscrepancyTracking — first_seen bookkeeping for days_open
#   - StorageAnalysisSnapshot    — 1 row per run (global + per region x scope row counts) for gauges/trend
"""Management command: storage data-quality (discrepancies) analysis."""

import datetime
import time
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand
from django.db import DatabaseError, transaction
from django.utils import timezone

from storage.discrepancy_utils import (
    RESOURCES, Current, JsonDict, build_snapshot_data, compute_current, get_config, sync_discrepancies,
    update_tracker,
)
from storage.models import StorageAnalysisSnapshot, StorageImportStatus

DRY_RUN_PREVIEW = 20
DEFAULT_SAFETY_THRESHOLD = 0.10


class AnalysisAborted(Exception):
    """Raised when the safety check rejects a run (empty table, suspicious population swing)."""


# Failures recorded in StorageImportStatus for one resource type without stopping the others
ANALYSIS_ERRORS = (AnalysisAborted, DatabaseError, OSError, KeyError, ValueError)


def write_log(message: str) -> None:
    """Timestamped console log, same format as the other import/analysis commands."""
    print(f"[{datetime.datetime.now():%H:%M:%S}] {message}")


def check_safety(resource_type: str, data: JsonDict) -> None:
    """
    An empty table or a big population swing usually means a broken import, not real news:
    abort instead of resolving every open issue.
    """
    total = data['total_assets']
    if total == 0:
        raise AnalysisAborted("No rows found in table (empty import?) — aborted, use --force to override")
    previous = StorageAnalysisSnapshot.objects.filter(resource_type=resource_type).first()
    if previous is None or not previous.total_assets:
        return
    threshold = get_config().get('safety_delta_threshold', DEFAULT_SAFETY_THRESHOLD)
    delta = abs(total - previous.total_assets) / previous.total_assets
    if delta > threshold:
        raise AnalysisAborted(
            f"Population changed by {delta:.0%} ({previous.total_assets} -> {total}), "
            f"above {threshold:.0%} threshold — aborted, use --force to override"
        )


def log_dry_run(current: Current) -> None:
    """Show a preview of the assets with issues without writing anything."""
    write_log("[DRY RUN] nothing written")
    for key, entry in list(current.items())[:DRY_RUN_PREVIEW]:
        write_log(f"  {key} | {entry['region']} | {entry['scope']} | missing={','.join(sorted(entry['missing']))}")
    if len(current) > DRY_RUN_PREVIEW:
        write_log(f"  ... and {len(current) - DRY_RUN_PREVIEW} more")


def persist(resource_type: str, current: Current, data: JsonDict, start: float) -> None:
    """Sync current state + tracker and write today's snapshot, in one transaction."""
    now = timezone.now()
    with transaction.atomic():
        created, updated, deleted = sync_discrepancies(resource_type, current)
        write_log(f"StorageDiscrepancy: {created} created, {updated} updated, {deleted} removed")
        created, updated, deleted = update_tracker(resource_type, current, now=now)
        write_log(f"Tracker: {created} created, {updated} updated, {deleted} resolved")

        # One snapshot per day and type: a re-run the same day replaces the earlier one
        StorageAnalysisSnapshot.objects.filter(resource_type=resource_type, analysis_date__date=now.date()).delete()
        StorageAnalysisSnapshot.objects.create(
            resource_type=resource_type, analysis_date=now,
            duration_seconds=round(time.monotonic() - start, 2), **data,
        )


class Command(BaseCommand):
    """Analyze required fields / duplicate IDs on storage shares and objects."""

    help = 'Analyze missing required fields / duplicate IDs on storage shares/objects and sync discrepancy tables'

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument('--type', choices=['share', 'object', 'all'], default='all')
        parser.add_argument('--force', action='store_true',
                            help='Bypass the safety check on population / issue count swings')
        parser.add_argument('--dry-run', action='store_true',
                            help='Compute and report without writing to the database')

    def handle(self, *args: Any, **options: Any) -> None:
        types = list(RESOURCES) if options['type'] == 'all' else [options['type']]
        failed = False
        for resource_type in types:
            try:
                self._analyze(resource_type, options['force'], options['dry_run'])
            except ANALYSIS_ERRORS as e:
                failed = True
                write_log(f"ERROR [{resource_type}]: {e}")
                if not options['dry_run']:
                    StorageImportStatus.objects.create(
                        source=f'disc-{resource_type}', success=False,
                        message=f'Error during analyze_storage_discrepancies ({resource_type}): {e}',
                    )
        if failed:
            raise SystemExit(1)

    def _analyze(self, resource_type: str, force: bool, dry_run: bool) -> None:
        """Analyze one resource type: compute, safety check, then write (or preview)."""
        start = time.monotonic()
        write_log("=" * 60)
        write_log(f"STORAGE DISCREPANCY ANALYSIS [{resource_type}]")

        current, population = compute_current(resource_type)
        data = build_snapshot_data(resource_type, current, population)
        write_log(f"Rows: {data['total_assets']}, with issues: {data['assets_with_issues']}, "
                  f"field_counts={data['field_counts']}")

        if not force:
            check_safety(resource_type, data)
        if dry_run:
            log_dry_run(current)
            return

        persist(resource_type, current, data, start)
        msg = (f"Storage discrepancy analysis ({resource_type}): {data['assets_with_issues']} / "
               f"{data['total_assets']} rows with issues")
        StorageImportStatus.objects.create(
            source=f'disc-{resource_type}', success=True, message=msg, nb_entries_created=data['assets_with_issues'],
        )
        write_log(msg)
