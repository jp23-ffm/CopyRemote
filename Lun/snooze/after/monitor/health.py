"""
Global health computation, shared by the cron command (update_global_health)
and the snooze views, so a snooze is reflected immediately in /monitor/status.
"""
from typing import Any, Dict, List, Tuple

from django.utils import timezone

import monitor.management.commands.status_checks as checks
from monitor.models import CheckSnooze, GlobalHealthStatus


def get_global_checks():
    return [
        # Table items count
        ("Business Continuity Server", lambda: checks.count_table_items(
            app_label="businesscontinuity", model_name="Server",
            display_name="Entries - Business Continuity")),
        ("Business Continuity ServerUnique", lambda: checks.count_table_items(
            app_label="businesscontinuity", model_name="ServerUnique",
            display_name="Entries - Business Continuity")),
        ("Inventory Server", lambda: checks.count_table_items(
            app_label="inventory", model_name="Server",
            display_name="Entries - Inventory")),
        ("Inventory ServerGroupSummary", lambda: checks.count_table_items(
            app_label="inventory", model_name="ServerGroupSummary",
            display_name="Entries - Inventory")),
        ("Discrepancies ServerDiscrepancy", lambda: checks.count_table_items(
            app_label="discrepancies", model_name="ServerDiscrepancy",
            display_name="Entries - Discrepancies")),

        # Imports status
        ("Last Import - Business Continuity", lambda: checks.check_businesscontinuity_last_import()),
        ("Last Import - Inventory", lambda: checks.check_inventory_last_import()),
        ("Last Import - Discrepancies", lambda: checks.check_discrepancies_last_import()),

        # SSL Certificate
        ("Check Certificate", lambda: checks.check_url_certificate(
            url="https://chimeraiaas.dev.echonet/login/")),
    ]


def apply_snoozes(results: List[Dict[str, Any]]) -> None:
    """
    Turn a snoozed Warning into Status "Snoozed" (in place).
    Only Warnings flagged "Snoozable" qualify: never Errors. The snooze must be
    active and bound to the same RefId (same failed import).
    """
    now = timezone.now()
    active = {s.check_name: s for s in CheckSnooze.objects.filter(snoozed_until__gt=now)}
    for r in results:
        r.setdefault("Snoozable", False)
        snooze = active.get(r.get("Name"))
        if (snooze and r.get("Status") == "Warning" and r.get("Snoozable")
                and snooze.ref_id == r.get("RefId", "")):
            r["Status"] = "Snoozed"
            r["SnoozedUntil"] = snooze.snoozed_until.isoformat()
            r["SnoozedBy"] = snooze.created_by.get_username() if snooze.created_by else ""
            r["SnoozeReason"] = snooze.reason


def compute_global_health(log=None) -> Tuple[str, List[Dict[str, Any]]]:
    """Run all global checks. Returns (overall_status, results). 'Snoozed' counts as OK."""
    results: List[Dict[str, Any]] = []
    for check_name, check_fn in get_global_checks():
        try:
            results.append(check_fn())
        except Exception as exc:
            results.append({"Name": check_name, "Status": "Error", "Details": f"Exception: {exc}"})
            if log:
                log(f"{check_name}: Error - {exc}")

    apply_snoozes(results)

    overall = "OK"
    for r in results:
        if r["Status"] == "Error":
            overall = "Error"
        elif r["Status"] == "Warning" and overall != "Error":
            overall = "Warning"
    return overall, results


def build_checks_data(results):
    return {
        'checks': results,
        'total_checks': len(results),
        'ok_count': sum(1 for c in results if c['Status'] == 'OK'),
        'warning_count': sum(1 for c in results if c['Status'] == 'Warning'),
        'error_count': sum(1 for c in results if c['Status'] == 'Error'),
        'snoozed_count': sum(1 for c in results if c['Status'] == 'Snoozed'),
    }


def refresh_global_health(log=None):
    overall, results = compute_global_health(log=log)
    GlobalHealthStatus.update_global_status(status=overall, checks_data=build_checks_data(results))
    return overall, results
