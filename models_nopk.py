# models.py
from django.db import models
from django.contrib.auth.models import User
import json

class Server(models.Model):
    # === IDENTITY AND NETWORK ===
    hostname = models.CharField(max_length=255, db_index=True, verbose_name="Hostname")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP Address")
    dns_primary = models.GenericIPAddressField(null=True, blank=True, verbose_name="Primary DNS")
    dns_secondary = models.GenericIPAddressField(null=True, blank=True, verbose_name="Secondary DNS")
    gateway = models.GenericIPAddressField(null=True, blank=True, verbose_name="Gateway")
    subnet_mask = models.CharField(max_length=15, null=True, blank=True, verbose_name="Subnet Mask")
    
    # === SYSTEM ===
    os = models.CharField(max_length=100, null=True, blank=True, db_index=True, verbose_name="Operating System")
    os_version = models.CharField(max_length=50, null=True, blank=True, verbose_name="OS Version")
    
    # === HARDWARE ===
    ram = models.CharField(max_length=50, null=True, blank=True, verbose_name="RAM")
    cpu = models.CharField(max_length=100, null=True, blank=True, verbose_name="Processor")
    cpu_cores = models.CharField(max_length=10, null=True, blank=True, verbose_name="CPU Cores")
    storage_type = models.CharField(max_length=50, null=True, blank=True, verbose_name="Storage Type")
    storage_size = models.CharField(max_length=50, null=True, blank=True, verbose_name="Storage Size")
    
    # === INFRASTRUCTURE ===
    datacenter = models.CharField(max_length=100, null=True, blank=True, db_index=True, verbose_name="Datacenter")
    rack = models.CharField(max_length=20, null=True, blank=True, verbose_name="Rack")
    availability_zone = models.CharField(max_length=50, null=True, blank=True, verbose_name="Availability Zone")
    network_vlan = models.CharField(max_length=50, null=True, blank=True, verbose_name="VLAN")
    network_speed = models.CharField(max_length=50, null=True, blank=True, verbose_name="Network Speed")
    
    # === APPLICATIONS AND SERVICES ===
    application = models.CharField(max_length=255, null=True, blank=True, db_index=True, verbose_name="Application")
    service_level = models.CharField(max_length=50, null=True, blank=True, verbose_name="Service Level")
    db_instance = models.CharField(max_length=255, null=True, blank=True, verbose_name="Database Instance")
    
    # === MANAGEMENT AND OWNERSHIP ===
    owner = models.CharField(max_length=100, null=True, blank=True, db_index=True, verbose_name="Owner")
    business_unit = models.CharField(max_length=100, null=True, blank=True, verbose_name="Business Unit")
    cost_center = models.CharField(max_length=50, null=True, blank=True, verbose_name="Cost Center")
    project_code = models.CharField(max_length=50, null=True, blank=True, verbose_name="Project Code")
    support_email = models.EmailField(null=True, blank=True, verbose_name="Support Email")
    
    # === VIRTUALIZATION ===
    virtualization = models.CharField(max_length=50, null=True, blank=True, verbose_name="Virtualization Technology")
    
    # === IMPORTANT DATES ===
    install_date = models.DateField(null=True, blank=True, verbose_name="Installation Date")
    last_boot_time = models.DateTimeField(null=True, blank=True, verbose_name="Last Boot Time")
    warranty_expiry = models.DateField(null=True, blank=True, verbose_name="Warranty Expiry")
    purchase_date = models.DateField(null=True, blank=True, verbose_name="Purchase Date")
    
    # === SECURITY AND COMPLIANCE ===
    security_zone = models.CharField(max_length=50, null=True, blank=True, verbose_name="Security Zone")
    compliance_level = models.CharField(max_length=50, null=True, blank=True, verbose_name="Compliance Level")
    antivirus = models.CharField(max_length=100, null=True, blank=True, verbose_name="Antivirus")
    patch_group = models.CharField(max_length=50, null=True, blank=True, verbose_name="Patch Group")
    
    # === MONITORING AND MAINTENANCE ===
    monitoring_tool = models.CharField(max_length=100, null=True, blank=True, verbose_name="Monitoring Tool")
    backup_policy = models.CharField(max_length=50, null=True, blank=True, verbose_name="Backup Policy")
    maintenance_window = models.CharField(max_length=100, null=True, blank=True, verbose_name="Maintenance Window")
    
    # === CURRENT STATES ===
    power_state = models.CharField(max_length=50, null=True, blank=True, verbose_name="Power State")
    health_status = models.CharField(max_length=50, null=True, blank=True, verbose_name="Health Status")
    deployment_status = models.CharField(max_length=50, null=True, blank=True, verbose_name="Deployment Status")
    
    # === PERFORMANCE METRICS ===
    cpu_utilization = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="CPU Utilization (%)")
    memory_utilization = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Memory Utilization (%)")
    disk_utilization = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Disk Utilization (%)")
    network_in_mbps = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Network In (Mbps)")
    network_out_mbps = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Network Out (Mbps)")
    
    # === HARDWARE IDENTIFICATION ===
    serial_number = models.CharField(max_length=50, null=True, blank=True, verbose_name="Serial Number")
    asset_tag = models.CharField(max_length=50, null=True, blank=True, verbose_name="Asset Tag")
    
    # === NOTES AND COMMENTS ===
    notes = models.TextField(null=True, blank=True, verbose_name="General Notes")
    configuration_notes = models.TextField(null=True, blank=True, verbose_name="Configuration Notes")
    tags = models.CharField(max_length=500, null=True, blank=True, verbose_name="Tags/Labels")
    
    # === TECHNICAL FIELDS (do not modify) ===
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.hostname} - {self.application or 'No App'}"
    
    class Meta:
        ordering = ['hostname']
        indexes = [
            models.Index(fields=['hostname']),
            models.Index(fields=['os']),
            models.Index(fields=['datacenter']),
            models.Index(fields=['owner']),
            models.Index(fields=['application']),
        ]

