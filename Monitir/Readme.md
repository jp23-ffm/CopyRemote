# Monitoring de Cluster Django - Approche DB

## Concept

Au lieu de faire des appels HTTP entre nodes (fragile, latence, timeouts…),
chaque node écrit son statut dans une table partagée toutes les 30 secondes.

**Avantages :**

- ✅ Simple et robuste
- ✅ Pas de dépendance HTTP entre nodes
- ✅ Détection automatique des nodes morts (staleness)
- ✅ Un seul appel API pour avoir l’état global
- ✅ Historisation possible (si besoin)

## Architecture

```
Node 1                          Node 2
  │                               │
  │ Toutes les 30s               │ Toutes les 30s
  │ ┌─────────────────┐          │ ┌─────────────────┐
  │ │ Cron/Systemd    │          │ │ Cron/Systemd    │
  │ │ update_node_    │          │ │ update_node_    │
  │ │ health command  │          │ │ health command  │
  │ └────────┬────────┘          │ └────────┬────────┘
  │          │                   │          │
  └──────────┼───────────────────┼──────────┘
             │                   │
             ▼                   ▼
        ┌──────────────────────────┐
        │ Table node_health_status │
        │ ┌──────┬────────┬─────┐ │
        │ │node-1│ OK     │16:30│ │
        │ │node-2│ Warning│16:30│ │
        │ └──────┴────────┴─────┘ │
        └──────────────────────────┘
                   ▲
                   │
            GET /api/status
            (lit la table)
```

## Installation

### 1. Ajouter le modèle

Copie le contenu de `models.py` dans ton `api/models.py`

### 2. Créer la migration

```bash
python manage.py makemigrations
python manage.py migrate
```

### 3. Ajouter la commande de management

Copie `management_command_update_status.py` vers :
`api/management/commands/update_node_health.py`

### 4. Ajouter les vues

Copie le contenu de `cluster_view_db.py` dans `api/views.py`

### 5. Configurer les URLs

Dans `api/urls.py` :

```python
from django.urls import path
from .views import ClusterStatusView, NodeDetailView

urlpatterns = [
    path('status', ClusterStatusView.as_view(), name='cluster-status'),
    path('status/<str:node_name>', NodeDetailView.as_view(), name='node-detail'),
]
```

### 6. Configurer les variables d’environnement

**Node 1** (`/etc/environment` ou `.env`) :

```bash
NODE_NAME=prod-node-01
APP_VERSION=1.2.3
```

**Node 2** :

```bash
NODE_NAME=prod-node-02
APP_VERSION=1.2.3
```

Dans `settings.py` :

```python
import os
CURRENT_NODE_NAME = os.getenv('NODE_NAME', 'unknown-node')
APP_VERSION = os.getenv('APP_VERSION', 'dev')
```

### 7. Configurer l’exécution périodique

#### Option A : Cron (simple)

```bash
# Éditer le crontab
crontab -e

# Ajouter ces lignes (exécution toutes les 30 secondes)
* * * * * cd /opt/app && /opt/app/venv/bin/python manage.py update_node_health
* * * * * sleep 30; cd /opt/app && /opt/app/venv/bin/python manage.py update_node_health
```

#### Option B : Systemd Timer (recommandé pour production)

1. Créer `/etc/systemd/system/node-health.service` :

```ini
[Unit]
Description=Node Health Status Update
After=network.target postgresql.service

[Service]
Type=oneshot
User=www-data
WorkingDirectory=/opt/app
Environment="NODE_NAME=prod-node-01"
Environment="APP_VERSION=1.2.3"
ExecStart=/opt/app/venv/bin/python /opt/app/manage.py update_node_health
StandardOutput=journal
StandardError=journal
```

1. Créer `/etc/systemd/system/node-health.timer` :

```ini
[Unit]
Description=Run node health check every 30 seconds
Requires=node-health.service

[Timer]
OnBootSec=10s
OnUnitActiveSec=30s
AccuracySec=1s

[Install]
WantedBy=timers.target
```

1. Activer et démarrer :

```bash
sudo systemctl daemon-reload
sudo systemctl enable node-health.timer
sudo systemctl start node-health.timer

# Vérifier
sudo systemctl status node-health.timer
sudo systemctl list-timers --all
```

## Utilisation

### API Endpoints

#### GET /api/status

Vue globale du cluster avec tous les nodes.

