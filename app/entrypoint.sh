#!/usr/bin/env bash
set -Eeuo pipefail

echo "🚀 Starting Django application..."

# -------- Config helpers --------
DB_HOST="${POSTGRES_HOST:-${DATABASE_HOST:-db}}"
DB_PORT="${POSTGRES_PORT:-${DATABASE_PORT:-5432}}"
DB_USER="${POSTGRES_USER:-${DATABASE_USER:-postgres}}"
DB_TIMEOUT_SEC="${DB_TIMEOUT_SEC:-60}"
DB_NAME="${POSTGRES_DB:-${DATABASE_NAME:-postgres}}"
DB_PASSWORD="${POSTGRES_PASSWORD:-${DATABASE_PASSWORD:-}}"

export PGHOST="$DB_HOST" PGPORT="$DB_PORT" PGUSER="$DB_USER" PGPASSWORD="$DB_PASSWORD"

echo "⏳ Waiting for database $PGHOST:$PGPORT ..."
until psql -d "$DB_NAME" -Atqc "select 1" >/dev/null 2>&1; do
  sleep 2
done
echo "✅ Database is ready!"

RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"
RUN_COLLECTSTATIC="${RUN_COLLECTSTATIC:-1}"

SITE_HOSTNAME="${SITE_HOSTNAME:-localhost}"
SITE_PORT="${SITE_PORT:-8000}"
SITE_NAME="${SITE_NAME:-Christian Bergane Portfolio}"
SITE_DEFAULT="${SITE_DEFAULT:-true}"

# -------- Wait for database (with timeout) --------
echo "⏳ Waiting for database ${DB_HOST}:${DB_PORT} (timeout ${DB_TIMEOUT_SEC}s)..."
secs=0
until pg_isready -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" >/dev/null 2>&1; do
  sleep 1
  secs=$((secs+1))
  if [ "$secs" -ge "$DB_TIMEOUT_SEC" ]; then
    echo "❌ Database not ready after ${DB_TIMEOUT_SEC}s" >&2
    exit 1
  fi
done
echo "✅ Database is ready!"

# -------- Django checks / migrations / static --------
echo "🔎 Django system check..."
python manage.py check || { echo "❌ manage.py check failed"; exit 1; }

if [ "${RUN_MIGRATIONS}" = "1" ]; then
  echo "🔄 Running migrations..."
  python manage.py migrate --noinput
else
  echo "⏭️ Skipping migrations (RUN_MIGRATIONS=0)"
fi

if [ "${RUN_COLLECTSTATIC}" = "1" ]; then
  echo "📦 Collecting static files..."
  python manage.py collectstatic --noinput --clear
else
  echo "⏭️ Skipping collectstatic (RUN_COLLECTSTATIC=0)"
fi

# -------- Ensure Wagtail Site/HomePage --------
echo "🏠 Ensuring Wagtail Site/HomePage..."
python - << 'PY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")  # <-- anpassa om din modul heter annat
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
    if HomePage and not HomePage.objects.exists():
        home = HomePage(title="Home", slug="home", show_in_menus=False)
        root.add_child(instance=home)
        home.save_revision().publish()
    else:
        home = (HomePage.objects.first().specific if HomePage and HomePage.objects.exists() else root)

    site, created = Site.objects.get_or_create(
        hostname=host, port=port,
        defaults={"site_name": site_name, "root_page": home, "is_default_site": is_default}
    )
    if not created and site.root_page_id != home.id:
        site.root_page = home
        site.save()
print("✅ Wagtail Site ok")
PY


# -------- Start Gunicorn --------
# Styrs via env med vettiga defaultvärden.
GUNICORN_BIND="${GUNICORN_BIND:-0.0.0.0:8000}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-2}"
GUNICORN_THREADS="${GUNICORN_THREADS:-4}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-90}"
GUNICORN_GRACEFUL_TIMEOUT="${GUNICORN_GRACEFUL_TIMEOUT:-30}"
GUNICORN_KEEP_ALIVE="${GUNICORN_KEEP_ALIVE:-5}"

echo "🌐 Starting Gunicorn on ${GUNICORN_BIND} ..."
exec gunicorn config.wsgi:application \
  --config config/gunicorn_config.py \
  --bind "${GUNICORN_BIND}" \
  --workers "${GUNICORN_WORKERS}" \
  --threads "${GUNICORN_THREADS}" \
  --timeout "${GUNICORN_TIMEOUT}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT}" \
  --keep-alive "${GUNICORN_KEEP_ALIVE}" \
  --access-logfile - \
  --error-logfile -
