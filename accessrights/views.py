import json
import os
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from .models import Permission, UserPermission, AuditLog

User = get_user_model()
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Dashboard page
# ──────────────────────────────────────────────
@login_required
def dashboard(request):
    """Renders the permission dashboard page."""
    return render(request, 'accessrights/dashboard.html')


# ──────────────────────────────────────────────
# JSON config endpoint
# ──────────────────────────────────────────────
@login_required
@require_GET
def get_config(request):
    """
    Returns the full config JSON for the dashboard.
    App definitions (keys, labels, colors) come from permissions.json.
    Users + their active permissions come from the database.
    """
    # Load static app definitions
    json_path = os.path.join(
        settings.BASE_DIR,
        'accessrights', 'static', 'accessrights', 'permissions.json',
    )
    try:
        with open(json_path) as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error(f"permissions.json not found at {json_path}")
        return JsonResponse({'error': 'Config file not found'}, status=500)

    # Build users list with their permissions from DB
    users = []
    for u in User.objects.filter(is_active=True).order_by('username'):
        user_perms = list(
            UserPermission.objects
            .filter(user=u)
            .values_list('permission__codename', flat=True)
        )
        users.append({
            'id': u.id,
            'name': u.get_full_name() or u.username,
            'username': u.username,
            'last_login': (
                u.last_login.strftime('%Y-%m-%d %H:%M')
                if u.last_login else '—'
            ),
            'permissions': user_perms,
        })

    config['admin'] = request.user.username
    config['users'] = users

    # List of codenames that exist in the DB (have been seeded)
    config['seeded'] = list(
        Permission.objects.values_list('codename', flat=True)
    )

    return JsonResponse(config)


# ──────────────────────────────────────────────
# Update permissions endpoint
# ──────────────────────────────────────────────
@login_required
@require_POST
def update_permissions(request):
    """
    Applies permission changes from the dashboard.
    Expects JSON body:
    {
        "changes": [
            {"user_id": 1, "permission": "inventory.edit", "action": "grant"},
            {"user_id": 3, "permission": "discrepancies.view", "action": "revoke"}
        ]
    }
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    changes = data.get('changes', [])
    applied = 0
    errors = []

    for change in changes:
        user_id = change.get('user_id')
        codename = change.get('permission')
        action = change.get('action')

        if not all([user_id, codename, action]):
            errors.append(f"Missing fields in: {change}")
            continue

        try:
            perm = Permission.objects.get(codename=codename)
            target_user = User.objects.get(id=user_id)
        except Permission.DoesNotExist:
            errors.append(f"Permission not found: {codename}")
            continue
        except User.DoesNotExist:
            errors.append(f"User not found: {user_id}")
            continue

        if action == 'grant':
            UserPermission.objects.get_or_create(
                user=target_user,
                permission=perm,
                defaults={'granted_by': request.user},
            )
        elif action == 'revoke':
            UserPermission.objects.filter(
                user=target_user,
                permission=perm,
            ).delete()
        else:
            errors.append(f"Unknown action: {action}")
            continue

        # Audit log
        AuditLog.objects.create(
            admin_user=request.user,
            target_user=target_user,
            permission=perm,
            action='granted' if action == 'grant' else 'revoked',
        )
        applied += 1

    response = {'status': 'ok', 'applied': applied}
    if errors:
        response['errors'] = errors

    return JsonResponse(response)


# ──────────────────────────────────────────────
# Audit log endpoint
# ──────────────────────────────────────────────
@login_required
@require_GET
def get_audit_log(request):
    """Returns recent audit log entries."""
    limit = min(int(request.GET.get('limit', 50)), 200)

    entries = AuditLog.objects.select_related(
        'admin_user', 'target_user', 'permission'
    )[:limit]

    log = []
    for e in entries:
        log.append({
            'timestamp': e.timestamp.strftime('%Y-%m-%d %H:%M'),
            'admin': e.admin_user.username if e.admin_user else 'system',
            'target': e.target_user.username,
            'permission': e.permission.codename,
            'action': e.action,
        })

    return JsonResponse({'log': log})