**Réponse (200 OK)** :

```json
{
  "cluster_status": "OK",
  "timestamp": "2025-11-20T16:30:45Z",
  "summary": {
    "total_nodes": 2,
    "healthy_nodes": 2,
    "stale_nodes": 0,
    "error_nodes": 0,
    "warning_nodes": 0
  },
  "nodes": [
    {
      "node_name": "prod-node-01",
      "status": "OK",
      "last_updated": "2025-11-20T16:30:30Z",
      "staleness_seconds": 14.67,
      "is_stale": false,
      "hostname": "srv-prod-01",
      "checks_summary": {
        "total": 8,
        "ok": 8,
        "warning": 0,
        "error": 0
      }
    }
  ]
}
```

#### GET /api/status?details=true

Même chose mais avec le détail de tous les checks.

#### GET /api/status/prod-node-01

Détails complets d’un node spécifique avec tous ses checks.

### Statuts possibles

**Cluster status** :

- `OK` : Tous les nodes sont OK
- `Warning` : Au moins un node a un warning
- `Degraded` : Au moins un node est en erreur ou stale
- `Critical` : Tous les nodes sont en erreur ou stale

**Node status** :

- `OK` : Tous les checks sont OK
- `Warning` : Au moins un check en warning
- `Error` : Au moins un check en erreur
- `Stale` : Le node n’a pas reporté depuis >2 minutes (probablement mort)

### Détection de staleness

Un node est considéré “stale” (mort/bloqué) si :

- Sa dernière mise à jour est > 120 secondes (2 minutes)
- Configurable dans la vue : `STALE_THRESHOLD_SECONDS`

Si un node est stale, le cluster passe automatiquement en “Degraded”.

## Tests

### Test manuel

```bash
# Mettre à jour le statut manuellement
python manage.py update_node_health

# Vérifier l'API
curl http://localhost:8000/api/status | jq

# Avec détails
curl http://localhost:8000/api/status?details=true | jq

# Node spécifique
curl http://localhost:8000/api/status/prod-node-01 | jq
```

### Vérifier que ça tourne

```bash
# Voir les logs systemd
sudo journalctl -u node-health.service -f

# Voir la table directement
python manage.py shell
>>> from api.models import NodeHealthStatus
>>> NodeHealthStatus.objects.all()
>>> node = NodeHealthStatus.objects.first()
>>> node.is_stale()
>>> node.get_staleness_seconds()
```

## Intégration avec Dynatrace

Tu peux configurer Dynatrace pour monitorer l’endpoint `/api/status` :

1. **Synthetic Monitor** : Ping `/api/status` toutes les minutes
1. **Alertes** : Si `cluster_status != "OK"` ou HTTP 503
1. **Métriques custom** : Parser le JSON et extraire les métriques
- `cluster.total_nodes`
- `cluster.healthy_nodes`
- `cluster.stale_nodes`
- etc.

## Debugging

### Node ne se met pas à jour

```bash
# Vérifier que le cron/timer tourne
sudo systemctl status node-health.timer

# Tester la commande manuellement
python manage.py update_node_health --verbosity=2

# Vérifier les logs
tail -f /var/log/syslog | grep node-health
```

### Tous les nodes sont “stale”

- Vérifier que les cron/timers tournent sur tous les nodes
- Vérifier que la DB est accessible
- Vérifier les timezones (tout doit être en UTC)

### Performance

La table est très petite (1 ligne par node), pas de souci de performance.
Si tu veux historiser, crée une table séparée et archive les anciens statuts.

## Améliorations possibles

1. **Historisation** : Garder l’historique des statuts pour des graphes
1. **Alertes** : Envoyer un email/Slack si un node est down
1. **Auto-discovery** : Détecter automatiquement les nodes actifs
1. **Métriques** : Exposer les données en format Prometheus

## Avantages vs appels HTTP

|Critère       |Appels HTTP|DB Table   |
|--------------|-----------|-----------|
|Simplicité    |❌ Complex  |✅ Simple   |
|Fiabilité     |❌ Timeouts |✅ Robust   |
|Performance   |❌ Latence  |✅ Rapide   |
|Scalabilité   |❌ N→N calls|✅ N→DB     |
|Détection down|⚠️ Timeout  |✅ Staleness|

Avec la DB, tu as une source de vérité unique et fiable. C’est le pattern standard
pour ce genre de monitoring distribué.
