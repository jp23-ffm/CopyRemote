# python manage.py import_hardware_csv [filepath]

import csv
import datetime
import logging
import os
import ssl
import traceback
from collections import Counter
from pathlib import Path

import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from requests.adapters import HTTPAdapter

from hardware.models import Server, ImportStatus
from .import_hardware_config import FIELD_MAP, EXTRA_READ, row_transform

log = logging.getLogger(__name__)
BATCH_SIZE = 500
DELTA_THRESHOLD = 5  # percent
LOG_PATH = '/data/DPR_DATA/logs/import_apm_hardware.log'
FILTERED_CSV = '/data/DPR_DATA/apm_filtered.csv'
DEFAULT_FILEPATH = '/data/DPR_DATA/apm_hardware.csv'
DPR_URL = 'https://dpr-backend.group.echonet/export/hardware/servers?format=csv'


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
        with open(LOG_PATH, 'a') as f:
            f.write(message + '\n')
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
    """Filter CSV for hardware+alive, deduplicate by all relevant fields, add COUNT."""
    relevant_columns = [
        'Serial number', 'Technology Standard Asset type', 'Live Status', 'AREA', 'COUNTRY', 'DATACENTER', 'Vendor', 'Model',
        'WARRANTY_ACTIVE', 'WARRANTY_ACTUAL_SUPPLIER', 'WARRANTY_INITIAL_PROVIDER_NAME', 'WARRANTY_INITIAL_START_DATE', 'WARRANTY_INITIAL_END_DATE',
        'WARRANTY_EXTENSION_PROVIDER_NAME', 'WARRANTY_EXTENSION_START_DATE', 'WARRANTY_EXTENSION_END_DATE', 'WARRANTY_SUPPORT_LEVEL',
        'WARRANTY_TO_STOP', 'SERVER IP', 'OS SHORTNAME', 'SHORT ENVIRONMENT', 'HW asset used for', 'HW host', 'PROVIDER', 'PAMELA__IDRACIP', 'SLOT-MANAGER__IDRAC_IP'
    ]

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
                values = tuple(row.get(col, '') for col in relevant_columns)
                if values not in seen:
                    seen.add(values)
                    temp_rows.append({col: row.get(col, '') for col in relevant_columns})

    with open(temp_file, 'w', newline='', encoding='utf-8') as f_out:
        writer = csv.DictWriter(f_out, fieldnames=relevant_columns)
        writer.writeheader()
        writer.writerows(temp_rows)

    serial_counts = Counter()
    with open(temp_file, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            serial = row.get('Serial number', '').strip()
            if serial:
                serial_counts[serial] += 1

    final_rows = []
    with open(temp_file, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            serial = row.get('Serial number', '').strip()
            if serial:
                row_dict = {col: row.get(col, '') for col in relevant_columns}
                row_dict['COUNT'] = str(serial_counts[serial])
                final_rows.append(row_dict)

    with open(FILTERED_CSV, 'w', newline='', encoding='utf-8') as f_out:
        writer = csv.DictWriter(f_out, fieldnames=relevant_columns + ['COUNT'])
        writer.writeheader()
        writer.writerows(final_rows)

    if os.path.exists(temp_file):
        os.remove(temp_file)

    return len(final_rows)


class Command(BaseCommand):
    help = 'Import hardware servers from CSV file'

    def add_arguments(self, parser):
        parser.add_argument('filepath', nargs='?', default=None,
                            help=f'Path to CSV file (default: download to {DEFAULT_FILEPATH})')
        parser.add_argument('--batch-size', type=int, default=BATCH_SIZE, help='Batch size for bulk_create')
        parser.add_argument('--preview', action='store_true', help='Show preview of records only')
        parser.add_argument('--limit', type=int, default=10, help='Number of records to preview')
        parser.add_argument('--dry-run', action='store_true', help='Parse but do not write to DB')
        parser.add_argument('--no-filter', action='store_true', help='Skip filtering and deduplication')
        parser.add_argument('--no-delta', action='store_true', help='Skip delta check')

    def handle(self, *args, **options):
        filepath = options['filepath']
        batch_size = options['batch_size']
        preview = options['preview']
        limit = options['limit']
        dry_run = options['dry_run']
        no_filter = options['no_filter']
        no_delta = options['no_delta']

        download_needed = filepath is None
        if download_needed:
            filepath = DEFAULT_FILEPATH

        start = datetime.datetime.now()
        write_log('----------------------------------------------------------------------------')
        write_log(f'[{start}] Starting hardware import: {filepath}')

        if download_needed:
            success, msg = download_csv(DPR_URL, filepath)
            if not success:
                write_log(f'[{datetime.datetime.now()}] ERROR: {msg}')
                ImportStatus.objects.create(success=False, message=msg, nb_entries_created=0)
                write_log('----------------------------------------------------------------------------')
                return
            write_log(f'[{datetime.datetime.now()}] {msg}')

        if not Path(filepath).exists():
            msg = f'File not found: {filepath}'
            write_log(f'[{datetime.datetime.now()}] ERROR: {msg}')
            ImportStatus.objects.create(success=False, message=msg, nb_entries_created=0)
            write_log('----------------------------------------------------------------------------')
            return

        file_size_mb = Path(filepath).stat().st_size / (1024 * 1024)
        if file_size_mb < 10:
            msg = f'CSV file too small ({file_size_mb:.2f} MB), minimum 10 MB'
            write_log(f'[{datetime.datetime.now()}] ERROR: {msg}')
            ImportStatus.objects.create(success=False, message=msg, nb_entries_created=0)
            write_log('----------------------------------------------------------------------------')
            return

        write_log(f'[{datetime.datetime.now()}] CSV file size: {file_size_mb:.2f} MB')

        if not no_filter:
            write_log(f'[{datetime.datetime.now()}] Filtering and deduplicating CSV...')
            unique_count = filter_and_deduplicate_csv(filepath)
            write_log(f'[{datetime.datetime.now()}] {unique_count} unique hardware+alive records → {FILTERED_CSV}')

        input_csv = FILTERED_CSV if not no_filter else filepath
        to_create = []
        errors = []

        with open(input_csv, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for lineno, row in enumerate(reader, start=1):
                if preview and lineno > limit:
                    break
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
                        errors.append(f'Line {lineno}: SERIAL empty, skipped')
                        continue

                    if preview:
                        self.stdout.write(f"\n{'='*60}\nRecord {lineno}:\n{'='*60}")
                        for k, v in mapped.items():
                            self.stdout.write(f'  {k}: {v}')
                        continue

                    to_create.append(Server(**mapped))

                except Exception as e:
                    errors.append(f'Line {lineno}: {e}')
                    log.debug('Line %d error', lineno, exc_info=True)

        if preview:
            self.stdout.write(f'\nPreview done ({min(lineno, limit)} rows shown). Run without --preview to import.')
            return

        write_log(f'[{datetime.datetime.now()}] Parsed {len(to_create)} rows ({len(errors)} errors)')

        if dry_run:
            write_log(f'[{datetime.datetime.now()}] DRY RUN — would insert {len(to_create)} rows')
            return

        if not no_delta:
            current_count = Server.objects.count()
            write_log(f'[{datetime.datetime.now()}] Current Server table: {current_count} records')
            if current_count > 0:
                delta_pct = abs(len(to_create) - current_count) / current_count * 100
                if delta_pct > DELTA_THRESHOLD:
                    msg = (f'Delta check failed: current={current_count}, new={len(to_create)}, '
                           f'delta={delta_pct:.1f}% > {DELTA_THRESHOLD}%. Use --no-delta to force.')
                    write_log(f'[{datetime.datetime.now()}] ERROR: {msg}')
                    ImportStatus.objects.create(success=False, message=msg, nb_entries_created=0)
                    write_log('----------------------------------------------------------------------------')
                    return

        try:
            with transaction.atomic():
                write_log(f'[{datetime.datetime.now()}] Deleting existing records...')
                Server.objects.all().delete()
                write_log(f'[{datetime.datetime.now()}] Inserting {len(to_create)} records...')
                inserted = 0
                for i in range(0, len(to_create), batch_size):
                    Server.objects.bulk_create(to_create[i:i + batch_size])
                    inserted += len(to_create[i:i + batch_size])
                    if inserted % 10000 == 0:
                        print(f'  {inserted}/{len(to_create)} rows inserted...')

            duration = datetime.datetime.now() - start
            msg = f'Import successful: {len(to_create)} entries imported in {duration}'
            write_log(f'[{datetime.datetime.now()}] {msg}')
            ImportStatus.objects.create(success=True, message=msg, nb_entries_created=len(to_create))
            if errors:
                warn = f'{len(errors)} parse errors (first 5): ' + ' | '.join(errors[:5])
                write_log(f'[{datetime.datetime.now()}] WARNING: {warn}')
            write_log('----------------------------------------------------------------------------')

        except Exception as e:
            msg = f'Import failed: {e}'
            write_log(f'[{datetime.datetime.now()}] ERROR: {msg}\n{traceback.format_exc()}')
            ImportStatus.objects.create(success=False, message=msg, nb_entries_created=0)
            write_log('----------------------------------------------------------------------------')
