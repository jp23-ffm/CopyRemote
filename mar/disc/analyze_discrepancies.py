#    python manage.py analyze_discrepancies

import datetime
import json
import os
from django.utils import timezone
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q, Count

from inventory.models import Server
from discrepancies.models import ServerDiscrepancy, AnalysisSnapshot, AnalysisSnapshotBreakdown, AnalysisSnapshotCrossBreakdown, DiscrepancyTracking, ImportStatus


# ============================================================================
# CONFIGURATION
# ============================================================================

FIELDS_TO_CHECK = [
    'LIVE_STATUS',
    'OSSHORTNAME',
    'OSFAMILY',
    'SNOW_SUPPORTGROUP',
    'MACHINE_TYPE',
    'MANUFACTURER',
    'COUNTRY',
    'APP_AUID_VALUE',
    'APP_NAME_VALUE',
    'REGION',
    'CITY',
    'INFRAVERSION',
    'IPADDRESS',
    'SNOW_STATUS',
    'IDRAC_NAME',
    'IDRAC_IP'
]

INCONSISTENCY_FIELDS = [
    'OSSHORTNAME',
    'OSFAMILY',
    'SNOW_SUPPORTGROUP',
    'MACHINE_TYPE',
    'MANUFACTURER',
    'COUNTRY',
    'APP_AUID_VALUE',
    'APP_NAME_VALUE',
    'REGION',
    'CITY',
    'INFRAVERSION',
    'IPADDRESS',
    'IDRAC_NAME',
    'IDRAC_IP'    
]

HARDWARE_ONLY = [
    'IDRAC_NAME',
    'IDRAC_IP'    
]

INVALID_VALUES = {
    '', 'EMPTY', 'N/A', 'NA', 'N.A.', 'UNKNOWN', '<UNKNOWN>', 'UNDEFINED', 'NULL', 'NONE', '-', '--', '?',
}

# Markers
MISSING_MARKER = 'MISSING'
VALIDATION_OK = 'OK'
VALIDATION_KO = 'KO'

# Safety threshold: abort if new count differs from previous by more than this %
SAFETY_DELTA_THRESHOLD = 0.10

# The list of breakdown dimensions (and their display labels) lives in
# discrepancies/breakdown_groups.json ("dimensions" key) — shared with views.py so
# adding a block to the History page is a config change, not a code change on both sides.
# Keep dimensions low-cardinality (a handful of distinct values) — this is a GROUP BY
# per field, not a filter combination; APP_AUID_VALUE-style fields would blow up.
# CARDINALITY_WARNING_THRESHOLD below catches that mistake at run time.
CARDINALITY_WARNING_THRESHOLD = 50

# Cross-tab dimensions: (row_field, bucket_field) — bucket_field values are grouped
# via breakdown_groups.json "groups" (e.g. OSFAMILY -> Windows / Linux / Other)
CROSS_BREAKDOWNS = [('REGION', 'OSFAMILY')]

BREAKDOWN_GROUPS_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'breakdown_groups.json')

# Three different populations for the three metrics — never compare across them.
# An alive-inconsistent server (ALIVE but RETIRED/NON-OPERATIONAL/N/A) is by definition
# outside the ALIVE+OPERATIONAL population used for missing-data checks, and a
# dead-inconsistent server (OPERATIONAL but DEAD) is outside it too.
POPULATION_FILTERS = {
    'missing_data':       dict(LIVE_STATUS='ALIVE', SNOW_STATUS='OPERATIONAL', INFRAVERSION__in=['IV1', 'IV2', 'IBM']),
    'alive_inconsistent': dict(LIVE_STATUS='ALIVE', INFRAVERSION__in=['IV1', 'IV2', 'IBM']),
    'dead_inconsistent':  dict(SNOW_STATUS='OPERATIONAL', INFRAVERSION__in=['IV1', 'IV2', 'IBM']),
}

