"""
bc_rules_views.py
-----------------
Views for the BC rules wizard.
Place in: businesscontinuity/bc_rules_views.py

Progress pattern: JSON polling via Django cache ('longcache', DB-backed —
shared across gunicorn workers, unlike the per-process 'default' cache).
No StreamingHttpResponse — no nginx/gunicorn buffering issues.

Flow:
  1. GET  /apply_bc_rules/                  -> wizard HTML (texts loaded from DB)
  2. GET  /apply_bc_rules/scope/            -> filter scope + sibling datacenter stats (JSON)
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
from django.core.cache import caches
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from urllib.parse import parse_qs, unquote

from .bc_rules_logic import (
    ALL_RULES, DEFAULT_TEXTS, compute_bc_results, group_by_rule
)
from .models import BCRuleTexts, Server, ServerUnique
from userapp.models import SavedOptions, UserPermissions, UserProfile
from .utils import is_editor
from .views import _build_filtered_queryset, selection_mismatch

# 'longcache' (DB-backed) is shared across gunicorn workers — 'default' is
# per-process LocMemCache and would be invisible to workers other than the
# one running the background thread.
cache = caches['longcache']

# Value written by the sibling reset, same as the DR Reset feature
RESET_VALUE = 'EMPTY'
# Hostnames returned to the UI for the warning lists
LISTED_SERVERS_CAP = 2000


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


def _blank_rules_error(rule_texts):
    """Return an error message if a rule text is blank, None otherwise."""
    blank = [key for key, text in rule_texts.items() if not str(text or '').strip()]
    if not blank:
        return None
    return (
        f"Action texts cannot be empty: {', '.join(blank)}. "
        f"Enter {RESET_VALUE} if no action is wanted."
    )


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


# ── Scope: filters from the server list ───────────────────────────────────────

class BCScopeError(Exception):
    """Raised when the requested scope or sibling datacenter is not usable."""


def _load_field_labels():
    """Load businesscontinuity/field_labels.json, empty dict if unreadable."""
    labels_path = os.path.join(
        settings.BASE_DIR, 'businesscontinuity', 'field_labels.json'
    )
    try:
        with open(labels_path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _resolve_scope(request, query):
    """
    Turn the server list query string into (queryset, datacenter).
    The filters must resolve to exactly one BC-eligible datacenter: the check
    runs on the matching rows because terms can be partial, negated or expanded.
    """
    query  = (query or '').lstrip('?')
    parsed = parse_qs(unquote(query), keep_blank_values=False)
    if not parsed.get('datacenter', [''])[0].strip():
        raise BCScopeError(
            'A Datacenter filter is required: filter the server list on one datacenter, '
            'then open Apply BC Rules again.'
        )

    servers_qs, _ = _build_filtered_queryset(request, query)
    found = list(
        servers_qs.order_by().values_list('DATACENTER', flat=True).distinct()[:11]
    )
    if not found:
        raise BCScopeError('No servers match the current filters.')
    if len(found) > 1:
        names = ', '.join(sorted(d or '(empty)' for d in found[:10]))
        raise BCScopeError(
            f'The filters must match exactly one datacenter, found: {names}. '
            'Tip: prefix the value with @ for an exact match.'
        )

    mismatch = selection_mismatch(
        servers_qs.order_by().values('server_unique_id').distinct().count(),
        parsed.get('expected_servers', [''])[0],
    )
    if mismatch:
        raise BCScopeError(mismatch)

    datacenter = found[0]
    if not datacenter:
        raise BCScopeError('The filters match servers without a datacenter.')
    if datacenter not in _load_field_labels().get('bc_datacenter_siblings', {}):
        raise BCScopeError(
            f'"{datacenter}" is not configured for BC rules '
            '(field_labels.json, key: bc_datacenter_siblings).'
        )
    return servers_qs, datacenter


def _validate_sibling(datacenter, sibling):
    """Return the cleaned sibling name (or None), raise if it cannot be used."""
    sibling = (sibling or '').strip() or None
    if sibling is None:
        return None
    if sibling == datacenter:
        raise BCScopeError('The sibling datacenter must differ from the affected datacenter.')
    if not Server.objects.filter(DATACENTER=sibling).exists():
        raise BCScopeError(f'No servers found for sibling datacenter "{sibling}".')
    return sibling


def _sibling_querysets(datacenter, sibling):
    """
    Return (all sibling servers, servers also in the affected datacenter, servers to reset).
    action_during_lp is stored per hostname: a server on both sites must keep the
    rule result, even when it is outside the filtered scope.
    """
    affected_ids = Server.objects.filter(DATACENTER=datacenter).values('server_unique_id')
    in_sibling   = ServerUnique.objects.filter(server_info__DATACENTER=sibling).distinct()
    to_reset = (
        in_sibling
        .exclude(id__in=affected_ids)
        .exclude(action_during_lp__isnull=True)
        .exclude(action_during_lp__in=['', RESET_VALUE])
    )
    return in_sibling, in_sibling.filter(id__in=affected_ids), to_reset


def _sibling_stats(datacenter, sibling):
    """Summarize the sibling reset for the wizard. None when no sibling is selected."""
    if not sibling:
        return None
    in_sibling, shared, to_reset = _sibling_querysets(datacenter, sibling)
    hostnames  = list(in_sibling.order_by('hostname').values_list('hostname', flat=True))
    reset      = set(to_reset.values_list('hostname', flat=True))
    shared_all = list(shared.order_by('hostname').values_list('hostname', flat=True))
    # The sibling reset ignores exceptions: tell how many of them it will reset
    reset_exceptions = sorted(to_reset.filter(bc_exception__iexact='YES').values_list('hostname', flat=True))
    return {
        'datacenter':        sibling,
        'total':             len(hostnames),
        'to_reset':          len(reset),
        'servers':           hostnames[:LISTED_SERVERS_CAP],
        'changed_servers':   [h for h in hostnames if h in reset][:LISTED_SERVERS_CAP],
        'unchanged_servers': [h for h in hostnames if h not in reset][:LISTED_SERVERS_CAP],
        'shared_count':      len(shared_all),
        'shared':            shared_all[:LISTED_SERVERS_CAP],
        'shared_truncated':  len(shared_all) > LISTED_SERVERS_CAP,
        'exceptions_reset':  {
            'count':     len(reset_exceptions),
            'servers':   reset_exceptions[:LISTED_SERVERS_CAP],
            'truncated': len(reset_exceptions) > LISTED_SERVERS_CAP,
        },
    }


def _split_exceptions(servers_qs):
    """Remove the servers in exception from the scope. Return (remaining scope, exception summary)."""
    in_exception = Q(server_unique__bc_exception__iexact='YES')
    hostnames = sorted(set(servers_qs.filter(in_exception).values_list('server_unique__hostname', flat=True)))
    return servers_qs.exclude(in_exception), {
        'count':     len(hostnames),
        'servers':   hostnames[:LISTED_SERVERS_CAP],
        'truncated': len(hostnames) > LISTED_SERVERS_CAP,
    }


def _skipped_with_action(servers_qs, results):
    """List skipped servers in scope that keep an existing action (never modified by the job)."""
    applied = {r.server_unique_id for r in results}
    rows = servers_qs.order_by().values_list(
        'server_unique_id', 'server_unique__hostname', 'server_unique__action_during_lp'
    )
    hostnames = sorted({
        hostname for su_id, hostname, action in rows
        if su_id not in applied and (action or '').strip() not in ('', RESET_VALUE)
    })
    return {
        'count':     len(hostnames),
        'servers':   hostnames[:LISTED_SERVERS_CAP],
        'truncated': len(hostnames) > LISTED_SERVERS_CAP,
    }


def _describe_filters(parsed, labels):
    """List the active server list filters as {label, value} for display."""
    described = []
    for field in labels.get('fields', {}).values():
        value = parsed.get(field.get('inputname'), [''])[0]
        if value:
            described.append({'label': field.get('displayname', ''), 'value': value})
    return described


def _active_permanent_filter(user, labels):
    """Return the name of the permanent filter applied to this user, if any."""
    name = (
        SavedOptions.objects
        .filter(user_profile__user=user)
        .values_list('businesscontinuity_permanentfilter', flat=True)
        .first()
    )
    return name if name in labels.get('permanentfilters', {}) else None


@login_required
@require_http_methods(["GET"])
def bc_scope(request):
    """
    Describe the scope built from the server list filters.
    Query params: query (server list query string), sibling (optional: the
    configured sibling is used when absent, an empty value means none).
    """
    query = request.GET.get('query', '')
    try:
        servers_qs, datacenter = _resolve_scope(request, query)
        labels     = _load_field_labels()
        configured = labels.get('bc_datacenter_siblings', {}).get(datacenter)
        options    = sorted(
            d for d in Server.objects.order_by().values_list('DATACENTER', flat=True).distinct()
            if d and d != datacenter
        )
        default_sibling = configured if configured in options else None
        requested = request.GET.get('sibling')
        sibling   = _validate_sibling(
            datacenter, default_sibling if requested is None else requested
        )
    except BCScopeError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    parsed = parse_qs(unquote(query.lstrip('?')), keep_blank_values=False)
    return JsonResponse({
        'datacenter':       datacenter,
        'filters':          _describe_filters(parsed, labels),
        'permanent_filter': _active_permanent_filter(request.user, labels),
        'count':            servers_qs.order_by().values('server_unique_id').distinct().count(),
        'count_total':      servers_qs.count(),
        'default_sibling':  default_sibling,
        'options':          options,
        'sibling':          _sibling_stats(datacenter, sibling),
    })


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

        blank_error = _blank_rules_error(rule_texts)
        if blank_error:
            return JsonResponse({'error': blank_error}, status=400)

        _save_rule_texts(rule_texts, request.user.username)
        return JsonResponse({'status': 'ok'})

    return JsonResponse({'error': 'Method not allowed'}, status=405)


# ── API: preview ──────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["POST"])
def bc_preview(request):
    """
    Compute BC rules for the filtered scope and return a grouped summary.
    Does NOT write anything to the database.

    Request body (JSON):
      {
        "query":      "datacenter=%40DC-PARIS-01&environment=PRD",
        "sibling":    "DC-PARIS-02",
        "rule_texts": { "cluster_yes_lp_yes": "...", ... }
      }
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    rule_texts   = data.get('rule_texts', {})
    unknown_keys = set(rule_texts.keys()) - set(ALL_RULES)
    if unknown_keys:
        return JsonResponse({'error': f'Unknown rule keys: {unknown_keys}'}, status=400)

    blank_error = _blank_rules_error(rule_texts)
    if blank_error:
        return JsonResponse({'error': blank_error}, status=400)

    try:
        servers_qs, datacenter = _resolve_scope(request, data.get('query'))
        sibling = _validate_sibling(datacenter, data.get('sibling'))
    except BCScopeError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    servers_qs, exceptions = _split_exceptions(servers_qs)
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
            'changed':     sum(r.changed for r in bc_results),
            'servers':     hostnames[:LISTED_SERVERS_CAP],
            'changed_servers':   [r.hostname for r in bc_results if r.changed][:LISTED_SERVERS_CAP],
            'unchanged_servers': [r.hostname for r in bc_results if not r.changed][:LISTED_SERVERS_CAP],
            'truncated':   len(hostnames) > LISTED_SERVERS_CAP,
        })
        total += len(bc_results)

    total_qs = servers_qs.order_by().values('server_unique_id').distinct().count()

    return JsonResponse({
        'datacenter': datacenter,
        'total':      total,
        'changed':    sum(r.changed for r in results),
        'skipped':    total_qs - total,
        'skipped_with_action': _skipped_with_action(servers_qs, results),
        'exceptions': exceptions,
        'summary':    summary,
        'sibling':    _sibling_stats(datacenter, sibling),
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
        "query":      "datacenter=%40DC-PARIS-01&environment=PRD",
        "sibling":    "DC-PARIS-02",
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

    try:
        servers_qs, datacenter = _resolve_scope(request, data.get('query'))
        sibling = _validate_sibling(datacenter, data.get('sibling'))
    except BCScopeError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    rule_texts = data.get('rule_texts', {})
    username   = request.user.username

    blank_error = _blank_rules_error(rule_texts)
    if blank_error:
        return JsonResponse({'error': blank_error}, status=400)

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
        f"[BC Rules] {username} started — datacenter={datacenter}, "
        f"sibling={sibling}, query={data.get('query')}"
    )
    threading.Thread(
        target=_run_bc_job,
        args=(job_id, servers_qs, datacenter, rule_texts, username, sibling),
        daemon=True,
    ).start()

    return JsonResponse({'job_id': job_id})


# ── Background thread ─────────────────────────────────────────────────────────

def _reset_sibling_servers(reset_ids, sibling, username, on_batch):
    """Set action_during_lp to EMPTY on the given servers, with their history."""
    batch_size = 100
    for i in range(0, len(reset_ids), batch_size):
        batch_ids  = reset_ids[i:i + batch_size]
        batch_objs = list(ServerUnique.objects.filter(id__in=batch_ids))
        # Per batch: changes.py pairs text and global history within a few seconds
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with transaction.atomic():
            for su in batch_objs:
                su.action_during_lp         = RESET_VALUE
                su.action_during_lp_history = (
                    f"[{now_str} - {username}] [BC Rules Reset] {RESET_VALUE}\n"
                    + (su.action_during_lp_history or '')
                )
                su.append_global_history(
                    changes={'action_during_lp': {
                        'info': f'Reset by BC Rules (sibling {sibling}) — check its history'
                    }},
                    username=username,
                    source='BC Rules Reset',
                )
            ServerUnique.objects.bulk_update(
                batch_objs,
                ['action_during_lp', 'action_during_lp_history', 'global_history']
            )
        on_batch(len(batch_objs))


def _run_bc_job(job_id, servers_qs, datacenter, rule_texts, username, sibling=None):
    """Runs in a background thread. Writes progress and the final recap to cache for polling."""

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

    started_at = datetime.datetime.now()
    # Filled as the job goes: on failure it tells what was really saved
    stats = {
        'datacenter':          datacenter,
        'sibling':             sibling,
        'total':               0,
        'changed':             0,
        'unchanged':           0,
        'updated':             0,
        'skipped':             0,
        'skipped_with_action': {'count': 0, 'servers': [], 'truncated': False},
        'reset':               0,
        'reset_planned':       0,
        'shared':              0,
        'exceptions':          {'count': 0, 'servers': [], 'truncated': False},
        'exceptions_reset':    0,
        'rules':               [],
    }

    def finish(message, error=None):
        finished_at = datetime.datetime.now()
        stats['finished'] = finished_at.strftime("%Y-%m-%d %H:%M:%S")
        stats['duration'] = round((finished_at - started_at).total_seconds(), 1)
        status = _get_job_status(job_id) or {}
        _set_job_status(job_id, {
            **status,
            'progress': 100 if error is None else status.get('progress', 0),
            'message':  message,
            'done':     True,
            'error':    error,
            'stats':    stats,
        })

    try:
        update(5, 'Loading servers...')

        if not servers_qs.exists():
            finish('Error', f'No servers match the scope in datacenter "{datacenter}".')
            return

        update(10, 'Computing BC rules...', f'Datacenter: {datacenter}')

        servers_qs, exceptions = _split_exceptions(servers_qs)
        stats['exceptions'] = exceptions
        results = compute_bc_results(servers_qs, datacenter, rule_texts)
        grouped = group_by_rule(results)
        total   = len(results)
        changed = sum(r.changed for r in results)

        total_qs = servers_qs.order_by().values('server_unique_id').distinct().count()
        skipped  = total_qs - total

        reset_ids, shared_count = [], 0
        if sibling:
            _, shared, to_reset = _sibling_querysets(datacenter, sibling)
            reset_ids    = list(to_reset.values_list('id', flat=True))
            shared_count = shared.count()
            stats['exceptions_reset'] = to_reset.filter(bc_exception__iexact='YES').count()
        total_work = max(changed + len(reset_ids), 1)

        rule_stats = {
            rule_key: {
                'rule_key':    rule_key,
                'action_text': bc_results[0].action_text,
                'written':     0,
                'unchanged':   sum(not r.changed for r in bc_results),
            }
            for rule_key, bc_results in grouped.items()
        }
        stats.update({
            'total':               total,
            'changed':             changed,
            'unchanged':           total - changed,
            'skipped':             skipped,
            'skipped_with_action': _skipped_with_action(servers_qs, results),
            'reset_planned':       len(reset_ids),
            'shared':              shared_count,
            'rules':               list(rule_stats.values()),
        })

        update(20, f'{changed} servers to change, {total - changed} unchanged, {skipped} skipped.',
               f'{total}/{total_qs} servers evaluated across {len(grouped)} rules: '
               f'{changed} to change, {total - changed} unchanged'
               + (f', {skipped} skipped (EMPTY/unknown cluster or in_live_play)' if skipped else ''))

        now_str      = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_hdr  = f"[{now_str} - {username}] [BC Rules Auto]"
        updated_count = 0
        batch_size    = 100

        for rule_index, (rule_key, bc_results) in enumerate(grouped.items(), start=1):
            action_text = bc_results[0].action_text
            # Servers already holding this text are left alone: no write, no history entry
            su_ids      = [r.server_unique_id for r in bc_results if r.changed]

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
                stats['updated'] = updated_count
                rule_stats[rule_key]['written'] += len(batch_objs)
                update(
                    20 + (updated_count / total_work) * 75,
                    f'Rule {rule_index}/{len(grouped)} ({updated_count}/{changed})',
                )

            short = action_text[:60] + ('...' if len(action_text) > 60 else '')
            update(
                20 + (updated_count / total_work) * 75,
                f'Rule {rule_index}/{len(grouped)} done.',
                f'✓ {len(su_ids)} changed, {len(bc_results) - len(su_ids)} unchanged → "{short}"',
            )

        reset_count = 0
        if sibling:
            def on_reset_batch(batch_len):
                nonlocal reset_count
                reset_count += batch_len
                stats['reset'] = reset_count
                update(
                    20 + ((updated_count + reset_count) / total_work) * 75,
                    f'Resetting {sibling} ({reset_count}/{len(reset_ids)})',
                )

            _reset_sibling_servers(reset_ids, sibling, username, on_reset_batch)
            update(
                95, f'{sibling} done.',
                f'✓ {reset_count} servers reset to {RESET_VALUE} in {sibling}'
                + (f', {shared_count} kept (also in {datacenter})' if shared_count else ''),
            )

        update(97, 'Finalizing...', '✓ History updated.')

        logger.info(
            f"[BC Rules] {username} completed — datacenter={datacenter}, "
            f"{updated_count} servers updated, {total - changed} unchanged across {len(grouped)} rules, "
            f"sibling={sibling}, {reset_count} reset"
        )
        finish(
            f'{updated_count} servers updated'
            + (f', {reset_count} reset.' if sibling else '.')
        )

    except Exception as exc:
        logger.error(
            f"[BC Rules] {username} — datacenter={datacenter} — unexpected error: {exc}",
            exc_info=True
        )
        current = (_get_job_status(job_id) or {}).get('progress', 0)
        update(current, 'Error', f'✕ Failed: {exc}')
        finish('Error', f'Unexpected error: {exc}')


# ── API: job status polling ───────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def bc_job_status(request, job_id):
    """Polled by the JS frontend every 800ms. Returns the current job status."""
    status = _get_job_status(str(job_id))
    if status is None:
        return JsonResponse({'error': 'Job not found or expired'}, status=404)
    return JsonResponse(status)
