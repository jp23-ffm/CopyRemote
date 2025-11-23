from django.db import models
from django.utils import timezone


class GlobalHealthStatus(models.Model):
    """
    Stocke l'état de santé global du cluster (checks partagés).
    Ces checks ne dépendent pas d'un host spécifique :
    - Comptage des tables (inventory, businesscontinuity, reportapp)
    - Status des derniers imports
    - Certificat SSL
    
    Un seul enregistrement existe (singleton).
    """
    
    # On utilise un ID fixe pour avoir un singleton
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
        help_text="État global des checks partagés"
    )
    
    checks_data = models.JSONField(
        default=dict,
        help_text="Détails de tous les checks globaux"
    )
    
    last_updated = models.DateTimeField(
        auto_now=True,
        db_index=True,
        help_text="Dernière mise à jour des checks globaux"
    )
    
    class Meta:
        db_table = 'global_health_status'
        verbose_name = 'Global Health Status'
        verbose_name_plural = 'Global Health Status'
    
    def __str__(self):
        return f"Global Checks - {self.status} (updated {self.last_updated})"
    
    def is_stale(self, max_age_seconds=7200):  # 2 heures par défaut
        """
        Vérifie si le statut est périmé.
        Par défaut, considère périmé si > 2 heures (checks toutes les heures).
        """
        if not self.last_updated:
            return True
        
        age = (timezone.now() - self.last_updated).total_seconds()
        return age > max_age_seconds
    
    def get_staleness_seconds(self):
        """Retourne l'âge du statut en secondes."""
        if not self.last_updated:
            return None
        return (timezone.now() - self.last_updated).total_seconds()
    
    @classmethod
    def get_or_create_singleton(cls):
        """Récupère ou crée l'unique instance."""
        obj, created = cls.objects.get_or_create(id=1)
        return obj
    
    @classmethod
    def update_global_status(cls, status, checks_data):
        """Met à jour le statut global."""
        obj = cls.get_or_create_singleton()
        obj.status = status
        obj.checks_data = checks_data
        obj.save()
        return obj
