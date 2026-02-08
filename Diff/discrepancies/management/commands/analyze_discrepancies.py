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
    '', 'EMPTY', 'N/A', 'NA', 'N.A.', 'UNKNOWN', 'UNDEFINED', 'NULL', 'NONE', '-', '--', '?',
}

MISSING_MARKER = 'MISSING'
VALIDATION_OK = 'OK'
VALIDATION_KO = 'KO'

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

    columns = ['SERVER_ID', 'missing_fields', 'analysis_date'] + FIELDS_TO_CHECK + ['live_status_snow_status_inconsistent']
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
        'live_status_snow_status_inconsistent': VALIDATION_OK
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
                'live_status_snow_status_inconsistent': VALIDATION_OK
            }
            data = server_data[server_id]
            for field in FIELDS_TO_CHECK:
                value = getattr(server, field, None)
                data['field_values'][field] = value
        else:
            server_data[server_id]['live_status_snow_status_inconsistent'] = VALIDATION_KO

    write_log(f"{inconsistent_count} entries with inconsistencies found")

    # Build discrepancy records
    records = []
    stats = {
        'discrepancies_by_field': defaultdict(int),
        'live_status_snow_status_inconsistent_count': 0
    }

    analysis_date = timezone.now().isoformat() 

    for server_id, data in server_data.items():
        # Only create records for servers with issues
        if not data['missing_fields'] and data['live_status_snow_status_inconsistent'] == VALIDATION_OK:
            continue

        missing_list = sorted(data['missing_fields'])

        record = {
            'SERVER_ID': server_id,
            'missing_fields': ','.join(missing_list),
            'analysis_date': analysis_date,
            'live_status_snow_status_inconsistent': data['live_status_snow_status_inconsistent']
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
        if data['live_status_snow_status_inconsistent'] == VALIDATION_KO: 
            stats['live_status_snow_status_inconsistent_count'] += 1

    stats['total_entries'] = total_entries
    stats['unique_servers'] = len(server_data)
    stats['servers_with_discrepancies'] = len(records)
    stats['records'] = records

    return stats, analysis_date


def create_analysis_snapshot(stats, analysis_date, duration):

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

    snapshot = AnalysisSnapshot(
        analysis_date=analysis_date,
        total_servers_analyzed=stats['total_entries'],
        servers_with_issues=stats['servers_with_discrepancies'],
        servers_clean=stats['total_entries'] - stats['servers_with_discrepancies'],
        duration_seconds=duration,
        live_status_snow_status_inconsistent_count=stats.get('live_status_snow_status_inconsistent_count', 0),
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
    inconsistent_count = stats.get('live_status_snow_status_inconsistent_count', 0)
    if inconsistent_count > 0:
        print(f"  Live Status/Snow Status inconsistencies: {inconsistent_count} servers ({(inconsistent_count / total * 100):.1f}%)")
    else:
        print(f"  No inconsistencies found")

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

            # Analyze
            stats, analysis_date = analyze_servers()

            # Insert records
            if stats['records']:
                write_log(f"Inserting discrepancy records...")
                bulk_insert_discrepancies(stats['records'])
            else:
                write_log("No discrepancies found")

            # Report
            print_report(stats)

            duration = datetime.datetime.now() - start_time

            create_analysis_snapshot(stats, analysis_date, duration.total_seconds())

            write_log(f"Completed in {duration}")

        except Exception as e:
            write_log(f"ERROR: {e}")
            raise