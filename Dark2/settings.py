import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = 'example-secret-key'
DEBUG = True
ALLOWED_HOSTS = []
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'servers',
    'api',
    'django_filters',
    'inventory', 
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'api.log_requests.LogAPIRequestsMiddleware'
]

ROOT_URLCONF = 'monprojet.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

REST_FRAMEWORK = {
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    #'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination', 
    'DEFAULT_PAGINATION_CLASS':  'rest_framework.pagination.PageNumberPagination', # can't be combined
    #'DEFAULT_PAGINATION_CLASS': 'api.pagination.HybridPagination',
    'PAGE_SIZE': 10,  # Only for ViewSets & ListAPIView
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',  
    )
}

WSGI_APPLICATION = 'monprojet.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}


LOGGING = {
    'version': 1,
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'c:\\temp\\api_requests.log',
        },
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'INFO',
        },
    },
    'loggers': {
        'request_logger': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'

CHART_AVAILABLE_FIELDS = {
    'hostname': {
        'label': 'Hostname',
        'suitable_charts': ['bar']
    },
    'os': {
        'label': 'Operating System',
        'suitable_charts': ['pie', 'doughnut', 'bar']
    },
    'datacenter': {
        'label': 'Datacenter',
        'suitable_charts': ['pie', 'doughnut', 'bar']
    },
    'owner': {
        'label': 'Owner',
        'suitable_charts': ['pie', 'doughnut', 'bar']
    },
    'application': {
        'label': 'Application',
        'suitable_charts': ['pie', 'doughnut', 'bar']
    },
    'virtualization': {
        'label': 'Virtualization Type',
        'suitable_charts': ['pie', 'doughnut']
    },
    'power_state': {
        'label': 'Power State',
        'suitable_charts': ['pie', 'doughnut']
    },
    'health_status': {
        'label': 'Health Status',
        'suitable_charts': ['pie', 'doughnut', 'bar']
    },
    'deployment_status': {
        'label': 'Deployment Status',
        'suitable_charts': ['pie', 'doughnut']
    },
    'security_zone': {
        'label': 'Security Zone',
        'suitable_charts': ['pie', 'doughnut', 'bar']
    },
    'business_unit': {
        'label': 'Business Unit',
        'suitable_charts': ['pie', 'doughnut', 'bar']
    },
}

# Filtres disponibles (pour ton interface principale et les graphiques)
AVAILABLE_FILTERS = {
    'hostname': {'label': 'Hostname', 'type': 'text'},
    'os': {'label': 'Operating System', 'type': 'text'},
    'datacenter': {'label': 'Datacenter', 'type': 'text'},
    'owner': {'label': 'Owner', 'type': 'text'},
    'application': {'label': 'Application', 'type': 'text'},
    'power_state': {'label': 'Power State', 'type': 'text'},
    'health_status': {'label': 'Health Status', 'type': 'text'},
}