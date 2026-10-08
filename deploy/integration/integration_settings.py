"""Synthetic container validation using the actual application settings."""
import os
from unittest.mock import patch

with patch('dotenv.load_dotenv'):
    from config.settings import *  # noqa: F403

PHASE4A_ISOLATED = True
for name in ('DISCORD_WEBHOOK_URL', 'TURNSTILE_SITE_KEY', 'TURNSTILE_SECRET_KEY', 'HTB_TOKEN', 'HTB_USER_ID'):
    os.environ[name] = ''
TURNSTILE_SITE_KEY = TURNSTILE_SECRET_KEY = ''

# Block integrations even if a test accidentally supplies an external URL.
_http_guard = patch('requests.sessions.Session.request', side_effect=RuntimeError(
    'Outbound application HTTP is disabled in the isolated integration stack.'
))
_http_guard.start()
