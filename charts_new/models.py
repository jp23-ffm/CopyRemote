# models.py - AJOUTER à tes modèles existants

class SavedChart(models.Model):
    """
    Sauvegarde des vues de graphiques.
    Suit le même pattern que SavedSearch.
    """
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='saved_charts')
    name = models.CharField(max_length=100)
    filters = models.JSONField()  # Stocke toute la query: {fields: [...], types: [...], filters: {...}}
    view = models.CharField(max_length=100, default='')  # Optionnel, pour catégoriser
    
    def __str__(self):
        return f"{self.user_profile.user.username} - {self.name}"
    
    class Meta:
        ordering = ['name']
