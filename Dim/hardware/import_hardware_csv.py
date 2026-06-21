# python manage.py import_hardware_csv [filepath]

import csv
import logging
import datetime
import os
import ssl
import traceback
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import connection as django_connection, transaction
from hardware.models import Server, ServerStaging, ImportStatus
from .import_hardware_config import FIELD_MAP, EXTRA_READ, row_transform
from collections import Counter

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)
BATCH_SIZE = 500
LOG_PATH = "/data/DPR_DATA/logs/import_apm_hardware.log"
FILTERED_CSV = "/data/DPR_DATA/apm_filtered.csv"
DEFAULT_FILEPATH = "/data/DPR_DATA/apm_hardware.csv"
DPR_URL = "https://dpr-backend.group.echonet/export/hardware/servers?format=csv"


class TLSAdapter(HTTPAdapter):
    """Work around [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] on some servers."""
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.set_ciphers('DEFAULT@SECLEVEL=1')
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)


def write_log(message):
    print(message)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, 'a') as log_file:
            log_file.write(message + '\n')
    except Exception as e:
        print(f'[write_log error] {e}')


def download_csv(url, dest_path):
    """Download CSV from url to dest_path, backing up the existing file first."""
    try:
        if os.path.exists(dest_path):
            backup_path = dest_path + '.bak'
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.rename(dest_path, backup_path)
            write_log(f'[{datetime.datetime.now()}] Existing file backed up to {backup_path}')
    except Exception as e:
        return False, f'Backup failed: {e}'

    write_log(f'[{datetime.datetime.now()}] Downloading from {url} ...')
    try:
        session = requests.Session()
        session.mount('https://', TLSAdapter())
        with session.get(url, stream=True, timeout=60, verify=False) as resp:
            resp.raise_for_status()
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
    except Exception as e:
        return False, f'Download failed: {e}'

    return True, f'Downloaded: {dest_path}'


def filter_and_deduplicate_csv(input_file):
    """Filter CSV for hardware+alive, deduplicate by all relevant fields, add COUNT"""
    relevant_columns = [
        'Serial number', 'Technology Standard Asset type', 'Live Status', 'AREA', 'COUNTRY', 'DATACENTER', 'Vendor', 'Model',
        'WARRANTY_ACTIVE', 'WARRANTY_ACTUAL_SUPPLIER', 'WARRANTY_INITIAL_PROVIDER_NAME', 'WARRANTY_INITIAL_START_DATE', 'WARRANTY_INITIAL_END_DATE',
        'WARRANTY_EXTENSION_PROVIDER_NAME', 'WARRANTY_EXTENSION_START_DATE', 'WARRANTY_EXTENSION_END_DATE', 'WARRANTY_SUPPORT_LEVEL', 
        'WARRANTY_TO_STOP', 'SERVER IP', 'OS SHORTNAME', 'SHORT ENVIRONMENT', 'HW asset used for', 'HW host', 'PROVIDER', 'PAMELA__IDRACIP', 'SLOT-MANAGER__IDRAC_IP'
    ]
    
    # First pass: filter hardware+alive and deduplicate (temp file)
    temp_file = FILTERED_CSV.replace('_filtered.csv', '_filtered_temp.csv')
    seen = set()
    temp_rows = []
    
    with open(input_file, newline='', encoding='utf-8-sig') as f_in:
        reader = csv.DictReader(f_in)
        
        for row in reader:
            asset_type = row.get('Technology Standard Asset type', '').strip().upper()
            live_status = row.get('Live Status', '').strip().upper()
            
            serial = row.get('Serial number', '').strip()
            if asset_type == 'HARDWARE' and live_status == 'ALIVE' and serial and serial != 'N/A':
                values = tuple([row.get(col, '') for col in relevant_columns])
                if values not in seen:
                    seen.add(values)
                    row_dict = {col: row.get(col, '') for col in relevant_columns}
                    temp_rows.append(row_dict)
    
    with open(temp_file, 'w', newline='', encoding='utf-8') as f_out:
        writer = csv.DictWriter(f_out, fieldnames=relevant_columns)
        writer.writeheader()
        writer.writerows(temp_rows)
    
    # Second pass: count occurrences from temp file
    serial_counts = Counter()
    with open(temp_file, newline='', encoding='utf-8') as f_temps:
        reader = csv.DictReader(f_temps)
        for row in reader:
            serial = row.get('Serial number', '').strip()
            if serial:
                serial_counts[serial] += 1
    
    # Third pass: write with COUNT
    final_rows = []
    
    with open(temp_file, newline='', encoding='utf-8') as f_temps:
        reader = csv.DictReader(f_temps)
        
        for row in reader:
            serial = row.get('Serial number', '').strip()
            if serial:
                row_dict = {col: row.get(col, '') for col in relevant_columns}
                row_dict['COUNT'] = str(serial_counts[serial])
                final_rows.append(row_dict)
    
    with open(FILTERED_CSV, 'w', newline='', encoding='utf-8') as f_out:
        writer = csv.DictWriter(f_out, fieldnames=relevant_columns + ['COUNT'])
        writer.writeheader()
        writer.writerows(final_rows)
    
    # Clean up temp file
    import os
    if os.path.exists(temp_file):
        os.remove(temp_file)
    
    return len(final_rows)


