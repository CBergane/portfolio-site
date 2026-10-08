"""Reuse the isolated test suite settings against this stack's PostgreSQL only."""
import os

assert os.environ.get('DATABASE_URL') == (
    'postgres://phase4a_user:phase4a-synthetic-password@db:5432/phase4a_db'
)
from config.test_settings import *  # noqa: F403

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': 'phase4a_db', 'USER': 'phase4a_user',
    'PASSWORD': 'phase4a-synthetic-password', 'HOST': 'db', 'PORT': '5432',
    'CONN_MAX_AGE': 0, 'TEST': {'NAME': 'test_phase4a'},
}}
