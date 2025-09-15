# admin.py
from django.contrib import admin
from .models import Server, ServerAnnotation, ServerGroupSummary

@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = ['hostname', 'application', 'os', 'ram', 'datacenter', 'owner']
    list_filter = ['os', 'datacenter', 'owner', 'business_unit', 'service_level', 'power_state', 'created_at']
    search_fields = ['hostname', 'application', 'owner', 'ip_address', 'serial_number', 'asset_tag']
    list_per_page = 50
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Identification', {
            'fields': ('hostname', 'ip_address', 'serial_number', 'asset_tag')
        }),
        ('Système', {
            'fields': ('os', 'os_version', 'ram', 'cpu', 'cpu_cores'),
            'classes': ('collapse',)
        }),
        ('Stockage et réseau', {
            'fields': ('storage_type', 'storage_size', 'network_speed', 'dns_primary', 'dns_secondary'),
            'classes': ('collapse',)
        }),
        ('Infrastructure', {
            'fields': ('datacenter', 'rack', 'availability_zone', 'network_vlan', 'virtualization')
        }),
        ('Applications et services', {
            'fields': ('application', 'service_level', 'db_instance')
        }),
        ('Management', {
            'fields': ('owner', 'business_unit', 'cost_center', 'project_code', 'support_email'),
            'classes': ('collapse',)
        }),
        ('Dates importantes', {
            'fields': ('install_date', 'purchase_date', 'warranty_expiry', 'last_boot_time'),
            'classes': ('collapse',)
        }),
        ('Sécurité', {
            'fields': ('security_zone', 'compliance_level', 'antivirus', 'patch_group'),
            'classes': ('collapse',)
        }),
        ('Monitoring', {
            'fields': ('monitoring_tool', 'backup_policy', 'maintenance_window'),
            'classes': ('collapse',)
        }),
        ('États actuels', {
            'fields': ('power_state', 'health_status', 'deployment_status')
        }),
        ('Métriques', {
            'fields': ('cpu_utilization', 'memory_utilization', 'disk_utilization', 'network_in_mbps', 'network_out_mbps'),
            'classes': ('collapse',)
        }),
        ('Notes', {
            'fields': ('notes', 'configuration_notes', 'tags'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ServerGroupSummary)
class ServerGroupSummaryAdmin(admin.ModelAdmin):
    list_display = ['hostname', 'total_instances', 'primary_server', 'last_updated']
    list_filter = ['total_instances', 'last_updated']
    search_fields = ['hostname']
    readonly_fields = ['hostname', 'total_instances', 'constant_fields', 'variable_fields', 'primary_server', 'last_updated']
    list_per_page = 50
    
    def has_add_permission(self, request):
        # Empêcher l'ajout manuel - ces données sont générées automatiquement
        return False
    
    def has_change_permission(self, request, obj=None):
        # Empêcher la modification manuelle
        return False


@admin.register(ServerAnnotation)
class ServerAnnotationAdmin(admin.ModelAdmin):
    list_display = ['hostname', 'get_display_status', 'priority', 'updated_by', 'updated_at']
    list_filter = ['status', 'priority', 'created_by', 'updated_by', 'created_at']
    search_fields = ['hostname', 'notes', 'custom_status']
    list_per_page = 50
    readonly_fields = ['created_by', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Serveur', {
            'fields': ('hostname',)
        }),
        ('Annotation', {
            'fields': ('status', 'custom_status', 'priority', 'notes')
        }),
        ('Audit', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:  # Nouvel objet
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)