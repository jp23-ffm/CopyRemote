# models.py
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class SavedChartQuery(models.Model):
    """
    Sauvegarde des requêtes de graphiques pour réutilisation rapide.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_chart_queries')
    name = models.CharField(max_length=200, help_text="Nom de la vue sauvegardée")
    description = models.TextField(blank=True, help_text="Description optionnelle")
    
    # La query string complète (tout ce qui est après le ?)
    query_string = models.TextField(help_text="Query string complète: fields=X&types=Y&filter=Z")
    
    # Métadonnées pour affichage
    chart_count = models.IntegerField(default=0, help_text="Nombre de graphiques")
    filters_count = models.IntegerField(default=0, help_text="Nombre de filtres appliqués")
    
    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(default=timezone.now)
    use_count = models.IntegerField(default=0, help_text="Nombre de fois utilisée")
    
    class Meta:
        ordering = ['-last_used']
        unique_together = ['user', 'name']
    
    def __str__(self):
        return f"{self.user.username} - {self.name}"
    
    def increment_usage(self):
        """Incrémenter le compteur d'utilisation"""
        self.use_count += 1
        self.last_used = timezone.now()
        self.save(update_fields=['use_count', 'last_used'])