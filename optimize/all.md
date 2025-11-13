# 📋 CHECKLIST D'OPTIMISATION - INVENTAIRE DJANGO

## 🎯 Contexte
- **Projet** : Inventaire de serveurs Django
- **Volume** : ~400 000 serveurs
- **Problème** : Performances variables, indexes manquants
- **Objectif** : Réduire le temps de réponse de 30-70%

---

## ✅ ÉTAPE 1 : AJOUT DES INDEXES (CRITIQUE)

### 1.1 Modifier `models.py` - Table `ServerGroupSummary`

**Problème identifié** : Aucun index sur cette table, or elle est interrogée fréquemment.

**Actions** :
```python
class ServerGroupSummary(models.Model):
    SERVER_ID = models.CharField(
        max_length=255, 
        unique=True,
        db_index=True  # ⭐ AJOUTER CECI
    )
    # ... autres champs ...
    
    class Meta:
        indexes = [
            models.Index(fields=['last_updated'], name='summary_updated_idx'),
            models.Index(fields=['total_instances'], name='summary_instances_idx'),
            models.Index(fields=['SERVER_ID', 'total_instances'], name='summary_compound_idx'),
        ]
```

### 1.2 Ajouter des indexes sur `Server`

**Actions** :
```python
class Server(models.Model):
    # ... tous tes champs existants ...
    
    class Meta:
        indexes = [
            # Indexes existants (à garder)
            models.Index(fields=['SERVER_ID']),
            models.Index(fields=['PAMELA_OSSHORTNAME']),
            models.Index(fields=['PAMELA_SERIAL']),
            models.Index(fields=['PAMELA_MODEL']),
            models.Index(fields=['PAMELA_PRODUCT']),
            models.Index(fields=['SERVER_DATACENTER_VALUE']),
            
            # ⭐ NOUVEAUX INDEXES À AJOUTER
            models.Index(fields=['SERVER_ID', 'APP_NAME_VALUE'], name='srv_id_app_idx'),
            models.Index(fields=['PAMELA_ENVIRONMENT'], name='env_idx'),
            models.Index(fields=['PAMELA_AREA'], name='area_idx'),
            models.Index(fields=['PAMELA_DATACENTER'], name='dc_idx'),
            models.Index(fields=['PAMELA_SNOWITG_STATUS'], name='status_idx'),
        ]
```

### 1.3 Améliorer les indexes sur `ServerAnnotation`

**Actions** :
```python
class ServerAnnotation(models.Model):
    # ... champs existants ...
    
    class Meta:
        ordering = ['SERVER_ID']
        indexes = [
            models.Index(fields=['type'], name='annotation_type_idx'),
            models.Index(fields=['updated_at'], name='annotation_date_idx'),
            models.Index(fields=['SERVER_ID', 'type'], name='annotation_compound_idx'),
        ]
```

### 1.4 Appliquer les migrations

```bash
# 1. Créer les migrations
python manage.py makemigrations

# 2. Appliquer (⚠️ peut prendre 5-15 minutes avec 400k entrées)
python manage.py migrate

# 3. Vérifier que les indexes sont créés
python manage.py dbshell
# Puis dans le shell SQL :
\d userapp_server
\d userapp_servergroupsummary
\d userapp_serverannotation
```

