#    python manage.py analyze_discrepancies

import datetime
from django.utils import timezone
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q

from inventory.models import Server
from discrepancies.models import ServerDiscrepancy, AnalysisSnapshot


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
    '', 'EMPTY', 'N/A', 'NA', 'N.A.', 'UNKNOWN',
    'UNDEFINED', 'NULL', 'NONE', '-', '--', '?',
}

# Markers
MISSING_MARKER = 'MISSING'
VALIDATION_OK = 'OK'
VALIDATION_KO = 'KO'


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
    
    queryset = Server.objects.only(*fields_to_fetch).filter(
        LIVE_STATUS__iexact='LIVE',
        #SNOW_STATUS__iexact='OPERATIONAL',
        # INFRAVERSION__in=['IV1', 'IV2', 'IBM'],  # Optionnel
    ).order_by('SERVER_ID')
    
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
                missing_fields.add(field)
        
        # Only add if has missing fields
        if missing_fields:
            add_or_update_server(servers_with_issues, server_id, missing_fields, field_values)
    
    write_log(f"  Found {count} entries")
    return count


def check_live_status_inconsistent(servers_with_issues):
    """
    Check for LIVE_STATUS inconsistencies.
    Servers that are OPERATIONAL but not ALIVE.
    """
    write_log("Check 2: LIVE_STATUS inconsistent (OPERATIONAL but not ALIVE)")
    
    fields_to_fetch = ['SERVER_ID'] + FIELDS_TO_CHECK
    
    queryset = Server.objects.only(*fields_to_fetch).filter(
        SNOW_STATUS__iexact='OPERATIONAL',
        # INFRAVERSION__in=['IV1', 'IV2', 'IBM'],
    ).exclude(
        LIVE_STATUS__iexact='ALIVE'
    ).order_by('SERVER_ID')
    
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
            inconsistencies={'live_status_inconsistent': VALIDATION_KO}
        )
    
    write_log(f"  Found {count} inconsistencies")
    return count


def check_snow_status_inconsistent(servers_with_issues):
    """
    Check for SNOW_STATUS inconsistencies.
    Servers that are ALIVE but RETIRED/NON-OPERATIONAL.
    """
    write_log("Check 3: SNOW_STATUS inconsistent (ALIVE but RETIRED/NON-OPERATIONAL)")
    
    fields_to_fetch = ['SERVER_ID'] + FIELDS_TO_CHECK
    
    queryset = Server.objects.only(*fields_to_fetch).filter(
        Q(SNOW_STATUS__iexact='RETIRED') | Q(SNOW_STATUS__iexact='NON-OPERATIONAL'),
        LIVE_STATUS__iexact='ALIVE',
        # INFRAVERSION__in=['IV1', 'IV2', 'IBM'],
    ).order_by('SERVER_ID')
    
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
            inconsistencies={'snow_status_inconsistent': VALIDATION_KO}
        )
    
    write_log(f"  Found {count} inconsistencies")
    return count


# Register all checks here
ALL_CHECKS = [
    check_missing_fields,
    check_live_status_inconsistent,
    check_snow_status_inconsistent,
    # Add more checks easily:
    # check_country_region_mismatch,
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def write_log(message):
    now = datetime.datetime.now()
    time_str = f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}"
    print(f"[{time_str}] {message}")


def is_value_missing(value):
    """Check if value is considered missing or invalid."""
    if value is None:
        return True
    return str(value).strip().upper() in INVALID_VALUES


def is_value_valid(value):
    """Check if value is considered valid (not missing/invalid)."""
    if value is None:
        return False
    return str(value).strip().upper() not in INVALID_VALUES


def add_or_update_server(servers_with_issues, server_id, missing_fields, field_values, inconsistencies=None):
    """
    Add or update a server in the issues dict.
    Properly merges missing_fields, field_values, and inconsistencies.
    """
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
        # New server
        # Initialize all inconsistency checks to OK if not provided
        all_inconsistencies = {check.__name__.replace('check_', ''): VALIDATION_OK 
                              for check in ALL_CHECKS if 'inconsistent' in check.__name__}
        all_inconsistencies.update(inconsistencies)
        
        servers_with_issues[server_id] = {
            'missing_fields': missing_fields.copy(),
            'field_values': field_values.copy(),
            'inconsistencies': all_inconsistencies
        }


# ============================================================================
# MAIN ANALYSIS
# ============================================================================

def analyze_servers():
    """
    Run all checks with their own querysets.
    """
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
            if field in data['missing_fields']:
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
    
    stats['total_entries'] = total_entries
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
    
    columns_str = ', '.join(columns)
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


def create_analysis_snapshot(stats, analysis_date, duration):
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
    
    snapshot_data = {
        'analysis_date': analysis_date,
        'total_servers_analyzed': stats['total_entries'],
        'servers_with_issues': stats['servers_with_discrepancies'],
        'servers_clean': stats['total_entries'] - stats['servers_with_discrepancies'],
        'duration_seconds': duration,
    }
    
    for field, count_attr in field_mapping.items():
        snapshot_data[count_attr] = stats.get('discrepancies_by_field', {}).get(field, 0)
    
    inconsistency_names = [check.__name__.replace('check_', '') 
                          for check in ALL_CHECKS if 'inconsistent' in check.__name__]
    
    for check_name in inconsistency_names:
        count_attr = f'{check_name}_count'
        snapshot_data[count_attr] = stats.get(count_attr, 0)
    
    snapshot = AnalysisSnapshot(**snapshot_data)
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
# COMMAND
# ============================================================================

class Command(BaseCommand):
    help = 'Analyze servers for missing/invalid data in critical fields'
    
    def handle(self, *args, **options):
        start_time = datetime.datetime.now()
        write_log("=" * 60)
        write_log("DISCREPANCY ANALYSIS START")
        write_log("=" * 60)
        
        try:
            stats, analysis_date = analyze_servers()
            
            if stats['records']:
                write_log(f"Inserting discrepancy records...")
                bulk_insert_discrepancies(stats['records'])
            else:
                write_log("No discrepancies found")
            
            print_report(stats)
            
            duration = datetime.datetime.now() - start_time
            create_analysis_snapshot(stats, analysis_date, duration.total_seconds())
            
            write_log(f"Completed in {duration}")
        
        except Exception as e:
            write_log(f"ERROR: {e}")
            raise