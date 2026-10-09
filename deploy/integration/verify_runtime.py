"""Validate the locked runtime and named-volume ownership without network I/O."""
from importlib.metadata import version
import os
from pathlib import Path
import re

from packaging.requirements import Requirement
import django
import requests
from unittest.mock import patch

django.setup()
from django.conf import settings

assert settings.PHASE4A_ISOLATED
assert settings.DATABASES['default']['USER'] == 'phase4a_user@:/#?%+'
assert settings.DATABASES['default']['PASSWORD'] == 'phase4a-synthetic-p@ss:/#?%+&= $!'
for name in ('DISCORD_WEBHOOK_URL', 'TURNSTILE_SITE_KEY', 'TURNSTILE_SECRET_KEY', 'HTB_TOKEN', 'HTB_USER_ID'):
    assert os.environ.get(name) == ''
with patch('socket.getaddrinfo', side_effect=AssertionError('External DNS must not run')) as dns:
    try:
        requests.get('https://phase4a.example.invalid/')
    except RuntimeError as error:
        assert 'Outbound application HTTP is disabled' in str(error)
    else:
        raise AssertionError('External HTTP guard is missing')
    dns.assert_not_called()

assert os.getuid() == 1000
assert not Path('/app/.env').exists()
for line in Path('/app/requirements.txt').read_text().splitlines():
    if not re.match(r'^[a-zA-Z0-9_.-]+==', line):
        continue
    requirement = Requirement(line.removesuffix('\\').strip())
    if not requirement.marker or requirement.marker.evaluate():
        assert version(requirement.name) in requirement.specifier, requirement.name
for directory in ('/app/staticfiles', '/app/media'):
    path = Path(directory)
    marker = path / 'phase4a-permission-probe'
    marker.write_text('synthetic permission probe')
    marker.unlink()
assert Path('/app/staticfiles/staticfiles.json').is_file()
assert Path('/app/staticfiles/css/output.css').read_bytes() == Path('/app/static/css/output.css').read_bytes()
print('PASS installed lock versions, non-root UID 1000, manifest/static collection and writable static/media volumes')