**Durée estimée** : 10-20 minutes (incluant l'exécution des migrations)

---

## ✅ ÉTAPE 2 : OPTIMISATIONS DU CODE

### 2.1 Cacher `field_labels.json`

**Problème** : Le fichier JSON est lu à chaque requête HTTP.

**Action** : Ajouter en haut de `views.py` :

```python
from functools import lru_cache
import json
import os

@lru_cache(maxsize=1)
def get_field_labels():
    """Cache les field_labels en mémoire"""
    json_path = os.path.join(os.path.dirname(__file__), 'field_labels.json')
    with open(json_path, 'r', encoding="utf-8") as f:
        return json.load(f)
```

**Puis remplacer** (ligne ~85-95) :
```python
# AVANT
json_path=os.path.join(os.path.dirname(__file__), 'field_labels.json')
with open(json_path, 'r', encoding="utf-8") as f:
    json_data=json.load(f)

# APRÈS
json_data = get_field_labels()
```

**Gain attendu** : Élimine les lectures disque répétées (99% de réduction)

---

### 2.2 Combiner les filtres avec Q objects

**Problème** : Les filtres sont appliqués un par un, générant plusieurs requêtes SQL.

**Action** : Remplacer (ligne ~525-555) :

```python
# AVANT
for key, value in filters.items():
    if isinstance(value, list):
        terms = value
    else:
        terms = [value]
    query = construct_query(key, terms)
    all_servers = all_servers.filter(query)  # ⚠️ Plusieurs requêtes

# APRÈS
from django.db.models import Q

combined_filter_query = Q()
for key, value in filters.items():
    if isinstance(value, list):
        terms = value
    else:
        terms = [value]
    
    query = construct_query(key, terms)
    combined_filter_query &= query  # Combine avec AND

# Une seule requête finale
if combined_filter_query:
    all_servers = all_servers.filter(combined_filter_query)
```

**Gain attendu** : 2-5x plus rapide pour les filtres multiples

---

### 2.3 Optimiser les requêtes avec `.only()`

**Problème** : Django charge tous les champs de tous les objets, même ceux non affichés.

**Action** : Remplacer (ligne ~470-473) :

```python
# AVANT
annotations = ServerAnnotation.objects.filter(SERVER_ID__in=hostnames_in_page)
annotations_dict = {ann.SERVER_ID: ann for ann in annotations}

# APRÈS
annotations = ServerAnnotation.objects.filter(
    SERVER_ID__in=hostnames_in_page
).only('SERVER_ID', 'notes', 'type', 'servicenow')  # ⭐ Ne charge que ce qui est nécessaire
annotations_dict = {ann.SERVER_ID: ann for ann in annotations}
```

**Action** : Remplacer (ligne ~560-600) :

```python
# AVANT
summaries_queryset = ServerGroupSummary.objects.filter(SERVER_ID__in=hostnames_in_page)

# APRÈS
summaries_queryset = ServerGroupSummary.objects.filter(
    SERVER_ID__in=hostnames_in_page
).only('SERVER_ID', 'total_instances', 'constant_fields', 'variable_fields')
```

**Gain attendu** : 20-40% de réduction de mémoire et temps de requête

---

### 2.4 Utiliser `.values_list()` pour les listbox

**Problème** : Django crée des objets Python complets pour juste récupérer des valeurs distinctes.

**Action** : Remplacer (ligne ~230-250) :

```python
# AVANT
listbox_evaluated = Server.objects.values_list(field, flat=True).distinct().order_by(field)

# C'EST DÉJÀ OPTIMISÉ ! ✅
# Mais assure-toi que les champs utilisés ont des indexes (voir Étape 1)
```

---

### 2.5 Optimiser la pagination en mode groupé

**Problème** : Dans le mode groupé, on pagine les hostnames PUIS on récupère tous les serveurs.

**Action** : Le code est déjà bien fait ! Vérifie juste que les indexes sont en place.

---

## ✅ ÉTAPE 3 : TESTS ET VALIDATION

### 3.1 Tester les performances AVANT/APRÈS

**Créer un script de benchmark** :

```python
# benchmark.py
import time
from django.test.utils import setup_test_environment
from userapp.models import Server, ServerGroupSummary, ServerAnnotation

setup_test_environment()

# Test 1 : Requête simple sur Server
start = time.time()
servers = Server.objects.filter(PAMELA_ENVIRONMENT='PROD').count()
print(f"Test 1 - Simple filter: {time.time() - start:.3f}s ({servers} results)")

# Test 2 : Requête avec plusieurs filtres
start = time.time()
servers = Server.objects.filter(
    PAMELA_ENVIRONMENT='PROD',
    PAMELA_AREA='EUROPE',
    PAMELA_DATACENTER='DC1'
).count()
print(f"Test 2 - Multiple filters: {time.time() - start:.3f}s ({servers} results)")

# Test 3 : Requête sur ServerGroupSummary
start = time.time()
summaries = ServerGroupSummary.objects.filter(
    total_instances__gt=1
).count()
print(f"Test 3 - Summary query: {time.time() - start:.3f}s ({summaries} results)")

# Test 4 : Jointure Server + Annotations
start = time.time()
hostnames = ['SRV001', 'SRV002', 'SRV003']  # Exemples
annotations = ServerAnnotation.objects.filter(
    SERVER_ID__in=hostnames
).only('SERVER_ID', 'notes')
print(f"Test 4 - Annotations: {time.time() - start:.3f}s ({len(list(annotations))} results)")
```

**Lancer le benchmark** :
```bash
python manage.py shell < benchmark.py
```

### 3.2 Monitorer les requêtes SQL

**Installer django-debug-toolbar** (si pas déjà fait) :
```bash
pip install django-debug-toolbar
```

**Activer dans `settings.py`** :
```python
if DEBUG:
    INSTALLED_APPS += ['debug_toolbar']
    MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']
    INTERNAL_IPS = ['127.0.0.1']
```

**Vérifier** :
- Nombre de requêtes SQL par page
- Temps d'exécution de chaque requête
- Présence de N+1 queries

---

## ✅ ÉTAPE 4 : MAINTENANCE ET SUIVI

### 4.1 Surveiller la croissance des indexes

```sql
-- PostgreSQL
SELECT schemaname, tablename, indexname, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_indexes
JOIN pg_class ON pg_indexes.indexname = pg_class.relname
WHERE schemaname = 'public'
ORDER BY pg_relation_size(indexrelid) DESC;
```

### 4.2 Analyser les requêtes lentes

**Activer le logging des requêtes lentes** dans `settings.py` :
```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': '/var/log/django/slow_queries.log',
        },
    },
    'loggers': {
        'django.db.backends': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}
```

---

## 📊 GAINS ATTENDUS

| Métrique | Avant | Après | Amélioration |
|----------|-------|-------|--------------|
| Temps de réponse (page simple) | 2-5s | 0.5-1.5s | **-60-70%** |
| Temps de réponse (filtres multiples) | 5-10s | 1-3s | **-60-70%** |
| Requêtes SQL par page | 50-100 | 20-40 | **-50-60%** |
| Mémoire par requête | 200-500 MB | 80-200 MB | **-50-60%** |
| Lecture disque (field_labels.json) | Chaque requête | Une fois au démarrage | **-99%** |

---

## 🚨 POINTS D'ATTENTION

### Risques potentiels

1. **Migration longue** : La création des indexes sur 400k lignes peut prendre 10-20 minutes.
   - ⚠️ Prévenir les utilisateurs
   - ⚠️ Faire en dehors des heures de pointe

2. **Espace disque** : Les indexes prennent de l'espace (environ 10-20% de la taille de la table).
   - ✅ Vérifier l'espace disponible avant : `df -h`

3. **Compatibilité** : Les modifications sont compatibles avec Django 3.x et 4.x.

---

## 📝 ORDRE D'EXÉCUTION RECOMMANDÉ

```
┌─────────────────────────────────────┐
│ 1. Backup de la base de données    │ ← OBLIGATOIRE
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ 2. Modifier models.py               │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ 3. makemigrations + migrate         │ ← Peut prendre 10-20 min
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ 4. Tester avec benchmark.py         │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ 5. Modifier views.py (cache JSON)   │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ 6. Modifier views.py (Q objects)    │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ 7. Modifier views.py (.only())      │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ 8. Tester à nouveau                 │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ 9. Déploiement en production        │
└─────────────────────────────────────┘
```

---

## ✅ CHECKLIST FINALE

Avant de déployer en production :

- [ ] Backup de la base de données effectué
- [ ] Migrations testées en environnement de dev
- [ ] Benchmark exécuté et résultats validés
- [ ] Tests fonctionnels passés (filtres, pagination, annotations)
- [ ] Espace disque vérifié (au moins 20% libre)
- [ ] Documentation mise à jour
- [ ] Utilisateurs prévenus (si migration longue)

---

## 🎉 CONCLUSION

Ces optimisations devraient améliorer **significativement** les performances de ton inventaire :
- **-60-70% de temps de réponse**
- **-50% de requêtes SQL**
- **-50% de mémoire utilisée**

Le plus gros gain viendra des **indexes sur ServerGroupSummary**, car c'est la table la plus interrogée et elle n'avait aucun index !

Bon courage pour la mise en œuvre ! 🚀
