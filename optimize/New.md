# 🎯 RÉCAPITULATIF FINAL - OPTIMISATIONS DJANGO INVENTORY

## 📋 RÉSUMÉ DE NOTRE DISCUSSION

**Contexte :**

- 400k serveurs, imports via tables Staging avec DROP/RENAME
- Pas de ForeignKey (à cause du double RENAME)
- `CREATE TABLE ServerStaging LIKE Server` → Les indexes sont copiés automatiquement ✅
- Migration Django va créer les indexes sur Server (10-20 min en dev)
- Les imports suivants préserveront les indexes via le LIKE

**Optimisations retenues :**

1. ✅ Ajout d’indexes sur les tables principales
1. ✅ Cache du JSON avec timeout (10 minutes)
1. ✅ Combinaison des filtres avec Q objects
1. ✅ Cache des listbox (1 heure)

**Optimisations écartées :**

- ❌ `.only()` : Gain marginal (125 KB/page), risque de requêtes supplémentaires avec colonnes dynamiques
- ❌ Indexes avec noms spécifiques : Complique inutilement, les noms auto-générés suffisent

-----

## 🗂️ 1. MODELS.PY - AJOUT DES INDEXES

### Server

```python
from django.db import models

class Server(models.Model):
    # === Tous tes champs existants (70+) ===
    APM_DETAILS_APPDESCRIPTION = models.CharField(max_length=100, null=True, blank=True)
    # ... (tous les autres champs)
    SERVER_ID = models.CharField(max_length=100, db_index=True)
    PAMELA_ENVIRONMENT = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_DATACENTER = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_AREA = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_SNOWITG_STATUS = models.CharField(max_length=100, null=True, blank=True)
    APP_NAME_VALUE = models.CharField(max_length=100, null=True, blank=True)
    # ... etc.

    class Meta:
        indexes = [
            # ✨ INDEXES EXISTANTS (à garder)
            models.Index(fields=['SERVER_ID']),
            models.Index(fields=['PAMELA_OSSHORTNAME']),
            models.Index(fields=['PAMELA_SERIAL']),
            models.Index(fields=['PAMELA_MODEL']),
            models.Index(fields=['PAMELA_PRODUCT']),
            models.Index(fields=['SERVER_DATACENTER_VALUE']),
            
            # ✨ NOUVEAUX INDEXES CRITIQUES
            # Index simples pour les champs filtrés fréquemment
            models.Index(fields=['PAMELA_ENVIRONMENT']),
            models.Index(fields=['PAMELA_AREA']),
            models.Index(fields=['PAMELA_DATACENTER']),
            models.Index(fields=['PAMELA_SNOWITG_STATUS']),
            
            # Index composé pour les requêtes groupées (SERVER_ID + autre champ)
            models.Index(fields=['SERVER_ID', 'APP_NAME_VALUE']),
        ]

    def __str__(self):
        return self.SERVER_ID
```

### ServerGroupSummary

```python
class ServerGroupSummary(models.Model):
    SERVER_ID = models.CharField(
        max_length=255, 
        unique=True,
        db_index=True  # ⭐ CRITIQUE : Index sur la clé de recherche
    )
    total_instances = models.PositiveIntegerField()
    constant_fields = models.JSONField(default=dict)
    variable_fields = models.JSONField(default=dict)
    last_updated = models.DateTimeField(auto_now=True)

    @property
    def servers(self):
        return Server.objects.filter(hostname=self.SERVER_ID)

    class Meta:
        indexes = [
            # ✨ NOUVEAUX INDEXES
            models.Index(fields=['last_updated']),
            models.Index(fields=['total_instances']),
            models.Index(fields=['SERVER_ID', 'total_instances']),
        ]
        verbose_name = "Server Group Summary"
        verbose_name_plural = "Server Group Summaries"
```

### ServerAnnotation

