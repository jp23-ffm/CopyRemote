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

from discrepancies.models import ServerDiscrepancyPamela, PamelaAnalysisSnapshot, PamelaImportStatus
from discrepancies.pamela_db_utils import get_missing_servers
from discrepancies.pamela_sync import PAMELA_TOOL_CHOICES, write_log, sync_serverdiscrepancypamela, update_pamela_tracker

# A single tool's server count swinging by more than this vs. the last snapshot before it (or
# coming back as exactly 0) is treated as a bad query result for that tool, not real news — see
# fetch_current_missing()'s docstring. Same idea as analyze_discrepancies.SAFETY_DELTA_THRESHOLD,
# but per-tool and skip-that-tool instead of per-run and abort-everything: one bad query
# shouldn't block the other 5 tools' otherwise-good data.
PAMELA_DELTA_THRESHOLD = 0.15


def _carry_forward_tool(tool, current):
    # Preserves a tool's existing server set (from ServerDiscrepancyPamela's current rows)
    # instead of leaving it empty when that tool's fetch is distrusted this run. Merging nothing
    # would read, to update_pamela_tracker, as "every server with this issue just got fixed" —
    # silently resolving real open issues because of a bad query, not because they're actually
    # fixed. For a --date backfill, ServerDiscrepancyPamela is today's state, not that date's —
    # an approximation (see fetch_current_missing), but a far better one than reporting 0.
    for sd in ServerDiscrepancyPamela.objects.exclude(missing_fields=''):
        if tool not in sd.missing_fields_list:
            continue
        entry = current.setdefault(sd.SERVER_ID, {
            'techfamily': sd.techfamily, 'area': sd.area, 'missing': set(),
        })
        entry['missing'].add(tool)


def fetch_current_missing(target_date, as_of, force=False):
    """
    Queries missing_AD/ADDM/SA/LA/EPO/CA for target_date and merges them per server.
    Returns {SERVER_ID: {'techfamily', 'area', 'missing': {tool_code, ...}}} — only servers
    missing at least one tool appear here at all.

    Per-tool safety check against the last PamelaAnalysisSnapshot strictly before `as_of` (so
    this works the same whether as_of is "now" for a normal run or a pinned historical date for
    --date/--replay-tracker, run in chronological order): a tool's count is distrusted — its
    fetched rows discarded and its existing server set carried forward instead (see
    _carry_forward_tool) — when either:
      - it comes back as exactly 0 (none of these 6 tools has ever legitimately been 0 in real
        data; that's a query-gone-wrong signal, not "full coverage"), or
      - it swings by more than PAMELA_DELTA_THRESHOLD vs. that previous snapshot.
    No previous snapshot at all (first run ever, or backfilling before any history exists) skips
    the check entirely — nothing to compare against, so the fetch is trusted as-is. Same for a
    tool whose previous count was itself 0 — no meaningful percentage to compute from a zero
    baseline, and recovering from 0 to something real isn't suspicious. --force bypasses all of
    this and trusts every fetch, same meaning as analyze_discrepancies.py's --force.
    """
    previous_snapshot = None
    if not force:
        previous_snapshot = PamelaAnalysisSnapshot.objects.filter(analysis_date__lt=as_of).order_by('-analysis_date').first()

    current = {}
    for tool in PAMELA_TOOL_CHOICES:
        report_name = f'missing_{tool}'
        write_log(f"Querying {report_name} for {target_date}...")
        rows = get_missing_servers(report_name, target_date)
        current_count = len(rows)
        write_log(f"  -> {current_count} servers missing {tool}")

        trust_fetch = True
        if previous_snapshot is not None:
            previous_count = previous_snapshot.tool_counts.get(tool, 0)
            if current_count == 0:
                write_log(f"  -> SKIPPED {tool}: query returned 0 (never a real count for this tool) — carrying forward existing data")
                trust_fetch = False
            elif previous_count > 0:
                delta = abs(current_count - previous_count) / previous_count
                if delta > PAMELA_DELTA_THRESHOLD:
                    write_log(
                        f"  -> SKIPPED {tool}: {current_count} vs previous {previous_count} "
                        f"({delta:.0%} change > {PAMELA_DELTA_THRESHOLD:.0%} threshold) — carrying forward existing data"
                    )
                    trust_fetch = False

        if trust_fetch:
            for row in rows:
                sid = row['SERVER_ID']
                entry = current.setdefault(sid, {
                    'techfamily': row['techfamily'],
                    'area': row['area'],
                    'missing': set(),
                })
                entry['missing'].add(tool)
        else:
            _carry_forward_tool(tool, current)

    return current