# ============================================================================
# CHECK CONFIGURATIONS - EACH CHECK HAS ITS OWN QUERYSET
# ============================================================================

def check_missing_fields(servers_with_issues):
    """
    Check for missing/invalid field values.
    Only on ALIVE + OPERATIONAL servers.
    """
    write_log("Check 1: Missing fields on ALIVE/OPERATIONAL servers")
    
    fields_to_fetch = ['SERVER_ID'] + FIELDS_TO_CHECK
    
    queryset = (
        Server.objects.only(*fields_to_fetch)
        .filter(
            LIVE_STATUS='ALIVE',
            SNOW_STATUS='OPERATIONAL',
            INFRAVERSION__in=['IV1', 'IV2', 'IBM'],
        )
        .order_by('SERVER_ID')
    ).distinct()
    
    count = 0
    for server in queryset.iterator(chunk_size=50000):
        count += 1
        if count % 100000 == 0:
            write_log(f"  Processed {count} entries...")
        
        server_id = server.SERVER_ID
        
        # Check for missing fields
        missing_fields = set()
        field_values = {}
        
        for field in FIELDS_TO_CHECK:
            value = getattr(server, field, None)
            field_values[field] = value
            
            if is_value_missing(value):
                if field in HARDWARE_ONLY and getattr(server, "MACHINE_TYPE", None) != "PHYSICAL":
                    field_values[field] = "Ignored"
                    continue
                missing_fields.add(field)
        
        # Only add if has missing fields
        if missing_fields:
            add_or_update_server(servers_with_issues, server_id, missing_fields, field_values)
    
    write_log(f"  Found {count} entries")
    return count


def check_alive_status_inconsistent(servers_with_issues):
    # Check for LIVE_STATUS inconsistencies, Servers that are ALIVE but RETIRED or NON-OPERATIONAL
    
    write_log("Check 2: LIVE_STATUS inconsistent (ALIVE but RETIRED, NON-OPERATIONAL or N/A)")
    
    fields_to_fetch = ['SERVER_ID'] + FIELDS_TO_CHECK
    
    q_live_status_alive_inconsistencies = (
        (Q(SNOW_STATUS__iexact='RETIRED') | Q(SNOW_STATUS__iexact='NON-OPERATIONAL') | Q(SNOW_STATUS__iexact='N/A')) &
        Q(LIVE_STATUS__iexact='ALIVE')
    )

    queryset = Server.objects.only(*fields_to_fetch).filter(
            q_live_status_alive_inconsistencies,
            INFRAVERSION__in=['IV1', 'IV2', 'IBM']
        ).distinct()
    
    count = 0
    for server in queryset.iterator(chunk_size=10000):
        count += 1
        server_id = server.SERVER_ID
        
        # Get field values
        field_values = {field: getattr(server, field, None) for field in FIELDS_TO_CHECK}
        
        # Add inconsistency flag
        add_or_update_server(
            servers_with_issues, 
            server_id, 
            missing_fields=set(),  # No missing fields for this check
            field_values=field_values,
            inconsistencies={'alive_status_inconsistent': VALIDATION_KO},
            force_empty_fields=True
        )
    
    write_log(f"  Found {count} inconsistencies")
    return count


def check_dead_status_inconsistent(servers_with_issues):
    # Check for SNOW_STATUS inconsistencies, Servers that are DEAD but OPERATIONAL

    write_log("Check 3: SNOW_STATUS inconsistent (DEAD but OPERATIONAL)")
    
    fields_to_fetch = ['SERVER_ID'] + FIELDS_TO_CHECK
    
    q_snow_status_operational_inconsistencies = Q(SNOW_STATUS__iexact='OPERATIONAL') & Q(LIVE_STATUS__iexact='DEAD')
    queryset = Server.objects.only(*fields_to_fetch).filter(
            q_snow_status_operational_inconsistencies,
            INFRAVERSION__in=['IV1', 'IV2', 'IBM']
        ).distinct()
    
    count = 0
    for server in queryset.iterator(chunk_size=10000):
        count += 1
        server_id = server.SERVER_ID
        
        # Get field values
        field_values = {field: getattr(server, field, None) for field in FIELDS_TO_CHECK}
        
        # Add inconsistency flag
        add_or_update_server(
            servers_with_issues,
            server_id,
            missing_fields=set(),
            field_values=field_values,
            inconsistencies={'dead_status_inconsistent': VALIDATION_KO},
            force_empty_fields=True
        )
    
    write_log(f"  Found {count} inconsistencies")
    return count


