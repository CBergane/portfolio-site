"""Prove the baseline cannot inherit service credentials or make live HTTP calls."""
import os
from datetime import datetime
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import get_connection
from django.test import SimpleTestCase, override_settings

from ..views import send_discord_notification, verify_turnstile


class TestSettingsIsolationTests(SimpleTestCase):
    def test_cache_mail_and_files_are_local(self):
        self.assertEqual(settings.CACHES['default']['BACKEND'], 'django.core.cache.backends.locmem.LocMemCache')
        cache.set('phase1-isolation', 'synthetic', 30)
        self.addCleanup(cache.delete, 'phase1-isolation')
        self.assertEqual(cache.get('phase1-isolation'), 'synthetic')
        self.assertEqual(get_connection().__class__.__module__, 'django.core.mail.backends.locmem')
        name = default_storage.save('phase1/synthetic.txt', ContentFile(b'synthetic test media'))
        self.addCleanup(default_storage.delete, name)
        with default_storage.open(name) as stored:
            self.assertEqual(stored.read(), b'synthetic test media')
        self.assertTrue(Path(default_storage.path(name)).is_relative_to(Path(settings.MEDIA_ROOT)))
        self.assertFalse(Path(settings.MEDIA_ROOT).is_relative_to(settings.BASE_DIR))
        self.assertFalse(Path(settings.STATIC_ROOT).is_relative_to(settings.BASE_DIR))

    def test_integrations_are_disabled_by_default(self):
        self.assertEqual(settings.TURNSTILE_SITE_KEY, '')
        self.assertEqual(settings.TURNSTILE_SECRET_KEY, '')
        for name in ('DISCORD_WEBHOOK_URL', 'HTB_TOKEN', 'HTB_USER_ID'):
            self.assertEqual(os.environ.get(name), '')
        with patch('home.views.requests.post') as post:
            self.assertFalse(verify_turnstile('synthetic-token', '192.0.2.1'))
            self.assertFalse(send_discord_notification(None))
        post.assert_not_called()

    def test_unmocked_http_is_blocked_before_network_access(self):
        with patch('socket.getaddrinfo', side_effect=AssertionError('DNS must not run')) as dns:
            with self.assertRaisesRegex(AssertionError, 'External HTTP is disabled'):
                requests.get('https://integration.example.invalid/')
        dns.assert_not_called()
        with override_settings(TURNSTILE_SECRET_KEY='synthetic-secret'):
            with self.assertRaisesRegex(AssertionError, 'External HTTP is disabled'):
                verify_turnstile('synthetic-token', '192.0.2.1')
        with patch.dict(os.environ, {'DISCORD_WEBHOOK_URL': 'https://webhook.example.invalid/'}):
            with self.assertRaisesRegex(AssertionError, 'External HTTP is disabled'):
                send_discord_notification(SimpleNamespace(
                    name='Synthetic', email='test@example.invalid', subject='',
                    message='Synthetic message', submitted_at=datetime(2026, 1, 1),
                    ip_address='192.0.2.1',
                ))

    def test_fresh_import_ignores_dotenv_and_inherited_service_configuration(self):
        script = '''
import os
from unittest.mock import patch
with patch('dotenv.find_dotenv', side_effect=AssertionError('.env must not be read')):
    from config import test_settings as test
expected_database = {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}
if os.environ['TEST_DATABASE_ENGINE'] == 'postgresql':
    expected_database = {
        'ENGINE': 'django.db.backends.postgresql', 'NAME': 'portfolio_phase1',
        'USER': 'portfolio_phase1', 'PASSWORD': 'phase1-synthetic-password',
        'HOST': '127.0.0.1', 'PORT': '55433', 'CONN_MAX_AGE': 0,
        'TEST': {'NAME': 'test_portfolio_phase1'},
    }
assert test.DATABASES['default'] == expected_database
assert test.CACHES['default']['BACKEND'] == 'django.core.cache.backends.locmem.LocMemCache'
assert test.SECRET_KEY == 'phase1-synthetic-test-key'
assert test.TURNSTILE_SECRET_KEY == test.TURNSTILE_SITE_KEY == ''
assert test.ALLOWED_HOSTS == ['testserver', 'localhost', '127.0.0.1']
assert test.WAGTAILADMIN_BASE_URL == 'http://testserver'
assert not any(name.startswith('PG') for name in os.environ)
for name in ('DISCORD_WEBHOOK_URL', 'HTB_TOKEN', 'HTB_USER_ID'):
    assert os.environ[name] == ''
'''
        env = {
            'DATABASE_URL': 'deliberately-invalid-synthetic-url',
            'CACHE_URL': 'redis://redis.example.invalid/1',
            'DJANGO_SECRET_KEY': 'inherited-synthetic-key',
            'DJANGO_DEBUG': '0',
            'DJANGO_ALLOWED_HOSTS': 'production.example.invalid',
            'WAGTAILADMIN_BASE_URL': 'https://admin.example.invalid',
            'TURNSTILE_SITE_KEY': 'inherited-synthetic-site-key',
            'TURNSTILE_SECRET_KEY': 'inherited-synthetic-secret',
            'DISCORD_WEBHOOK_URL': 'https://webhook.example.invalid/',
            'HTB_TOKEN': 'inherited-synthetic-token',
            'HTB_USER_ID': '123',
            'POSTGRES_DB': 'inherited_synthetic_database',
            'POSTGRES_USER': 'inherited_synthetic_user',
            'POSTGRES_PASSWORD': 'inherited-synthetic-password',
            'POSTGRES_HOST': 'database.example.invalid',
            'TEST_POSTGRES_PORT': '55433',
            'PGHOSTADDR': '192.0.2.1',
            'PGSERVICE': 'synthetic_external_service',
            'PGSERVICEFILE': '/synthetic/nonexistent/service.conf',
            'PGOPTIONS': '-c search_path=synthetic',
        }
        for backend in ('sqlite', 'postgresql'):
            with self.subTest(backend=backend):
                result = subprocess.run(
                    [sys.executable, '-c', script], cwd=settings.BASE_DIR,
                    env={**env, 'TEST_DATABASE_ENGINE': backend},
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_invalid_database_selector_fails_closed(self):
        for env in ({'TEST_DATABASE_ENGINE': 'production'},
                    {'TEST_DATABASE_ENGINE': 'postgresql', 'TEST_POSTGRES_PORT': 'invalid'}):
            with self.subTest(env=env):
                result = subprocess.run(
                    [sys.executable, '-c', 'from config import test_settings'],
                    cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, timeout=30,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('ImproperlyConfigured', result.stderr)
