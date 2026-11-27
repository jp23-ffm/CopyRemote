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
