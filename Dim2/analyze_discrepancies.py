#    python manage.py analyze_discrepancies

import datetime
from django.utils import timezone
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q

from inventory.models import Server
from discrepancies.models import ServerDiscrepancy, AnalysisSnapshot, DiscrepancyTracking, ImportStatus


# ============================================================================
# CONFIGURATION
# ============================================================================

FIELDS_TO_CHECK = [
    'LIVE_STATUS',
    'OSSHORTNAME',
    'OSFAMILY',
    'MACHINE_TYPE',
    'MANUFACTURER',
    'COUNTRY',
    'APP_AUID_VALUE',
    'APP_NAME_VALUE',
    'REGION',
    'CITY',
    'INFRAVERSION',
    'IPADDRESS',
    'SNOW_STATUS'
]

INVALID_VALUES = {
    '', 'EMPTY', 'N/A', 'NA', 'N.A.', 'UNKNOWN', 'UNDEFINED', 'NULL', 'NONE', '-', '--', '?',
}

MISSING_MARKER = 'MISSING'
VALIDATION_OK = 'OK'
VALIDATION_KO = 'KO'

# Safety threshold: abort if new count differs from previous by more than this %
SAFETY_DELTA_THRESHOLD = 0.10

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def write_log(message):
    print(f"[{datetime.datetime.now()}] {message}")


def is_value_missing(value):
    # Check if value is considered missing or invalid
    if value is None:
        return True
    return str(value).strip().upper() in INVALID_VALUES


def is_value_valid(value):
    # Check if value is considered valid (not missing/invalid)
    if value is None:
        return False
    return str(value).strip().upper() not in INVALID_VALUES


def bulk_insert_discrepancies(records):
    if not records:
        return

    columns = ['SERVER_ID', 'missing_fields', 'analysis_date'] + FIELDS_TO_CHECK + ['live_status_inconsistent']
    columns_str = ', '.join(columns)

    chunk_size = 1000
    total = 0

    ServerDiscrepancy.objects.all().delete()

    with connection.cursor() as cursor:
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]

            # Create the placeholders : (%s, %s, %s, ...), (%s, %s, %s, ...), ...
            placeholders = ', '.join(['(' + ', '.join(['%s'] * len(columns)) + ')'] * len(chunk))

            # Flatten the values
            values_list = []
            for record in chunk:
                row_values = [record.get(col) for col in columns]
                values_list.extend(row_values)

            insert_sql = f"""
                INSERT INTO discrepancies_serverdiscrepancy ({columns_str})
                VALUES {placeholders}
            """

            cursor.execute(insert_sql, values_list)
            total += len(chunk)

    write_log(f"Inserted {total} records in {(len(records) + chunk_size - 1) // chunk_size} batches")


# ============================================================================
# DIFF
# ============================================================================

def compute_diff(new_records):
    """
    Compare new analysis records against the current ServerDiscrepancy table.
    Must be called BEFORE bulk_insert_discrepancies() drops the table.

    Returns:
        {
          'new':      [server_id, ...]          – appeared for the first time
          'resolved': [server_id, ...]          – no longer have any issue
          'changed':  {server_id: {'added': [...], 'removed': [...]}}
        }
    """
    # ── Current state from DB ─────────────────────────────────────
    current = {}
    for s in ServerDiscrepancy.objects.only(
        'SERVER_ID', 'missing_fields', 'live_status_inconsistent'
    ):
        fields = (
            {f.strip() for f in s.missing_fields.split(',') if f.strip()}
            if s.missing_fields else set()
        )
        if s.live_status_inconsistent == VALIDATION_KO:
            fields.add('live_status_inconsistent')
        current[s.SERVER_ID] = fields

    # ── New state from analysis records ───────────────────────────
    new_state = {}
    for r in new_records:
        fields = {f.strip() for f in r.get('missing_fields', '').split(',') if f.strip()}
        if r.get('live_status_inconsistent') == VALIDATION_KO:
            fields.add('live_status_inconsistent')
        new_state[r['SERVER_ID']] = fields

    current_ids = set(current)
    new_ids     = set(new_state)

    new_servers      = sorted(new_ids - current_ids)
    resolved_servers = sorted(current_ids - new_ids)

    changed_servers = {}
    for sid in current_ids & new_ids:
        added   = sorted(new_state[sid] - current[sid])
        removed = sorted(current[sid]   - new_state[sid])
        if added or removed:
            changed_servers[sid] = {'added': added, 'removed': removed}

    return {
        'new':      new_servers,
        'resolved': resolved_servers,
        'changed':  changed_servers,
    }


# ============================================================================
# MAIN ANALYSIS
# ============================================================================

