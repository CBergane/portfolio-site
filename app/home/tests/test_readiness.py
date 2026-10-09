"""Deployment probes and credentials use synthetic settings and mocked I/O."""
from contextlib import redirect_stderr
from io import StringIO
import os
from pathlib import Path
import runpy
from urllib.parse import quote
from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase, override_settings

from config import healthcheck


class DatabaseConfigurationTests(SimpleTestCase):
    def configuration(self, **environment):
        with patch('dotenv.load_dotenv'), patch.dict(os.environ, {
            'DJANGO_SECRET_KEY': 'phase6a-synthetic-key', 'DJANGO_DEBUG': '0',
            **environment,
        }, clear=True):
            return runpy.run_path(str(Path(__file__).resolve().parents[2] / 'config' / 'settings.py'))

    def test_separate_fields_preserve_reserved_characters(self):
        user, password, name = 'user@:/#?%+', 'synthetic:p@ss/#?%+&= $!\'"\\', 'db/#?%+'
        settings = self.configuration(POSTGRES_USER=user, POSTGRES_PASSWORD=password, POSTGRES_DB=name)
        database = settings['DATABASES']['default']
        self.assertEqual((database['USER'], database['PASSWORD'], database['NAME']), (user, password, name))
        self.assertEqual(database['HOST'], 'db')
        self.assertEqual(database['OPTIONS']['connect_timeout'], 3)
        self.assertEqual(settings['CACHES']['default']['OPTIONS'], {
            'socket_connect_timeout': 2, 'socket_timeout': 2,
        })

    def test_explicit_encoded_database_url_remains_supported(self):
        user, password = 'user@:/#?%+', 'synthetic:p@ss/#?%+&= $!\'"\\'
        url = f'postgres://{quote(user, safe="")}:{quote(password, safe="")}@localhost:5433/example'
        database = self.configuration(DATABASE_URL=url, POSTGRES_USER='unused')['DATABASES']['default']
        self.assertEqual((database['USER'], database['PASSWORD']), (user, password))
        self.assertEqual((database['HOST'], database['PORT']), ('localhost', 5433))

    def test_sqlite_url_does_not_receive_postgresql_options(self):
        database = self.configuration(DATABASE_URL='sqlite:///:memory:')['DATABASES']['default']
        self.assertEqual(database['ENGINE'], 'django.db.backends.sqlite3')
        self.assertNotIn('connect_timeout', database.get('OPTIONS', {}))


class ReadinessTests(SimpleTestCase):
    def setUp(self):
        self.database = self.enterContext(patch.object(healthcheck, 'connection'))
        self.cursor = self.database.cursor.return_value.__enter__.return_value
        self.cursor.fetchone.return_value = (1,)
        self.cache = self.enterContext(patch.object(healthcheck, 'cache'))
        self.cache.get.return_value = 'ok'
        self.http = self.enterContext(patch.object(healthcheck, 'urlopen'))
        self.response = self.http.return_value.__enter__.return_value
        self.response.status, self.response.read.return_value = 200, b'OK'

    @override_settings(ALLOWED_HOSTS=['cbergane.se'])
    def test_success_probes_database_cache_and_local_http(self):
        self.assertEqual(healthcheck.main(), 0)
        self.cursor.execute.assert_called_once_with('SELECT 1')
        self.database.close.assert_called_once()
        request = self.http.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:8000/healthz')
        self.assertEqual(request.get_header('Host'), 'cbergane.se')
        self.assertEqual(request.get_header('X-forwarded-proto'), 'https')
        self.assertEqual(self.http.call_args.kwargs['timeout'], 2)

    def test_overlapping_probes_use_different_short_lived_cache_keys(self):
        self.assertEqual(healthcheck.main(), 0)
        self.assertEqual(healthcheck.main(), 0)
        calls = self.cache.set.call_args_list
        self.assertNotEqual(calls[0].args[0], calls[1].args[0])
        self.assertEqual(calls[0].kwargs['timeout'], 15)

    def test_database_failure_is_redacted_and_stops_other_probes(self):
        self.database.cursor.side_effect = OperationalError('synthetic-private-connection-details')
        output = StringIO()
        with redirect_stderr(output):
            self.assertEqual(healthcheck.main(), 1)
        self.assertEqual(output.getvalue(), 'Application readiness failed.\n')
        self.cache.set.assert_not_called()
        self.http.assert_not_called()

    def test_cache_outage_is_a_readiness_failure(self):
        self.cache.set.side_effect = ConnectionError('synthetic-private-cache-details')
        with redirect_stderr(StringIO()):
            self.assertEqual(healthcheck.main(), 1)
        self.http.assert_not_called()

    def test_missing_cache_write_is_a_readiness_failure(self):
        self.cache.get.return_value = None
        with redirect_stderr(StringIO()):
            self.assertEqual(healthcheck.main(), 1)
        self.http.assert_not_called()

    def test_incorrect_http_response_is_a_readiness_failure(self):
        self.response.read.return_value = b'not ready'
        with redirect_stderr(StringIO()):
            self.assertEqual(healthcheck.main(), 1)

    def test_settings_failure_does_not_escape_as_a_traceback(self):
        output = StringIO()
        with patch.object(healthcheck.django, 'setup', side_effect=ValueError('synthetic secret')):
            with redirect_stderr(output):
                self.assertEqual(healthcheck.main(), 1)
        self.assertEqual(output.getvalue(), 'Application readiness failed.\n')
