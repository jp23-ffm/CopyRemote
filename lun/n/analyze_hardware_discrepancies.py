#    python manage.py analyze_hardware_discrepancies [--force] [--dry-run]
#
# Data-quality analysis for hardware assets: checks come from hardware/discrepancies_config.json
# (presence checks + value checks such as WARRANTY_ACTIVE == YES). Syncs:
#   - HardwareDiscrepancy         — current state, 1 row per SERIAL failing at least one check
#   - HardwareDiscrepancyTracking — first_seen bookkeeping for days_open
#   - HardwareAnalysisSnapshot    — 1 row per day (global + per region x country row counts)
"""Management command: hardware data-quality (discrepancies) analysis."""

import datetime
import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from hardware.discrepancy_utils import (
    Current, JsonDict, build_snapshot_data, compute_current, get_config, sync_discrepancies, update_tracker,
)
from hardware.models import HardwareAnalysisSnapshot

DRY_RUN_PREVIEW = 20
DEFAULT_SAFETY_THRESHOLD = 0.10


def write_log(message: str) -> None:
    """Timestamped console log, same format as the other import/analysis commands."""
    print(f"[{datetime.datetime.now():%H:%M:%S}] {message}")


def check_safety(data: JsonDict) -> None:
    """An empty table or a big population swing usually means a broken import: abort."""
    total = data['total_rows']
    if total == 0:
        raise CommandError("No rows found in hardware table (empty import?) — aborted, use --force to override")
    previous = HardwareAnalysisSnapshot.objects.first()
    if previous is None or not previous.total_rows:
        return
    threshold = get_config().get('safety_delta_threshold', DEFAULT_SAFETY_THRESHOLD)
    delta = abs(total - previous.total_rows) / previous.total_rows
    if delta > threshold:
        raise CommandError(
            f"Population changed by {delta:.0%} ({previous.total_rows} -> {total}), "
            f"above {threshold:.0%} threshold — aborted, use --force to override"
        )


def log_dry_run(current: Current) -> None:
    """Show a preview of the serials with issues without writing anything."""
    write_log("[DRY RUN] nothing written")
    for key, entry in list(current.items())[:DRY_RUN_PREVIEW]:
        write_log(f"  {key} | {entry['region']} | {entry['country']} | issues={','.join(sorted(entry['missing']))}")
    if len(current) > DRY_RUN_PREVIEW:
        write_log(f"  ... and {len(current) - DRY_RUN_PREVIEW} more")


class Command(BaseCommand):
    """Analyze missing / invalid fields on hardware assets."""

    help = 'Analyze missing / invalid fields on hardware assets and sync discrepancy tables'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Bypass the safety check on population swings')
        parser.add_argument('--dry-run', action='store_true', help='Compute and report without writing')

    def handle(self, *args: Any, **options: Any) -> None:
        start = time.monotonic()
        write_log("=" * 60)
        write_log("HARDWARE DISCREPANCY ANALYSIS")

        current, population = compute_current()
        data = build_snapshot_data(current, population)
        write_log(f"Rows: {data['total_rows']}, with issues: {data['rows_with_issues']}, "
                  f"field_counts={data['field_counts']}")

        if not options['force']:
            check_safety(data)
        if options['dry_run']:
            log_dry_run(current)
            return

        now = timezone.now()
        with transaction.atomic():
            created, updated, deleted = sync_discrepancies(current)
            write_log(f"HardwareDiscrepancy: {created} created, {updated} updated, {deleted} removed")
            created, updated, deleted = update_tracker(current, now=now)
            write_log(f"Tracker: {created} created, {updated} updated, {deleted} resolved")
            # One snapshot per day: a re-run the same day replaces the earlier one
            HardwareAnalysisSnapshot.objects.filter(analysis_date__date=now.date()).delete()
            HardwareAnalysisSnapshot.objects.create(
                analysis_date=now, duration_seconds=round(time.monotonic() - start, 2), **data,
            )
        write_log(f"Done: {data['rows_with_issues']} / {data['total_rows']} rows with issues")