def analyze_servers():
    # Analyze all servers for missing data, returns statistics dict

    write_log("Starting analysis")
    write_log("Checking empty fields")

    # Group data by SERVER_ID (handles duplicates)
    server_data = defaultdict(lambda: {
        'missing_fields': set(), 
        'field_values': {},
        'live_status_inconsistent': VALIDATION_OK
    })

    fields_to_fetch = ['SERVER_ID'] + FIELDS_TO_CHECK

    """queryset = (
        Server.objects.only(*fields_to_fetch)
        .filter(
            LIVE_STATUS='ALIVE',
            SNOW_STATUS='OPERATIONAL',
            INFRAVERSION__in=['IV1', 'IV2', 'IBM'],
        )
        .order_by('SERVER_ID')
    )"""
    
    queryset = (
        Server.objects.only(*fields_to_fetch)
        .filter(
            LIVE_STATUS='ALIVE'
        )
        .order_by('SERVER_ID')
    )    

    queryset = (
        Server.objects.only(*fields_to_fetch)
        .order_by('SERVER_ID')
    )

    total_entries = 0
    for server in queryset.iterator(chunk_size=50000):
        total_entries += 1

        if total_entries % 100000 == 0:
            write_log(f"  Processed {total_entries} entries...")

        server_id = server.SERVER_ID
        data = server_data[server_id]

        # === Check Empty fields ===
        for field in FIELDS_TO_CHECK:
            value = getattr(server, field, None)

            # Keep first non-empty value
            if field not in data['field_values'] or is_value_missing(data['field_values'][field]):
                data['field_values'][field] = value

            # Track missing
            if is_value_missing(value):
                data['missing_fields'].add(field)

    write_log(f"Analyzed {total_entries} entries for {len(server_data)} unique servers")
    write_log("Check the LIVE STATUS/OPERATIONAL STATUS inconsistencies")

    """inconsistent_servers = Server.objects.only(*fields_to_fetch).filter(
        LIVE_STATUS='Live',
        SNOW_STATUS__in=['RETIRED', 'NON-OPERATIONAL'],
        INFRAVERSION__in=['IV1', 'IV2', 'IBM'],
    )""" 
    
    """
    inconsistent_servers = Server.objects.only(*fields_to_fetch).filter(
        Q(SNOW_STATUS__iexact='RETIRED') | Q(SNOW_STATUS__iexact='NON-OPERATIONAL'),
        LIVE_STATUS__iexact='ALIVE',
        INFRAVERSION__in=['IV1', 'IV2', 'IBM'],
    )"""

    inconsistent_servers = Server.objects.only(*fields_to_fetch).filter(
        Q(SNOW_STATUS__iexact='RETIRED') | Q(SNOW_STATUS__iexact='NON-OPERATIONAL'),
        LIVE_STATUS__iexact='LIVE',   #ALIVE
        #INFRAVERSION__in=['IV1', 'IV2', 'IBM'],
    )

    inconsistent_count = 0
    for server in inconsistent_servers:
        server_id = server.SERVER_ID
        inconsistent_count += 1

        if server_id not in server_data:
            server_data[server_id] = {
                'missing_fields': set(),
                'field_values': {},
                'live_status_inconsistent': VALIDATION_OK
            }
            data = server_data[server_id]
            for field in FIELDS_TO_CHECK:
                value = getattr(server, field, None)
                data['field_values'][field] = value
        else:
            server_data[server_id]['live_status_inconsistent'] = VALIDATION_KO

    write_log(f"{inconsistent_count} entries with inconsistencies found")

    # Build discrepancy records
    records = []
    stats = {
        'discrepancies_by_field': defaultdict(int),
        'live_status_inconsistent_count': 0
    }

    analysis_date = timezone.now().isoformat() 

    for server_id, data in server_data.items():
        # Only create records for servers with issues
        if not data['missing_fields'] and data['live_status_inconsistent'] == VALIDATION_OK:
            continue

        missing_list = sorted(data['missing_fields'])

        record = {
            'SERVER_ID': server_id,
            'missing_fields': ','.join(missing_list),
            'analysis_date': analysis_date,
            'live_status_inconsistent': data['live_status_inconsistent']
        }

        for field in FIELDS_TO_CHECK:
            value = data['field_values'].get(field)
            # Store actual value if valid, otherwise store MISSING marker
            record[field] = value if is_value_valid(value) else MISSING_MARKER

        records.append(record)

        # Count per-field issues
        for field in missing_list:
            stats['discrepancies_by_field'][field] += 1

        # Count inconsistency issues
        if data['live_status_inconsistent'] == VALIDATION_KO: 
            stats['live_status_inconsistent_count'] += 1

    stats['total_entries'] = total_entries
    stats['unique_servers'] = len(server_data)
    stats['servers_with_discrepancies'] = len(records)
    stats['records'] = records

    return stats, analysis_date