# Register all checks here
ALL_CHECKS = [
    check_missing_fields,
    check_alive_status_inconsistent,
    check_dead_status_inconsistent,
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def write_log(message):
    now = datetime.datetime.now()
    time_str = f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}"
    print(f"[{time_str}] {message}")


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


def add_or_update_server(servers_with_issues, server_id, missing_fields, field_values, inconsistencies=None, force_empty_fields=False):
    # Add or update a server in the issues dict. Merges missing_fields, field_values, and inconsistencies.

    if inconsistencies is None:
        inconsistencies = {}
    
    if server_id in servers_with_issues:
        # Server already exists - merge data
        
        # Union of missing fields
        servers_with_issues[server_id]['missing_fields'].update(missing_fields)
        
        # Update field_values: DON'T overwrite if field is in missing_fields
        for field, value in field_values.items():
            if field in servers_with_issues[server_id]['missing_fields']:
                # This field is missing in at least one entry - keep it missing
                continue
            
            # If current stored value is missing, replace with new value
            current_value = servers_with_issues[server_id]['field_values'].get(field)
            if is_value_missing(current_value) and is_value_valid(value):
                servers_with_issues[server_id]['field_values'][field] = value
        
        # Merge inconsistencies (KO takes precedence over OK)
        for check_name, status in inconsistencies.items():
            if status == VALIDATION_KO:
                servers_with_issues[server_id]['inconsistencies'][check_name] = VALIDATION_KO
            elif check_name not in servers_with_issues[server_id]['inconsistencies']:
                servers_with_issues[server_id]['inconsistencies'][check_name] = status
    else:
        # New server: Initialize all inconsistency checks to OK if not provided
        if force_empty_fields:
            field_values = {field: value for field, value in field_values.items()}

        
            #field_values = {field: value for field, value in field_values.items()
            #                            if is_value_valid(value)}
                                        
            #updated_field_values = {field: 'Op. Status issue' for field in INCONSISTENCY_FIELDS}
            #updated_field_values = {field: f"*{field}" for field in INCONSISTENCY_FIELDS}
            #field_values.update(updated_field_values)
        
        all_inconsistencies = {check.__name__.replace('check_', ''): VALIDATION_OK 
                               for check in ALL_CHECKS if 'inconsistent' in check.__name__}
        all_inconsistencies.update(inconsistencies)
        
        servers_with_issues[server_id] = {
            'missing_fields': missing_fields.copy(),
            'field_values': field_values.copy(),
            'inconsistencies': all_inconsistencies
        }


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
    for s in ServerDiscrepancy.objects.only('SERVER_ID', 'missing_fields', 'alive_status_inconsistent', 'dead_status_inconsistent'):
        fields = (
            {f.strip() for f in s.missing_fields.split(',') if f.strip()}
            if s.missing_fields else set()
        )
        if s.alive_status_inconsistent == VALIDATION_KO:
            fields.add('alive_status_inconsistent')
        if s.dead_status_inconsistent == VALIDATION_KO:
            fields.add('dead_status_inconsistent')            
        current[s.SERVER_ID] = fields

    # ── New state from analysis records ───────────────────────────
    new_state = {}
    for r in new_records:
        fields = {f.strip() for f in r.get('missing_fields', '').split(',') if f.strip()}
        if r.get('alive_status_inconsistent') == VALIDATION_KO:
            fields.add('alive_status_inconsistent')
        if r.get('dead_status_inconsistent') == VALIDATION_KO:
            fields.add('dead_status_inconsistent')            
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
    # Run all checks with their own querysets.

    write_log("Starting analysis")
    
    servers_with_issues = {}
    total_entries = 0
    
    # Run each check with its own queryset
    for check_func in ALL_CHECKS:
        count = check_func(servers_with_issues)
        total_entries += count
    
    write_log(f"Total servers with issues: {len(servers_with_issues)}")
    
    # Build discrepancy records
    records = []
    stats = {'discrepancies_by_field': defaultdict(int)}
    analysis_date = timezone.now().isoformat()
    
    # Get all inconsistency check names
    inconsistency_names = [check.__name__.replace('check_', '') 
                          for check in ALL_CHECKS if 'inconsistent' in check.__name__]
    
    for check_name in inconsistency_names:
        stats[f'{check_name}_count'] = 0
    
    for server_id, data in servers_with_issues.items():
        missing_list = sorted(data['missing_fields'])
        
        record = {
            'SERVER_ID': server_id,
            'missing_fields': ','.join(missing_list),
            'analysis_date': analysis_date,
        }
        
        # Add field values (with MISSING marker)
        for field in FIELDS_TO_CHECK:
            value = data['field_values'].get(field)
            
            # If field is in missing_fields, force MISSING
            if missing_list == []:  # An empty missing_list means server with inconsistency, no modification
                record[field] = value
            elif field in data['missing_fields']:
                record[field] = MISSING_MARKER
            else:
                record[field] = value if is_value_valid(value) else MISSING_MARKER
        
        # Add inconsistency statuses
        for check_name, status in data['inconsistencies'].items():
            record[check_name] = status
        
        records.append(record)
        
        # Update stats
        for field in missing_list:
            stats['discrepancies_by_field'][field] += 1
        
        for check_name, status in data['inconsistencies'].items():
            if status == VALIDATION_KO:
                stats[f'{check_name}_count'] += 1
    
    physical_servers = (
        Server.objects.only('SERVER_ID','LIVE_STATUS','SNOW_STATUS','INFRAVERSION','MACHINE_TYPE')
        .filter(
            LIVE_STATUS='ALIVE',
            SNOW_STATUS='OPERATIONAL',
            INFRAVERSION__in=['IV1', 'IV2', 'IBM'],
            MACHINE_TYPE='PHYSICAL'
        )
    ).distinct()

    all_servers = (
        Server.objects.only('SERVER_ID','LIVE_STATUS','SNOW_STATUS','INFRAVERSION')
        .filter(
            LIVE_STATUS='ALIVE',
            SNOW_STATUS='OPERATIONAL',
            INFRAVERSION__in=['IV1', 'IV2', 'IBM']
        )
    ).distinct()
    
    stats['total_entries'] = all_servers.count()
    stats['total_physical_servers'] = physical_servers.count()
    stats['unique_servers'] = len(servers_with_issues)
    stats['servers_with_discrepancies'] = len(records)
    stats['records'] = records
    
    return stats, analysis_date


