"""Reuse the isolated test suite settings against this stack's PostgreSQL only."""
import os

assert not os.environ.get('DATABASE_URL')
assert (os.environ.get('POSTGRES_HOST'), os.environ.get('POSTGRES_DB'), os.environ.get('POSTGRES_USER')) == (
    'db', 'phase4a_db', 'phase4a_user@:/#?%+',
)
_password = os.environ['POSTGRES_PASSWORD']
from config.test_settings import *  # noqa: F403

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': 'phase4a_db', 'USER': 'phase4a_user@:/#?%+',
    'PASSWORD': _password, 'HOST': 'db', 'PORT': '5432',
    'CONN_MAX_AGE': 0, 'TEST': {'NAME': 'test_phase4a'},
}}
