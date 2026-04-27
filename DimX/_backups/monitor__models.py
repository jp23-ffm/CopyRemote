from django.db import models
from django.utils import timezone


class LoginLog(models.Model):
    username = models.CharField(max_length=100, blank=True)
    login_time = models.DateTimeField(auto_now_add=True)
    client_ip_address = models.GenericIPAddressField(null=True, blank=True)
    client_hostname = models.CharField(max_length=100, blank=True)
    server_hostname = models.CharField(max_length=100, blank=True)
    
    class Meta:
        ordering = ['-login_time']
    
    def __str__(self):
        return f"{self.user.username} - {self.login_time}"


class HostHealthStatus(models.Model):
    host_name = models.CharField(max_length=100, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=[
        ('OK', 'OK'), 
        ('Warning', 'Warning'),
        ('Error', 'Error'), 
        ('Unknown', 'Unknown')
    ], default='Unknown')
    checks_data = models.JSONField(default=dict)
    last_updated = models.DateTimeField(auto_now=True, db_index=True)
    hostname = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    version = models.CharField(max_length=50, blank=True)
    uptime = models.CharField(max_length=50, blank=True)
    
    class Meta:
        db_table = 'host_health_status'
        ordering = ['host_name']
    
    def is_stale(self, max_age=120):
        if not self.last_updated:
            return True
        return (timezone.now() - self.last_updated).total_seconds() > max_age
    
    def get_staleness_seconds(self):
        if not self.last_updated:
            return None
        return (timezone.now() - self.last_updated).total_seconds()
    
    @classmethod
    def update_host_status(cls, host_name, status, checks_data, **kwargs):
        obj, _ = cls.objects.update_or_create(
            host_name=host_name,
            defaults={'status': status, 'checks_data': checks_data, **kwargs}
        )
        return obj


class GlobalHealthStatus(models.Model):

    # Keep the global health of the cluster like the counting of the tables, the last import checks, the SSL check

    id = models.IntegerField(primary_key=True, default=1, editable=False)
    
    status = models.CharField(
        max_length=20,
        choices=[
            ('OK', 'OK'),
            ('Warning', 'Warning'),
            ('Error', 'Error'),
            ('Unknown', 'Unknown'),
        ],
        default='Unknown',
        help_text="Global health state"
    )
    
    checks_data = models.JSONField(
        default=dict,
        help_text="Details of the global checks"
    )
    
    last_updated = models.DateTimeField(
        auto_now=True,
        db_index=True,
        help_text="Last check update"
    )
    
    class Meta:
        db_table = 'global_health_status'
        verbose_name = 'Global Health Status'
        verbose_name_plural = 'Global Health Status'
    
    def __str__(self):
        return f"Global Checks - {self.status} (updated {self.last_updated})"
    
    def is_stale(self, max_age_seconds=7200):  # 2 hours by default
       # Check if the chesk is too old
        if not self.last_updated:
            return True
        
        age = (timezone.now() - self.last_updated).total_seconds()
        return age > max_age_seconds
    
    def get_staleness_seconds(self):
        if not self.last_updated:
            return None
        return (timezone.now() - self.last_updated).total_seconds()
    
    @classmethod
    def get_or_create_singleton(cls):
        # Get or create the unique id
        obj, created = cls.objects.get_or_create(id=1)
        return obj
    
    @classmethod
    def update_global_status(cls, status, checks_data):
        # Update the status
        obj = cls.get_or_create_singleton()
        obj.status = status
        obj.checks_data = checks_data
        obj.save()
        return obj