# ============================================================================
# TABLE OPERATIONS
# ============================================================================

def bulk_insert_discrepancies(records):
    if not records:
        return
    
    # Build column list dynamically
    inconsistency_names = [check.__name__.replace('check_', '') 
                          for check in ALL_CHECKS if 'inconsistent' in check.__name__]
    
    columns = ['SERVER_ID', 'missing_fields', 'analysis_date'] + FIELDS_TO_CHECK
    columns.extend(inconsistency_names)
    
    #columns_str = ', '.join(columns)
    columns_str = ', '.join([f'"{col}"' for col in columns])
    chunk_size = 1000
    total = 0
    
    ServerDiscrepancy.objects.all().delete()
    
    with connection.cursor() as cursor:
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            
            placeholders = ', '.join(['(' + ', '.join(['%s'] * len(columns)) + ')'] * len(chunk))
            
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


def filter_persistent_records(records, days_threshold):
    """
    Keep only records for servers whose oldest active issue (DiscrepancyTracking.oldest_first_seen)
    has been open for at least `days_threshold` days. A field missing for a single day and fixed
    the next isn't a "real" discrepancy for KPI/historic purposes — only persistent ones are.

    Must be called AFTER update_tracker(), so oldest_first_seen reflects the current run.
    """
    cutoff = timezone.now() - datetime.timedelta(days=days_threshold)
    persistent_ids = set(
        DiscrepancyTracking.objects.filter(oldest_first_seen__lte=cutoff).values_list('SERVER_ID', flat=True)
    )
    return [r for r in records if r['SERVER_ID'] in persistent_ids]


