"""
bc_rules_views.py
-----------------
Views for the BC rules wizard.
Place in: businesscontinuity/bc_rules_views.py

Progress pattern: JSON polling via Django cache.
No StreamingHttpResponse — no nginx/gunicorn buffering issues.

Flow:
  1. GET  /apply_bc_rules/                  -> wizard HTML (texts loaded from DB)
  2. GET  /apply_bc_rules/datacenters/      -> datacenter list + server counts (JSON)
  3. GET  /apply_bc_rules/texts/            -> current saved rule texts (JSON)
  4. POST /apply_bc_rules/preview/          -> compute preview, no DB write (JSON)
  5. POST /apply_bc_rules/start/            -> start background thread, return job_id (JSON)
  6. GET  /apply_bc_rules/status/<job_id>/ -> poll job progress (JSON)
"""

import datetime
import json
import logging
import os
import threading
import uuid

logger = logging.getLogger('businesscontinuity')

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .bc_rules_logic import (
    ALL_RULES, DEFAULT_TEXTS, compute_bc_results, group_by_rule
)
from .models import BCRuleTexts, Server, ServerUnique
from userapp.models import UserPermissions, UserProfile
from .utils import is_editor


# ── Helpers ───────────────────────────────────────────────────────────────────

# Editor check is handled by utils.is_editor() — imported above


def _job_cache_key(job_id):
    return f"bc_rules_job_{job_id}"


def _set_job_status(job_id, data):
    """Write job status to cache (TTL 1 hour)."""
    cache.set(_job_cache_key(job_id), data, timeout=3600)


def _get_job_status(job_id):
    return cache.get(_job_cache_key(job_id))


def _load_rule_texts():
    """
    Load saved rule texts from BCRuleTexts.
    Falls back to DEFAULT_TEXTS for any missing rule_key.
    Always returns a complete dict with all 9 rule keys.
    """
    saved = {obj.rule_key: obj.action_text
             for obj in BCRuleTexts.objects.all()}
    # Use saved value if key exists in DB (even if empty string),
    # fall back to DEFAULT_TEXTS only if the key has never been saved.
    return {key: saved[key] if key in saved else DEFAULT_TEXTS[key]
            for key in ALL_RULES}


def _save_rule_texts(rule_texts, username):
    """
    Persist rule texts to BCRuleTexts (upsert).
    Only saves keys present in ALL_RULES.
    """
    for rule_key, action_text in rule_texts.items():
        if rule_key not in ALL_RULES:
            continue
        BCRuleTexts.objects.update_or_create(
            rule_key=rule_key,
            defaults={
                'action_text': action_text,
                'updated_by':  username,
            }
        )


# ── View: wizard HTML ─────────────────────────────────────────────────────────

@login_required
def apply_bc_rules_view(request):
    user_is_editor = is_editor(request)
    saved_texts = _load_rule_texts()
    return render(request, 'businesscontinuity/apply_bc_rules.html', {
        'is_user_editor': user_is_editor,
        'saved_texts':    json.dumps(saved_texts),
        'default_texts':  json.dumps(DEFAULT_TEXTS),
        'all_rules':      json.dumps(ALL_RULES),
        'appname':        'businesscontinuity',
    })


# ── API: datacenter list ──────────────────────────────────────────────────────

