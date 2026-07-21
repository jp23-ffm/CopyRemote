from django.db import models
from django.utils import timezone


def safe_percentage(count, total):
    """
    count/total as a percentage, rounded to 2 decimals — except a nonzero count never
    rounds down to a literal 0.0 (1 server out of a large population must not silently
    read as "no issues"), it floors to 0.01 instead. Numeric, not a display string:
    callers include Excel severity-fill thresholds (pct >= 20 etc.) that compare it.
    """
    if not total:
        return 0
    pct = round((count / total) * 100, 2)
    if count > 0 and pct == 0:
        return 0.01
    return pct


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
    SNOW_SUPPORTGROUP = models.CharField(max_length=200, blank=True, null=True)
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
    IDRAC_NAME = models.CharField(max_length=200, blank=True, null=True)
    IDRAC_IP = models.CharField(max_length=100, blank=True, null=True)
    
    # Validation error flags (boolean)
    # These flags indicate logical inconsistencies between fields
    alive_status_inconsistent = models.CharField(max_length=50, blank=True, null=True)
    dead_status_inconsistent = models.CharField(max_length=50, blank=True, null=True)

    
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
    total_physical_servers = models.IntegerField()
    servers_with_issues = models.IntegerField()
    servers_clean = models.IntegerField()
    
    # Per-field issue counts
    missing_live_status_count = models.IntegerField(default=0)
    missing_osshortname_count = models.IntegerField(default=0)
    missing_osfamily_count = models.IntegerField(default=0)
    missing_snow_supportgroup_count = models.IntegerField(default=0)
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
    missing_idrac_name_count = models.IntegerField(default=0)
    missing_idrac_ip_count = models.IntegerField(default=0)    
    
    # Validation error counts
    alive_status_inconsistent_count = models.IntegerField(default=0)
    dead_status_inconsistent_count = models.IntegerField(default=0)

    # Diff vs previous run
    new_issues_count      = models.IntegerField(default=0)
    resolved_issues_count = models.IntegerField(default=0)
    changed_issues_count  = models.IntegerField(default=0)
    # {'new': [...], 'resolved': [...], 'changed': {server_id: {'added': [...], 'removed': [...]}}}
    diff_summary = models.JSONField(default=dict)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    duration_seconds = models.FloatField(null=True, blank=True)

    # "Real" discrepancies — servers whose oldest active issue has been open for at
    # least persistent_days_threshold days (see DiscrepancyTracking.oldest_first_seen).
    # Used by the historic table view, kept separate from servers_with_issues above
    # (which is the raw, unfiltered daily count used by the live dashboard).
    #
    # These three counts are three DIFFERENT populations, not one split three ways:
    # persistent_servers_with_issues = missing-data issues, population ALIVE+OPERATIONAL+IV1/IV2/IBM
    # persistent_alive_inconsistent_count = ALIVE servers with a contradicting SNOW_STATUS, population ALIVE+IV1/IV2/IBM
    # persistent_dead_inconsistent_count = OPERATIONAL servers that are actually DEAD, population OPERATIONAL+IV1/IV2/IBM
    # An alive-inconsistent server is, by definition, not part of the ALIVE+OPERATIONAL
    # population — never sum these three or compare them against the same denominator.
    persistent_days_threshold = models.IntegerField(default=7)
    persistent_servers_with_issues = models.IntegerField(default=0)
    persistent_alive_inconsistent_count = models.IntegerField(default=0)
    persistent_dead_inconsistent_count = models.IntegerField(default=0)

    # ALL servers in scope (IV1/IV2/IBM), regardless of LIVE_STATUS/SNOW_STATUS — the same
    # denominator the live dashboard uses for its "Operational Inconsistencies" gauge. This is
    # the correct population for alive/dead inconsistency percentages: an alive-inconsistent
    # server isn't part of the ALIVE-only or OPERATIONAL-only population, it's part of the
    # whole fleet. Snapshots created before this field existed have it at 0 (see views.py
    # fallback). Not used for missing_data, which has its own eligible population/percentage
    # (total_servers_analyzed / percentage_persistent_clean).
    total_all_servers = models.IntegerField(default=0)

    class Meta:
        db_table = 'discrepancies_analysissnapshot'
        ordering = ['-analysis_date']

    @property
    def persistent_servers_clean(self):
        return max(0, self.total_servers_analyzed - self.persistent_servers_with_issues)

    @property
    def percentage_persistent_issues(self):
        return safe_percentage(self.persistent_servers_with_issues, self.total_servers_analyzed)

    @property
    def percentage_persistent_clean(self):
        return round(100 - self.percentage_persistent_issues, 2)

    def __str__(self):
        return f"Analysis {self.analysis_date} - {self.servers_with_issues}/{self.total_servers_analyzed} issues"
    
    @property
    def percentage_with_issues(self):
        """Calculate percentage of servers with issues"""
        return safe_percentage(self.servers_with_issues, self.total_servers_analyzed)
    
    @property
    def percentage_clean(self):
        """Calculate percentage of clean servers"""
        return round(100 - self.percentage_with_issues, 2)
        