def create_analysis_snapshot(stats, analysis_date, duration, diff=None):

    # Mapping of the fields to the snapshot attributes
    field_mapping = {
        'LIVE_STATUS': 'missing_live_status_count',
        'OSSHORTNAME': 'missing_osshortname_count',
        'OSFAMILY': 'missing_osfamily_count',
        'MACHINE_TYPE': 'missing_machine_type_count',
        'MANUFACTURER': 'missing_manufacturer_count',
        'COUNTRY': 'missing_country_count',
        'APP_AUID_VALUE': 'missing_app_auid_value_count',
        'APP_NAME_VALUE': 'missing_app_name_value_count',
        'REGION': 'missing_region_count',
        'CITY': 'missing_city_count',
        'INFRAVERSION': 'missing_infraversion_count',
        'IPADDRESS': 'missing_ipaddress_count',
        'SNOW_STATUS': 'missing_snow_status_count',
    }

    diff = diff or {}
    snapshot = AnalysisSnapshot(
        analysis_date=analysis_date,
        total_servers_analyzed=stats['total_entries'],
        servers_with_issues=stats['servers_with_discrepancies'],
        servers_clean=stats['total_entries'] - stats['servers_with_discrepancies'],
        duration_seconds=duration,
        live_status_inconsistent_count=stats.get('live_status_inconsistent_count', 0),
        new_issues_count=len(diff.get('new', [])),
        resolved_issues_count=len(diff.get('resolved', [])),
        changed_issues_count=len(diff.get('changed', {})),
        diff_summary=diff,
    )

    # Fill the values by fields
    for field, count_attr in field_mapping.items():
        count = stats.get('discrepancies_by_field', {}).get(field, 0)
        setattr(snapshot, count_attr, count)

    snapshot.save()
    write_log(f"Created analysis snapshot: {snapshot.id}")

    return snapshot


def print_report(stats):

    total = stats['unique_servers'] or 1
    discrepancies = stats['servers_with_discrepancies']
    pct = discrepancies / total * 100

    print("\n" + "=" * 60)
    print("DISCREPANCY ANALYSIS REPORT")
    print("=" * 60)
    print(f"Total entries analyzed: {stats['total_entries']}")
    print(f"Unique servers: {stats['unique_servers']}")
    print(f"Servers with discrepancies: {discrepancies} ({pct:.1f}%)")
    print("\nMissing fields:")

    for field, count in sorted(stats['discrepancies_by_field'].items(), key=lambda x: -x[1]):
        field_pct = count / total * 100
        print(f"  {field}: {count} ({field_pct:.1f}%)")

    print("\nValidation errors:")
    inconsistent_count = stats.get('live_status_inconsistent_count', 0)
    if inconsistent_count > 0:
        print(f"  Live Status/Snow Status inconsistencies: {inconsistent_count} servers ({(inconsistent_count / total * 100):.1f}%)")
    else:
        print(f"  No inconsistencies found")

    print("=" * 60 + "\n")


# ============================================================================
# TRACKER
# ============================================================================

def _compute_oldest_first_seen(active_issues):
    """Return the oldest first_seen datetime across all active issues."""
    from django.utils.dateparse import parse_datetime
    dates = [parse_datetime(v['first_seen']) for v in active_issues.values()]
    dates = [d for d in dates if d is not None]
    return min(dates) if dates else None


