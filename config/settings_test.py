"""Test/CI settings for PPM.

Production settings live in config.settings. This module keeps production
behaviour untouched and only relaxes the pieces that make automated tests
impossible to run:

* SQLite in-memory DB instead of MySQL (no server dependency)
* HTTPS redirect / secure cookies disabled (Django test client speaks http)
* deterministic placeholder secrets so the module imports without a .env

Run with:
    DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test
"""

import os

# Must be set before config.settings is imported: django-environ's read_env
# never overwrites variables that already exist, so these win over .env.
os.environ.setdefault('DJANGO_SECRET_KEY', 'test-only-secret-key-not-for-production')
os.environ.setdefault('MYSQL_PASSWORD', 'test-only-placeholder')
os.environ.setdefault('AUTH_LOG_SIGNING_KEY', 'test-only-signing-key-not-for-production')
os.environ.setdefault('DEBUG', 'True')

from config.settings import *  # noqa: F401,F403,E402

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

DEBUG = True
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
