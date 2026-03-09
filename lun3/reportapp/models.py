from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    full_name = models.CharField(max_length=100)

class UserProfile(models.Model):
    user = models.OneToOneField(CustomUser, unique=True, on_delete=models.CASCADE)
    email_address = models.EmailField(max_length=255, unique=False, default='')

class SavedSearch(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    filters = models.JSONField()
    tags = models.JSONField()
    view = models.CharField(max_length=100, default='')
    
class SavedOptions(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    businesscontinuity_permanentfilter = models.CharField(max_length=100, default='')
    reportapp_permanentfilter = models.CharField(max_length=100, default='')
    inventory_permanentfilter = models.CharField(max_length=100, default='')
    discrepancies_permanentfilter = models.CharField(max_length=100, default='')
    
class UserPermissions(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    businesscontinuity_allowedit = models.BooleanField(default=False)
    inventory_allowedit = models.BooleanField(default=False)

class SavedChart(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='saved_charts')
    name = models.CharField(max_length=100)
    filters = models.JSONField()  # Save all the query: {fields: [...], types: [...], filters: {...}}
    view = models.CharField(max_length=100, default='')
    app_name = models.CharField(max_length=50, default='inventory')
    
    def __str__(self):
        return f"{self.user_profile.user.username} - {self.name}"
    
    class Meta:
        ordering = ['name']
        unique_together = ['user_profile', 'app_name', 'name']
        