```python
class ServerAnnotation(models.Model):
    SERVER_ID = models.CharField(max_length=255, unique=True, db_index=True)
    notes = models.TextField(blank=True, help_text="Current annotation")
    type = models.CharField(max_length=50, null=True, blank=True, help_text="Type of annotation")
    servicenow = models.CharField(max_length=255, blank=True, help_text="ServiceNow RITM number")
    history = models.JSONField(default=list, help_text="Historical entries")
    updated_at = models.DateTimeField(auto_now=True)

    def add_entry(self, text, user, annotation_type, servicenow):
        if not self.history:
            self.history = []

        self.history.append({
            'text': text,
            'user': user.username if user else 'Unknown',
            'date': timezone.now().isoformat(),
            'type': annotation_type,
            'servicenow': servicenow
        })

        self.notes = text
        self.type = annotation_type
        self.servicenow = servicenow
        self.save()

    def get_history_display(self):
        if not self.history:
            return []
        return sorted(self.history, key=lambda x: x['date'], reverse=True)

    def __str__(self):
        return f"{self.SERVER_ID} - {self.notes[:50] if self.notes else 'No annotation'}"

    class Meta:
        ordering = ['SERVER_ID']
        verbose_name = "Server Annotation"
        verbose_name_plural = "Server Annotations"
        
        indexes = [
            # ✨ NOUVEAUX INDEXES
            models.Index(fields=['type']),
            models.Index(fields=['updated_at']),
            models.Index(fields=['SERVER_ID', 'type']),
        ]
```

### ImportStatus (optionnel)

```python
class ImportStatus(models.Model):
    date_import = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    message = models.TextField(blank=True, null=True)
    nb_entries_created = models.IntegerField(default=0)
    nb_groups_created = models.IntegerField(default=0)
    source_url = models.URLField(blank=True, null=True)

    def __str__(self):
        return f"{'OK' if self.success else 'KO'} {self.date_import.strftime('%d.%m.%Y %H:%M')}"

    class Meta:
        indexes = [
            models.Index(fields=['-date_import']),  # Pour ORDER BY date_import DESC
        ]
```

### Tables Staging

```python
class ServerStaging(models.Model):
    # ⚠️ MÊMES champs que Server
    # (copier-coller tous les champs de Server ici)
    
    class Meta:
        managed = False  # ← Django ne touche PAS à cette table
        db_table = 'userapp_serverstaging'  # Nom explicite
        # PAS besoin de définir les indexes, le CREATE TABLE ... LIKE les copiera

class ServerGroupSummaryStaging(models.Model):
    # ⚠️ MÊMES champs que ServerGroupSummary
    # (copier-coller tous les champs)
    
    class Meta:
        managed = False
        db_table = 'userapp_servergroupsummarystaging'
```

-----

## 🚀 2. VIEWS.PY - OPTIMISATIONS CODE

### Cache du JSON avec timeout (10 minutes)

```python
import json
import os
import time
from threading import Lock
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Q

# ✨ OPTIMISATION 1 : Cache JSON avec expiration 10 minutes
_field_labels_cache = None
_field_labels_timestamp = 0
_cache_lock = Lock()
CACHE_TTL = 600  # 10 minutes

def get_field_labels():
    """
    Cache avec expiration de 10 minutes
    Thread-safe pour Gunicorn
    """
    global _field_labels_cache, _field_labels_timestamp
    
    current_time = time.time()
    
    # Vérifier si le cache est encore valide
    if _field_labels_cache is not None and (current_time - _field_labels_timestamp) < CACHE_TTL:
        return _field_labels_cache
    
    # Cache expiré ou inexistant → recharger
    with _cache_lock:
        # Double-check après avoir acquis le lock
        if _field_labels_cache is not None and (current_time - _field_labels_timestamp) < CACHE_TTL:
            return _field_labels_cache
        
        # Charger le fichier
        json_path = os.path.join(os.path.dirname(__file__), 'field_labels.json')
        with open(json_path, 'r', encoding="utf-8") as f:
            _field_labels_cache = json.load(f)
        
        _field_labels_timestamp = current_time
        
    return _field_labels_cache


@login_required
def server_view(request):
    try:
        profile = UserProfile.objects.get(user=request.user)
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    # ✨ Utilise le cache au lieu de lire le fichier
    json_data = get_field_labels()
    
    # ... ton code existant pour permanent filters ...
    
    # Initialize filters dictionary
    filters = {}
    
    # Create filters from URL parameters
    for field_key, field_info in json_data['fields'].items():
        input_name = field_info.get('inputname')
        if input_name:
            filter_value = request.GET.get(input_name, '').split(',')
            filters[field_key] = [v for v in filter_value if v]
    
    # Get all servers
    all_servers = Server.objects.all().order_by('SERVER_ID')
    
    # Apply permanent filter
    if permanent_filter_query:
        all_servers = all_servers.filter(permanent_filter_query)
    
    # ✨ OPTIMISATION 2 : Combine tous les filtres avec Q objects
    combined_filter_query = Q()
    for key, values in filters.items():
        if not values:
            continue
        
        # Construire la query pour ce champ
        query = construct_query(key, values)
        combined_filter_query &= query  # Combine avec AND
    
    # Appliquer tous les filtres en une seule requête
    if combined_filter_query:
        all_servers = all_servers.filter(combined_filter_query)
    
    # Get filtered servers
    filtered_servers = all_servers.order_by('SERVER_ID', 'APP_NAME_VALUE')
    
    # ... reste de ta vue (pagination, etc.)
    # GARDE ton code existant, enlève juste les .only() si tu en avais
    
    return render(request, f'{app_name}/servers.html', context)
```