def create_analysis_snapshot(
    stats, analysis_date, duration, diff=None,
    persistent_records=None, persistent_days_threshold=7,
    persistent_alive_inconsistent_count=0, persistent_dead_inconsistent_count=0,
):
    # persistent_records here is the missing-data-only persistent list — see
    # POPULATION_FILTERS and the comment on AnalysisSnapshot.persistent_servers_with_issues.
    field_mapping = {
        'LIVE_STATUS': 'missing_live_status_count',
        'OSSHORTNAME': 'missing_osshortname_count',
        'OSFAMILY': 'missing_osfamily_count',
        'SNOW_SUPPORTGROUP': 'missing_snow_supportgroup_count',
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
        'IDRAC_NAME': 'missing_idrac_name_count',
        'IDRAC_IP': 'missing_idrac_ip_count',
    }
    
    diff = diff or {}
    snapshot = AnalysisSnapshot(
        analysis_date=analysis_date,
        total_servers_analyzed=stats['total_entries'],
        total_physical_servers=stats['total_physical_servers'],
        servers_with_issues=stats['servers_with_discrepancies'],
        servers_clean=stats['total_entries'] - stats['servers_with_discrepancies'],
        duration_seconds=duration,
        alive_status_inconsistent_count=stats.get('alive_status_inconsistent_count', 0),
        dead_status_inconsistent_count=stats.get('dead_status_inconsistent_count', 0),
        new_issues_count=len(diff.get('new', [])),
        resolved_issues_count=len(diff.get('resolved', [])),
        changed_issues_count=len(diff.get('changed', {})),
        diff_summary=diff,
        persistent_days_threshold=persistent_days_threshold,
        persistent_servers_with_issues=len(persistent_records or []),
        persistent_alive_inconsistent_count=persistent_alive_inconsistent_count,
        persistent_dead_inconsistent_count=persistent_dead_inconsistent_count,
    )
    
    for field, count_attr in field_mapping.items():
        #snapshot_data[count_attr] = stats.get('discrepancies_by_field', {}).get(field, 0)
        count = stats.get('discrepancies_by_field', {}).get(field, 0)
        setattr(snapshot, count_attr, count)
    
    inconsistency_names = [check.__name__.replace('check_', '') 
                          for check in ALL_CHECKS if 'inconsistent' in check.__name__]
    
    snapshot.save()
    
    write_log(f"Created analysis snapshot: {snapshot.id}")
    return snapshot


