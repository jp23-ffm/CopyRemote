

ENVIRONMENT = 'DEV'


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'djangosaml2.middleware.SamlSessionMiddleware',
    'common.middleware.ClientLoggingMiddleware',
    #'businesscontinuity.middleware.BusinessContinuityEditorMiddleware',
    'monitor.middleware.StatsMiddleware',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': ['common'],
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


SAML_CREATE_UNKNOWN_USER = True
SAML_CSP_HANDLER=''
SESSION_COOKIE_SECURE = True


_LOG_DIR = '/apps/chimera/logs'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s %(levelname)-8s %(name)s %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'client_access': {
            'format': '%(asctime)s - IP: %(ip)s - User: %(user)s - %(method)s %(path)s - %(user_agent)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
            'level': 'WARNING',
        },
        'app_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': f'{_LOG_DIR}/chimera.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'standard',
            'encoding': 'utf-8',
        },
        'api_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': f'{_LOG_DIR}/chimera_api.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'standard',
            'encoding': 'utf-8',
        },
        'access_file': {
            'class': 'logging.FileHandler',
            'filename': f'{_LOG_DIR}/client_access.log',
            'formatter': 'client_access',
            'encoding': 'utf-8',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'app_file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'app_file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'djangosaml2': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'saml2': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'common.middleware': {
            'handlers': ['access_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'inventory': {
            'handlers': ['console', 'app_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'businesscontinuity': {
            'handlers': ['console', 'app_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'discrepancies': {
            'handlers': ['console', 'app_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'monitor': {
            'handlers': ['console', 'app_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'accessrights': {
            'handlers': ['console', 'app_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'api': {
            'handlers': ['console', 'api_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

