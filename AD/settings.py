"""
Django settings for myapps project.
"""

import os
import shlex
import saml2
from pathlib import Path



# common/ad_credentials.py reads it from CyberArk at runtime by running the
# command below, given as one string in the environment (no shell is involved),
# e.g. AD_GET_CRED_CMD="/usr/local/bin/get-cred --safe MY_SAFE --object MY_OBJECT"

AD_GET_CRED_CMD = shlex.split(os.environ.get("AD_GET_CRED_CMD", ""))
AD_GET_CRED_TIMEOUT = 10        # seconds before get-cred is killed
AD_PASSWORD_TTL = 6 * 3600      # seconds before the cached password is refreshed anyway
AD_BIND_COOLDOWN = 60           # seconds without any AD bind after a non-rotation failure



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
        'access_file': {
            'class': 'logging.FileHandler',
            'filename': f'{_LOG_DIR}/client_access.log',
            'formatter': 'client_access',
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

        # AD service account password handling and shared LDAP group lookup
        'common.ad_credentials': {
            'handlers': ['console', 'app_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'common.ldap_utils': {
            'handlers': ['console', 'app_file'],
            'level': 'INFO',
            'propagate': False,
        },

    },
}