def compute_breakdowns(records, dimension_fields, population_filter, track_field_counts=True):
    """
    Aggregate issue counts by dimension value (REGION, OSSHORTNAME, ...) for the current run,
    against ONE specific eligible population (see POPULATION_FILTERS). `records` must already
    be scoped to the matching metric (e.g. only alive-inconsistent records for the
    'alive_inconsistent' population) — mixing metrics under one population is meaningless,
    since e.g. an alive-inconsistent server is by definition not in the ALIVE+OPERATIONAL population.

    Returns {dimension: {value: {'total_servers', 'servers_with_issues', 'servers_clean', 'field_counts'}}}
    """
    write_log("Computing breakdowns: " + ', '.join(dimension_fields))

    breakdowns = {}

    for dimension in dimension_fields:
        population = (
            Server.objects.filter(**population_filter)
            .values(dimension)
            .annotate(total=Count('SERVER_ID', distinct=True))
        )
        totals = defaultdict(int)
        for row in population:
            value = row[dimension] if is_value_valid(row[dimension]) else MISSING_MARKER
            totals[value] += row['total']

        per_value = defaultdict(lambda: {'servers_with_issues': 0, 'field_counts': defaultdict(int)})
        for record in records:
            value = record.get(dimension) if is_value_valid(record.get(dimension)) else MISSING_MARKER
            slot = per_value[value]
            slot['servers_with_issues'] += 1

            if track_field_counts:
                for field in [f for f in record.get('missing_fields', '').split(',') if f]:
                    slot['field_counts'][field] += 1

        rows = {}
        for value in set(totals) | set(per_value):
            total = totals.get(value, 0)
            with_issues = per_value[value]['servers_with_issues']
            rows[value] = {
                'total_servers': total,
                'servers_with_issues': with_issues,
                'servers_clean': max(0, total - with_issues),
                'field_counts': dict(per_value[value]['field_counts']),
            }
        breakdowns[dimension] = rows

        if len(rows) > CARDINALITY_WARNING_THRESHOLD:
            write_log(
                f"WARNING: dimension '{dimension}' has {len(rows)} distinct values (> {CARDINALITY_WARNING_THRESHOLD}) — "
                f"check breakdown_groups.json, this dimension may not be a good fit for the history table."
            )

    return breakdowns


def save_breakdowns(snapshot, metric, breakdowns):
    rows = [
        AnalysisSnapshotBreakdown(
            snapshot=snapshot,
            metric=metric,
            dimension=dimension,
            dimension_value=value,
            total_servers=data['total_servers'],
            servers_with_issues=data['servers_with_issues'],
            servers_clean=data['servers_clean'],
            field_counts=data['field_counts'],
        )
        for dimension, values in breakdowns.items()
        for value, data in values.items()
    ]
    if rows:
        AnalysisSnapshotBreakdown.objects.bulk_create(rows, batch_size=500)
        write_log(f"Saved {len(rows)} breakdown rows (metric={metric})")