class ServerStaging(models.Model):
    # === IDENTITY AND NETWORK ===
    hostname = models.CharField(max_length=255, db_index=True, verbose_name="Hostname")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP Address")
    dns_primary = models.GenericIPAddressField(null=True, blank=True, verbose_name="Primary DNS")
    dns_secondary = models.GenericIPAddressField(null=True, blank=True, verbose_name="Secondary DNS")
    gateway = models.GenericIPAddressField(null=True, blank=True, verbose_name="Gateway")
    subnet_mask = models.CharField(max_length=15, null=True, blank=True, verbose_name="Subnet Mask")
    
    # === SYSTEM ===
    os = models.CharField(max_length=100, null=True, blank=True, db_index=True, verbose_name="Operating System")
    os_version = models.CharField(max_length=50, null=True, blank=True, verbose_name="OS Version")
    
    # === HARDWARE ===
    ram = models.CharField(max_length=50, null=True, blank=True, verbose_name="RAM")
    cpu = models.CharField(max_length=100, null=True, blank=True, verbose_name="Processor")
    cpu_cores = models.CharField(max_length=10, null=True, blank=True, verbose_name="CPU Cores")
    storage_type = models.CharField(max_length=50, null=True, blank=True, verbose_name="Storage Type")
    storage_size = models.CharField(max_length=50, null=True, blank=True, verbose_name="Storage Size")
    
    # === INFRASTRUCTURE ===
    datacenter = models.CharField(max_length=100, null=True, blank=True, db_index=True, verbose_name="Datacenter")
    rack = models.CharField(max_length=20, null=True, blank=True, verbose_name="Rack")
    availability_zone = models.CharField(max_length=50, null=True, blank=True, verbose_name="Availability Zone")
    network_vlan = models.CharField(max_length=50, null=True, blank=True, verbose_name="VLAN")
    network_speed = models.CharField(max_length=50, null=True, blank=True, verbose_name="Network Speed")
    
    # === APPLICATIONS AND SERVICES ===
    application = models.CharField(max_length=255, null=True, blank=True, db_index=True, verbose_name="Application")
    service_level = models.CharField(max_length=50, null=True, blank=True, verbose_name="Service Level")
    db_instance = models.CharField(max_length=255, null=True, blank=True, verbose_name="Database Instance")
    
    # === MANAGEMENT AND OWNERSHIP ===
    owner = models.CharField(max_length=100, null=True, blank=True, db_index=True, verbose_name="Owner")
    business_unit = models.CharField(max_length=100, null=True, blank=True, verbose_name="Business Unit")
    cost_center = models.CharField(max_length=50, null=True, blank=True, verbose_name="Cost Center")
    project_code = models.CharField(max_length=50, null=True, blank=True, verbose_name="Project Code")
    support_email = models.EmailField(null=True, blank=True, verbose_name="Support Email")
    
    # === VIRTUALIZATION ===
    virtualization = models.CharField(max_length=50, null=True, blank=True, verbose_name="Virtualization Technology")
    
    # === IMPORTANT DATES ===
    install_date = models.DateField(null=True, blank=True, verbose_name="Installation Date")
    last_boot_time = models.DateTimeField(null=True, blank=True, verbose_name="Last Boot Time")
    warranty_expiry = models.DateField(null=True, blank=True, verbose_name="Warranty Expiry")
    purchase_date = models.DateField(null=True, blank=True, verbose_name="Purchase Date")
    
    # === SECURITY AND COMPLIANCE ===
    security_zone = models.CharField(max_length=50, null=True, blank=True, verbose_name="Security Zone")
    compliance_level = models.CharField(max_length=50, null=True, blank=True, verbose_name="Compliance Level")
    antivirus = models.CharField(max_length=100, null=True, blank=True, verbose_name="Antivirus")
    patch_group = models.CharField(max_length=50, null=True, blank=True, verbose_name="Patch Group")
    
    # === MONITORING AND MAINTENANCE ===
    monitoring_tool = models.CharField(max_length=100, null=True, blank=True, verbose_name="Monitoring Tool")
    backup_policy = models.CharField(max_length=50, null=True, blank=True, verbose_name="Backup Policy")
    maintenance_window = models.CharField(max_length=100, null=True, blank=True, verbose_name="Maintenance Window")
    
    # === CURRENT STATES ===
    power_state = models.CharField(max_length=50, null=True, blank=True, verbose_name="Power State")
    health_status = models.CharField(max_length=50, null=True, blank=True, verbose_name="Health Status")
    deployment_status = models.CharField(max_length=50, null=True, blank=True, verbose_name="Deployment Status")
    
    # === PERFORMANCE METRICS ===
    cpu_utilization = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="CPU Utilization (%)")
    memory_utilization = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Memory Utilization (%)")
    disk_utilization = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Disk Utilization (%)")
    network_in_mbps = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Network In (Mbps)")
    network_out_mbps = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Network Out (Mbps)")
    
    # === HARDWARE IDENTIFICATION ===
    serial_number = models.CharField(max_length=50, null=True, blank=True, verbose_name="Serial Number")
    asset_tag = models.CharField(max_length=50, null=True, blank=True, verbose_name="Asset Tag")
    
    # === NOTES AND COMMENTS ===
    notes = models.TextField(null=True, blank=True, verbose_name="General Notes")
    configuration_notes = models.TextField(null=True, blank=True, verbose_name="Configuration Notes")
    tags = models.CharField(max_length=500, null=True, blank=True, verbose_name="Tags/Labels")
    
    # === TECHNICAL FIELDS (do not modify) ===
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.hostname} - {self.application or 'No App'}"
    
    class Meta:
        managed = False 
        db_table = 'claude_server_staging'