### Cache des listbox (1 heure)

```python
from django.core.cache import cache

def get_cached_listbox(field_name):
    """
    Cache des valeurs distinctes - 1 heure
    Indépendant des filtres (listbox doit toujours montrer toutes les valeurs)
    """
    cache_key = f'listbox_{field_name}'
    
    cached_values = cache.get(cache_key)
    if cached_values is not None:
        return cached_values
    
    # Calculer depuis TOUTE la table (pas de filtre)
    values = list(
        Server.objects.values_list(field_name, flat=True)
        .distinct()
        .order_by(field_name)
    )
    
    # Gérer EMPTY
    if any(x is None or (isinstance(x, str) and x.upper() == "EMPTY") for x in values):
        values = [x for x in values if x and x.upper() != "EMPTY"]
        values.sort()
        values.append("EMPTY")
    
    # Cache 1 heure
    cache.set(cache_key, values, 3600)
    
    return values


# Dans la boucle de génération des listbox
for field, info in json_data_fields.items():
    listbox_value = info.get('listbox', '')
    if listbox_value:
        if permanent_filter_attributes is not None and field in permanent_filter_attributes:
            # Cas permanent filter (déjà géré)
            listbox_evaluated = permanent_filter_attributes[field]
        else:
            # ✨ Utilise le cache
            listbox_evaluated = get_cached_listbox(field)
        
        # ... reste du code
```

### Invalidation du cache après import

```python
# Dans management/commands/import_servers.py
from django.core.cache import cache

class Command(BaseCommand):
    def handle(self, *args, **options):
        # ... ton code d'import ...
        
        # À la fin de l'import, invalider les caches
        # 1. Cache des listbox
        for field in ['PAMELA_ENVIRONMENT', 'PAMELA_DATACENTER', 'PAMELA_AREA', 
                      'PAMELA_SNOWITG_STATUS', 'APP_NAME_VALUE', 'PAMELA_OSSHORTNAME',
                      # ... ajoute tous les champs qui ont des listbox
                     ]:
            cache.delete(f'listbox_{field}')
        
        # 2. Le cache JSON se rafraîchira automatiquement dans les 10 minutes
        # Pas besoin de l'invalider manuellement
        
        self.stdout.write(self.style.SUCCESS('✅ Import terminé, caches invalidés'))
```

-----

## 🔍 3. COMMENT VÉRIFIER LES INDEXES

### Commandes SQL selon ta base de données

#### PostgreSQL

```bash
# Se connecter à la base
python manage.py dbshell
```

```sql
-- Lister tous les indexes d'une table
\d userapp_server

-- Résultat attendu :
-- Indexes:
--     "userapp_server_pkey" PRIMARY KEY, btree (id)
--     "userapp_server_SERVER_I_abc123_idx" btree (SERVER_ID)
--     "userapp_server_PAMELA__def456_idx" btree (PAMELA_ENVIRONMENT)
--     "userapp_server_PAMELA__ghi789_idx" btree (PAMELA_DATACENTER)
--     "userapp_server_SERVER_I_jkl012_idx" btree (SERVER_ID, APP_NAME_VALUE)
--     etc.

-- Vérifier ServerGroupSummary
\d userapp_servergroupsummary

-- Vérifier ServerAnnotation
\d userapp_serverannotation

-- Compter les indexes par table
SELECT 
    tablename, 
    COUNT(*) as nb_indexes 
FROM pg_indexes 
WHERE schemaname = 'public' 
  AND tablename IN ('userapp_server', 'userapp_servergroupsummary', 'userapp_serverannotation')
GROUP BY tablename;

-- Résultat attendu :
--         tablename          | nb_indexes
-- ---------------------------+------------
--  userapp_server            |         11
--  userapp_servergroupsummary|          4
--  userapp_serverannotation  |          4

-- Voir la taille des indexes
SELECT 
    schemaname, 
    tablename, 
    indexname, 
    pg_size_pretty(pg_relation_size(indexrelid)) as size
FROM pg_indexes
JOIN pg_class ON pg_indexes.indexname = pg_class.relname
WHERE schemaname = 'public'
  AND tablename = 'userapp_server'
ORDER BY pg_relation_size(indexrelid) DESC;
```

