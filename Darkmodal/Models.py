# userapp/models.py

class UserPreferences(models.Model):
    """
    Préférences utilisateur par app.
    Stocke tous les settings dans un JSONField pour flexibilité.
    """
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='preferences')
    app_name = models.CharField(max_length=50, default='global')  # 'global', 'inventory', 'businesscontinuity'
    settings = models.JSONField(default=dict)  # Tous les settings en JSON
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user_profile', 'app_name']
        ordering = ['app_name']
    
    def __str__(self):
        return f"{self.user_profile.user.username} - {self.app_name}"
    
    def get_setting(self, key, default=None):
        """Récupérer un setting spécifique"""
        return self.settings.get(key, default)
    
    def set_setting(self, key, value):
        """Définir un setting spécifique"""
        self.settings[key] = value
        self.save()
