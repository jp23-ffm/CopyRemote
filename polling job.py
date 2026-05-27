"""
polling_job.py
--------------
Generic background job utility for polling-based progress tracking.
Place in: businesscontinuity/polling_job.py

Replaces StreamingHttpResponse / SSE entirely.
Works reliably behind nginx, Apache mod_proxy, or any buffering reverse proxy.
Works with multiple Gunicorn workers, multiple servers behind a load balancer,
and SQLite in local development — because job state is stored in the database
cache ('db_cache'), shared across all workers and servers.

Prerequisites
-------------
1. Add to settings.py CACHES:

    CACHES = {
        'default': {
            # Keep your existing default cache unchanged
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        },
        'db_cache': {
            # Shared cache for background job state — works with any DB
            'BACKEND':  'django.core.cache.backends.db.DatabaseCache',
            'LOCATION': 'chimera_cache_table',
        },
    }

2. Create the cache table (run once):

    python manage.py createcachetable

Usage in a view
---------------
    from .polling_job import start_job, update_job, finish_job, fail_job, get_job_response

    def my_start_view(request):
        job_id = start_job()

        def run():
            update_job(job_id, 10, 'Loading data...')
            # ... do work ...
            update_job(job_id, 100, 'Done.', log='✓ All records updated.')
            finish_job(job_id, stats={'total': 42})

        threading.Thread(target=run, daemon=True).start()
        return JsonResponse({'job_id': job_id})

    def my_status_view(request, job_id):
        return get_job_response(job_id)

Response shape (GET /status/<job_id>/)
---------------------------------------
    {
        "progress": 62.5,       # 0–100
        "message":  "Saving…",  # current status label
        "log":      [           # append-only list of timestamped lines
            {"ts": "14:03:21", "msg": "✓ 50 records updated"}
        ],
        "done":  false,         # true when finished (success or error)
        "error": null,          # error message string, or null
        "stats": null           # arbitrary dict set on finish_job()
    }
"""

import datetime
import threading
import uuid

from django.core.cache import caches
from django.http import JsonResponse


# Cache TTL — jobs expire after 2 hours
_JOB_TTL = 7200

# Module-level lock to avoid race conditions on log appends within a single worker.
# Cross-worker safety is ensured by the database cache backend.
_lock = threading.Lock()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _cache():
    """Return the shared database cache backend used for job state."""
    return caches['db_cache']


def _key(job_id: str) -> str:
    return f"polling_job_{job_id}"


def _read(job_id: str) -> dict:
    return _cache().get(_key(job_id)) or {}


def _write(job_id: str, data: dict) -> None:
    _cache().set(_key(job_id), data, timeout=_JOB_TTL)


# ── Public API ────────────────────────────────────────────────────────────────

def start_job(meta: dict = None) -> str:
    """
    Create a new job entry in the shared cache and return its UUID string.

    Args:
        meta: Optional dict of arbitrary metadata to store with the job
              (e.g. {'datacenter': 'FR-PAR-DC-MARNEEST'}).
    """
    job_id = str(uuid.uuid4())
    _write(job_id, {
        'progress': 0,
        'message':  'Starting...',
        'log':      [],
        'done':     False,
        'error':    None,
        'stats':    None,
        'meta':     meta or {},
    })
    return job_id


def update_job(
    job_id: str,
    progress: float,
    message: str,
    log: str = None,
) -> None:
    """
    Update job progress. Safe to call from a background thread.

    Args:
        job_id:   UUID string returned by start_job().
        progress: Completion percentage (0–100).
        message:  Short status label shown below the progress bar.
        log:      Optional log line to append (timestamped automatically).
    """
    with _lock:
        data = _read(job_id)
        if not data:
            return  # Job expired or never created — silently ignore

        if log:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            data['log'].append({'ts': ts, 'msg': log})

        data['progress'] = round(progress, 1)
        data['message']  = message
        _write(job_id, data)


def finish_job(job_id: str, stats: dict = None) -> None:
    """
    Mark the job as successfully completed.

    Args:
        job_id: UUID string returned by start_job().
        stats:  Optional summary dict (e.g. {'total': 42, 'errors': 0}).
    """
    with _lock:
        data = _read(job_id)
        if not data:
            return
        data['progress'] = 100
        data['done']     = True
        data['error']    = None
        data['stats']    = stats or {}
        _write(job_id, data)


def fail_job(job_id: str, error: str) -> None:
    """
    Mark the job as failed with an error message.

    Args:
        job_id: UUID string returned by start_job()
        error:  Human-readable error description.
    """
    with _lock:
        data = _read(job_id)
        if not data:
            return
        data['progress'] = 100
        data['done']     = True
        data['error']    = error
        _write(job_id, data)


def get_job_response(job_id: str) -> JsonResponse:
    """
    Return a JsonResponse with the current job status.
    Call this from the polling endpoint view.

    Returns HTTP 404 if the job does not exist or has expired.
    """
    data = _read(str(job_id))
    if not data:
        return JsonResponse({'error': 'Job not found or expired'}, status=404)
    return JsonResponse(data)
