#    python manage.py analyze_pamela_discrepancies
#
# PAMELA equivalent of analyze_discrepancies.py — much simpler, no breakdowns/cross-tabs/diff,
# no inventory.Server population checks (PAMELA's own population is DailyPamelaDBSummary,
# maintained by a separate pipeline). Queries the 6 missing_* reports per server (via
# pamela_db_utils.get_missing_servers, MSSQL/pyodbc), then syncs 3 tables the same way
# analyze_discrepancies.py syncs ServerDiscrepancy/DiscrepancyTracking/AnalysisSnapshot:
#   - ServerDiscrepancyPamela   — current state, 1 row per server still missing something
#   - PamelaDiscrepancyTracking — days_open bookkeeping, 1 row per server, mirrors DiscrepancyTracking
#   - PamelaAnalysisSnapshot    — 1 row per run, feeds the Quality Trend chart
# A server no longer missing anything simply has no row in either of the first two tables —
# not "included with an empty missing_fields", genuinely absent, same convention as
# DiscrepancyTracking (tracker row deleted once active_issues is empty).
#
# The actual sync functions (sync_serverdiscrepancypamela/update_pamela_tracker) live in
# discrepancies/pamela_sync.py, not here — that module has no pyodbc dependency, so
# seed_pamela_server_discrepancies.py can reuse the exact same sync logic to build demo data
# without needing pyodbc installed just to seed a dev database.

import datetime
from collections import Counter

from django.core.management.base import BaseCommand
from django.utils import timezone

from discrepancies.models import PamelaAnalysisSnapshot, PamelaImportStatus
from discrepancies.pamela_db_utils import get_missing_servers
from discrepancies.pamela_sync import PAMELA_TOOL_CHOICES, write_log, sync_serverdiscrepancypamela, update_pamela_tracker


def fetch_current_missing(target_date):
    """
    Queries missing_AD/ADDM/SA/LA/EPO/CA for target_date and merges them per server.
    Returns {SERVER_ID: {'techfamily', 'area', 'missing': {tool_code, ...}}} — only servers
    missing at least one tool appear here at all.
    """
    current = {}
    for tool in PAMELA_TOOL_CHOICES:
        report_name = f'missing_{tool}'
        write_log(f"Querying {report_name} for {target_date}...")
        rows = get_missing_servers(report_name, target_date)
        write_log(f"  -> {len(rows)} servers missing {tool}")
        for row in rows:
            sid = row['SERVER_ID']
            entry = current.setdefault(sid, {
                'techfamily': row['techfamily'],
                'area': row['area'],
                'missing': set(),
            })
            entry['missing'].add(tool)
    return current


class Command(BaseCommand):
    help = 'Query PAMELA tool coverage per server (MSSQL) and sync ServerDiscrepancyPamela / PamelaDiscrepancyTracking / PamelaAnalysisSnapshot'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', type=str, default=None,
            help='Target date to query (YYYY-MM-DD). Defaults to today.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Query and report without writing to the database',
        )

    def handle(self, *args, **options):
        start_time = datetime.datetime.now()
        write_log("=" * 60)
        write_log("PAMELA DISCREPANCY ANALYSIS START")
        write_log("=" * 60)

        target_date = options['date'] or timezone.now().date().isoformat()
        write_log(f"Target date: {target_date}")

        try:
            current = fetch_current_missing(target_date)
            write_log(f"Total distinct servers with at least one missing tool: {len(current)}")

            if options['dry_run']:
                write_log("[DRY RUN] Would sync ServerDiscrepancyPamela / PamelaDiscrepancyTracking / PamelaAnalysisSnapshot — nothing written")
                for sid, data in list(current.items())[:20]:
                    write_log(f"  {sid} | {data['techfamily']} | {data['area']} | missing={','.join(sorted(data['missing']))}")
                if len(current) > 20:
                    write_log(f"  ... and {len(current) - 20} more")
                return

            created, updated, deleted = sync_serverdiscrepancypamela(current)
            write_log(f"ServerDiscrepancyPamela: {created} created, {updated} updated, {deleted} removed (no longer missing anything)")

            update_pamela_tracker(current)

            tool_counts = Counter()
            for data in current.values():
                tool_counts.update(data['missing'])
            PamelaAnalysisSnapshot.objects.create(
                analysis_date=timezone.now(),
                servers_with_any_missing=len(current),
                tool_counts=dict(tool_counts),
            )
            write_log(f"Snapshot saved: {len(current)} servers with issues, tool_counts={dict(tool_counts)}")

            duration = datetime.datetime.now() - start_time
            write_log(f"Completed in {duration}")
            msg = f"Pamela analysis complete: {len(current)} servers with at least one missing tool"
            PamelaImportStatus.objects.create(success=True, message=msg, nb_entries_created=len(current))

        except Exception as e:
            msg = f"Error during the execution of analyze_pamela_discrepancies: {e}"
            write_log(f"ERROR: {e}")
            PamelaImportStatus.objects.create(success=False, message=msg)
            raise