def update_tracker(records, analysis_date):
    """
    Updates DiscrepancyTracking (1 row per server, active_issues JSONField).
    - New issues    → added to active_issues with first_seen=now
    - Known issues  → first_seen preserved as-is
    - Fixed issues  → removed from active_issues
    - No more issues → tracker row deleted
    """

    now = timezone.now()
    now_str = now.isoformat()

    # 1. Build current issues: {SERVER_ID: {field_name, ...}}
    current_issues = defaultdict(set)
    for record in records:
        server_id = record['SERVER_ID']
        missing = record.get('missing_fields', '')
        if missing:
            for field_name in missing.split(','):
                field_name = field_name.strip()
                if field_name:
                    current_issues[server_id].add(field_name)
        if record.get('live_status_inconsistent') == 'KO':
            current_issues[server_id].add('live_status_inconsistent')

    write_log(f"Tracker: {sum(len(v) for v in current_issues.values())} active issues across {len(current_issues)} servers")

    # 2. Load all existing trackers
    existing_trackers = {t.SERVER_ID: t for t in DiscrepancyTracking.objects.all()}

    # 3. Process every server that is either currently broken or was previously tracked
    all_server_ids = set(current_issues.keys()) | set(existing_trackers.keys())

    to_create = []
    to_update = []
    to_delete_ids = []

    for server_id in all_server_ids:
        current_fields = current_issues.get(server_id, set())
        tracker = existing_trackers.get(server_id)

        if tracker:
            active = dict(tracker.active_issues)

            # Add new issues (preserve first_seen for already-tracked ones)
            for field in current_fields:
                if field not in active:
                    active[field] = {'first_seen': now_str}

            # Remove fields that are no longer broken
            for field in list(active.keys()):
                if field not in current_fields:
                    del active[field]

            if not active:
                to_delete_ids.append(tracker.pk)
            else:
                tracker.active_issues = active
                tracker.oldest_first_seen = _compute_oldest_first_seen(active)
                to_update.append(tracker)

        elif current_fields:
            active = {field: {'first_seen': now_str} for field in current_fields}
            to_create.append(DiscrepancyTracking(
                SERVER_ID=server_id,
                active_issues=active,
                oldest_first_seen=now,
            ))

    # 4. Apply changes
    if to_create:
        DiscrepancyTracking.objects.bulk_create(to_create, batch_size=1000)
        write_log(f"Tracker: created {len(to_create)} new entries")

    if to_update:
        DiscrepancyTracking.objects.bulk_update(
            to_update, ['active_issues', 'oldest_first_seen'], batch_size=1000
        )
        write_log(f"Tracker: updated {len(to_update)} entries")

    if to_delete_ids:
        DiscrepancyTracking.objects.filter(pk__in=to_delete_ids).delete()
        write_log(f"Tracker: deleted {len(to_delete_ids)} fully-resolved entries")


# ============================================================================
# COMMAND
# ============================================================================

class Command(BaseCommand):
    help = 'Analyze servers for missing/invalid data in critical fields'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Bypass the 10%% safety threshold check (for manual runs)',
        )

    def handle(self, *args, **options):
        start_time = datetime.datetime.now()
        write_log("=" * 60)
        write_log("DISCREPANCY ANALYSIS START")
        write_log("=" * 60)

        try:

            # Analyze
            stats, analysis_date = analyze_servers()

            # ── Safety check ──────────────────────────────────────────────
            if options['force']:
                write_log("Safety check bypassed (--force)")
            else:
                try:
                    previous = AnalysisSnapshot.objects.latest('analysis_date')
                    prev_count = previous.servers_with_issues
                    new_count  = stats['servers_with_discrepancies']
                    if prev_count > 0:
                        delta_pct = abs(new_count - prev_count) / prev_count
                        if delta_pct > SAFETY_DELTA_THRESHOLD:
                            msg = (
                                f"SAFETY ABORT: new analysis shows {new_count} servers with issues "
                                f"vs {prev_count} previously ({delta_pct:.1%} change > "
                                f"{SAFETY_DELTA_THRESHOLD:.0%} threshold). "
                                f"Possible inventory data issue. Nothing was written. "
                                f"Use --force to override."
                            )
                            write_log(f"ERROR: {msg}")
                            ImportStatus.objects.create(success=False, message=msg)
                            return
                except AnalysisSnapshot.DoesNotExist:
                    pass  # First run — no reference to compare against

            # ── Diff (before the table is dropped) ────────────────────────
            write_log("Computing diff against current state...")
            diff = compute_diff(stats['records'])
            write_log(
                f"Diff: +{len(diff['new'])} new, "
                f"-{len(diff['resolved'])} resolved, "
                f"~{len(diff['changed'])} changed"
            )

            # Insert records
            if stats['records']:
                write_log(f"Inserting discrepancy records...")
                bulk_insert_discrepancies(stats['records'])
            else:
                write_log("No discrepancies found")

            # Update tracker
            update_tracker(stats['records'], analysis_date)

            # Report
            print_report(stats)

            duration = datetime.datetime.now() - start_time

            create_analysis_snapshot(stats, analysis_date, duration.total_seconds(), diff)

            write_log(f"Completed in {duration}")

            msg = (f"Analysis complete: {stats['servers_with_discrepancies']} servers with discrepancies "
                   f"out of {stats['unique_servers']} analyzed ({duration})")
            ImportStatus.objects.create(success=True, message=msg, nb_entries_created=stats['servers_with_discrepancies'])

        except Exception as e:
            msg = f"analyze_discrepancies error: {e}"
            write_log(f"ERROR: {e}")
            ImportStatus.objects.create(success=False, message=msg)
            raise