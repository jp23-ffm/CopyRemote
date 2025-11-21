# 🚀 QUICK START - Configuration en 10 minutes

## TL;DR

Tu as 2 serveurs Django derrière un load balancer. Tu veux un endpoint `/api/status` qui te donne l’état des 2 serveurs en une seule requête, avec détection automatique des serveurs morts.

**Solution:** Chaque serveur écrit son statut dans une table DB toutes les 30s. L’endpoint lit juste cette table.

-----

## Installation rapide (copier-coller)

### 1️⃣ Ajouter le modèle (2 min)

Dans `api/models.py`, ajoute à la fin :

```python
from django.db import models
from django.utils import timezone

class NodeHealthStatus(models.Model):
    node_name = models.CharField(max_length=100, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=[
        ('OK', 'OK'), ('Warning', 'Warning'),
        ('Error', 'Error'), ('Unknown', 'Unknown')
    ], default='Unknown')
    checks_data = models.JSONField(default=dict)
    last_updated = models.DateTimeField(auto_now=True, db_index=True)
    hostname = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    version = models.CharField(max_length=50, blank=True)
    
    class Meta:
        db_table = 'node_health_status'
        ordering = ['node_name']
    
    def is_stale(self, max_age=120):
        if not self.last_updated:
            return True
        return (timezone.now() - self.last_updated).total_seconds() > max_age
    
    def get_staleness_seconds(self):
        if not self.last_updated:
            return None
        return (timezone.now() - self.last_updated).total_seconds()
    
    @classmethod
    def update_node_status(cls, node_name, status, checks_data, **kwargs):
        obj, _ = cls.objects.update_or_create(
            node_name=node_name,
            defaults={'status': status, 'checks_data': checks_data, **kwargs}
        )
        return obj
```

Puis :

```bash
python manage.py makemigrations
python manage.py migrate
```

### 2️⃣ Créer la commande (2 min)

Crée `api/management/commands/update_node_health.py` :

```python
import socket
from django.core.management.base import BaseCommand
from django.conf import settings
from api.views import StatusCheck  # Ta classe existante
from api.models import NodeHealthStatus

class Command(BaseCommand):
    help = 'Update node health in DB'
    
    def handle(self, *args, **options):
        node_name = getattr(settings, 'CURRENT_NODE_NAME', socket.gethostname())
        hostname = socket.gethostname()
        
        # Réutilise ta logique de checks existante
        checks_results = []
        overall_status = "OK"
        
        for name, fn in StatusCheck.CHECKS:
            try:
                result = fn()
                checks_results.append(result)
                if result["Status"] == "Error":
                    overall_status = "Error"
                elif result["Status"] == "Warning" and overall_status != "Error":
                    overall_status = "Warning"
            except Exception as e:
                checks_results.append({"Name": name, "Status": "Error", "Details": str(e)})
                overall_status = "Error"
        
        # Sauvegarde dans DB
        NodeHealthStatus.update_node_status(
            node_name=node_name,
            status=overall_status,
            checks_data={
                'checks': checks_results,
                'total_checks': len(checks_results),
                'ok_count': sum(1 for c in checks_results if c['Status'] == 'OK'),
                'warning_count': sum(1 for c in checks_results if c['Status'] == 'Warning'),
                'error_count': sum(1 for c in checks_results if c['Status'] == 'Error'),
            },
            hostname=hostname
        )
        
        self.stdout.write(self.style.SUCCESS(f"✓ {node_name}: {overall_status}"))
```

Test :

```bash
python manage.py update_node_health
```

### 3️⃣ Ajouter la vue cluster (3 min)

Dans `api/views.py`, ajoute à la fin :

