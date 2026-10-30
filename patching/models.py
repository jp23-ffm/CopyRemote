from django.db import models


class PatchingServer(models.Model):
    """Current patching state of a server, refreshed by the import_patching command."""
    SERVERNAME = models.CharField(max_length=255, unique=True)
    SUB_REGION = models.TextField(null=True, blank=True)
    TEMPLATE = models.TextField(null=True, blank=True)
    HOST_COMMENT = models.TextField(null=True, blank=True)
    SLOT_ID = models.TextField(null=True, blank=True)
    SCHEDULE_ID = models.TextField(null=True, blank=True)
    HOST_DEFAULT_SCHEDULE_COMMENT = models.TextField(null=True, blank=True)
    SERVER_PATCHING_STATUS = models.TextField(null=True, blank=True)
    PATCHING_SUMMARY = models.TextField(null=True, blank=True)
    PROGRAMMING_STATUS = models.TextField(null=True, blank=True)
    SERVER_CAMPAIGN_STATUS = models.TextField(null=True, blank=True)
    NEXT_PATCH_START_TIME = models.TextField(null=True, blank=True)
    LAST_PATCH_START_TIME = models.TextField(null=True, blank=True)
    NEXT_PRECHECK_START_TIME = models.TextField(null=True, blank=True)
    LAST_PRECHECK_START_TIME = models.TextField(null=True, blank=True)
    PRECHECK_TEMPLATE = models.TextField(null=True, blank=True)
    PRECHECK_STATUS = models.TextField(null=True, blank=True)
    PRECHECK_SUMMARY = models.TextField(null=True, blank=True)
    PRECHECK_PROGRAMMING_STATUS = models.TextField(null=True, blank=True)
    MOVEMENT_BLOCKED = models.TextField(null=True, blank=True)
    LATEST_PATCHING_TOWER_JOB_ID = models.TextField(null=True, blank=True)
    LATEST_PRECHECK_TOWER_JOB_ID = models.TextField(null=True, blank=True)
    NEXT_MANUAL_PATCH_START_TIME = models.TextField(null=True, blank=True)
    LAST_MANUAL_PATCH_START_TIME = models.TextField(null=True, blank=True)
    DEFAULT_SCHEDULE_START_TIME = models.TextField(null=True, blank=True)
    DEFAULT_SCHEDULE_NAME = models.TextField(null=True, blank=True)
    DEFAULT_SCHEDULE_COMMENT = models.TextField(null=True, blank=True)
    DEFAULT_SCHEDULE_PAAS_BOOL = models.TextField(null=True, blank=True)
    DEFAULT_SCHEDULE_WAVE_NAME = models.TextField(null=True, blank=True)
    DEFAULT_SCHEDULE_ID = models.TextField(null=True, blank=True)
    BLACKLIST_NAME = models.TextField(null=True, blank=True)
    BLACKLIST_COMMENT = models.TextField(null=True, blank=True)
    BLACKLIST_IS_PERMANENT = models.TextField(null=True, blank=True)
    BLACKLIST_START_TIME = models.TextField(null=True, blank=True)
    BLACKLIST_END_TIME = models.TextField(null=True, blank=True)
    BLACKLIST_REQUESTER = models.TextField(null=True, blank=True)
    BLACKLIST_RISK_CARD = models.TextField(null=True, blank=True)
    BLACKLIST_SERVERNAME = models.TextField(null=True, blank=True)
    BLACKLIST_CAMPAIGN_NAME = models.TextField(null=True, blank=True)
    BLACKLIST_ID = models.TextField(null=True, blank=True)

    # Set by the import SQL (not auto_now): updated_at only moves when a value changed
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        ordering = ['SERVERNAME']

    def __str__(self):
        return self.SERVERNAME


class PatchingImportStatus(models.Model):
    """One row per import run."""
    date_import = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    skipped = models.BooleanField(default=False)  # file identical to the previous one
    file_name = models.CharField(max_length=500, blank=True)
    file_hash = models.CharField(max_length=64, blank=True)
    nb_rows_read = models.IntegerField(default=0)
    nb_inserted = models.IntegerField(default=0)
    nb_updated = models.IntegerField(default=0)
    nb_unchanged = models.IntegerField(default=0)
    duration_seconds = models.FloatField(null=True, blank=True)
    message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-date_import']

    def __str__(self):
        return f"{'OK' if self.success else 'KO'} {self.date_import.strftime('%d.%m.%Y %H:%M')}"
