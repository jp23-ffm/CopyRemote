from django.db import models


class Application(models.Model):
    APPLICATION_AUID = models.CharField(max_length=100, db_index=True)
    APPLICATION_MANAGER_EMAIL = models.CharField(max_length=255, null=True, blank=True)
    IT_CLUSTER = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['APPLICATION_AUID']),
        ]

    def __str__(self):
        return self.APPLICATION_AUID


class ImportStatus(models.Model):
    date_import = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    message = models.TextField(blank=True, null=True)
    nb_entries_created = models.IntegerField(default=0)

    def __str__(self):
        return f"{'OK' if self.success else 'KO'} {self.date_import.strftime('%d.%m.%Y %H:%M')}"
