# Phase 1: safe baseline

Use Python 3.13 and Node.js 24 (the CI versions). Install the existing dependencies
in a disposable virtual environment; no production environment file is needed.
Run these commands from the repository root:

```sh
python3.13 -m venv /tmp/portfolio-phase1-venv
/tmp/portfolio-phase1-venv/bin/python -m pip install -r app/requirements.txt
cd app
```

Every Django command below selects `config.test_settings` explicitly. This module
reuses application configuration while suppressing `.env` loading and replacing
inherited environment configuration with synthetic values. Redis is replaced by
process-local memory, email stays in memory, and media/static output goes into an
automatically cleaned temporary directory. Discord and HTB environment credentials
and Turnstile keys are cleared. Unmocked Requests HTTP calls raise an assertion
before network access; integration tests must mock their responses. Wagtail search
uses the database backend and external embed finders are disabled.

The cache is intentionally limited to one test process. Rate limiting remains
enabled and tested. These settings are for validation commands only.

## SQLite

No database service is required. Django creates a new in-memory database and
applies the existing migrations before the tests:

```sh
TEST_DATABASE_ENGINE=sqlite /tmp/portfolio-phase1-venv/bin/python manage.py check --settings=config.test_settings
TEST_DATABASE_ENGINE=sqlite /tmp/portfolio-phase1-venv/bin/python manage.py makemigrations --check --dry-run --noinput --settings=config.test_settings
TEST_DATABASE_ENGINE=sqlite /tmp/portfolio-phase1-venv/bin/python manage.py test --noinput --settings=config.test_settings
```

To run only the new compatibility and isolation checks, add
`home.test_baseline home.test_isolation` after `manage.py test`.

## PostgreSQL 16

Start a separate disposable PostgreSQL 16 container; use no production Compose
configuration, mounts, credentials, volumes, or backups. Docker is shown below;
`podman` can replace `docker` when a working rootless runtime is available.
The name is specific to this task and the port is bound only to loopback:

```sh
docker run --detach --rm --name portfolio-phase1-postgres \
  --publish 127.0.0.1:55432:5432 \
  --env POSTGRES_DB=portfolio_phase1 \
  --env POSTGRES_USER=portfolio_phase1 \
  --env POSTGRES_PASSWORD=phase1-synthetic-password \
  postgres:16
docker exec portfolio-phase1-postgres pg_isready -U portfolio_phase1 -d portfolio_phase1
```

Repeat the readiness command until it exits successfully. The container's
synthetic user can create Django's test database. Verify the major version, then
run the same baseline against this instance (from `app/`):

```sh
docker exec portfolio-phase1-postgres psql -U portfolio_phase1 -d portfolio_phase1 -c 'SHOW server_version;'
TEST_DATABASE_ENGINE=postgresql TEST_POSTGRES_PORT=55432 /tmp/portfolio-phase1-venv/bin/python manage.py check --settings=config.test_settings
TEST_DATABASE_ENGINE=postgresql TEST_POSTGRES_PORT=55432 /tmp/portfolio-phase1-venv/bin/python manage.py makemigrations --check --dry-run --noinput --settings=config.test_settings
TEST_DATABASE_ENGINE=postgresql TEST_POSTGRES_PORT=55432 /tmp/portfolio-phase1-venv/bin/python manage.py test --noinput --settings=config.test_settings
docker stop portfolio-phase1-postgres
```

The host, database name, username and password are fixed synthetic values in
`test_settings`; only the dedicated test port is configurable. `DATABASE_URL` and
`POSTGRES_*` from the caller are ignored; libpq's inherited `PG*` environment
variables are cleared so they cannot redirect the connection. Django creates and destroys
`test_portfolio_phase1`; the base database is also disposable. If port 55432 is
occupied, choose another unused loopback port in the container command and set
`TEST_POSTGRES_PORT` to match. Do not point these commands at an existing database.

## Syntax and frontend build

From the repository root, check every tracked JavaScript and shell file. Install
frontend dependencies from the existing lockfile and build into `/tmp`, keeping
the tracked CSS untouched:

```sh
git ls-files -z '*.js' | xargs -0 -r -n 1 node --check
git ls-files -z '*.sh' | xargs -0 -r -n 1 bash -n
cd app
npm ci --ignore-scripts
npm run build:css -- --output /tmp/portfolio-phase1.css
```

`.github/workflows/ci.yml` runs Django checks, migration drift checks and the test
suite on both database backends using a fresh PostgreSQL 16 service, then syntax
and frontend build checks in a separate job. It uses no deployment steps or
repository secrets. Service configuration follows the
[GitHub PostgreSQL service guide](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).

`makemigrations --check --dry-run` exits unsuccessfully if model state differs
from committed migrations and writes no migration files; see
[Django's command reference](https://docs.djangoproject.com/en/5.2/ref/django-admin/#makemigrations).
Report that as drift and leave model/migration changes for a separately approved
phase. Missing dependencies or an unavailable PostgreSQL 16 runtime mean the
affected checks are blocked, not passed.
