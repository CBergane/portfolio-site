"""Private container readiness: database, cache and the local Gunicorn response."""
import os
import sys
from urllib.request import Request, urlopen
from uuid import uuid4

import django
from django.conf import settings
from django.core.cache import cache
from django.db import connection


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        django.setup()
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            if cursor.fetchone() != (1,):
                raise RuntimeError('Database probe failed')
        connection.close()
        # A unique key proves a fresh write/read even when probes overlap.
        key = 'portfolio-readiness:' + uuid4().hex
        cache.set(key, 'ok', timeout=15)
        if cache.get(key) != 'ok':
            raise RuntimeError('Cache probe failed')
        host = settings.ALLOWED_HOSTS[0].lstrip('.')
        request = Request('http://127.0.0.1:8000/healthz', headers={
            'Host': 'localhost' if host == '*' else host,
            'X-Forwarded-Proto': 'https',
        })
        with urlopen(request, timeout=2) as response:
            if response.status != 200 or response.read(16) != b'OK':
                raise RuntimeError('HTTP probe failed')
    except Exception:
        # Connection errors may contain credentials; report only the outcome.
        print('Application readiness failed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