def _backfill_snapshot(target_date, current):
    """
    --date mode: (re)creates ONLY the PamelaAnalysisSnapshot for that calendar day — does NOT
    touch ServerDiscrepancyPamela or PamelaDiscrepancyTracking.

    Those two tables only make sense as "the real current day": ServerDiscrepancyPamela is
    wholesale-replaced current state, and PamelaDiscrepancyTracking's first_seen bookkeeping is
    only meaningful when stamped with the moment the run actually happened. Running the full
    sync for a past --date would silently overwrite today's real current state with stale data,
    and would stamp first_seen at "now" for issues that may have started (or been resolved)
    days ago — actively corrupting days_open rather than fixing a gap.

    The trade-off this accepts: if a real daily run is missed entirely (the reason --date
    exists), the tracker has no memory of that missing day at all — when the next real run
    happens, any issue that started during the gap gets first_seen = that next run's time, so
    days_open undercounts by roughly the length of the outage. That's the same kind of
    imprecision analyze_discrepancies.py already lives with when a run fails — not something
    worth the risk of trying to rewrite tracker history for.
    """
    tool_counts = Counter()
    for data in current.values():
        tool_counts.update(data['missing'])

    snapshot_date = datetime.date.fromisoformat(target_date) if isinstance(target_date, str) else target_date
    snapshot_dt = timezone.make_aware(datetime.datetime.combine(snapshot_date, datetime.time.min))

    # Keyed on the calendar day, not the exact datetime: re-running a backfill for the same
    # date must replace its own previous attempt, and this also lets --date correct a bad
    # snapshot from a real run that already happened that day (the "en cas de problème" case).
    replaced = PamelaAnalysisSnapshot.objects.filter(analysis_date__date=snapshot_dt.date())
    replaced_count = replaced.count()
    replaced.delete()

    PamelaAnalysisSnapshot.objects.create(
        analysis_date=snapshot_dt,
        servers_with_any_missing=len(current),
        tool_counts=dict(tool_counts),
    )
    write_log(
        f"Snapshot backfilled for {snapshot_date}"
        + (f" (replaced {replaced_count} existing row)" if replaced_count else "")
        + f": {len(current)} servers with issues, tool_counts={dict(tool_counts)}"
    )


def _full_sync(current, sync_now):
    # Wholesale-replaces ServerDiscrepancyPamela + incrementally advances PamelaDiscrepancyTracking
    # + (re)writes that day's PamelaAnalysisSnapshot — sync_now is what "first_seen"/"analysis_date"
    # get stamped with. The normal (no --date) run always calls this with timezone.now(); a
    # --date --replay-tracker run calls it with the historical date pinned instead.
    created, updated, deleted = sync_serverdiscrepancypamela(current)
    write_log(f"ServerDiscrepancyPamela: {created} created, {updated} updated, {deleted} removed (no longer missing anything)")

    update_pamela_tracker(current, now=sync_now)

    tool_counts = Counter()
    for data in current.values():
        tool_counts.update(data['missing'])
    PamelaAnalysisSnapshot.objects.filter(analysis_date__date=sync_now.date()).delete()
    PamelaAnalysisSnapshot.objects.create(
        analysis_date=sync_now,
        servers_with_any_missing=len(current),
        tool_counts=dict(tool_counts),
    )
    write_log(f"Snapshot saved: {len(current)} servers with issues, tool_counts={dict(tool_counts)}")