class AnalysisSnapshotBreakdown(models.Model):
    """
    Per-dimension (region/OS/live status/...) aggregate counts for a given AnalysisSnapshot
    and metric. One row per (snapshot, metric, dimension, dimension_value) — feeds the
    historic table view and its Excel export. The list of dimensions is config-driven,
    see discrepancies/breakdown_groups.json ("dimensions") — dimension is any Server field
    name, not a fixed enum here.

    metric separates three DIFFERENT populations that must never be mixed under one
    denominator — see the comment on AnalysisSnapshot.persistent_servers_with_issues.
    """

    METRIC_MISSING_DATA = 'missing_data'
    METRIC_ALIVE_INCONSISTENT = 'alive_inconsistent'
    METRIC_DEAD_INCONSISTENT = 'dead_inconsistent'

    snapshot = models.ForeignKey(AnalysisSnapshot, on_delete=models.CASCADE, related_name='breakdowns')
    metric = models.CharField(max_length=30, default=METRIC_MISSING_DATA)
    dimension = models.CharField(max_length=50)
    dimension_value = models.CharField(max_length=200)

    total_servers = models.IntegerField(default=0)
    servers_with_issues = models.IntegerField(default=0)
    servers_clean = models.IntegerField(default=0)

    # {field_name: count, ...} — missing-field breakdown for this slice (missing_data metric only)
    field_counts = models.JSONField(default=dict)

    class Meta:
        db_table = 'discrepancies_analysissnapshotbreakdown'
        indexes = [
            models.Index(fields=['snapshot', 'metric', 'dimension']),
            models.Index(fields=['dimension', 'dimension_value']),
        ]

    def __str__(self):
        return f"{self.snapshot.analysis_date:%Y-%m-%d} - {self.dimension}={self.dimension_value}"

    @property
    def percentage_with_issues(self):
        # Global KPI, not a "rate within this dimension value" — AMER's % is AMER's issue
        # count over the WHOLE eligible population for the metric, not over AMER's own
        # population (self.total_servers). That makes rows directly comparable as each
        # dimension value's contribution to the overall metric, instead of e.g. a
        # small region looking artificially worse/better just because it has fewer servers.
        total = (
            self.snapshot.total_servers_analyzed
            if self.metric == self.METRIC_MISSING_DATA
            else self.snapshot.total_all_servers
        )
        return safe_percentage(self.servers_with_issues, total)


class AnalysisSnapshotCrossBreakdown(models.Model):
    """
    row_field-value x OS-bucket matrix for a given AnalysisSnapshot and metric (bucket
    grouping — e.g. Windows / Linux / Other — defined in discrepancies/breakdown_groups.json).
    One row per (snapshot, metric, row_field, row_value, os_bucket). row_field is any
    Server field (REGION for the region x OS split, or one of breakdown_groups.json's
    "recap.row_fields" for the recap table). metric separates the three populations
    (missing_data / alive_inconsistent / dead_inconsistent) — see AnalysisSnapshotBreakdown
    for why they must never be mixed.
    """

    snapshot = models.ForeignKey(AnalysisSnapshot, on_delete=models.CASCADE, related_name='cross_breakdowns')
    metric = models.CharField(max_length=30, default=AnalysisSnapshotBreakdown.METRIC_MISSING_DATA)
    row_field = models.CharField(max_length=50, default='REGION')
    row_value = models.CharField(max_length=200)
    os_bucket = models.CharField(max_length=100)
    # Region split for RECAP rows only ('' = all-regions aggregate). REGION-row_field rows
    # already encode the region in row_value and leave this blank.
    region = models.CharField(max_length=100, blank=True, default='')

    total_servers = models.IntegerField(default=0)
    servers_with_issues = models.IntegerField(default=0)
    servers_clean = models.IntegerField(default=0)

    class Meta:
        db_table = 'discrepancies_analysissnapshotcrossbreakdown'
        indexes = [
            models.Index(fields=['snapshot', 'metric', 'row_field']),
            models.Index(fields=['row_field', 'row_value']),
        ]

    def __str__(self):
        return f"{self.snapshot.analysis_date:%Y-%m-%d} - {self.row_field}={self.row_value}/{self.os_bucket}"

    @property
    def percentage_with_issues(self):
        return safe_percentage(self.servers_with_issues, self.total_servers)

    @property
    def percentage_clean(self):
        # Not just "100 - percentage_with_issues" — safe_percentage's floor applies
        # independently on each side, so a real nonzero servers_clean count never displays
        # as a literal 0% either, same as servers_with_issues doesn't.
        return safe_percentage(self.servers_clean, self.total_servers)


class DiscrepancyTracking(models.Model):
    """
    Tracks active discrepancy issues per server.
    One row per server. active_issues stores per-field first_seen timestamps.
    When a field is fixed it is simply removed from active_issues.
    """

    SERVER_ID = models.CharField(max_length=100)

    # {field_name: {"first_seen": "<ISO datetime>"}}
    active_issues = models.JSONField(default=dict)

    # Denormalised: oldest first_seen across active_issues — kept in sync for fast SQL sorting
    oldest_first_seen = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'discrepancies_discrepancytracking'
        constraints = [
            models.UniqueConstraint(fields=['SERVER_ID'], name='disctracking_serverid_uniq'),
        ]
        indexes = [
            models.Index(fields=['oldest_first_seen'], name='disctracking_oldest_idx'),
        ]

    def __str__(self):
        return f"{self.SERVER_ID} - {len(self.active_issues)} active issues"

    @property
    def issues_count(self):
        return len(self.active_issues)

# To remove
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


class ImportStatus(models.Model):
    date_import = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    message = models.TextField(blank=True, null=True)
    nb_entries_created = models.IntegerField(default=0)

    def __str__(self):
        return f"{'OK' if self.success else 'KO'} {self.date_import.strftime('%d.%m.%Y %H:%M')}"


class ExcludedServer(models.Model):
    # Servers manually excluded from discrepancy analysis, managed via the dashboard UI (add/delete/export)
    server_name = models.CharField(max_length=255)
    reason = models.TextField(blank=True)
    owner = models.CharField(max_length=150, blank=True)
    exclusion_date = models.DateField(null=True, blank=True)
    created_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'discrepancies_excludedserver'
        ordering = ['server_name']

    def __str__(self):
        return self.server_name