```python
from django.http import JsonResponse
from django.views import View
from django.utils import timezone

class ClusterStatusView(View):
    STALE_THRESHOLD = 120  # 2 minutes
    
    def get(self, request):
        from api.models import NodeHealthStatus
        
        nodes = NodeHealthStatus.objects.all()
        if not nodes:
            return JsonResponse({
                "cluster_status": "Unknown",
                "nodes": []
            }, status=503)
        
        nodes_data = []
        stale_count = error_count = 0
        
        for node in nodes:
            is_stale = node.is_stale(self.STALE_THRESHOLD)
            if is_stale:
                stale_count += 1
            elif node.status == "Error":
                error_count += 1
            
            nodes_data.append({
                "node_name": node.node_name,
                "status": "Stale" if is_stale else node.status,
                "is_stale": is_stale,
                "last_updated": node.last_updated.isoformat(),
                "staleness_seconds": round(node.get_staleness_seconds() or 0, 1),
                "hostname": node.hostname,
                "checks_summary": {
                    "total": node.checks_data.get('total_checks', 0),
                    "ok": node.checks_data.get('ok_count', 0),
                    "warning": node.checks_data.get('warning_count', 0),
                    "error": node.checks_data.get('error_count', 0),
                }
            })
        
        # Statut global
        if stale_count + error_count == len(nodes):
            cluster_status = "Critical"
        elif stale_count > 0 or error_count > 0:
            cluster_status = "Degraded"
        else:
            cluster_status = "OK"
        
        return JsonResponse({
            "cluster_status": cluster_status,
            "timestamp": timezone.now().isoformat(),
            "summary": {
                "total_nodes": len(nodes),
                "healthy_nodes": len(nodes) - stale_count - error_count,
            },
            "nodes": nodes_data
        }, status=200 if cluster_status == "OK" else 503)
```

### 4️⃣ Ajouter la route (1 min)

Dans ton `urls.py` :

```python
from .views import ClusterStatusView

urlpatterns = [
    # ... tes URLs existantes
    path('status', ClusterStatusView.as_view(), name='cluster-status'),
]
```

Test :

```bash
curl http://localhost:8000/api/status | jq
```

### 5️⃣ Configurer les variables d’env (1 min)

**Sur le serveur 1** :

```bash
export NODE_NAME="prod-node-01"
```

**Sur le serveur 2** :

```bash
export NODE_NAME="prod-node-02"
```

Dans `settings.py` :

```python
import os
CURRENT_NODE_NAME = os.getenv('NODE_NAME', 'unknown')
```

### 6️⃣ Automatiser avec cron (1 min)

**Sur chaque serveur** :

```bash
crontab -e
```

Ajoute :

```cron
* * * * * cd /opt/app && /opt/app/venv/bin/python manage.py update_node_health
* * * * * sleep 30; cd /opt/app && /opt/app/venv/bin/python manage.py update_node_health
```

-----

## ✅ C’est tout !

Tu as maintenant :

**GET /api/status** → État global du cluster

```json
{
  "cluster_status": "OK",
  "summary": {
    "total_nodes": 2,
    "healthy_nodes": 2
  },
  "nodes": [
    {
      "node_name": "prod-node-01",
      "status": "OK",
      "staleness_seconds": 12.3,
      "checks_summary": {"total": 8, "ok": 8}
    },
    {
      "node_name": "prod-node-02", 
      "status": "OK",
      "staleness_seconds": 18.7,
      "checks_summary": {"total": 8, "ok": 7, "warning": 1}
    }
  ]
}
```

-----

## 🔍 Vérifications

```bash
# 1. Vérifier que la commande fonctionne
python manage.py update_node_health

# 2. Vérifier la DB
python manage.py shell
>>> from api.models import NodeHealthStatus
>>> NodeHealthStatus.objects.all()

# 3. Vérifier l'API
curl http://localhost:8000/api/status | jq

# 4. Vérifier le cron (après 1 minute)
tail -f /var/log/syslog | grep CRON
```

-----

## 🚨 Troubleshooting

**Problème : “Aucun node trouvé”**
→ Le cron ne tourne pas, lance `python manage.py update_node_health` manuellement

**Problème : “Nodes en Stale”**
→ Le cron ne tourne pas sur ce serveur, vérifie avec `crontab -l`

**Problème : “Table does not exist”**
→ Lance `python manage.py migrate`

-----

## 📊 Bonus : Monitoring CLI

Crée `watch_cluster.py` et lance :

```bash
python watch_cluster.py
```

Pour voir l’état du cluster en temps réel ! (Fichier disponible dans les outputs)

-----

## 💡 Prochaines étapes

1. ✅ Configure Dynatrace pour monitorer `/api/status`
1. ✅ Ajoute des alertes si `cluster_status != "OK"`
1. ✅ Crée un dashboard avec les métriques
1. ✅ Profit ! 🎉