def recreate_staging_table():
    with django_connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS hardware_serverstaging;")
        cursor.execute("CREATE TABLE hardware_serverstaging (LIKE hardware_server INCLUDING ALL);")


class Command(BaseCommand):
    help = "Import servers from CSV file"

    def add_arguments(self, parser):
        parser.add_argument('filepath', nargs='?', default=None,
                            help=f'Path to CSV file (default: download to {DEFAULT_FILEPATH})')
        parser.add_argument('--batch-size', type=int, default=BATCH_SIZE, help='Batch size for bulk operations')
        parser.add_argument('--preview', action='store_true', help='Show preview of records only')
        parser.add_argument('--limit', type=int, default=10, help='Number of records to preview')
        parser.add_argument('--dry-run', action='store_true', help='Show what would be imported without importing')
        parser.add_argument('--no-filter', action='store_true', help='Skip filtering and deduplication')

    def handle(self, *args, **options):
        filepath = options['filepath']
        batch_size = options['batch_size']
        preview = options['preview']
        limit = options['limit']
        dry_run = options['dry_run']
        no_filter = options['no_filter']

        download_needed = filepath is None
        if download_needed:
            filepath = DEFAULT_FILEPATH

        start_time = datetime.datetime.now()
        write_log("----------------------------------------------------------------------------")
        write_log(f"[{start_time}] Starting hardware import")
        write_log(f"[{start_time}] CSV file: {filepath}")

        if download_needed:
            success, msg = download_csv(DPR_URL, filepath)
            if not success:
                write_log(f"[{datetime.datetime.now()}] ERROR: {msg}")
                ImportStatus.objects.create(success=False, message=msg, nb_entries_created=0)
                write_log("----------------------------------------------------------------------------")
                return
            write_log(f"[{datetime.datetime.now()}] {msg}")

        # Check if file exists
        if not Path(filepath).exists():
            error_msg = f"Import failed: CSV file not found: {filepath}"
            write_log(f"[{start_time}] ERROR: {error_msg}")
            ImportStatus.objects.create(success=False, message=error_msg, nb_entries_created=0)
            write_log("----------------------------------------------------------------------------")
            return

        # Check file size (minimum 10 MB)
        file_size_mb = Path(filepath).stat().st_size / (1024 * 1024)
        if file_size_mb < 10:
            error_msg = f"Import failed: CSV file is too small ({file_size_mb:.2f} MB). Minimum size: 10 MB."
            write_log(f"[{start_time}] ERROR: {error_msg}")
            ImportStatus.objects.create(success=False, message=error_msg, nb_entries_created=0)
            write_log("----------------------------------------------------------------------------")
            return
        
        write_log(f"[{start_time}] CSV file size: {file_size_mb:.2f} MB")

        if not no_filter:
            write_log(f"[{datetime.datetime.now()}] Filtering and deduplicating CSV...")
            unique_count = filter_and_deduplicate_csv(filepath)
            write_log(f"[{datetime.datetime.now()}] Filtered to {unique_count} unique hardware+alive records")
            write_log(f"[{datetime.datetime.now()}] Filtered CSV: {FILTERED_CSV}")

        # Calculate delta between CSV count and current table count
        current_table_count = Server.objects.count()
        write_log(f"[{datetime.datetime.now()}] Current Server table has {current_table_count} records")

        to_create, errors = [], []
        input_csv = FILTERED_CSV if not no_filter else filepath
        max_lines = 0

        with open(input_csv, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            raw_headers = reader.fieldnames or []

            for lineno, row in enumerate(reader, start=1):
                if lineno > limit and preview and not no_filter:
                    continue

                try:
                    mapped = {}
                    for csv_col, (model_field, transformer) in FIELD_MAP.items():
                        value = row.get(csv_col, '') or ''
                        mapped[model_field] = transformer(value) if transformer else value

                    extra = {col: row.get(col, 'EMPTY') for col in EXTRA_READ}
                    extra['PAMELA_IDRACIP'] = row.get('PAMELA_IDRACIP', 'EMPTY')
                    extra['SLOT-MANAGER__IDRAC_IP'] = row.get('SLOT-MANAGER__IDRAC_IP', 'EMPTY')
                    mapped = row_transform(mapped, {**row, **extra})

                    if not mapped.get('SERIAL'):
                        errors.append(f"Line {lineno}: SERIAL empty, ignored")
                        continue

                    if preview:
                        self.stdout.write(f"\n{'='*60}")
                        self.stdout.write(f"Record {lineno}:")
                        self.stdout.write(f"{'='*60}")
                        for k, v in mapped.items():
                            self.stdout.write(f"  {k}: {v}")
                        if lineno >= limit:
                            self.stdout.write(f"\n... (showing first {limit} records, use --limit N to change)")
                            break

                    to_create.append(ServerStaging(**mapped))

                except Exception as e:
                    errors.append(f"Line {lineno}: {e}")
                    log.debug("Line %d error", lineno, exc_info=True)

                max_lines = lineno

            if preview:
                self.stdout.write(f"\n\nTotal records in CSV: {max_lines}")
                self.stdout.write(f"Records to insert: {len(to_create)}")
                self.stdout.write(f"\nRun without --preview to actually import")
                return

            if dry_run:
                self.stdout.write(f"\nDRY RUN - Would import {len(to_create)} records")
                self.stdout.write(f"Errors: {len(errors)}")
                self.stdout.write(f"Run without --dry-run to actually import")
                return

            end_time = datetime.datetime.now()
            total_duration = end_time - start_time
            
            try:
                write_log(f"[{datetime.datetime.now()}] Recreating staging table...")
            
                # Calculate delta and check for anomalies
                csv_count = len(to_create)
                delta = csv_count - current_table_count
                delta_percent = (delta / current_table_count * 100) if current_table_count > 0 else 100.0
                
                write_log(f"[{datetime.datetime.now()}] CSV will add {csv_count} records")
                write_log(f"[{datetime.datetime.now()}] Delta from current table: {delta:+d} ({delta_percent:+.2f}%)")
                
                if abs(delta_percent) > 5:
                    error_msg = f"Discrepancies found: CSV has {csv_count} records, Server table has {current_table_count} records (delta: {delta:+d}, {delta_percent:+.2f}%). Import cancelled."
                    write_log(f"[{datetime.datetime.now()}] ERROR: {error_msg}")
                    ImportStatus.objects.create(success=False, message=error_msg, nb_entries_created=0)
                    write_log("----------------------------------------------------------------------------")
                    return
                
                recreate_staging_table()

                write_log(f"[{datetime.datetime.now()}] Bulk creating staging records ({len(to_create)} records)...")
                ServerStaging.objects.bulk_create(to_create, batch_size=batch_size)

                write_log(f"[{datetime.datetime.now()}] Swapping ServerStaging -> Server")
                with django_connection.cursor() as cursor:
                    cursor.execute("BEGIN;")
                    cursor.execute("DROP TABLE IF EXISTS hardware_serverbackup;")
                    cursor.execute("ALTER TABLE hardware_server RENAME TO hardware_serverbackup;")
                    cursor.execute("ALTER TABLE hardware_serverstaging RENAME TO hardware_server;")
                    cursor.execute("COMMIT;")

                inserted = len(to_create)
                msg = f"Import successful: {inserted} entries imported"
                ImportStatus.objects.create(success=True, message=msg, nb_entries_created=inserted)
                write_log(f"[{datetime.datetime.now()}] {msg}")
                write_log(f"[{datetime.datetime.now()}] Total duration for import: {total_duration}")
                write_log("----------------------------------------------------------------------------")

            except Exception as e:
                end_time = datetime.datetime.now()
                total_duration = end_time - start_time
                error_msg = f"Import failed: {str(e)}"
                write_log(f"[{datetime.datetime.now()}] ERROR: {error_msg}")
                write_log(f"[{datetime.datetime.now()}] Traceback: {traceback.format_exc()}")
                ImportStatus.objects.create(success=False, message=error_msg, nb_entries_created=0)
                write_log("----------------------------------------------------------------------------")
