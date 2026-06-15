# python manage.py import_storage_csv [filepath]

import csv
import datetime
import traceback
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import transaction
from storage.models import StorageShare, StorageImportStatus

BATCH_SIZE = 1000
DELTA_THRESHOLD = 10  # percent
DEFAULT_FILEPATH = '/data/DPR_DATA/apm_storage_shares.csv'

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
        parser.add_argument('filepath', nargs='?', default=DEFAULT_FILEPATH,
                            help=f'Path to the storage CSV file (default: {DEFAULT_FILEPATH})')
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

        start = datetime.datetime.now()
        self.stdout.write(f'[{start}] Starting storage (shares) import: {filepath}')

        if not Path(filepath).exists():
            is_default = (filepath == DEFAULT_FILEPATH)
            msg = f'File not found: {filepath}' + (' (default path)' if is_default else '')
            StorageImportStatus.objects.create(source='share', success=False, message=msg)
            self.stderr.write(self.style.ERROR(msg))
            return

        to_create = []
        errors = []

        with open(filepath, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for lineno, row in enumerate(reader, start=1):
                # Strip all keys and values
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

        self.stdout.write(f'Parsed {len(to_create)} rows ({len(errors)} errors)')

        if dry_run:
            self.stdout.write(self.style.WARNING(f'DRY RUN — would insert {len(to_create)} rows'))
            return

        # Delta check
        if not no_delta:
            current_count = StorageShare.objects.count()
            if current_count > 0:
                delta_pct = abs(len(to_create) - current_count) / current_count * 100
                if delta_pct > DELTA_THRESHOLD:
                    msg = (f'Delta check failed: current={current_count}, new={len(to_create)}, '
                           f'delta={delta_pct:.1f}% > {DELTA_THRESHOLD}%. Use --no-delta to force.')
                    StorageImportStatus.objects.create(source='share', success=False, message=msg)
                    self.stderr.write(self.style.ERROR(msg))
                    return

        try:
            with transaction.atomic():
                StorageShare.objects.all().delete()
                for i in range(0, len(to_create), batch_size):
                    StorageShare.objects.bulk_create(to_create[i:i + batch_size])

            duration = datetime.datetime.now() - start
            msg = f'Import successful: {len(to_create)} shares imported in {duration}'
            StorageImportStatus.objects.create(source='share', success=True, message=msg, nb_entries_created=len(to_create))
            self.stdout.write(self.style.SUCCESS(msg))
            if errors:
                self.stdout.write(self.style.WARNING(f'{len(errors)} parse errors (first 5):'))
                for e in errors[:5]:
                    self.stdout.write(f'  {e}')

        except Exception as e:
            msg = f'Import failed: {e}'
            StorageImportStatus.objects.create(source='share', success=False, message=msg)
            self.stderr.write(self.style.ERROR(f'{msg}\n{traceback.format_exc()}'))
