
import os
os.makedirs(BASE_DIR / 'logs', exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '{asctime} {levelname} {name}: {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'chimera.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'standard',
            'encoding': 'utf-8',
        },
        'api_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'chimera_api.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'standard',
            'encoding': 'utf-8',
        },
        'apps_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'chimera_apps.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'standard',
            'encoding': 'utf-8',
        },
        'compact_weekly_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'compact_weekly.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 3,
            'formatter': 'standard',
            'encoding': 'utf-8',
        },
        'compact_monthly_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'compact_monthly.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 3,
            'formatter': 'standard',
            'encoding': 'utf-8',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'inventory': {
            'handlers': ['console', 'apps_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'businesscontinuity': {
            'handlers': ['console', 'apps_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'discrepancies': {
            'handlers': ['console', 'apps_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'monitor': {
            'handlers': ['console', 'apps_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'accessrights': {
            'handlers': ['console', 'apps_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'api': {
            'handlers': ['console', 'api_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'compact.weekly': {
            'handlers': ['console', 'compact_weekly_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'compact.monthly': {
            'handlers': ['console', 'compact_monthly_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}