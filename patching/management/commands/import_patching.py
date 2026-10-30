# python manage.py import_patching <filepath> [--force] [--dry-run]
#
# Loads the patching CSV into PatchingServer:
#   - skip if the file is identical to the last imported one (sha256)
#   - parse + clean in Python (null -> EMPTY / NULL, see import_config.py)
#   - one transaction: temp staging table, bulk load (COPY on Postgres), upsert
#   - upsert only writes new or changed rows; servers missing from the file are kept

import csv
import datetime
import hashlib
import io
import os
import time
import traceback
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from patching.import_config import (
    EMPTY_FIELDS, EMPTY_VALUE, FIELD_MAP, KEY_COLUMN, NULL_VALUES,
)
from patching.models import PatchingImportStatus, PatchingServer

LOG_PATH = '/data/DPR_DATA/logs/import_patching.log'
STAGING_TABLE = 'patching_staging'
LOCK_KEY = 742015  # arbitrary constant identifying this import for pg_advisory_lock
SEPARATOR = '-' * 76

qn = connection.ops.quote_name


def write_log(message):
    print(message)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, 'a') as f:
            f.write(message + '\n')
    except Exception as e:
        print(f'[write_log error] {e}')


def now_str():
    return str(datetime.datetime.now())


def file_sha256(path):
    """Return the sha256 hex digest of a file, read by chunks."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def normalize_value(column, raw):
    """Strip a raw CSV value; null-like values become EMPTY_VALUE or None depending on the column."""
    value = raw.strip()
    if value.lower() in NULL_VALUES:
        return EMPTY_VALUE if column in EMPTY_FIELDS else None
    return value


def parse_csv(path):
    """Read and clean the CSV. Return (records, stats) with one record (tuple) per unique key."""
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f, delimiter=';')
        header = [h.strip() for h in next(reader, [])]

        missing = [c for c in FIELD_MAP if c not in header]
        if missing:
            # A missing column would overwrite existing values with NULL: refuse
            raise ValueError(f'Missing columns in CSV header: {", ".join(missing)}')
        unknown = [c for c in header if c and c not in FIELD_MAP]

        index = {col: header.index(col) for col in FIELD_MAP}
        needed = max(index.values()) + 1
        key_pos = list(FIELD_MAP).index(KEY_COLUMN)

        by_key = {}
        stats = {'read': 0, 'duplicates': 0, 'no_key': 0, 'malformed': 0, 'unknown_columns': unknown}
        for line in reader:
            if not any(cell.strip() for cell in line):
                continue
            stats['read'] += 1
            # Trailing ';' adds an extra empty cell: ignored. Short lines are truncated rows: skipped.
            if len(line) < needed:
                stats['malformed'] += 1
                continue
            record = tuple(normalize_value(col, line[i]) for col, i in index.items())
            key = record[key_pos]
            if not key or key == EMPTY_VALUE:
                stats['no_key'] += 1
                continue
            if key in by_key:
                stats['duplicates'] += 1
            by_key[key] = record  # last occurrence wins

    return list(by_key.values()), stats


def copy_escape(value):
    """Escape a value for the Postgres COPY text format."""
    if value is None:
        return r'\N'
    return (value.replace('\\', '\\\\').replace('\t', '\\t')
                 .replace('\n', '\\n').replace('\r', '\\r'))


def create_staging(cursor, columns):
    """Create the temp staging table (dropped at COMMIT on Postgres)."""
    cols_def = ', '.join(f'{qn(c)} TEXT' for c in columns)
    if connection.vendor == 'postgresql':
        cursor.execute(f'CREATE TEMP TABLE {STAGING_TABLE} ({cols_def}) ON COMMIT DROP')
    else:
        cursor.execute(f'DROP TABLE IF EXISTS temp.{STAGING_TABLE}')
        cursor.execute(f'CREATE TEMP TABLE {STAGING_TABLE} ({cols_def})')


def load_staging(cursor, columns, records):
    """Bulk-load records into staging: COPY on Postgres, executemany elsewhere (dev SQLite)."""
    cols_sql = ', '.join(qn(c) for c in columns)
    if connection.vendor == 'postgresql':
        buf = io.StringIO()
        for rec in records:
            buf.write('\t'.join(copy_escape(v) for v in rec))
            buf.write('\n')
        buf.seek(0)
        sql = f'COPY {STAGING_TABLE} ({cols_sql}) FROM STDIN'
        raw = cursor.cursor
        if hasattr(raw, 'copy'):  # psycopg 3
            with raw.copy(sql) as copy:
                copy.write(buf.getvalue())
        else:  # psycopg2
            raw.copy_expert(sql, buf)
    else:
        placeholders = ', '.join(['%s'] * len(columns))
        cursor.executemany(f'INSERT INTO {STAGING_TABLE} ({cols_sql}) VALUES ({placeholders})', records)


def upsert(cursor, columns, key_column, now):
    """Insert new rows, update changed rows only. Return the number of rows written."""
    table = qn(PatchingServer._meta.db_table)
    created = qn(PatchingServer._meta.get_field('created_at').column)
    updated = qn(PatchingServer._meta.get_field('updated_at').column)
    value_cols = [c for c in columns if c != key_column]
    cols_sql = ', '.join(qn(c) for c in columns)
    set_sql = ', '.join(f'{qn(c)} = excluded.{qn(c)}' for c in value_cols)
    # NULL-safe comparison: IS DISTINCT FROM (Postgres) / IS NOT (SQLite)
    op = 'IS DISTINCT FROM' if connection.vendor == 'postgresql' else 'IS NOT'
    changed_sql = ' OR '.join(f'{table}.{qn(c)} {op} excluded.{qn(c)}' for c in value_cols)

    # "WHERE true" is required by SQLite to parse INSERT ... SELECT ... ON CONFLICT
    sql = (
        f'INSERT INTO {table} ({cols_sql}, {created}, {updated}) '
        f'SELECT {cols_sql}, %s, %s FROM {STAGING_TABLE} WHERE true '
        f'ON CONFLICT ({qn(key_column)}) DO UPDATE SET {set_sql}, {updated} = excluded.{updated} '
        f'WHERE {changed_sql}'
    )
    ts = connection.ops.adapt_datetimefield_value(now)
    cursor.execute(sql, [ts, ts])
    return cursor.rowcount


def acquire_lock(cursor):
    """Prevent two imports from running at the same time (Postgres only)."""
    if connection.vendor != 'postgresql':
        return True
    cursor.execute('SELECT pg_try_advisory_lock(%s)', [LOCK_KEY])
    return cursor.fetchone()[0]


def release_lock(cursor):
    if connection.vendor == 'postgresql':
        cursor.execute('SELECT pg_advisory_unlock(%s)', [LOCK_KEY])


class Command(BaseCommand):
    help = 'Import the patching CSV into PatchingServer (writes new/changed rows only)'

    def add_arguments(self, parser):
        parser.add_argument('filepath', help='Path to the patching CSV file')
        parser.add_argument('--force', action='store_true', help='Import even if the file is identical to the last one')
        parser.add_argument('--dry-run', action='store_true', help='Parse and report, do not write to DB')

    def handle(self, *args, **options):
        filepath = options['filepath']
        start = time.monotonic()

        write_log(SEPARATOR)
        write_log(f'[{now_str()}] Starting patching import: {filepath}')

        if not Path(filepath).exists():
            self.finish(start, filepath, '', success=False, message=f'File not found: {filepath}')
            return

        with connection.cursor() as cursor:
            if not acquire_lock(cursor):
                write_log(f'[{now_str()}] Another import is running, exit')
                write_log(SEPARATOR)
                return
            try:
                self.run_import(cursor, filepath, options, start)
            finally:
                release_lock(cursor)

    def run_import(self, cursor, filepath, options, start):
        file_hash = ''
        try:
            file_hash = file_sha256(filepath)
            last = PatchingImportStatus.objects.filter(success=True).exclude(file_hash='').first()
            if last and last.file_hash == file_hash and not options['force'] and not options['dry_run']:
                self.finish(start, filepath, file_hash, success=True, skipped=True,
                            message='File identical to the last import, nothing to do')
                return

            records, stats = parse_csv(filepath)
            write_log(f'[{now_str()}] Parsed {stats["read"]} rows -> {len(records)} unique servers '
                      f'({stats["duplicates"]} duplicates, {stats["no_key"]} without servername, '
                      f'{stats["malformed"]} malformed)')
            if stats['unknown_columns']:
                write_log(f'[{now_str()}] WARNING: unmapped CSV columns ignored: '
                          f'{", ".join(stats["unknown_columns"])}')
            if not records:
                raise ValueError('No valid row in file')

            if options['dry_run']:
                write_log(f'[{now_str()}] DRY RUN: nothing written')
                write_log(SEPARATOR)
                return

            columns = [PatchingServer._meta.get_field(f).column for f in FIELD_MAP.values()]
            key_column = PatchingServer._meta.get_field(FIELD_MAP[KEY_COLUMN]).column

            with transaction.atomic():
                count_before = PatchingServer.objects.count()
                create_staging(cursor, columns)
                load_staging(cursor, columns, records)
                written = upsert(cursor, columns, key_column, timezone.now())
                if connection.vendor != 'postgresql':
                    cursor.execute(f'DROP TABLE IF EXISTS temp.{STAGING_TABLE}')
                inserted = PatchingServer.objects.count() - count_before

            self.finish(start, filepath, file_hash, success=True,
                        nb_rows_read=stats['read'],
                        nb_inserted=inserted,
                        nb_updated=written - inserted,
                        nb_unchanged=len(records) - written)

        except Exception as e:
            write_log(f'[{now_str()}] ERROR: {e}\n{traceback.format_exc()}')
            self.finish(start, filepath, file_hash, success=False, message=f'Import failed: {e}')

    def finish(self, start, filepath, file_hash, success, message='', **counts):
        """Log the outcome and record a PatchingImportStatus row."""
        duration = time.monotonic() - start
        if success and not message:
            message = (f'Import successful in {duration:.1f}s: {counts.get("nb_inserted", 0)} inserted, '
                       f'{counts.get("nb_updated", 0)} updated, {counts.get("nb_unchanged", 0)} unchanged')
        write_log(f'[{now_str()}] {"" if success else "ERROR: "}{message}')
        PatchingImportStatus.objects.create(
            success=success,
            skipped=counts.pop('skipped', False),
            file_name=os.path.basename(filepath),
            file_hash=file_hash,
            duration_seconds=round(duration, 2),
            message=message,
            **counts,
        )
        write_log(SEPARATOR)