class ServerGroupSummary(models.Model):
    hostname = models.CharField(max_length=255, unique=True, db_index=True)
    total_instances = models.PositiveIntegerField()
    constant_fields = models.JSONField(default=dict)
    variable_fields = models.JSONField(default=dict)

    #primary_server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='as_primary')

    @property
    def servers(self):
        """Tous les serveurs de ce groupe"""
        return Server.objects.filter(hostname=self.hostname)
    
    @property
    def primary_server_new(self):
        """Nouveau: premier serveur par hostname (sans FK)"""
        return self.servers.first()


class ServerGroupSummaryStaging(models.Model):
    hostname = models.CharField(max_length=255, unique=True, db_index=True)
    total_instances = models.PositiveIntegerField()
    constant_fields = models.JSONField(default=dict)
    variable_fields = models.JSONField(default=dict)
    primary_server_id = models.IntegerField()  # Simple integer, pas de ForeignKey !
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        managed = False  # Django ne gère pas cette table
        db_table = 'claude_servergroupsummary_staging'
        

class ServerAnnotation(models.Model):
    """
    Persistent manual annotations on servers.
    Survives data imports.
    """
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]
    
    STATUS_CHOICES = [
        ('production', 'In Production'),
        ('maintenance', 'Under Maintenance'),
        ('upgrade_needed', 'Needs Upgrade'),
        ('decommission', 'To Decommission'),
        ('monitoring', 'Under Monitoring'),
        ('custom', 'Custom'),
    ]
    
    hostname = models.CharField(max_length=255, unique=True, db_index=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='production')
    custom_status = models.CharField(max_length=200, blank=True, help_text="Custom status if 'custom' selected")
    notes = models.TextField(blank=True, help_text="Detailed notes and comments")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    
    # Audit metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='annotations_created')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='annotations_updated')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def get_display_status(self):
        """Returns the status to display (custom_status if status='custom', otherwise the choice label)"""
        if self.status == 'custom' and self.custom_status:
            return self.custom_status
        return dict(self.STATUS_CHOICES).get(self.status, self.status)
    
    def get_priority_badge_class(self):
        """Returns the CSS class for the priority badge"""
        priority_classes = {
            'low': 'badge-priority-low',
            'normal': 'badge-priority-normal', 
            'high': 'badge-priority-high',
            'critical': 'badge-priority-critical',
        }
        return priority_classes.get(self.priority, 'badge-priority-normal')
    
    def __str__(self):
        return f"{self.hostname} - {self.get_display_status()}"
    
    class Meta:
        ordering = ['hostname']
        verbose_name = "Server Annotation"
        verbose_name_plural = "Server Annotations"