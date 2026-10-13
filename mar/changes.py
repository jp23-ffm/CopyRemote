"""
changes.py
----------
Build a flat summary of ServerUnique changes from global_history, enriched with
the real values stored in action_during_lp_history / original_action_during_lp_history.

Shared by the export_bc_changes management command and the changes_summary view.
Servers are read in keyset-paginated chunks (hostname > last) so that memory and
query size stay bounded on both SQLite and PostgreSQL, without server-side cursors.
"""

import csv
import datetime
import json
import re

from .models import ServerUnique


TRACKED_FIELDS = [
    'priority_asset',
    'in_live_play',
    'action_during_lp',
    'original_action_during_lp',
    'cluster',
    'cluster_type',
]

# Fields whose real values live in a separate text history: "[YYYY-MM-DD HH:MM:SS - user] text"
TEXT_HISTORY_FIELDS = {
    'action_during_lp': 'action_during_lp_history',
    'original_action_during_lp': 'original_action_during_lp_history',
}

SOURCES = [
    'Single Edit',
    'Bulk Edit',
    'CSV Import',
    'Application CSV Import',
    'BC Rules',
    'DR Reset',
    '(history only)',
]

HEADERS = ['date', 'user', 'source', 'hostname'] + TRACKED_FIELDS + ['other_changes']

DEFAULT_CHUNK_SIZE = 500

HISTORY_LINE_RE = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - (.*?)\]\s?(.*)$')
DATE_FMT = '%Y-%m-%d %H:%M:%S'
NOT_MODIFIED = 'Not set or not modified'
# Text history and global_history timestamps are computed separately and can differ by a second or two
MATCH_TOLERANCE = datetime.timedelta(seconds=5)


def clean_value(value):
    """Flatten a value to a single CSV-safe line."""
    if value is None:
        return ''
    text = str(value)
    text = text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
    return ' '.join(text.split())


def parse_date(value):
    """Parse a history timestamp, return None if malformed."""
    try:
        return datetime.datetime.strptime(value, DATE_FMT)
    except (TypeError, ValueError):
        return None


def date_bounds(d_from, d_to):
    """Return (start, end) datetimes covering both dates inclusively."""
    return (datetime.datetime.combine(d_from, datetime.time.min),
            datetime.datetime.combine(d_to, datetime.time.max))


def parse_text_history(text):
    """Parse a *_history text field into a list of {date, user, text, used} dicts."""
    entries = []
    for line in (text or '').splitlines():
        m = HISTORY_LINE_RE.match(line)
        if m:
            entries.append({
                'date': parse_date(m.group(1)),
                'user': m.group(2),
                'text': m.group(3),
                'used': False,
            })
        elif entries and line.strip():
            # Continuation line of a multi-line value
            entries[-1]['text'] += ' ' + line.strip()
    return [e for e in entries if e['date']]


def find_text_entry(entries, date, user):
    """Return the closest unused text history entry for the same user within tolerance."""
    best = None
    for e in entries:
        if e['used'] or e['user'] != user:
            continue
        delta = abs(e['date'] - date)
        if delta <= MATCH_TOLERANCE and (best is None or delta < abs(best['date'] - date)):
            best = e
    if best:
        best['used'] = True
    return best


def format_change(change):
    """Return 'old -> new', or '' when the change is a no-op."""
    if not isinstance(change, dict):
        return clean_value(change)
    if 'old' in change or 'new' in change:
        old, new = change.get('old'), change.get('new')
        if new == NOT_MODIFIED or old == new:
            return ''
        return f"{clean_value(old)} -> {clean_value(new)}"
    info = change.get('info', '')
    if NOT_MODIFIED in str(info):
        return ''
    return clean_value(info)


def rows_for_server(hostname, global_history, text_histories_raw, start, end):
    """Build change rows for one server within [start, end], newest first."""
    if isinstance(global_history, str):
        try:
            global_history = json.loads(global_history)
        except ValueError:
            global_history = []
    if not isinstance(global_history, list):
        global_history = []

    text_histories = {
        field: [e for e in parse_text_history(text_histories_raw.get(field)) if start <= e['date'] <= end]
        for field in TEXT_HISTORY_FIELDS
    }

    rows = []
    for entry in global_history:
        if not isinstance(entry, dict):
            continue
        date = parse_date(entry.get('date'))
        if not date or not (start <= date <= end):
            continue
        user = entry.get('user', '')
        row = dict.fromkeys(HEADERS, '')
        row.update(date=entry['date'], user=user, source=entry.get('fromsource', ''), hostname=hostname)

        others = []
        for field, change in (entry.get('changes') or {}).items():
            value = format_change(change)
            if field in TEXT_HISTORY_FIELDS and value and not (isinstance(change, dict) and 'old' in change):
                # Value is only "check its history": fetch the real text
                match = find_text_entry(text_histories[field], date, user)
                if match:
                    value = clean_value(match['text'])
            if not value:
                continue
            if field in TRACKED_FIELDS:
                row[field] = value
            else:
                others.append(f"{field}: {value}")
        row['other_changes'] = ' | '.join(others)

        if any(row[f] for f in TRACKED_FIELDS) or row['other_changes']:
            rows.append(row)

    # Text history lines with no matching global_history entry (old data, wiped history...)
    for field, entries in text_histories.items():
        for e in entries:
            if e['used']:
                continue
            row = dict.fromkeys(HEADERS, '')
            row.update(date=e['date'].strftime(DATE_FMT), user=e['user'],
                       source='(history only)', hostname=hostname)
            row[field] = clean_value(e['text'])
            rows.append(row)

    rows.sort(key=lambda r: r['date'], reverse=True)
    return rows


def iter_server_chunks(hostname=None, chunk_size=DEFAULT_CHUNK_SIZE):
    """Yield lists of server tuples, keyset-paginated on the unique hostname column."""
    qs = ServerUnique.objects.order_by('hostname')
    if hostname:
        qs = qs.filter(hostname__icontains=hostname)
    columns = ['hostname', 'global_history'] + list(TEXT_HISTORY_FIELDS.values())

    last = None
    while True:
        page = qs.filter(hostname__gt=last) if last is not None else qs
        chunk = list(page.values_list(*columns)[:chunk_size])
        if not chunk:
            return
        yield chunk
        last = chunk[-1][0]


def iter_change_row_chunks(d_from, d_to, hostname=None, user=None, source=None,
                           chunk_size=DEFAULT_CHUNK_SIZE):
    """Yield lists of change rows, one list per server chunk, ordered by hostname then date desc."""
    start, end = date_bounds(d_from, d_to)
    user = (user or '').strip().lower()

    for chunk in iter_server_chunks(hostname, chunk_size):
        rows = []
        for host, gh, *texts in chunk:
            raw = dict(zip(TEXT_HISTORY_FIELDS.keys(), texts))
            for row in rows_for_server(host, gh, raw, start, end):
                if user and user not in row['user'].lower():
                    continue
                if source and row['source'] != source:
                    continue
                rows.append(row)
        yield rows


class _Echo:
    """File-like object whose write() returns the value, for streaming csv.writer output."""

    def write(self, value):
        return value


def iter_csv_lines(row_chunks):
    """Yield CSV text (BOM + header, then one block per chunk) for StreamingHttpResponse or a file."""
    writer = csv.DictWriter(_Echo(), fieldnames=HEADERS, delimiter=';')
    yield '﻿' + writer.writeheader()
    for rows in row_chunks:
        if rows:
            yield ''.join(writer.writerow(r) for r in rows)
