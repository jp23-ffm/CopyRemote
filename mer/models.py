from django.db import models
from django.utils import timezone


class ServerDiscrepancy(models.Model):
    """
    Stores servers with data quality issues detected during analysis.
    Each record represents a server that has at least one invalid or missing field.
    Missing/invalid values are stored as 'MISSING' for easy filtering.
    """
    
    SERVER_ID = models.CharField(max_length=100, db_index=True)
    analysis_date = models.DateTimeField()
    
    # Comma-separated list of missing field names
    missing_fields = models.TextField(blank=True)
    
    # Data fields being validated
    # Values are stored as-is if valid, or 'MISSING' if invalid/empty
    LIVE_STATUS = models.CharField(max_length=200, blank=True, null=True)
    OSSHORTNAME = models.CharField(max_length=200, blank=True, null=True)
    OSFAMILY = models.CharField(max_length=200, blank=True, null=True)
    MACHINE_TYPE = models.CharField(max_length=100, blank=True, null=True)
    MANUFACTURER = models.CharField(max_length=200, blank=True, null=True)
    COUNTRY = models.CharField(max_length=100, blank=True, null=True)
    APP_AUID_VALUE = models.CharField(max_length=100, blank=True, null=True)
    APP_NAME_VALUE = models.CharField(max_length=100, blank=True, null=True)
    REGION = models.CharField(max_length=200, blank=True, null=True)
    CITY = models.CharField(max_length=200, blank=True, null=True)
    INFRAVERSION = models.CharField(max_length=50, blank=True, null=True)
    IPADDRESS = models.CharField(max_length=100, blank=True, null=True)
    SNOW_STATUS = models.CharField(max_length=50, blank=True, null=True)

    # Hardware-specific fields (checked on PHYSICAL servers only)
    IDRAC_NAME = models.CharField(max_length=200, blank=True, null=True)
    IDRAC_IP = models.CharField(max_length=100, blank=True, null=True)

    # Validation error flags - 'OK' or 'KO'
    # These flags indicate logical inconsistencies between fields
    live_status_inconsistent = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    snow_status_inconsistent = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    # Add more inconsistency checks here as needed
    
    class Meta:
        db_table = 'discrepancies_serverdiscrepancy'
        indexes = [
            models.Index(fields=['analysis_date']),
            models.Index(fields=['SERVER_ID', 'analysis_date']),
        ]
    
    def __str__(self):
        return f"{self.SERVER_ID} - {self.analysis_date}"


class AnalysisSnapshot(models.Model):
    """
    Summary statistics for each analysis run.
    Stores pre-calculated metrics for fast dashboard rendering.
    """
    
    analysis_date = models.DateTimeField(unique=True, db_index=True)
    
    # Global metrics
    total_servers_analyzed = models.IntegerField()
    servers_with_issues = models.IntegerField()
    servers_clean = models.IntegerField()
    
    # Per-field issue counts
    missing_live_status_count = models.IntegerField(default=0)
    missing_osshortname_count = models.IntegerField(default=0)
    missing_osfamily_count = models.IntegerField(default=0)
    missing_machine_type_count = models.IntegerField(default=0)
    missing_manufacturer_count = models.IntegerField(default=0)
    missing_country_count = models.IntegerField(default=0)
    missing_app_auid_value_count = models.IntegerField(default=0)
    missing_app_name_value_count = models.IntegerField(default=0)
    missing_region_count = models.IntegerField(default=0)
    missing_city_count = models.IntegerField(default=0)
    missing_infraversion_count = models.IntegerField(default=0)
    missing_ipaddress_count = models.IntegerField(default=0)
    missing_snow_status_count = models.IntegerField(default=0)

    # Hardware-specific issue counts (PHYSICAL servers only)
    missing_idrac_name_count = models.IntegerField(default=0)
    missing_idrac_ip_count = models.IntegerField(default=0)

    # Validation error counts
    live_status_inconsistent_count = models.IntegerField(default=0)
    snow_status_inconsistent_count = models.IntegerField(default=0)
    # Add more inconsistency counters here as needed
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    
    class Meta:
        db_table = 'discrepancies_analysissnapshot'
        ordering = ['-analysis_date']
    
    def __str__(self):
        return f"Analysis {self.analysis_date} - {self.servers_with_issues}/{self.total_servers_analyzed} issues"
    
    @property
    def percentage_with_issues(self):
        """Calculate percentage of servers with issues"""
        if self.total_servers_analyzed == 0:
            return 0
        return round((self.servers_with_issues / self.total_servers_analyzed) * 100, 2)
    
    @property
    def percentage_clean(self):
        """Calculate percentage of clean servers"""
        return round(100 - self.percentage_with_issues, 2)


class DiscrepancyTracker(models.Model):
    """
    Tracks the duration of each discrepancy issue per server and field.
    One row per (SERVER_ID, field_name) combination.
    Keeps resolved entries for historical reference.
    """

    SERVER_ID = models.CharField(max_length=100, db_index=True)
    field_name = models.CharField(max_length=100, db_index=True)

    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()

    is_resolved = models.BooleanField(default=False, db_index=True)
    resolved_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'discrepancies_discrepancytracker'
        unique_together = [('SERVER_ID', 'field_name')]
        indexes = [
            models.Index(fields=['is_resolved', 'first_seen']),
            models.Index(fields=['SERVER_ID', 'is_resolved']),
        ]

    def __str__(self):
        status = 'resolved' if self.is_resolved else f'open {self.days_open}d'
        return f"{self.SERVER_ID} - {self.field_name} ({status})"

    @property
    def days_open(self):
        if self.is_resolved:
            return (self.resolved_date - self.first_seen).days + 1
        return (timezone.now() - self.first_seen).days + 1


class DiscrepancyAnnotation(models.Model):
    SERVER_ID = models.CharField(max_length=255, unique=True, db_index=True)
    comment = models.TextField(blank=True)
    assigned_to = models.CharField(max_length=150, blank=True)
    history = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'discrepancies_discrepancyannotation'

    def add_entry(self, comment, assigned_to, user):
        if not self.history:
            self.history = []
        self.history.append({
            'comment': comment,
            'assigned_to': assigned_to,
            'user': user.username if user else 'Unknown',
            'date': timezone.now().isoformat(),
        })
        self.comment = comment
        self.assigned_to = assigned_to
        self.save()

    def get_history_display(self):
        if not self.history:
            return []
        return sorted(self.history, key=lambda x: x['date'], reverse=True)