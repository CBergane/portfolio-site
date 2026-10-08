"""Check HTTP, PostgreSQL and Redis, without adding a public health endpoint."""
import os
from urllib.request import urlopen

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'integration_settings')
django.setup()
from django.core.cache import cache
from django.db import connection

with connection.cursor() as cursor:
    cursor.execute('SELECT 1')
    assert cursor.fetchone() == (1,)
cache.set('phase4a-health', 'ok', timeout=30)
assert cache.get('phase4a-health') == 'ok'
with urlopen('http://127.0.0.1:8000/healthz', timeout=3) as response:
    assert response.status == 200 and response.read() == b'OK'
