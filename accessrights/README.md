# accessrights — Django App

Centralized permission management dashboard for Inventory, Business Continuity, and Discrepancies.

## Structure

```
accessrights/
├── static/accessrights/
│   ├── css/dashboard.css        ← Styles (light + dark mode)
│   ├── js/dashboard.js          ← Dashboard engine (data-driven)
│   └── permissions.json         ← App definitions, colors, permission types
├── templates/accessrights/
│   └── dashboard.html           ← Django template
├── templatetags/
│   └── accessrights_tags.py     ← {% has_perm %} template tag
├── management/commands/
│   └── seed_permissions.py      ← Seed Permission table from JSON
├── models.py                    ← Permission, UserPermission, AuditLog
├── views.py                     ← Dashboard + JSON endpoints
├── urls.py                      ← URL routing
├── helpers.py                   ← has_perm(), user_perms() for views
├── signals.py                   ← Login signal (optional AD sync)
├── admin.py                     ← Django admin registration
└── apps.py                      ← AppConfig
```

## Installation

### 1. Add to INSTALLED_APPS

```python
# settings.py
INSTALLED_APPS = [
    ...
    'accessrights',
]
```

### 2. Add URL route

```python
# project/urls.py
urlpatterns = [
    ...
    path('accessrights/', include('accessrights.urls')),
]
```

### 3. Run migrations

```bash
python manage.py makemigrations accessrights
python manage.py migrate
```

### 4. Seed permissions from JSON

```bash
python manage.py seed_permissions
```

## Usage in your views

```python
from accessrights.helpers import has_perm

def edit_server(request, server_id):
    if not has_perm(request.user, 'inventory.edit'):
        return HttpResponseForbidden()
    ...
```

## Usage in templates

```html
{% load accessrights_tags %}

{% has_perm user 'inventory.edit' as can_edit %}
{% if can_edit %}
    <button class="edit-btn">Edit</button>
{% endif %}
```

## Adding a new app or permission

1. Edit `static/accessrights/permissions.json`
2. Run `python manage.py seed_permissions`
3. Done — no migration needed
