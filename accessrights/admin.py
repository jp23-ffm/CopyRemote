from django.contrib import admin
from .models import Permission, UserPermission, AuditLog


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ('codename', 'app', 'action', 'label')
    list_filter = ('app',)
    search_fields = ('codename', 'label')


@admin.register(UserPermission)
class UserPermissionAdmin(admin.ModelAdmin):
    list_display = ('user', 'permission', 'granted_at', 'granted_by')
    list_filter = ('permission__app',)
    search_fields = ('user__username', 'permission__codename')
    raw_id_fields = ('user', 'granted_by')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'admin_user', 'target_user', 'permission', 'action')
    list_filter = ('action', 'permission__app')
    search_fields = ('admin_user__username', 'target_user__username')
    readonly_fields = ('timestamp', 'admin_user', 'target_user', 'permission', 'action')
    date_hierarchy = 'timestamp'