#### MySQL

```bash
python manage.py dbshell
```

```sql
-- Lister les indexes
SHOW INDEX FROM userapp_server;

-- Résultat sous forme de tableau avec colonnes :
-- Table | Non_unique | Key_name | Seq_in_index | Column_name | ...

-- Compter les indexes
SELECT 
    TABLE_NAME, 
    COUNT(DISTINCT INDEX_NAME) as nb_indexes
FROM information_schema.statistics
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('userapp_server', 'userapp_servergroupsummary', 'userapp_serverannotation')
GROUP BY TABLE_NAME;

-- Voir la taille des indexes
SELECT 
    TABLE_NAME,
    INDEX_NAME,
    ROUND(STAT_VALUE * @@innodb_page_size / 1024 / 1024, 2) AS size_mb
FROM mysql.innodb_index_stats
WHERE DATABASE_NAME = DATABASE()
  AND TABLE_NAME = 'userapp_server'
ORDER BY size_mb DESC;
```

#### SQLite (dev)

```bash
python manage.py dbshell
```

```sql
-- Lister les indexes
.indexes userapp_server

-- Voir la structure complète (avec indexes)
.schema userapp_server

-- Résultat attendu :
-- CREATE TABLE userapp_server (...);
-- CREATE INDEX "userapp_server_SERVER_I_abc123_idx" ON "userapp_server" ("SERVER_ID");
-- CREATE INDEX "userapp_server_PAMELA__def456_idx" ON "userapp_server" ("PAMELA_ENVIRONMENT");
-- etc.
```

### Script Python pour vérifier les indexes

```python
# management/commands/check_indexes.py
from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Vérifie les indexes sur les tables principales'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # PostgreSQL
            if connection.vendor == 'postgresql':
                cursor.execute("""
                    SELECT tablename, indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename IN ('userapp_server', 'userapp_servergroupsummary', 'userapp_serverannotation')
                    ORDER BY tablename, indexname
                """)
                
                current_table = None
                for row in cursor.fetchall():
                    table, index_name, index_def = row
                    if table != current_table:
                        self.stdout.write(f"\n📋 {table}")
                        current_table = table
                    self.stdout.write(f"  ✓ {index_name}")
            
            # MySQL
            elif connection.vendor == 'mysql':
                for table in ['userapp_server', 'userapp_servergroupsummary', 'userapp_serverannotation']:
                    cursor.execute(f"SHOW INDEX FROM {table}")
                    self.stdout.write(f"\n📋 {table}")
                    indexes = set()
                    for row in cursor.fetchall():
                        index_name = row[2]  # Key_name column
                        if index_name not in indexes:
                            indexes.add(index_name)
                            self.stdout.write(f"  ✓ {index_name}")
            
            # SQLite
            elif connection.vendor == 'sqlite':
                for table in ['userapp_server', 'userapp_servergroupsummary', 'userapp_serverannotation']:
                    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='{table}'")
                    self.stdout.write(f"\n📋 {table}")
                    for row in cursor.fetchall():
                        self.stdout.write(f"  ✓ {row[0]}")
        
        self.stdout.write(self.style.SUCCESS('\n✅ Vérification terminée'))
```

**Usage :**

```bash
python manage.py check_indexes
```

### Vérification après import

```bash
# 1. Vérifier AVANT import
python manage.py check_indexes > indexes_before.txt

# 2. Lancer l'import
python manage.py import_servers

# 3. Vérifier APRÈS import
python manage.py check_indexes > indexes_after.txt

# 4. Comparer
diff indexes_before.txt indexes_after.txt
# Résultat attendu : Aucune différence ! ✅
```

-----

## 📊 4. GAINS ATTENDUS

|Métrique                                |Avant                 |Après               |Amélioration|
|----------------------------------------|----------------------|--------------------|------------|
|**Temps de réponse (page simple)**      |2-5s                  |0.5-1.5s            |**-60-70%** |
|**Temps de réponse (filtres multiples)**|5-10s                 |1-3s                |**-60-70%** |
|**Lecture JSON**                        |Chaque requête (10ms) |1× toutes les 10 min|**-99%**    |
|**Calcul listbox**                      |Chaque requête (750ms)|1× par heure        |**-99%**    |
|**Requêtes SQL (filtres)**              |1 par filtre          |1 pour tous         |**-50-80%** |