def load_breakdown_groups():
    # discrepancies/breakdown_groups.json — {"dimensions": [{"field", "label"}, ...], "groups": {field: {"buckets": {...}, "other_label": "..."}}}
    try:
        with open(BREAKDOWN_GROUPS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        write_log(f"WARNING: could not load breakdown_groups.json ({e}) — no breakdowns will be computed")
        return {}


def breakdown_dimension_fields(config):
    return [d['field'] for d in config.get('dimensions', [])]


def bucket_for(value, group_def):
    # Map a raw field value to its configured bucket name, or the fallback "other_label".
    # Case-insensitive: breakdown_groups.json says "Windows", the DB may say "WINDOWS".
    if not is_value_valid(value):
        return MISSING_MARKER
    value_key = str(value).strip().upper()
    for bucket_name, members in group_def.get('buckets', {}).items():
        member_keys = {str(m).strip().upper() for m in members}
        if value_key in member_keys:
            return bucket_name
    return group_def.get('other_label', 'Other')


def compute_cross_breakdown(records, row_field, bucket_field, group_def, population_filter):
    """
    row_field x bucket_field matrix (e.g. REGION x OS-bucket). Population totals come
    from the given eligible Server population; issue counts from the given (already
    metric-scoped, persistent-filtered) records.

    Returns {(row_value, bucket_value): {'total_servers', 'servers_with_issues', 'servers_clean'}}
    """
    population = (
        Server.objects.filter(**population_filter)
        .values(row_field, bucket_field)
        .annotate(total=Count('SERVER_ID', distinct=True))
    )
    totals = defaultdict(int)
    for row in population:
        row_value = row[row_field] if is_value_valid(row[row_field]) else MISSING_MARKER
        bucket_value = bucket_for(row[bucket_field], group_def)
        totals[(row_value, bucket_value)] += row['total']

    issues = defaultdict(int)
    for record in records:
        row_value = record.get(row_field) if is_value_valid(record.get(row_field)) else MISSING_MARKER
        bucket_value = bucket_for(record.get(bucket_field), group_def)
        issues[(row_value, bucket_value)] += 1

    matrix = {}
    for key in set(totals) | set(issues):
        total = totals.get(key, 0)
        with_issues = issues.get(key, 0)
        matrix[key] = {
            'total_servers': total,
            'servers_with_issues': with_issues,
            'servers_clean': max(0, total - with_issues),
        }
    return matrix


def save_cross_breakdown(snapshot, matrix):
    rows = [
        AnalysisSnapshotCrossBreakdown(
            snapshot=snapshot,
            region=row_value,
            os_bucket=bucket_value,
            total_servers=data['total_servers'],
            servers_with_issues=data['servers_with_issues'],
            servers_clean=data['servers_clean'],
        )
        for (row_value, bucket_value), data in matrix.items()
    ]
    if rows:
        AnalysisSnapshotCrossBreakdown.objects.bulk_create(rows, batch_size=200)
        write_log(f"Saved {len(rows)} cross-breakdown rows")


def print_report(stats):
    total = stats['unique_servers'] or 1
    discrepancies = stats['servers_with_discrepancies']
    pct = discrepancies / total * 100
    
    print("\n" + "=" * 60)
    print("DISCREPANCY ANALYSIS REPORT")
    print("=" * 60)
    print(f"Total entries analyzed: {stats['total_entries']}")
    print(f"Total physical servers: {stats['total_physical_servers']}")
    print(f"Unique servers with issues: {stats['unique_servers']}")
    print(f"Servers with discrepancies: {discrepancies} ({pct:.1f}%)")
    print("\nMissing fields:")
    
    for field, count in sorted(stats['discrepancies_by_field'].items(), key=lambda x: -x[1]):
        field_pct = count / total * 100
        print(f"  {field}: {count} ({field_pct:.1f}%)")
    
    print("\nValidation errors:")
    inconsistency_names = [check.__name__.replace('check_', '') 
                          for check in ALL_CHECKS if 'inconsistent' in check.__name__]
    
    for check_name in inconsistency_names:
        count = stats.get(f'{check_name}_count', 0)
        if count > 0:
            pct = (count / total * 100)
            print(f"  {check_name}: {count} servers ({pct:.1f}%)")
    
    print("=" * 60 + "\n")


# ============================================================================
# TRACKER
# ============================================================================

def _compute_oldest_first_seen(active_issues):
    # Return the oldest first_seen datetime across all active issues
    
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

    # Build current issues: {SERVER_ID: {field_name, ...}}
    current_issues = defaultdict(set)
    for record in records:
        server_id = record['SERVER_ID']
        missing = record.get('missing_fields', '')
        if missing:
            for field_name in missing.split(','):
                field_name = field_name.strip()
                if field_name:
                    current_issues[server_id].add(field_name)
        if record.get('alive_status_inconsistent') == 'KO':
            current_issues[server_id].add('alive_status_inconsistent')
        if record.get('dead_status_inconsistent') == 'KO':
            current_issues[server_id].add('dead_status_inconsistent')
            
    write_log(f"Tracker: {sum(len(v) for v in current_issues.values())} active issues across {len(current_issues)} servers")

    # Load all existing trackers
    existing_trackers = {t.SERVER_ID: t for t in DiscrepancyTracking.objects.all()}

    # Process every server that is either currently broken or was previously tracked
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
# MAIN COMMAND
# ============================================================================

class Command(BaseCommand):
    help = 'Analyze servers for missing/invalid data in critical fields'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Bypass the 10%% safety threshold check (for manual runs)',
        )
        parser.add_argument(
            '--persistent-days',
            type=int,
            default=7,
            help='Minimum days an issue must stay open to count as a "real" discrepancy in the historic snapshot (default: 7)',
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

            # Split into the 3 metrics — each has its own eligible population (see
            # POPULATION_FILTERS) and must not be mixed with the others.
            missing_data_all = [r for r in stats['records'] if r.get('missing_fields')]
            alive_inconsistent_all = [r for r in stats['records'] if r.get('alive_status_inconsistent') == VALIDATION_KO]
            dead_inconsistent_all = [r for r in stats['records'] if r.get('dead_status_inconsistent') == VALIDATION_KO]

            # Persistent issues (>= N days open) — the "real" discrepancies for the historic snapshot
            persistent_days = options['persistent_days']
            missing_data_persistent = filter_persistent_records(missing_data_all, persistent_days)
            alive_inconsistent_persistent = filter_persistent_records(alive_inconsistent_all, persistent_days)
            dead_inconsistent_persistent = filter_persistent_records(dead_inconsistent_all, persistent_days)
            write_log(
                f"Persistent (>= {persistent_days}d open) — "
                f"missing data: {len(missing_data_persistent)}/{len(missing_data_all)}, "
                f"alive-inconsistent: {len(alive_inconsistent_persistent)}/{len(alive_inconsistent_all)}, "
                f"dead-inconsistent: {len(dead_inconsistent_persistent)}/{len(dead_inconsistent_all)}"
            )

            # Report
            print_report(stats)

            duration = datetime.datetime.now() - start_time
            snapshot = create_analysis_snapshot(
                stats, analysis_date, duration.total_seconds(), diff,
                persistent_records=missing_data_persistent, persistent_days_threshold=persistent_days,
                persistent_alive_inconsistent_count=len(alive_inconsistent_persistent),
                persistent_dead_inconsistent_count=len(dead_inconsistent_persistent),
            )

            group_config = load_breakdown_groups()
            dimension_fields = breakdown_dimension_fields(group_config)

            missing_breakdowns = compute_breakdowns(
                missing_data_persistent, dimension_fields, POPULATION_FILTERS['missing_data'], track_field_counts=True
            )
            save_breakdowns(snapshot, AnalysisSnapshotBreakdown.METRIC_MISSING_DATA, missing_breakdowns)

            alive_breakdowns = compute_breakdowns(
                alive_inconsistent_persistent, dimension_fields, POPULATION_FILTERS['alive_inconsistent'], track_field_counts=False
            )
            save_breakdowns(snapshot, AnalysisSnapshotBreakdown.METRIC_ALIVE_INCONSISTENT, alive_breakdowns)

            dead_breakdowns = compute_breakdowns(
                dead_inconsistent_persistent, dimension_fields, POPULATION_FILTERS['dead_inconsistent'], track_field_counts=False
            )
            save_breakdowns(snapshot, AnalysisSnapshotBreakdown.METRIC_DEAD_INCONSISTENT, dead_breakdowns)

            groups = group_config.get('groups', {})
            for row_field, bucket_field in CROSS_BREAKDOWNS:
                group_def = groups.get(bucket_field)
                if not group_def:
                    write_log(f"WARNING: no breakdown_groups.json entry for '{bucket_field}' — skipping {row_field}x{bucket_field} cross-breakdown")
                    continue
                matrix = compute_cross_breakdown(
                    missing_data_persistent, row_field, bucket_field, group_def, POPULATION_FILTERS['missing_data']
                )
                save_cross_breakdown(snapshot, matrix)

            write_log(f"Completed in {duration}")
            msg = (f"Analysis complete: {stats['total_entries']} analyzed, {stats['servers_with_discrepancies']} servers with discrepancies")
            ImportStatus.objects.create(success=True, message=msg, nb_entries_created=stats['servers_with_discrepancies'])
        
        except Exception as e:
            msg = f"Error during the execution of analyze_discrepancies: {e}"
            write_log(f"ERROR: {e}")
            ImportStatus.objects.create(success=False, message=msg)
            raise
