# pamela_db_utils.py
#
# Minimal MSSQL query runner for analyze_pamela_discrepancies.py — same connection pattern as
# the prod db_utils.py (pyodbc, MSSQL_HOST/DB/USER/PASSWORD/DRIVER env vars), pointed at
# pamela_report_queries.json instead of report_queries.json. Kept as its own small module
# rather than reusing db_utils.py directly: db_utils.py isn't part of this repo (it lives in
# the run_daily_report.py pipeline, which populates DailyPamelaDBSummary — a separate,
# already-working pipeline this command must not touch), and its QUERIES_PATH is hardcoded to
# its own report_queries.json. Deliberately uses plain os.environ instead of django-environ
# (used in the shown db_utils.py) to avoid adding a new dependency to this repo just for this
# — same env var names, so the same .env entries work for both if they ever run side by side.

import os

import pyodbc

from discrepancies.pamela_sync import load_pamela_report_queries


def _env(name, default=''):
    return os.environ.get(name, default)


def _connection_string():
    driver = _env('MSSQL_DRIVER', 'ODBC Driver 18 for SQL Server')
    server = _env('MSSQL_HOST')
    database = _env('MSSQL_DB')
    username = _env('MSSQL_USER')
    password = _env('MSSQL_PASSWORD')
    return (
        f"DRIVER={driver};SERVER={server};DATABASE={database};"
        f"UID={username};PWD={password};Encrypt=yes;TrustServerCertificate=yes;"
    ), database


def test_connection():
    """Test the MS SQL Server connection. Returns (success: bool, message: str)."""
    server = _env('MSSQL_HOST')
    database = _env('MSSQL_DB')
    username = _env('MSSQL_USER')
    password = _env('MSSQL_PASSWORD')

    if not all([server, database, username, password]):
        return False, 'Missing connection parameters (MSSQL_HOST, MSSQL_DB, MSSQL_USER, MSSQL_PASSWORD)'

    conn_str, _ = _connection_string()
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        version = cursor.fetchone()[0]
        conn.close()
        return True, f'Connected successfully! SQL Server: {version[:100]}...'
    except pyodbc.Error as e:
        return False, f'Connection failed: {e}'


def get_missing_servers(report_name, target_date):
    """
    Runs the pamela_report_queries.json query for one report (missing_AD, missing_ADDM, ...)
    on one date. Returns a list of {'SERVER_ID', 'techfamily', 'area'} dicts.

    Raises RuntimeError on missing query config or connection/query failure — the caller
    (analyze_pamela_discrepancies) is responsible for catching it and logging via
    PamelaImportStatus, same convention as analyze_discrepancies's own error handling.
    """
    queries = load_pamela_report_queries()
    report_config = queries.get(report_name)
    if not report_config:
        raise RuntimeError(f"No query configured for report '{report_name}' in pamela_report_queries.json")

    conn_str, database = _connection_string()
    sql = '\n'.join(report_config['query']).format(database=database)

    conn = pyodbc.connect(conn_str)
    try:
        cursor = conn.cursor()
        cursor.execute(sql, [target_date, report_name])
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()

    return [
        {
            'SERVER_ID': row.get('SERVER_ID'),
            'techfamily': (row.get('techfamily') or '').strip() or 'MISSING',
            'area': (row.get('area') or '').strip() or 'MISSING',
        }
        for row in rows
        if row.get('SERVER_ID')
    ]
