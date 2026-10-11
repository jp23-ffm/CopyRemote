from django.db import models
from django.utils import timezone


class StorageShare(models.Model):
    ID = models.CharField(max_length=255, db_column='share_id')
    PROVIDER = models.CharField(max_length=100, null=True, blank=True)
    CLUSTER = models.CharField(max_length=255, null=True, blank=True)
    FILER = models.CharField(max_length=255, null=True, blank=True)
    SHARE_NAME = models.CharField(max_length=500, db_index=True, null=True, blank=True)
    SHARE_REAL_NAME = models.CharField(max_length=500, null=True, blank=True)
    SHARE_PATH = models.CharField(max_length=1000, null=True, blank=True)
    VOLUME = models.CharField(max_length=255, null=True, blank=True)
    PROTOCOL = models.CharField(max_length=100, null=True, blank=True)
    IP_ADDRESS = models.CharField(max_length=100, null=True, blank=True)
    UUID = models.CharField(max_length=255, null=True, blank=True)
    CONSUMER_TYPE = models.CharField(max_length=100, null=True, blank=True)
    ALLOCATION = models.CharField(max_length=100, null=True, blank=True)
    USAGE = models.CharField(max_length=100, null=True, blank=True)
    APPLICATION_NAME = models.CharField(max_length=500, null=True, blank=True)
    BAM_VALUE = models.CharField(max_length=255, null=True, blank=True)
    APPLICATION_AUID_VALUE = models.CharField(max_length=255, null=True, blank=True)
    ENVIRONMENT = models.CharField(max_length=100, null=True, blank=True)
    IS_OPEN = models.CharField(max_length=50, null=True, blank=True)
    OPEN_SHARE_EXCEPTION = models.CharField(max_length=50, null=True, blank=True)
    REGION = models.CharField(max_length=100, null=True, blank=True)
    COUNTRY = models.CharField(max_length=100, null=True, blank=True)
    SCOPE = models.CharField(max_length=255, null=True, blank=True)
    ECOSYSTEM = models.CharField(max_length=100, null=True, blank=True)
    VITAL_APPLICATION = models.CharField(max_length=50, null=True, blank=True)
    IT_CLUSTER = models.CharField(max_length=255, null=True, blank=True)
    IT_SUBCLUSTER = models.CharField(max_length=255, null=True, blank=True)
    IN_NAS_REF = models.CharField(max_length=50, null=True, blank=True)
    IN_NETAPP_SCANNER = models.CharField(max_length=50, null=True, blank=True)
    IN_NAS_CAPSULE = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['SHARE_NAME']),
            models.Index(fields=['PROVIDER']),
            models.Index(fields=['ENVIRONMENT']),
            models.Index(fields=['REGION']),
        ]

    def __str__(self):
        return self.SHARE_NAME or self.ID or ''


class StorageObject(models.Model):
    ID = models.CharField(max_length=255, db_column='object_id')
    NAME = models.CharField(max_length=500, db_index=True, null=True, blank=True)
    PROTOCOL = models.CharField(max_length=100, null=True, blank=True)
    ALLOCATION = models.CharField(max_length=100, null=True, blank=True)
    USAGE = models.CharField(max_length=100, null=True, blank=True)
    APPLICATION_NAME = models.CharField(max_length=500, null=True, blank=True)
    BAM_VALUE = models.CharField(max_length=255, null=True, blank=True)
    AUID_VALUE = models.CharField(max_length=255, null=True, blank=True)
    ENVIRONMENT = models.CharField(max_length=100, null=True, blank=True)
    REGION = models.CharField(max_length=100, null=True, blank=True)
    COUNTRY = models.CharField(max_length=100, null=True, blank=True)
    SCOPE = models.CharField(max_length=255, null=True, blank=True)
    ECOSYSTEM = models.CharField(max_length=100, null=True, blank=True)
    IT_CLUSTER = models.CharField(max_length=255, null=True, blank=True)
    IT_SUBCLUSTER = models.CharField(max_length=255, null=True, blank=True)
    IN_S3_REF = models.CharField(max_length=50, null=True, blank=True)
    IN_CAPSULE_REF_S3 = models.CharField(max_length=50, null=True, blank=True)
    CAPSULE_SPECIAL_USECASE = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['NAME']),
            models.Index(fields=['PROTOCOL']),
            models.Index(fields=['ENVIRONMENT']),
            models.Index(fields=['REGION']),
        ]

    def __str__(self):
        return self.NAME or self.ID or ''


