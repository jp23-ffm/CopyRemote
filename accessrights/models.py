from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class Permission(models.Model):
    """
    Catalog of all available permissions.
    Add new ones anytime — no migration needed, just insert a row.

    codename format: "app_key.action"
    Examples:
        inventory.view
        inventory.edit
        businesscontinuity.export
        discrepancies.edit
    """
    codename = models.CharField(max_length=100, unique=True)
    app = models.CharField(max_length=50, db_index=True)
    action = models.CharField(max_length=30)
    label = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        db_table = 'acl_permissions'
        ordering = ['app', 'codename']

    def __str__(self):
        return self.codename

    def save(self, *args, **kwargs):
        if not self.label:
            self.label = self.action.capitalize()
        super().save(*args, **kwargs)


class UserPermission(models.Model):
    """
    Junction table: one row = one user has one permission.
    Grant = create row, revoke = delete row.
    granted_by = NULL means it was set by an automated process (AD sync, etc.)
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='access_permissions',
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name='user_grants',
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='grants_given',
    )

    class Meta:
        db_table = 'acl_user_permissions'
        unique_together = ('user', 'permission')

    def __str__(self):
        return f"{self.user.username} → {self.permission.codename}"


class AuditLog(models.Model):
    """
    Tracks every permission change for compliance.
    One row per grant/revoke action.
    """
    ACTIONS = [
        ('granted', 'Granted'),
        ('revoked', 'Revoked'),
    ]

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    admin_user = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        related_name='acl_admin_actions',
    )
    target_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='acl_target_logs',
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
    )
    action = models.CharField(max_length=10, choices=ACTIONS)

    class Meta:
        db_table = 'acl_audit_log'
        ordering = ['-timestamp']

    def __str__(self):
        return (
            f"{self.timestamp:%Y-%m-%d %H:%M} "
            f"{self.admin_user} {self.action} "
            f"{self.permission.codename} → {self.target_user}"
        )