-----

## ✅ 5. CHECKLIST DE MISE EN ŒUVRE

### Étape 1 : Backup (OBLIGATOIRE)

```bash
# PostgreSQL
pg_dump -U username -d database_name > backup_$(date +%Y%m%d).sql

# MySQL
mysqldump -u username -p database_name > backup_$(date +%Y%m%d).sql

# SQLite (dev)
cp db.sqlite3 db.sqlite3.backup
```

### Étape 2 : Modifier models.py

- [ ] Ajouter les indexes sur `Server`
- [ ] Ajouter les indexes sur `ServerGroupSummary`
- [ ] Ajouter les indexes sur `ServerAnnotation`
- [ ] Vérifier que `ServerStaging` a `managed = False`
- [ ] Vérifier que `ServerGroupSummaryStaging` a `managed = False`

### Étape 3 : Créer et appliquer les migrations

```bash
# Créer les migrations
python manage.py makemigrations

# Vérifier ce qui va être fait (optionnel)
python manage.py sqlmigrate inventory 0XXX

# Appliquer (10-20 minutes en dev avec 400k lignes)
python manage.py migrate
```

### Étape 4 : Vérifier les indexes

```bash
# Vérification SQL
python manage.py dbshell
# Puis : \d userapp_server (PostgreSQL) ou SHOW INDEX (MySQL)

# Ou avec le script
python manage.py check_indexes
```

### Étape 5 : Modifier views.py

- [ ] Ajouter la fonction `get_field_labels()` avec cache 10 min
- [ ] Remplacer `with open(...)` par `get_field_labels()`
- [ ] Ajouter la fonction `get_cached_listbox()` avec cache 1h
- [ ] Remplacer le calcul listbox par `get_cached_listbox(field)`
- [ ] Modifier la logique de filtres pour utiliser Q objects combinés

### Étape 6 : Modifier import_servers.py

- [ ] Ajouter l’invalidation des caches listbox à la fin

### Étape 7 : Tester

```bash
# Test 1 : Import avec nouveaux indexes
python manage.py import_servers

# Test 2 : Vérifier que les indexes survivent
python manage.py check_indexes

# Test 3 : Tester les performances
# → Ouvrir la page dans le navigateur
# → Vérifier les temps de réponse dans les logs Django
```

### Étape 8 : Configurer le cache Django (settings.py)

Si pas déjà fait :

```python
# Option 1 : Cache simple (en mémoire, par worker)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

# Option 2 : Redis (partagé entre workers, recommandé en prod)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
    }
}
```

-----

## 🎉 6. RÉSUMÉ ULTRA-COURT

**Ce que tu dois faire :**

1. ✅ Ajouter les indexes dans `models.py` (sans noms spécifiques)
1. ✅ `makemigrations` + `migrate` (10-20 min)
1. ✅ Ajouter le cache JSON (10 min timeout) dans `views.py`
1. ✅ Ajouter le cache listbox (1h timeout) dans `views.py`
1. ✅ Combiner les filtres avec Q objects dans `views.py`
1. ✅ Invalider les caches dans `import_servers.py`
1. ✅ Tester un import et vérifier les indexes

**Ce que tu ne dois PAS faire :**

- ❌ Toucher aux tables Staging (le `LIKE` copie tout)
- ❌ Utiliser `.only()` (gain marginal, risque de bugs)
- ❌ Mettre des noms spécifiques aux indexes (complique pour rien)
- ❌ Ajouter des ForeignKey (bloque le DROP/RENAME)

**Gains attendus :**

- 🚀 60-70% plus rapide sur les pages avec filtres
- 🚀 99% de réduction sur la lecture JSON
- 🚀 99% de réduction sur le calcul des listbox

-----

## 📞 AIDE SUPPLÉMENTAIRE

Si tu as des problèmes :

1. **Migration trop longue ?** → Normal avec 400k lignes, va boire un café ☕
1. **Indexes pas copiés après import ?** → Vérifier avec `\d userapp_server`
1. **Cache ne fonctionne pas ?** → Vérifier les settings `CACHES` dans Django
1. **Performance pas améliorée ?** → Vérifier que les indexes sont bien créés

**Bon courage pour la mise en œuvre ! 🚀**
