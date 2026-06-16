# python manage.py import_storage_csv [filepath]

import csv
import datetime
import os
import traceback
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import transaction
from storage.models import StorageShare, StorageImportStatus

import ssl
import requests
from requests.adapters import HTTPAdapter

BATCH_SIZE = 1000
DELTA_THRESHOLD = 10  # percent
DEFAULT_FILEPATH = '/data/DPR_DATA/apm_storage_shares.csv'
DPR_URL = 'https://dpr-backend.group.echonet/export/storage/shares?format=csv'
LOG_PATH = '/data/DPR_DATA/logs/import_storage_shares.log'


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

# CSV column name → model field name
FIELD_MAP = {
    'ID': 'ID',
    'PROVIDER': 'PROVIDER',
    'CLUSTER': 'CLUSTER',
    'FILER': 'FILER',
    'NAME': 'SHARE_NAME',
    'SHARE REAL NAME': 'SHARE_REAL_NAME',
    'SHARE PATH': 'SHARE_PATH',
    'VOLUME': 'VOLUME',
    'PROTOCOL': 'PROTOCOL',
    'IP ADDRESS': 'IP_ADDRESS',
    'UUID': 'UUID',
    'CONSUMER TYPE': 'CONSUMER_TYPE',
    'ALLOCATION': 'ALLOCATION',
    'USAGE': 'USAGE',
    'APPLICATION NAME': 'APPLICATION_NAME',
    'BAM VALUE': 'BAM_VALUE',
    'APPLICATION_AUID_VALUE': 'APPLICATION_AUID_VALUE',
    'ENVIRONMENT': 'ENVIRONMENT',
    'IS OPEN': 'IS_OPEN',
    'OPEN SHARE EXCEPTION': 'OPEN_SHARE_EXCEPTION',
    'REGION': 'REGION',
    'COUNTRY': 'COUNTRY',
    'SCOPE': 'SCOPE',
    'ECOSYSTEM': 'ECOSYSTEM',
    'VITAL APPLICATION': 'VITAL_APPLICATION',
    'IT CLUSTER': 'IT_CLUSTER',
    'IT SUB CLUSTER': 'IT_SUBCLUSTER',
    'IN_NAS_REF': 'IN_NAS_REF',
    'IN_NETAPP_SCANNER': 'IN_NETAPP_SCANNER',
    'IN_NAS_CAPSULE': 'IN_NAS_CAPSULE',
}

EMPTY_VALUES = {'', 'N/A', 'NA', 'NULL', 'NONE', '-'}


def normalize(value):
    """Strip, uppercase, and replace empty/N/A values with 'EMPTY'."""
    v = value.strip().upper() if value else ''
    return 'EMPTY' if v in EMPTY_VALUES else v


class Command(BaseCommand):
    help = 'Import NAS shares from CSV into StorageShare'

    def add_arguments(self, parser):
        parser.add_argument('filepath', nargs='?', default=None,
                            help=f'Path to the storage CSV file (default: download to {DEFAULT_FILEPATH})')
        parser.add_argument('--batch-size', type=int, default=BATCH_SIZE)
        parser.add_argument('--dry-run', action='store_true', help='Parse but do not write to DB')
        parser.add_argument('--preview', action='store_true', help='Print first 10 rows and exit')
        parser.add_argument('--limit', type=int, default=10, help='Number of rows for --preview')
        parser.add_argument('--no-delta', action='store_true', help='Skip delta check')

    def handle(self, *args, **options):
        filepath = options['filepath']
        batch_size = options['batch_size']
        dry_run = options['dry_run']
        preview = options['preview']
        limit = options['limit']
        no_delta = options['no_delta']

        download_needed = filepath is None
        if download_needed:
            filepath = DEFAULT_FILEPATH

        start = datetime.datetime.now()
        write_log(f'[{start}] Starting storage (shares) import: {filepath}')

        if download_needed:
            success, msg = download_csv(DPR_URL, filepath)
            if not success:
                write_log(f'[{datetime.datetime.now()}] ERROR: {msg}')
                StorageImportStatus.objects.create(source='share', success=False, message=msg)
                return
            write_log(f'[{datetime.datetime.now()}] {msg}')

        if not Path(filepath).exists():
            msg = f'File not found: {filepath}'
            write_log(f'[{datetime.datetime.now()}] ERROR: {msg}')
            StorageImportStatus.objects.create(source='share', success=False, message=msg)
            return

        to_create = []
        errors = []

        with open(filepath, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for lineno, row in enumerate(reader, start=1):
                row = {k.strip(): v.strip() for k, v in row.items()}

                if preview and lineno > limit:
                    break

                try:
                    mapped = {model_field: normalize(row.get(csv_col, ''))
                              for csv_col, model_field in FIELD_MAP.items()}

                    if not mapped.get('ID'):
                        errors.append(f'Line {lineno}: ID empty, skipped')
                        continue

                    if preview:
                        self.stdout.write(f'\n--- Row {lineno} ---')
                        for k, v in mapped.items():
                            self.stdout.write(f'  {k}: {v}')
                        continue

                    to_create.append(StorageShare(**mapped))

                except Exception as e:
                    errors.append(f'Line {lineno}: {e}')

        if preview:
            self.stdout.write(f'\nPreview done ({min(lineno, limit)} rows shown). Run without --preview to import.')
            return

        write_log(f'[{datetime.datetime.now()}] Parsed {len(to_create)} rows ({len(errors)} errors)')

        if dry_run:
            write_log(f'[{datetime.datetime.now()}] DRY RUN — would insert {len(to_create)} rows')
            return

        # Delta check
        if not no_delta:
            current_count = StorageShare.objects.count()
            if current_count > 0:
                delta_pct = abs(len(to_create) - current_count) / current_count * 100
                if delta_pct > DELTA_THRESHOLD:
                    msg = (f'Delta check failed: current={current_count}, new={len(to_create)}, '
                           f'delta={delta_pct:.1f}% > {DELTA_THRESHOLD}%. Use --no-delta to force.')
                    write_log(f'[{datetime.datetime.now()}] ERROR: {msg}')
                    StorageImportStatus.objects.create(source='share', success=False, message=msg)
                    return

        try:
            with transaction.atomic():
                StorageShare.objects.all().delete()
                inserted = 0
                for i in range(0, len(to_create), batch_size):
                    StorageShare.objects.bulk_create(to_create[i:i + batch_size])
                    inserted += len(to_create[i:i + batch_size])
                    if inserted % 10000 == 0:
                        print(f'  {inserted}/{len(to_create)} rows inserted...')

            duration = datetime.datetime.now() - start
            msg = f'Import successful: {len(to_create)} shares imported in {duration}'
            write_log(f'[{datetime.datetime.now()}] {msg}')
            StorageImportStatus.objects.create(source='share', success=True, message=msg, nb_entries_created=len(to_create))
            if errors:
                warn = f'{len(errors)} parse errors (first 5): ' + ' | '.join(errors[:5])
                write_log(f'[{datetime.datetime.now()}] WARNING: {warn}')

        except Exception as e:
            msg = f'Import failed: {e}'
            tb = traceback.format_exc()
            write_log(f'[{datetime.datetime.now()}] ERROR: {msg}\n{tb}')
            StorageImportStatus.objects.create(source='share', success=False, message=msg)
