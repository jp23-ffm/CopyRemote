from django.db import models
from django.utils import timezone


class ServerStaging(models.Model):
    SERIAL = models.CharField(max_length=100, db_index=True)
    REGION = models.CharField(max_length=100, null=True, blank=True)
    COUNTRY = models.CharField(max_length=100, null=True, blank=True)
    DATACENTER = models.CharField(max_length=100, null=True, blank=True)
    MANUFACTURER = models.CharField(max_length=100, null=True, blank=True)
    MODEL = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_ACTIVE = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_ACTUAL_SUPPLIER = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_INITIAL_PROVIDER_NAME = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_INITIAL_START_DATE = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_INITIAL_END_DATE = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_EXTENSION_PROVIDER_NAME = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_EXTENSION_START_DATE = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_EXTENSION_END_DATE = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_SUPPORT_LEVEL = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_TO_STOP = models.CharField(max_length=100, null=True, blank=True)
    IDRAC_NAME = models.CharField(max_length=100, null=True, blank=True)
    IDRAC_IP = models.CharField(max_length=100, null=True, blank=True)
    IDRAC_MAC = models.CharField(max_length=100, null=True, blank=True)
    IDRAC_LIVE_STATUS = models.CharField(max_length=100, null=True, blank=True)
    INFRAVERSION = models.CharField(max_length=100, null=True, blank=True)
    SERVER_ID = models.CharField(max_length=100, null=True, blank=True)
    SERVER_IP = models.CharField(max_length=100, null=True, blank=True)
    LIVE_STATUS = models.CharField(max_length=100, null=True, blank=True)
    TECHFAMILY = models.CharField(max_length=100, null=True, blank=True)
    SUBTECHFAMILY = models.CharField(max_length=100, null=True, blank=True)
    OSFAMILY = models.CharField(max_length=100, null=True, blank=True)
    OSFULLVERSION = models.CharField(max_length=100, null=True, blank=True)
    COUNT = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'hardware_serverstaging'
        indexes = [
            models.Index(fields=['SERIAL']),
            models.Index(fields=['MANUFACTURER']),
            models.Index(fields=['SERVER_ID']),
            models.Index(fields=['MODEL']),
        ]

    def __str__(self):
        return self.SERIAL


class Server(models.Model):
    SERIAL = models.CharField(max_length=100, db_index=True)
    REGION = models.CharField(max_length=100, null=True, blank=True)
    COUNTRY = models.CharField(max_length=100, null=True, blank=True)
    DATACENTER = models.CharField(max_length=100, null=True, blank=True)
    MANUFACTURER = models.CharField(max_length=100, null=True, blank=True)
    MODEL = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_ACTIVE = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_ACTUAL_SUPPLIER = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_INITIAL_PROVIDER_NAME = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_INITIAL_START_DATE = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_INITIAL_END_DATE = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_EXTENSION_PROVIDER_NAME = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_EXTENSION_START_DATE = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_EXTENSION_END_DATE = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_SUPPORT_LEVEL = models.CharField(max_length=100, null=True, blank=True)
    WARRANTY_TO_STOP = models.CharField(max_length=100, null=True, blank=True)
    IDRAC_NAME = models.CharField(max_length=100, null=True, blank=True)
    IDRAC_IP = models.CharField(max_length=100, null=True, blank=True)
    IDRAC_MAC = models.CharField(max_length=100, null=True, blank=True)
    IDRAC_LIVE_STATUS = models.CharField(max_length=100, null=True, blank=True)
    INFRAVERSION = models.CharField(max_length=100, null=True, blank=True)
    SERVER_ID = models.CharField(max_length=100, null=True, blank=True)
    SERVER_IP = models.CharField(max_length=100, null=True, blank=True)
    LIVE_STATUS = models.CharField(max_length=100, null=True, blank=True)
    TECHFAMILY = models.CharField(max_length=100, null=True, blank=True)
    SUBTECHFAMILY = models.CharField(max_length=100, null=True, blank=True)
    OSFAMILY = models.CharField(max_length=100, null=True, blank=True)
    OSFULLVERSION = models.CharField(max_length=100, null=True, blank=True)
    COUNT = models.IntegerField(default=0)
    
    class Meta:
        indexes = [
            models.Index(fields=['SERIAL']),
            models.Index(fields=['MANUFACTURER']),
            models.Index(fields=['SERVER_ID']),
            models.Index(fields=['MODEL']),

        ]

    def __str__(self):
        return self.SERIAL


class Annotation(models.Model):
    SERIAL = models.CharField(max_length=255, unique=True, db_index=True)
    comment = models.TextField(blank=True)
    assigned_to = models.CharField(max_length=150, blank=True)
    history = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'hardware_annotation'

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
        

class ImportStatus(models.Model):
    date_import = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    message = models.TextField(blank=True, null=True)
    nb_entries_created = models.IntegerField(default=0)

    def __str__(self):
        return f"{'OK' if self.success else 'KO'} {self.date_import.strftime('%d.%m.%Y %H:%M')}"


# ------- Data-quality discrepancies (missing / invalid fields) -------

class HardwareDiscrepancy(models.Model):
    """Current state: one row per SERIAL with at least one check failing (replaced on each analysis)."""
    SERIAL = models.CharField(max_length=100, unique=True)  # same key as Annotation.SERIAL
    region = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    # Comma-separated list of failing checks (field names), e.g. "IDRAC_IP,SERVER_IP"
    missing_fields = models.TextField(blank=True)
    # Number of the serial's rows failing each check + "_any" — dashboard counts are in rows
    row_counts = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['region'], name='hwdisc_region_idx'),
            models.Index(fields=['country'], name='hwdisc_country_idx'),
        ]

    def __str__(self):
        return f"{self.SERIAL} - {self.missing_fields}"


class HardwareDiscrepancyTracking(models.Model):
    """Per-serial first_seen bookkeeping for days_open (row deleted once every check passes)."""
    SERIAL = models.CharField(max_length=100, unique=True)
    # {field_name: {"first_seen": "<ISO datetime>"}}
    active_issues = models.JSONField(default=dict)
    # Denormalised: oldest first_seen across active_issues, for fast SQL sorting/filtering
    oldest_first_seen = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['oldest_first_seen'], name='hwdisctrack_oldest_idx'),
        ]

    def __str__(self):
        return f"{self.SERIAL} - {len(self.active_issues)} active issues"


class HardwareAnalysisSnapshot(models.Model):
    """Summary of one analysis run — feeds gauges population and trend chart (counts are rows)."""
    analysis_date = models.DateTimeField(unique=True)
    total_rows = models.IntegerField(default=0)
    rows_with_issues = models.IntegerField(default=0)
    # {field_name: count}
    field_counts = models.JSONField(default=dict)
    # {region: {country: {"total": n, "with_issues": n, "field_counts": {field_name: count}}}}
    breakdown = models.JSONField(default=dict)
    duration_seconds = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['-analysis_date']

    def __str__(self):
        return f"{self.analysis_date} - {self.rows_with_issues}/{self.total_rows}"