# CHANGED: SHARE_ID field renamed to SHARE_NAME — annotations now keyed on SHARE_NAME
class ShareAnnotation(models.Model):
    share_key = models.CharField(max_length=1500, unique=True, db_index=True)  # f"{FILER}|{SHARE_PATH}"
    comment = models.TextField(blank=True)
    assigned_to = models.CharField(max_length=150, blank=True)
    history = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

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

    def __str__(self):
        return self.share_key


class ObjectAnnotation(models.Model):
    NAME = models.CharField(max_length=500, unique=True, db_index=True)
    comment = models.TextField(blank=True)
    assigned_to = models.CharField(max_length=150, blank=True)
    history = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

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

    def __str__(self):
        return self.NAME


class StorageImportStatus(models.Model):
    source = models.CharField(max_length=20)  # 'share' or 'object'
    date_import = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    message = models.TextField(blank=True, null=True)
    nb_entries_created = models.IntegerField(default=0)

    def __str__(self):
        return f"[{self.source}] {'OK' if self.success else 'KO'} {self.date_import.strftime('%d.%m.%Y %H:%M')}"


# ------- Missing-data discrepancies (shares / objects) -------

class StorageDiscrepancy(models.Model):
    """Current state: one row per asset with at least one required field missing (replaced on each analysis)."""
    resource_type = models.CharField(max_length=10)  # 'share' or 'object'
    asset_key = models.CharField(max_length=1500)  # same key as ShareAnnotation.share_key / ObjectAnnotation.NAME
    region = models.CharField(max_length=100, blank=True)
    scope = models.CharField(max_length=255, blank=True)
    # Comma-separated list of missing required fields, e.g. "BAM_VALUE,IT_CLUSTER"
    missing_fields = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['resource_type', 'asset_key'], name='storagedisc_type_key_uniq'),
        ]
        indexes = [
            models.Index(fields=['resource_type', 'scope'], name='storagedisc_type_scope_idx'),
            models.Index(fields=['resource_type', 'region'], name='storagedisc_type_region_idx'),
        ]

    def __str__(self):
        return f"[{self.resource_type}] {self.asset_key} - {self.missing_fields}"

    @property
    def missing_fields_list(self):
        return [f for f in self.missing_fields.split(',') if f]


class StorageDiscrepancyTracking(models.Model):
    """Per-asset first_seen bookkeeping for days_open (row deleted once nothing is missing)."""
    resource_type = models.CharField(max_length=10)
    asset_key = models.CharField(max_length=1500)
    # {field_name: {"first_seen": "<ISO datetime>"}}
    active_issues = models.JSONField(default=dict)
    # Denormalised: oldest first_seen across active_issues, for fast SQL sorting/filtering
    oldest_first_seen = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['resource_type', 'asset_key'], name='storagedisctrack_type_key_uniq'),
        ]
        indexes = [
            models.Index(fields=['oldest_first_seen'], name='storagedisctrack_oldest_idx'),
        ]

    def __str__(self):
        return f"[{self.resource_type}] {self.asset_key} - {len(self.active_issues)} active issues"


class StorageAnalysisSnapshot(models.Model):
    """Summary of one analysis run for one resource type — feeds gauges population and trend chart."""
    resource_type = models.CharField(max_length=10)
    analysis_date = models.DateTimeField(db_index=True)
    total_assets = models.IntegerField(default=0)
    assets_with_issues = models.IntegerField(default=0)
    # {field_name: count}
    field_counts = models.JSONField(default=dict)
    # {region: {scope: {"total": n, "with_issues": n, "field_counts": {field_name: count}}}}
    breakdown = models.JSONField(default=dict)
    duration_seconds = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['-analysis_date']
        constraints = [
            models.UniqueConstraint(fields=['resource_type', 'analysis_date'], name='storagesnap_type_date_uniq'),
        ]

    def __str__(self):
        return f"[{self.resource_type}] {self.analysis_date} - {self.assets_with_issues}/{self.total_assets}"
