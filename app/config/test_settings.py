"""Isolated validation; never load .env or use production service credentials."""
import os
import tempfile
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured

_database_engine = os.environ.get('TEST_DATABASE_ENGINE', 'sqlite')
_postgres_port = os.environ.get('TEST_POSTGRES_PORT', '55432')

# Reuse app/template configuration without evaluating the caller's environment.
with patch('dotenv.load_dotenv'), patch.dict(os.environ, {
    'DJANGO_SECRET_KEY': 'phase1-synthetic-test-key',
    'DJANGO_DEBUG': '1',
    'DATABASE_URL': 'sqlite:///:memory:',
}, clear=True):
    from .settings import *  # noqa: F403

SECRET_KEY = 'phase1-synthetic-test-key'
DEBUG = True
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
SECURE_SSL_REDIRECT = False
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
if _database_engine == 'postgresql':
    if not _postgres_port.isdecimal() or not 1 <= int(_postgres_port) <= 65535:
        raise ImproperlyConfigured('TEST_POSTGRES_PORT must be a valid TCP port.')
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'portfolio_phase1',
        'USER': 'portfolio_phase1',
        'PASSWORD': 'phase1-synthetic-password',
        'HOST': '127.0.0.1',
        'PORT': _postgres_port,
        'CONN_MAX_AGE': 0,
        'TEST': {'NAME': 'test_portfolio_phase1'},
    }}
elif _database_engine != 'sqlite':
    raise ImproperlyConfigured('TEST_DATABASE_ENGINE must be sqlite or postgresql.')

# libpq must not inherit an alternate host address, service file or SQL options.
for _name in tuple(os.environ):
    if _name.startswith('PG'):
        del os.environ[_name]

CACHES = {'default': {
    'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    'LOCATION': 'portfolio-phase1-tests',
}}
_test_files = tempfile.TemporaryDirectory(prefix='portfolio-phase1-')
MEDIA_ROOT = os.path.join(_test_files.name, 'media')
STATIC_ROOT = os.path.join(_test_files.name, 'static')
os.makedirs(STATIC_ROOT)
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
WAGTAILADMIN_BASE_URL = 'http://testserver'
WAGTAILSEARCH_BACKENDS = {'default': {'BACKEND': 'wagtail.search.backends.database'}}
WAGTAILEMBEDS_FINDERS = []
TURNSTILE_SITE_KEY = ''
TURNSTILE_SECRET_KEY = ''

# Discord reads os.environ at call time rather than Django settings.
for _name in ('DISCORD_WEBHOOK_URL', 'HTB_TOKEN', 'HTB_USER_ID'):
    os.environ[_name] = ''

# Tests may mock HTTP responses explicitly; unmocked integrations fail before I/O.
_http_guard = patch('requests.sessions.Session.request', side_effect=AssertionError(
    'External HTTP is disabled by config.test_settings; mock the integration.'
))
_http_guard.start()
