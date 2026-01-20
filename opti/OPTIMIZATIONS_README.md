# Optimisations Inventory - Guide d'intégration

Ce document explique les optimisations apportées aux requêtes de base de données et au chargement différé (lazy loading) des colonnes.

## Fichiers créés/modifiés

### Nouveaux fichiers
- `views_optimized.py` - Version optimisée des vues avec requêtes améliorées
- `urls_optimized.py` - URLs avec nouveaux endpoints API
- `static/inventory/js/column-lazy-loader.js` - JavaScript pour le lazy loading
- `templates/inventory/table-lazyload.html` - Template optimisé pour le lazy loading

### Fichiers modifiés
- `templatetags/inventory_custom_filters.py` - Nouveaux filtres `is_column_visible` et `split`

---

## 1. Optimisations des requêtes de base de données

### Problèmes corrigés

| Problème | Solution |
|----------|----------|
| Lecture répétée de field_labels.json | Cache en mémoire avec TTL de 10 minutes |
| Requêtes listbox individuelles (N requêtes) | Batch loading + cache Django (1 heure) |
| Mode groupé: 4+ requêtes séparées | Optimisé à 2-3 requêtes avec prefetch |
| Double ordering | Supprimé, un seul `.order_by()` final |

### Gains estimés

- **Listbox loading**: De ~20 requêtes à ~0 (cache hit) ou ~20 requêtes batch optimisées
- **Mode groupé**: De 4 requêtes à 2-3 requêtes
- **JSON config**: De ~5 lectures fichier par requête à 1 (cachée)

---

## 2. Lazy Loading des colonnes

### Principe

Au lieu de rendre toutes les colonnes dans le HTML initial (même cachées), seules les colonnes visibles sont rendues avec leurs données. Quand l'utilisateur active une nouvelle colonne:

1. La colonne devient visible (CSS)
2. Une requête AJAX charge uniquement les données de cette colonne
3. Les données sont injectées dans le DOM sans rechargement de page

### Avantages

- **DOM initial plus petit**: Moins de cellules à créer/parser
- **Payload JavaScript réduit**: `serversData` ne contient que les colonnes visibles
- **Temps de rendu initial réduit**: Le navigateur a moins de travail
- **Meilleure UX**: Pas de rechargement de page

---

## 3. Guide d'intégration

### Étape 1: Activer les vues optimisées

Modifier `inventory/urls.py`:

```python
# Remplacer
from . import views

# Par
from . import views_optimized

# Et changer les références
path('', views_optimized.server_view, name='server_view'),
```

Ou simplement renommer `urls_optimized.py` en `urls.py` (après backup).

### Étape 2: Activer le template lazy loading

Dans `servers.html`, modifier l'include du tableau:

```html
{% comment %} Ancien code {% endcomment %}
{% if flat_view %}
    {% include 'inventory/table-flat.html' %}
{% else %}
    {% include 'inventory/table.html' %}
{% endif %}

{% comment %} Nouveau code avec lazy loading {% endcomment %}
{% if flat_view %}
    {% include 'inventory/table-flat.html' %}
{% else %}
    {% include 'inventory/table-lazyload.html' %}
{% endif %}
```

### Étape 3: Ajouter le JavaScript

Dans `servers.html`, ajouter avant la fermeture de `</body>`:

```html
<script src="{% static appname|add:'/js/column-lazy-loader.js' %}"></script>
```

### Étape 4: Tester

1. Ouvrir la page inventory
2. Observer la console développeur (F12)
3. Décocher une colonne → elle disparaît (pas de requête)
4. Cocher une colonne non chargée → requête AJAX visible dans Network
5. Les données apparaissent sans rechargement

---

## 4. API Endpoints

### GET /inventory/api/column-data/

Charge les données pour des colonnes spécifiques.

**Paramètres:**
- `columns`: Colonnes à charger (ex: `ENVIRONMENT,REGION`)
- `hostnames`: SERVER_IDs pour lesquels charger (optionnel)
- `page`, `page_size`: Pagination si hostnames non fournis
- `filters`: Filtres JSON encodés
- `permanentfilter`: Nom du filtre permanent
- `view`: `flat` ou `grouped`

**Réponse:**
```json
{
  "data": {
    "SERVER001": {
      "constant_fields": {"ENVIRONMENT": "PROD"},
      "variable_fields": {},
      "instances": [{"ENVIRONMENT": "PROD"}, {"ENVIRONMENT": "PROD"}]
    }
  },
  "columns": ["ENVIRONMENT"],
  "hostnames": ["SERVER001"]
}
```

### GET /inventory/api/listbox-values/

Charge les valeurs distinctes pour les dropdowns.

**Paramètres:**
- `columns`: Colonnes pour lesquelles charger les valeurs

**Réponse:**
```json
{
  "data": {
    "ENVIRONMENT": ["DEV", "PROD", "UAT"],
    "REGION": ["EMEA", "APAC", "US"]
  }
}
```

---

## 5. Configuration avancée

### Ajuster le cache

Dans `views_optimized.py`:

```python
# Cache JSON config (en secondes)
FIELD_LABELS_CACHE_TTL = 600  # 10 minutes

# Dans batch_load_listbox_values:
cache.set(cache_key, values, 3600)  # 1 heure pour listbox
```

### Ajuster le lazy loader JavaScript

Dans `column-lazy-loader.js`:

```javascript
const CONFIG = {
    cacheDuration: 5 * 60 * 1000,  // 5 minutes cache côté client
    loadingIndicatorDelay: 100,     // Délai avant spinner
};
```

---

## 6. Rollback

Pour revenir à la version originale:

1. Dans `urls.py`: remplacer `views_optimized` par `views`
2. Dans `servers.html`: utiliser `table.html` au lieu de `table-lazyload.html`
3. Retirer l'include de `column-lazy-loader.js`

Les optimisations du cache listbox dans `views_optimized.py` peuvent être réutilisées indépendamment du lazy loading.

---

## 7. Tests recommandés

- [ ] Page charge correctement avec colonnes par défaut
- [ ] Clic sur checkbox colonne: données chargées via AJAX
- [ ] Pas de rechargement page lors changement colonnes
- [ ] Export fonctionne avec nouvelles vues
- [ ] Filtres fonctionnent
- [ ] Mode flat fonctionne
- [ ] Mode grouped fonctionne
- [ ] Annotations fonctionnent
- [ ] Performance améliorée (mesurer avec DevTools)
