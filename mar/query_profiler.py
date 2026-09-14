"""
Profiling SQL opt-in, quasi gratuit quand désactivé.
Activer : env QUERY_PROFILING=1 (timing seul) ou +QUERY_PROFILING_EXPLAIN=1 (+ plan)
Compatible PostgreSQL et SQLite.
"""
import logging
import os
import time
from contextlib import contextmanager
from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext

logger = logging.getLogger("query_profiler")

ENABLED = getattr(settings, "QUERY_PROFILING_ENABLED", os.environ.get("QUERY_PROFILING") == "1")
EXPLAIN = getattr(settings, "QUERY_PROFILING_EXPLAIN", os.environ.get("QUERY_PROFILING_EXPLAIN") == "1")
SLOW_MS = float(getattr(settings, "QUERY_PROFILING_SLOW_MS", 50))


def _explain(sql):
    """Renvoie (plan_text, is_full_scan) selon le moteur."""
    with connection.cursor() as cur:
        if connection.vendor == "sqlite":
            cur.execute(f"EXPLAIN QUERY PLAN {sql}")
            rows = cur.fetchall()
            plan = "\n".join(str(r) for r in rows)
            # SQLite (versions récentes) : "SCAN <table>" = full scan (le mot TABLE
            # n'apparaît plus systématiquement dans le libellé selon la version).
            # "USING INDEX" / "USING COVERING INDEX" = index utilisé.
            is_full_scan = any(
                "SCAN" in str(r) and "USING INDEX" not in str(r) and "USING COVERING INDEX" not in str(r)
                for r in rows
            )
        else:  # postgresql
            cur.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}")
            plan = "\n".join(r[0] for r in cur.fetchall())
            is_full_scan = "Seq Scan" in plan
    return plan, is_full_scan


@contextmanager
def profile_queries(label=""):
    if not ENABLED:
        yield
        return

    wall_start = time.perf_counter()
    with CaptureQueriesContext(connection) as ctx:
        yield
    wall_ms = (time.perf_counter() - wall_start) * 1000

    sql_ms = sum(float(q["time"]) for q in ctx.captured_queries) * 1000
    non_sql_ms = wall_ms - sql_ms

    logger.info(
        "[%s] %d requêtes, %.1f ms SQL, %.1f ms total réel (dont %.1f ms hors-SQL)",
        label, len(ctx.captured_queries), sql_ms, wall_ms, non_sql_ms,
    )

    for q in ctx.captured_queries:
        ms = float(q["time"]) * 1000
        if ms < SLOW_MS:
            continue
        sql = q["sql"]
        logger.warning("[%s] LENTE (%.1f ms): %s", label, ms, sql[:300])

        if EXPLAIN and sql.strip().upper().startswith("SELECT"):
            try:
                plan, is_full_scan = _explain(sql)
                kind = "Scan complet ⚠️" if is_full_scan else "Index utilisé ✅"
                logger.warning("[%s] plan (%s):\n%s", label, kind, plan)
            except Exception as e:
                logger.error("[%s] EXPLAIN a échoué: %s", label, e)
