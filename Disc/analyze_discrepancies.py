"""
Analyze server discrepancies - finds servers with missing/invalid data.

Reads from Server table, writes to ServerDiscrepancy table via staging swap.

Usage:
    python manage.py analyze_discrepancies
"""

import datetime
import sqlite3
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from inventory.models import Server, ServerDiscrepancy


# ============================================================================
# CONFIGURATION
# ============================================================================

FIELDS_TO_CHECK = [
    'APP_NAME_VALUE',
    'APP_AUID_VALUE',
    'PAMELA_DATACENTER',
    'OS',
    'OSSHORTNAME',
    'ENVIRONMENT',
    'REGION',
    'TECHFAMILY',
    'SNOW_SUPPORTGROUP',
    'APP_SUPPORTGROUP_NAME',
    'LIVE_STATUS',
    'MACHINE_TYPE',
    'IPADDRESS',
]

INVALID_VALUES = {
    '', 'EMPTY', 'N/A', 'NA', 'N.A.', 'UNKNOWN',
    'UNDEFINED', 'NULL', 'NONE', '-', '--', '?',
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def write_log(message):
    print(f"[{datetime.datetime.now()}] {message}")


def is_value_missing(value):
    """Check if value is considered missing or invalid."""
    if value is None:
        return True
    return str(value).strip().upper() in INVALID_VALUES


def get_db_config():
    """Get database configuration."""
    db_config = settings.DATABASES['default']
    is_sqlite = 'sqlite' in db_config.get('ENGINE', '')
    return db_config, is_sqlite


# ============================================================================
# STAGING TABLE OPERATIONS
# ============================================================================

def recreate_staging_table():
    """Recreate the discrepancy staging table."""
    db_config, is_sqlite = get_db_config()

    if is_sqlite:
        conn = sqlite3.connect(db_config['NAME'])
        try:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS inventory_serverdiscrepancystaging;")

            # Build column definitions
            columns = [
                "id INTEGER PRIMARY KEY AUTOINCREMENT",
                "SERVER_ID VARCHAR(100) NOT NULL UNIQUE",
            ]
            for field in FIELDS_TO_CHECK:
                columns.append(f"{field} VARCHAR(100)")
            columns.append("missing_fields TEXT")
            columns.append("analysis_date DATETIME")

            create_sql = f"CREATE TABLE inventory_serverdiscrepancystaging ({', '.join(columns)});"
            cursor.execute(create_sql)

            # Create indexes (matching ServerDiscrepancy model)
            cursor.execute("CREATE INDEX idx_staging_server_id ON inventory_serverdiscrepancystaging (SERVER_ID);")
            cursor.execute("CREATE INDEX idx_staging_environment ON inventory_serverdiscrepancystaging (ENVIRONMENT);")
            cursor.execute("CREATE INDEX idx_staging_region ON inventory_serverdiscrepancystaging (REGION);")
            cursor.execute("CREATE INDEX idx_staging_analysis_date ON inventory_serverdiscrepancystaging (analysis_date);")

            conn.commit()
        finally:
            conn.close()
    else:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS inventory_serverdiscrepancystaging;")
            cursor.execute("""
                CREATE TABLE inventory_serverdiscrepancystaging
                (LIKE inventory_serverdiscrepancy INCLUDING ALL);
            """)

    write_log("Staging table created")


def swap_tables():
    """Swap staging table to production."""
    db_config, is_sqlite = get_db_config()

    if is_sqlite:
        conn = sqlite3.connect(db_config['NAME'])
        try:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS inventory_serverdiscrepancybackup;")

            # Check if main table exists
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='inventory_serverdiscrepancy';
            """)
            if cursor.fetchone():
                cursor.execute("ALTER TABLE inventory_serverdiscrepancy RENAME TO inventory_serverdiscrepancybackup;")

            cursor.execute("ALTER TABLE inventory_serverdiscrepancystaging RENAME TO inventory_serverdiscrepancy;")
            conn.commit()
        finally:
            conn.close()
    else:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN;")
            cursor.execute("DROP TABLE IF EXISTS inventory_serverdiscrepancybackup;")
            cursor.execute("ALTER TABLE inventory_serverdiscrepancy RENAME TO inventory_serverdiscrepancybackup;")
            cursor.execute("ALTER TABLE inventory_serverdiscrepancystaging RENAME TO inventory_serverdiscrepancy;")
            cursor.execute("COMMIT;")

    write_log("Tables swapped")


def bulk_insert_discrepancies(records):
    """Bulk insert discrepancy records."""
    if not records:
        return

    columns = ['SERVER_ID', 'missing_fields', 'analysis_date'] + FIELDS_TO_CHECK
    placeholders = ', '.join(['%s'] * len(columns))
    columns_str = ', '.join(columns)

    insert_sql = f"""
        INSERT INTO inventory_serverdiscrepancystaging ({columns_str})
        VALUES ({placeholders})
    """

    chunk_size = 5000
    total = 0

    with connection.cursor() as cursor:
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            values_list = [[record.get(col) for col in columns] for record in chunk]
            cursor.executemany(insert_sql, values_list)
            total += len(chunk)
            write_log(f"Inserted {total}/{len(records)} records")


# ============================================================================
# MAIN ANALYSIS
# ============================================================================

def analyze_servers():
    """
    Analyze all servers for missing data.
    Returns statistics dict.
    """
    write_log(f"Starting analysis - checking fields: {', '.join(FIELDS_TO_CHECK)}")

    # Group data by SERVER_ID (handles duplicates)
    server_data = defaultdict(lambda: {'missing_fields': set(), 'field_values': {}})

    fields_to_fetch = ['SERVER_ID'] + FIELDS_TO_CHECK
    queryset = Server.objects.only(*fields_to_fetch).order_by('SERVER_ID')

    total_entries = 0
    for server in queryset.iterator(chunk_size=50000):
        total_entries += 1

        if total_entries % 100000 == 0:
            write_log(f"Processed {total_entries} entries...")

        server_id = server.SERVER_ID
        data = server_data[server_id]

        for field in FIELDS_TO_CHECK:
            value = getattr(server, field, None)

            # Keep first non-empty value
            if field not in data['field_values'] or is_value_missing(data['field_values'][field]):
                data['field_values'][field] = value

            # Track missing
            if is_value_missing(value):
                data['missing_fields'].add(field)

    write_log(f"Analyzed {total_entries} entries for {len(server_data)} unique servers")

    # Build discrepancy records
    records = []
    stats = {'discrepancies_by_field': defaultdict(int)}
    analysis_date = datetime.datetime.now().isoformat()

    for server_id, data in server_data.items():
        if not data['missing_fields']:
            continue

        missing_list = sorted(data['missing_fields'])

        record = {
            'SERVER_ID': server_id,
            'missing_fields': ','.join(missing_list),
            'analysis_date': analysis_date,
        }

        for field in FIELDS_TO_CHECK:
            value = data['field_values'].get(field)
            record[field] = value if not is_value_missing(value) else None

        records.append(record)

        for field in missing_list:
            stats['discrepancies_by_field'][field] += 1

    stats['total_entries'] = total_entries
    stats['unique_servers'] = len(server_data)
    stats['servers_with_discrepancies'] = len(records)
    stats['records'] = records

    return stats


def print_report(stats):
    """Print analysis report."""
    total = stats['unique_servers'] or 1
    discrepancies = stats['servers_with_discrepancies']
    pct = discrepancies / total * 100

    print("\n" + "=" * 60)
    print("DISCREPANCY ANALYSIS REPORT")
    print("=" * 60)
    print(f"Total entries analyzed: {stats['total_entries']}")
    print(f"Unique servers: {stats['unique_servers']}")
    print(f"Servers with discrepancies: {discrepancies} ({pct:.1f}%)")
    print("\nBy field:")

    for field, count in sorted(stats['discrepancies_by_field'].items(), key=lambda x: -x[1]):
        field_pct = count / total * 100
        print(f"  {field}: {count} ({field_pct:.1f}%)")

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
            # Create staging table
            recreate_staging_table()

            # Analyze
            stats = analyze_servers()

            # Insert records
            if stats['records']:
                write_log(f"Inserting {len(stats['records'])} discrepancy records...")
                bulk_insert_discrepancies(stats['records'])
            else:
                write_log("No discrepancies found")

            # Swap tables
            swap_tables()

            # Report
            print_report(stats)

            duration = datetime.datetime.now() - start_time
            write_log(f"Completed in {duration}")

        except Exception as e:
            write_log(f"ERROR: {e}")
            raise
