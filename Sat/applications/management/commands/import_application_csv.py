# python manage.py import_application_csv [filepath]

import csv
import datetime
import logging
import os
import ssl
import traceback
from pathlib import Path

import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from requests.adapters import HTTPAdapter

from applications.models import Application, ImportStatus

log = logging.getLogger(__name__)
BATCH_SIZE = 500
DELTA_THRESHOLD = 5  # percent
LOG_PATH = '/data/DPR_DATA/logs/import_applications.log'
DEFAULT_FILEPATH = '/data/DPR_DATA/dpr_saphir_application.csv'
# TODO: confirm exact endpoint with the DPR team — inferred from the hardware
# export URL pattern (https://dpr-backend.group.echonet/export/hardware/servers?format=csv)
DPR_URL = 'https://dpr-backend.group.echonet/export/application/list?format=csv'

INVALID_AUID_VALUES = {'', 'MISSING', 'N/A', 'UNKNOWN', 'NULL', '-'}


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


class Command(BaseCommand):
    help = 'Import applications from CSV file (chimera_dpr_saphir_application.csv)'

    def add_arguments(self, parser):
        parser.add_argument('filepath', nargs='?', default=None,
                            help=f'Path to CSV file (default: download to {DEFAULT_FILEPATH})')
        parser.add_argument('--batch-size', type=int, default=BATCH_SIZE, help='Batch size for bulk_create')
        parser.add_argument('--preview', action='store_true', help='Show preview of records only')
        parser.add_argument('--limit', type=int, default=10, help='Number of records to preview')
        parser.add_argument('--dry-run', action='store_true', help='Parse but do not write to DB')
        parser.add_argument('--no-delta', action='store_true', help='Skip delta check')

    def handle(self, *args, **options):
        filepath = options['filepath']
        batch_size = options['batch_size']
        preview = options['preview']
        limit = options['limit']
        dry_run = options['dry_run']
        no_delta = options['no_delta']

        download_needed = filepath is None
        if download_needed:
            filepath = DEFAULT_FILEPATH

        start = datetime.datetime.now()
        write_log('----------------------------------------------------------------------------')
        write_log(f'[{start}] Starting applications import: {filepath}')

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

        to_create = []
        errors = []
        skipped_null_auid = 0

        with open(filepath, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=';')
            for lineno, row in enumerate(reader, start=1):
                if preview and lineno > limit:
                    break
                try:
                    auid = (row.get('Application AUID') or '').strip()

                    if auid.upper() in INVALID_AUID_VALUES:
                        skipped_null_auid += 1
                        continue

                    manager_email = (row.get('Application Manager email') or '').strip()
                    it_cluster = (row.get('IT Cluster') or '').strip()

                    mapped = {
                        'APPLICATION_AUID': auid,
                        'APPLICATION_MANAGER_EMAIL': manager_email or None,
                        'IT_CLUSTER': it_cluster or None,
                    }

                    if preview:
                        self.stdout.write(f"\n{'='*60}\nRecord {lineno}:\n{'='*60}")
                        for k, v in mapped.items():
                            self.stdout.write(f'  {k}: {v}')
                        continue

                    to_create.append(Application(**mapped))

                except Exception as e:
                    errors.append(f'Line {lineno}: {e}')
                    log.debug('Line %d error', lineno, exc_info=True)

        if preview:
            self.stdout.write(f'\nPreview done. Run without --preview to import.')
            return

        write_log(f'[{datetime.datetime.now()}] Parsed {len(to_create)} rows '
                  f'({skipped_null_auid} skipped for missing AUID, {len(errors)} errors)')

        if dry_run:
            write_log(f'[{datetime.datetime.now()}] DRY RUN — would insert {len(to_create)} rows')
            return

        if not no_delta:
            current_count = Application.objects.count()
            write_log(f'[{datetime.datetime.now()}] Current Application table: {current_count} records')
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
                Application.objects.all().delete()
                write_log(f'[{datetime.datetime.now()}] Inserting {len(to_create)} records...')
                inserted = 0
                for i in range(0, len(to_create), batch_size):
                    Application.objects.bulk_create(to_create[i:i + batch_size])
                    inserted += len(to_create[i:i + batch_size])

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
