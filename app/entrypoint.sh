#!/usr/bin/env bash
set -Eeuo pipefail

# One-off mode: if a command is provided, run it and exit
if [[ $# -gt 0 ]]; then
  echo "▶ Running one-off command: $*"
  exec "$@"
fi

echo "🚀 Starting Django application..."


RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"
RUN_COLLECTSTATIC="${RUN_COLLECTSTATIC:-1}"

# -------- Wait for DB (prefer DATABASE_URL) --------
if [[ -n "${DATABASE_URL:-}" ]]; then
  echo "⏳ Waiting for database via DATABASE_URL ..."
  # loopa tills vi kan göra en enkel query
  until psql "${DATABASE_URL}" -Atqc "select 1" >/dev/null 2>&1; do
    sleep 2
  done
else
  DB_HOST="${POSTGRES_HOST:-${DATABASE_HOST:-db}}"
  DB_PORT="${POSTGRES_PORT:-${DATABASE_PORT:-5432}}"
  DB_USER="${POSTGRES_USER:-${DATABASE_USER:-postgres}}"
  DB_NAME="${POSTGRES_DB:-${DATABASE_NAME:-postgres}}"
  DB_PASSWORD="${POSTGRES_PASSWORD:-${DATABASE_PASSWORD:-}}"
  export PGHOST="$DB_HOST" PGPORT="$DB_PORT" PGUSER="$DB_USER" PGPASSWORD="$DB_PASSWORD"

  echo "⏳ Waiting for database ${PGHOST}:${PGPORT} (db=${DB_NAME}) ..."
  secs=0; limit="${DB_TIMEOUT_SEC:-60}"
  until psql -d "$DB_NAME" -Atqc "select 1" >/dev/null 2>&1; do
    sleep 2; secs=$((secs+2))
    if (( secs >= limit )); then
      echo "❌ Database not ready after ${limit}s" >&2
      exit 1
    fi
  done
fi
echo "✅ Database is ready!"

# -------- Django checks / migrations / static --------
echo "🔎 Django system check..."
python manage.py check || { echo "❌ manage.py check failed"; exit 1; }

if [[ "${RUN_MIGRATIONS}" = "1" ]]; then
  echo "🔄 Running migrations..."
  python manage.py migrate --noinput
else
  echo "⏭️ Skipping migrations (RUN_MIGRATIONS=0)"
fi

if [[ "${RUN_COLLECTSTATIC}" = "1" ]]; then
  echo "📦 Collecting static files..."
  python manage.py collectstatic --noinput --clear
else
  echo "⏭️ Skipping collectstatic (RUN_COLLECTSTATIC=0)"
fi

# -------- Ensure Wagtail Site/HomePage (optional) --------
if [[ "${INIT_WAGTAIL_HOME:-1}" = "1" ]]; then
  echo "🏠 Ensuring Wagtail Site/HomePage..."
  python - << 'PY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
django.setup()

from wagtail.models import Page, Site
from django.db import transaction
try:
    from home.models import HomePage
except Exception:
    HomePage = None

host = os.environ.get("SITE_HOSTNAME","localhost")
port = int(os.environ.get("SITE_PORT","8000"))
site_name = os.environ.get("SITE_NAME","Site")
is_default = os.environ.get("SITE_DEFAULT","true").lower() in ("1","true","yes")

with transaction.atomic():
    root = Page.get_first_root_node()

    # Reuse only a real HomePage. Wagtail's initial welcome Page also uses slug "home".
    home = Page.objects.type(HomePage).specific().first() if HomePage else None

    if not home and HomePage:
        slug = "home"
        if Page.objects.filter(slug=slug, path__startswith=root.path).exists():
            slug = "portfolio-home"
        home = HomePage(title="Home", slug=slug)
        root.add_child(instance=home)
        home.save_revision().publish()

    site, created = Site.objects.get_or_create(
        hostname=host,
        port=port,
        defaults={"site_name": site_name, "root_page": home or root, "is_default_site": False},
    )

    if is_default:
        Site.objects.exclude(pk=site.pk).update(is_default_site=False)

    site.site_name = site_name
    site.root_page = home or root
    site.is_default_site = is_default
    site.save()
print("✅ Wagtail Site ok")
PY
else
  echo "⏭️ Skipping Wagtail ensure (INIT_WAGTAIL_HOME=0)"
fi

# -------- Start Gunicorn --------
echo "🌐 Starting Gunicorn ..."
exec gunicorn config.wsgi:application \
  --config config/gunicorn_config.py \
  --bind "${GUNICORN_BIND:-0.0.0.0:8000}" \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-90}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
  --keep-alive "${GUNICORN_KEEP_ALIVE:-5}" \
  --access-logfile - \
  --error-logfile -