class Command(BaseCommand):
    help = 'Query PAMELA tool coverage per server (MSSQL) and sync ServerDiscrepancyPamela / PamelaDiscrepancyTracking / PamelaAnalysisSnapshot'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', type=str, default=None,
            help=(
                'Query a specific past date (YYYY-MM-DD) instead of today. Backfill mode: only '
                '(re)creates that day\'s PamelaAnalysisSnapshot (for the Quality Trend chart) — '
                'does NOT touch ServerDiscrepancyPamela / PamelaDiscrepancyTracking, which only '
                'reflect the real current day. Use this to fill in a day the daily run missed, '
                'or to correct a bad snapshot. Combine with --replay-tracker to also advance the '
                'tracker for DEV bootstrapping (see that flag\'s help).'
            ),
        )
        parser.add_argument(
            '--replay-tracker', action='store_true',
            help=(
                'Only valid with --date. DEV bootstrapping only — NOT for a one-off prod backfill: '
                'also syncs ServerDiscrepancyPamela / PamelaDiscrepancyTracking for --date, with '
                '"now" pinned to that date instead of the real current time, so first_seen/days_open '
                'build up correctly. Run a sequence of dates in strict chronological order, ending '
                'on the most recent one — ServerDiscrepancyPamela always ends up reflecting whichever '
                'date was processed LAST, so stopping mid-sequence or running out of order leaves it '
                'stuck on the wrong day. Against a tracker that already reflects today\'s real data, '
                'this overwrites it with the queried date\'s data instead — that\'s the whole point '
                'for a from-scratch replay, but it means this is destructive to run against '
                'already-correct current state.'
            ),
        )
        parser.add_argument(
            '--force', action='store_true',
            help=(
                f'Bypass the per-tool {PAMELA_DELTA_THRESHOLD:.0%} delta/zero-count safety check '
                '(for manual runs after a known legitimate mass change)'
            ),
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

        is_backfill = bool(options['date'])
        replay_tracker = options['replay_tracker']
        target_date = options['date'] or timezone.now().date().isoformat()

        if replay_tracker and not is_backfill:
            write_log("ERROR: --replay-tracker requires --date")
            return

        # The moment the per-tool delta check compares against ("last snapshot strictly before
        # this") — pinned to the historical date for --date modes so a --replay-tracker sequence
        # compares each date against the one just before it, not against today's snapshot.
        if is_backfill:
            snapshot_date = datetime.date.fromisoformat(target_date)
            as_of = timezone.make_aware(datetime.datetime.combine(snapshot_date, datetime.time.min))
        else:
            as_of = timezone.now()

        mode_label = ''
        if is_backfill:
            mode_label = '  [REPLAY: full sync, pinned to this date]' if replay_tracker else '  [BACKFILL: snapshot-only]'
        write_log(f"Target date: {target_date}{mode_label}")

        try:
            current = fetch_current_missing(target_date, as_of, force=options['force'])
            write_log(f"Total distinct servers with at least one missing tool: {len(current)}")

            if options['dry_run']:
                if replay_tracker:
                    action = "Would sync ServerDiscrepancyPamela / PamelaDiscrepancyTracking / PamelaAnalysisSnapshot (pinned to this date)"
                elif is_backfill:
                    action = "Would backfill only the PamelaAnalysisSnapshot"
                else:
                    action = "Would sync ServerDiscrepancyPamela / PamelaDiscrepancyTracking / PamelaAnalysisSnapshot"
                write_log(f"[DRY RUN] {action} — nothing written")
                for sid, data in list(current.items())[:20]:
                    write_log(f"  {sid} | {data['techfamily']} | {data['area']} | missing={','.join(sorted(data['missing']))}")
                if len(current) > 20:
                    write_log(f"  ... and {len(current) - 20} more")
                return

            if is_backfill and not replay_tracker:
                _backfill_snapshot(target_date, current)
                msg = f"Pamela snapshot backfilled for {target_date}: {len(current)} servers with at least one missing tool"
            else:
                _full_sync(current, as_of)
                msg = f"Pamela analysis complete for {target_date}: {len(current)} servers with at least one missing tool"

            duration = datetime.datetime.now() - start_time
            write_log(f"Completed in {duration}")
            PamelaImportStatus.objects.create(success=True, message=msg, nb_entries_created=len(current))

        except Exception as e:
            msg = f"Error during the execution of analyze_pamela_discrepancies: {e}"
            write_log(f"ERROR: {e}")
            PamelaImportStatus.objects.create(success=False, message=msg)
            raise
