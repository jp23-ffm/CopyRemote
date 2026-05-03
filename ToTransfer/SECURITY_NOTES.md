# Security Notes — settings_dev.py

Points identifiés, sans ordre de priorité d'implémentation.
Ne pas commiter ce fichier s'il est complété avec des valeurs réelles.

---

## Critique

### 1. Credentials hardcodés dans le fichier source

Quatre secrets sont en clair dans `settings_dev.py`. S'ils sont dans git, ils sont dans
l'historique de façon permanente même après suppression.

- `SECRET_KEY` : clé Django préfixée `django-insecure-`, invalide pour la production
- `LDAP_BIND_PASSWORD` : mot de passe du compte de service AD
- `DATABASES['default']['PASSWORD']`
- `DATABASES['secondary']['PASSWORD']`

**Recommandation** : variables d'environnement, lues au démarrage.

```python
import os

SECRET_KEY       = os.environ['DJANGO_SECRET_KEY']
LDAP_BIND_PASSWORD = os.environ['LDAP_BIND_PASSWORD']

DATABASES = {
    'default': {
        ...
        'PASSWORD': os.environ['DB_PASSWORD'],
    },
    'secondary': {
        ...
        'PASSWORD': os.environ['DB_SECONDARY_PASSWORD'],
    },
}
```

Les variables peuvent être déclarées dans un fichier `/etc/chimera/chimera.env` chargé
par le service systemd (`EnvironmentFile=`), ou dans un `.env` local exclu de git.

---

### 2. ALLOWED_HOSTS trop large

```python
ALLOWED_HOSTS = ['*']
```

Permet les attaques par Host header (cache poisoning, génération de liens de
réinitialisation avec un domaine contrôlé par l'attaquant).

**Recommandation** :
```python
ALLOWED_HOSTS = ['chimeraiaas.dev.echonet']
```

---

## Important

### 3. Assertions SAML non signées

```python
'want_response_signed': False,
'want_assertions_signed': False,
```

Les deux à `False` simultanément signifient que Django accepte des assertions SAML
sans vérification de signature. Un attaquant capable d'intercepter ou de forger une
réponse SAML (MITM, IdP compromis) pourrait s'authentifier sans credentials valides.

**Recommandation** : passer les deux à `True` si l'IdP le supporte (PingFederate,
ADFS, Okta le supportent tous). À valider avec l'équipe IdP.

```python
'want_response_signed': True,
'want_assertions_signed': True,
```

---

### 4. SAML debug activé

```python
'debug': True,
```

Expose des informations détaillées sur les échanges SAML dans les logs.
Acceptable en dev, à désactiver en production.

**Recommandation** : `'debug': False`

---

### 5. Headers HTTPS incomplets

`SESSION_COOKIE_SECURE = True` est déjà présent (bien).
Il manque :

```python
CSRF_COOKIE_SECURE = True
# Indique à Django qu'il est derrière un proxy HTTPS :
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
```

Sans `SECURE_PROXY_SSL_HEADER`, `request.is_secure()` retourne `False` même en HTTPS,
ce qui peut affecter certaines redirections et la génération d'URLs absolues.

Option supplémentaire (si nginx ne gère pas HSTS) :
```python
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
```

---

## Mineur

### 6. SAML_CREATE_UNKNOWN_USER = True

Crée automatiquement un compte Django à la première connexion SAML réussie.
Acceptable pour du SSO entreprise, mais implique que tout compte AD valide
peut obtenir un accès si l'IdP est mal configuré ou compromis.

Pas d'action urgente, juste à avoir en tête lors des revues d'accès.

---

### 7. DATA_UPLOAD_MAX_MEMORY_SIZE = 209715200 (200 Mo)

Limite très haute. Un utilisateur authentifié peut forcer Django à allouer 200 Mo
par requête, ce qui peut mener à un épuisement mémoire.

**Recommandation** : réduire si les imports CSV n'ont pas besoin de 200 Mo,
ou limiter ce paramètre aux vues d'import uniquement.

---

### 8. STATICFILES_DIRS inclut reportappdev/static

```python
os.path.join(BASE_DIR, 'reportappdev/static'),
```

Un répertoire de dev (`reportappdev`) est exposé comme répertoire statique.
À vérifier si ce dossier existe en production et si son contenu peut être exposé.

---

### 9. SAML_CSP_HANDLER = ''

Aucun handler Content-Security-Policy côté Django.
Pas critique si nginx gère les headers CSP (`add_header Content-Security-Policy ...`).
À vérifier dans la config nginx.

---

### 10. Durée de vie des sessions (non configuré)

Aucun paramètre de session n'est défini → Django applique ses défauts :
- `SESSION_COOKIE_AGE` = 1 209 600 s = **2 semaines**
- `SESSION_EXPIRE_AT_BROWSER_CLOSE` = **False** (survit à la fermeture du navigateur)

Conséquence : un utilisateur peut revenir 13 jours plus tard via un favori et être
toujours authentifié. Le SAML n'est sollicité que quand la session Django a expiré.

**Recommandation pour un outil interne :**

```python
SESSION_COOKIE_AGE = 28800           # 8h max depuis la dernière action
SESSION_EXPIRE_AT_BROWSER_CLOSE = True  # détruite à la fermeture du navigateur
SESSION_SAVE_EVERY_REQUEST = True    # expiry glissant : repart à chaque requête
```

Avec ces trois combinés : session active tant que l'utilisateur travaille,
déconnexion automatique après 8h d'inactivité ou fermeture du navigateur.

La table `django_session` n'est jamais purgée automatiquement. Ajouter un cron
quotidien pour supprimer les sessions expirées (les sessions actives ne sont pas
touchées) :

```bash
# /etc/cron.d/chimera  ou crontab -e
0 3 * * * /apps/chimera/venv/bin/python /apps/chimera/manage.py clearsessions
```

Note : si la commande n'a jamais été lancée, faire un premier passage manuel
avant de mettre le cron en place.
