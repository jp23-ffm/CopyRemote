from django.db import models
from django.utils import timezone


class StorageShare(models.Model):
    ID = models.CharField(max_length=255, db_column='share_id', db_index=True)
    PROVIDER = models.CharField(max_length=100, null=True, blank=True)
    CLUSTER = models.CharField(max_length=255, null=True, blank=True)
    FILER = models.CharField(max_length=255, null=True, blank=True)
    SHARE_NAME = models.CharField(max_length=500, null=True, blank=True)
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
            models.Index(fields=['ID']),
            models.Index(fields=['PROVIDER']),
            models.Index(fields=['ENVIRONMENT']),
            models.Index(fields=['REGION']),
        ]

    def __str__(self):
        return self.ID or ''


class StorageObject(models.Model):
    ID = models.CharField(max_length=255, db_column='object_id', db_index=True)
    NAME = models.CharField(max_length=500, null=True, blank=True)
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
            models.Index(fields=['ID']),
            models.Index(fields=['PROTOCOL']),
            models.Index(fields=['ENVIRONMENT']),
            models.Index(fields=['REGION']),
        ]

    def __str__(self):
        return self.ID or ''


class ShareAnnotation(models.Model):
    SHARE_ID = models.CharField(max_length=255, unique=True, db_index=True)
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
        return self.SHARE_ID


class ObjectAnnotation(models.Model):
    OBJECT_ID = models.CharField(max_length=255, unique=True, db_index=True)
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
        return self.OBJECT_ID


class StorageImportStatus(models.Model):
    source = models.CharField(max_length=20)  # 'share' or 'object'
    date_import = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    message = models.TextField(blank=True, null=True)
    nb_entries_created = models.IntegerField(default=0)

    def __str__(self):
        return f"[{self.source}] {'OK' if self.success else 'KO'} {self.date_import.strftime('%d.%m.%Y %H:%M')}"