def _load_allowed_datacenters():
    """
    Load the list of BC-eligible datacenters from field_labels.json.
    Falls back to an empty list if the key is missing.
    """
    labels_path = os.path.join(
        settings.BASE_DIR, 'businesscontinuity', 'field_labels.json'
    )
    try:
        with open(labels_path, encoding='utf-8') as f:
            return json.load(f).get('bc_affected_datacenters', [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


@login_required
@require_http_methods(["GET"])
def bc_datacenters(request):
    """
    Return the list of BC-eligible datacenters (from field_labels.json)
    with their distinct ServerUnique count.
    """
    allowed = _load_allowed_datacenters()
    if not allowed:
        return JsonResponse(
            {'error': 'No datacenters configured in field_labels.json (key: bc_affected_datacenters)'},
            status=500
        )

    result = []
    for dc in allowed:
        count_unique = (
            Server.objects
            .filter(DATACENTER=dc)
            .values('server_unique_id')
            .distinct()
            .count()
        )
        count_total = (
            Server.objects
            .filter(DATACENTER=dc)
            .count()
        )
        result.append({
            'datacenter':   dc,
            'count':        count_unique,
            'count_total':  count_total,
        })

    return JsonResponse({'datacenters': result})


# ── API: current saved texts ──────────────────────────────────────────────────

@login_required
def bc_texts(request):
    """
    GET : return the currently saved rule texts (DB, falling back to defaults).
    POST: save rule texts without applying rules (called on step 2 changes).
    """
    if request.method == 'GET':
        return JsonResponse({'texts': _load_rule_texts()})

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON body'}, status=400)

        rule_texts   = data.get('rule_texts', {})
        unknown_keys = set(rule_texts.keys()) - set(ALL_RULES)
        if unknown_keys:
            return JsonResponse({'error': f'Unknown rule keys: {unknown_keys}'}, status=400)

        _save_rule_texts(rule_texts, request.user.username)
        return JsonResponse({'status': 'ok'})

    return JsonResponse({'error': 'Method not allowed'}, status=405)


# ── API: preview ──────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["POST"])
def bc_preview(request):
    """
    Compute BC rules for the selected datacenter and return a grouped summary.
    Does NOT write anything to the database.

    Request body (JSON):
      {
        "datacenter": "FR-PAR-DC-MARNEEST",
        "rule_texts": { "cluster_yes_lp_yes": "...", ... }
      }
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    datacenter = (data.get('datacenter') or '').strip()
    if not datacenter:
        return JsonResponse({'error': 'datacenter is required'}, status=400)

    rule_texts   = data.get('rule_texts', {})
    unknown_keys = set(rule_texts.keys()) - set(ALL_RULES)
    if unknown_keys:
        return JsonResponse({'error': f'Unknown rule keys: {unknown_keys}'}, status=400)

    servers_qs = (
        Server.objects
        .filter(DATACENTER=datacenter)
        .select_related('server_unique')
        .order_by('SERVER_ID')
    )

    if not servers_qs.exists():
        return JsonResponse(
            {'error': f'No servers found for datacenter "{datacenter}"'},
            status=404
        )

    results = compute_bc_results(servers_qs, datacenter, rule_texts)
    grouped = group_by_rule(results)

    summary = []
    total   = 0
    for rule_key, bc_results in grouped.items():
        hostnames = [r.hostname for r in bc_results]
        summary.append({
            'rule_key':    rule_key,
            'action_text': bc_results[0].action_text,
            'count':       len(bc_results),
            'servers':     hostnames[:200],
            'truncated':   len(hostnames) > 200,
        })
        total += len(bc_results)

    total_qs = (
        Server.objects
        .filter(DATACENTER=datacenter)
        .values('server_unique_id')
        .distinct()
        .count()
    )

    return JsonResponse({
        'datacenter': datacenter,
        'total':      total,
        'skipped':    total_qs - total,
        'summary':    summary,
    })


# ── API: start job ────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["POST"])
def bc_start(request):
    """
    Persist rule texts, then start the BC apply job in a background thread.
    Returns a job_id for polling.

    Request body (JSON):
      {
        "datacenter": "FR-PAR-DC-MARNEEST",
        "rule_texts": { ... }
      }
    """
    if not is_editor(request):
        return JsonResponse(
            {'error': 'Permission denied. Editor role required.'},
            status=403
        )

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    datacenter = (data.get('datacenter') or '').strip()
    if not datacenter:
        return JsonResponse({'error': 'datacenter is required'}, status=400)

    rule_texts = data.get('rule_texts', {})
    username   = request.user.username

    # Persist texts before starting the job
    _save_rule_texts(rule_texts, username)

    job_id = str(uuid.uuid4())
    _set_job_status(job_id, {
        'progress': 0,
        'message':  'Starting...',
        'log':      [],
        'done':     False,
        'error':    None,
        'stats':    None,
    })

    logger.info(
        f"[BC Rules] {username} started — datacenter={datacenter}"
    )
    threading.Thread(
        target=_run_bc_job,
        args=(job_id, datacenter, rule_texts, username),
        daemon=True,
    ).start()

    return JsonResponse({'job_id': job_id})


# ── Background thread ─────────────────────────────────────────────────────────

def _run_bc_job(job_id, datacenter, rule_texts, username):
    """Runs in a background thread. Writes progress to cache for polling."""

    def update(progress, message, log_line=None):
        status = _get_job_status(job_id) or {}
        log    = status.get('log', [])
        if log_line:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            log.append({'ts': ts, 'msg': log_line})
        _set_job_status(job_id, {
            **status,
            'progress': round(progress, 1),
            'message':  message,
            'log':      log,
        })

    try:
        update(5, 'Loading servers...')

        servers_qs = (
            Server.objects
            .filter(DATACENTER=datacenter)
            .select_related('server_unique')
            .order_by('SERVER_ID')
        )

        if not servers_qs.exists():
            _set_job_status(job_id, {
                'progress': 100, 'done': True,
                'error':    f'No servers found for datacenter "{datacenter}".',
                'log':      [], 'message': 'Error', 'stats': None,
            })
            return

        update(10, 'Computing BC rules...', f'Datacenter: {datacenter}')

        results = compute_bc_results(servers_qs, datacenter, rule_texts)
        grouped = group_by_rule(results)
        total   = len(results)

        total_qs = servers_qs.values('server_unique_id').distinct().count()
        skipped  = total_qs - total

        update(20, f'{total} servers to process ({skipped} skipped — undetermined values).',
               f'{total}/{total_qs} servers identified across {len(grouped)} rules'
               + (f', {skipped} skipped (EMPTY/unknown cluster or in_live_play)' if skipped else ''))

        now_str      = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_hdr  = f"[{now_str} - {username}] [BC Rules Auto]"
        updated_count = 0
        batch_size    = 100

        for rule_index, (rule_key, bc_results) in enumerate(grouped.items(), start=1):
            action_text = bc_results[0].action_text
            su_ids      = [r.server_unique_id for r in bc_results]

            for i in range(0, len(su_ids), batch_size):
                batch_ids  = su_ids[i:i + batch_size]
                batch_objs = list(ServerUnique.objects.filter(id__in=batch_ids))

                with transaction.atomic():
                    for su in batch_objs:
                        su.action_during_lp         = action_text
                        su.action_during_lp_history = (
                            f"{history_hdr} {action_text}\n"
                            + (su.action_during_lp_history or '')
                        )
                        su.append_global_history(
                            changes={'action_during_lp': {
                                'info': 'Updated by BC Rules — check its history'
                            }},
                            username=username,
                            source='BC Rules',
                        )
                    ServerUnique.objects.bulk_update(
                        batch_objs,
                        ['action_during_lp', 'action_during_lp_history', 'global_history']
                    )

                updated_count += len(batch_objs)
                update(
                    20 + (updated_count / total) * 75,
                    f'Rule {rule_index}/{len(grouped)} ({updated_count}/{total})',
                )

            short = action_text[:60] + ('...' if len(action_text) > 60 else '')
            update(
                20 + (updated_count / total) * 75,
                f'Rule {rule_index}/{len(grouped)} done.',
                f'✓ {len(su_ids)} servers → "{short}"',
            )

        update(97, 'Finalizing...', '✓ History updated.')

        logger.info(
            f"[BC Rules] {username} completed — datacenter={datacenter}, "
            f"{updated_count} servers updated across {len(grouped)} rules"
        )
        _set_job_status(job_id, {
            **(_get_job_status(job_id) or {}),
            'progress': 100,
            'message':  f'{updated_count} servers updated.',
            'done':     True,
            'error':    None,
            'stats': {
                'total':      total,
                'skipped':    total_qs - total,
                'datacenter': datacenter,
                'rules':      {k: len(v) for k, v in grouped.items()},
            },
        })

    except Exception as exc:
        logger.error(
            f"[BC Rules] {username} — datacenter={datacenter} — unexpected error: {exc}",
            exc_info=True
        )
        _set_job_status(job_id, {
            **(_get_job_status(job_id) or {}),
            'progress': 100,
            'done':     True,
            'error':    f'Unexpected error: {exc}',
            'message':  'Error',
        })


# ── API: job status polling ───────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def bc_job_status(request, job_id):
    """Polled by the JS frontend every 800ms. Returns the current job status."""
    status = _get_job_status(str(job_id))
    if status is None:
        return JsonResponse({'error': 'Job not found or expired'}, status=404)
    return JsonResponse(status)
