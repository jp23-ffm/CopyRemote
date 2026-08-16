# pamela_sync.py
#
# Shared sync logic for ServerDiscrepancyPamela / PamelaDiscrepancyTracking /
# PamelaAnalysisSnapshot — split out of analyze_pamela_discrepancies.py so it has no pyodbc
# dependency (analyze_pamela_discrepancies.py imports pamela_db_utils, which does need pyodbc
# to be installed). seed_pamela_server_discrepancies.py imports from here to build demo data
# with the exact same sync functions the real daily run uses, without needing pyodbc installed
# just to seed a dev database.

import datetime
import json
import os

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from discrepancies.models import ServerDiscrepancyPamela, PamelaDiscrepancyTracking

PAMELA_REPORT_QUERIES_PATH = os.path.join(os.path.dirname(__file__), 'pamela_report_queries.json')


def load_pamela_report_queries():
    # Pure JSON load, no pyodbc — lives here (not pamela_db_utils.py) so PAMELA_TOOL_CHOICES
    # below and seed_pamela_server_discrepancies can read the queries file without needing
    # pyodbc installed. pamela_db_utils.get_missing_servers() imports this same function.
    try:
        with open(PAMELA_REPORT_QUERIES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f'Cannot load pamela_report_queries.json: {e}')


def _pamela_tool_choices():
    # Derived from pamela_report_queries.json's keys (missing_AD -> AD) instead of hardcoded a
    # second time — that file is already the single source of truth for which per-tool reports
    # exist; adding/removing a tool there is enough, nothing else needs editing to match.
    queries = load_pamela_report_queries()
    order = {name: i for i, name in enumerate(queries.keys())}
    tools = [name[len('missing_'):] for name in queries if name.startswith('missing_')]
    return sorted(tools, key=lambda t: order[f'missing_{t}'])


PAMELA_TOOL_CHOICES = _pamela_tool_choices()


def write_log(message):
    now = datetime.datetime.now()
    time_str = f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}"
    print(f"[{time_str}] {message}")


def sync_serverdiscrepancypamela(current):
    """
    current: {SERVER_ID: {'techfamily', 'area', 'missing': {tool_code, ...}}}

    Wholesale-current-state sync, incrementally (update_or_create semantics via bulk ops,
    same batching style as analyze_discrepancies's bulk_insert_discrepancies) — a server
    dropped from `current` (no longer missing anything) gets its row deleted, not zeroed out.
    """
    existing = {s.SERVER_ID: s for s in ServerDiscrepancyPamela.objects.all()}

    to_create, to_update = [], []
    for sid, data in current.items():
        missing_fields = ','.join(sorted(data['missing']))
        obj = existing.get(sid)
        if obj:
            obj.techfamily = data['techfamily']
            obj.area = data['area']
            obj.missing_fields = missing_fields
            to_update.append(obj)
        else:
            to_create.append(ServerDiscrepancyPamela(
                SERVER_ID=sid, techfamily=data['techfamily'], area=data['area'],
                missing_fields=missing_fields,
            ))

    to_delete_ids = [obj.pk for sid, obj in existing.items() if sid not in current]

    if to_create:
        ServerDiscrepancyPamela.objects.bulk_create(to_create, batch_size=1000)
    if to_update:
        ServerDiscrepancyPamela.objects.bulk_update(to_update, ['techfamily', 'area', 'missing_fields'], batch_size=1000)
    if to_delete_ids:
        ServerDiscrepancyPamela.objects.filter(pk__in=to_delete_ids).delete()

    return len(to_create), len(to_update), len(to_delete_ids)


def update_pamela_tracker(current, now=None):
    """
    Updates PamelaDiscrepancyTracking (1 row per server, active_issues JSONField) — exact
    mirror of analyze_discrepancies.update_tracker(), tool codes instead of field names.
    - New missing tool     -> added to active_issues with first_seen=now
    - Still-missing tool   -> first_seen preserved as-is (this IS the "increment days_open
      once per server, not once per missing tool" the daily run needs: oldest_first_seen is a
      min() across all of a server's active tools, so 3 tools missing on the same server still
      yields exactly one days_open value for that server).
    - Restored tool        -> removed from active_issues
    - No more missing tools -> tracker row deleted

    `now` is overridable (defaults to timezone.now()) so seed_pamela_server_discrepancies can
    reuse this exact function to simulate several days of history with realistic first_seen
    timestamps instead of duplicating the sync logic for demo data.
    """
    now = now or timezone.now()
    now_str = now.isoformat()

    existing_trackers = {t.SERVER_ID: t for t in PamelaDiscrepancyTracking.objects.all()}
    all_server_ids = set(current.keys()) | set(existing_trackers.keys())

    to_create, to_update, to_delete_ids = [], [], []

    for sid in all_server_ids:
        current_tools = current.get(sid, {}).get('missing', set())
        tracker = existing_trackers.get(sid)

        if tracker:
            active = dict(tracker.active_issues)

            for tool in current_tools:
                if tool not in active:
                    active[tool] = {'first_seen': now_str}

            for tool in list(active.keys()):
                if tool not in current_tools:
                    del active[tool]

            if not active:
                to_delete_ids.append(tracker.pk)
            else:
                tracker.active_issues = active
                tracker.oldest_first_seen = min(parse_datetime(v['first_seen']) for v in active.values())
                to_update.append(tracker)

        elif current_tools:
            active = {tool: {'first_seen': now_str} for tool in current_tools}
            to_create.append(PamelaDiscrepancyTracking(
                SERVER_ID=sid, active_issues=active, oldest_first_seen=now,
            ))

    if to_create:
        PamelaDiscrepancyTracking.objects.bulk_create(to_create, batch_size=1000)
        write_log(f"Tracker: created {len(to_create)} new entries")
    if to_update:
        PamelaDiscrepancyTracking.objects.bulk_update(to_update, ['active_issues', 'oldest_first_seen'], batch_size=1000)
        write_log(f"Tracker: updated {len(to_update)} entries")
    if to_delete_ids:
        PamelaDiscrepancyTracking.objects.filter(pk__in=to_delete_ids).delete()
        write_log(f"Tracker: deleted {len(to_delete_ids)} fully-resolved entries")
