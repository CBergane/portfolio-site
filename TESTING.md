# Phase 1: safe baseline

Use Python 3.11 (production) and 3.13 (additional CI compatibility), with Node.js 24.
Install the locked dependencies
in a disposable virtual environment; no production environment file is needed.
Run these commands from the repository root:

```sh
python3.13 -m venv /tmp/portfolio-phase1-venv
/tmp/portfolio-phase1-venv/bin/python -m pip install --require-hashes --only-binary=:all: -r app/requirements.txt
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
  postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea
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
git ls-files -z '*.py' | xargs -0 -r /tmp/portfolio-phase1-venv/bin/python -m py_compile
git ls-files -z '*.sh' | xargs -0 -r -n 1 bash -n
bash -n deploy/scripts/portfolio-wait-healthy
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

## Phase 2A: document access and webhook privacy

`WAGTAILDOCS_SERVE_METHOD = "serve_view"` keeps existing
`/documents/<id>/<filename>` URLs and lets Wagtail enforce collection restrictions
on the response that carries the document. Nginx returns 403 for raw
`/media/documents/` requests, including public documents; use their canonical
Wagtail URLs. Image renditions, originals and other media/static paths retain
their existing behavior. This follows
[Wagtail 8's document-serving guidance](https://docs.wagtail.org/en/v8.0/advanced_topics/documents/storing_and_serving.html#security-considerations).

The Django suite covers public downloads, inherited login/group/password
restrictions, authorized downloads, security headers, and conditional/HEAD
requests. Webhook tests use only synthetic URLs and mocked HTTP responses. They
inspect formatted logs, complete log records, stdout and stderr for secrets and
personal data, and verify that a webhook failure still stores the submission and
returns the existing success response. Webhook log records use `event`, `outcome`
and, on failure, the exception class in `error_type`; exception text and request
or response objects are never logged.

Django tests do **not** validate Nginx. With a local Nginx binary, run from the
repository root:

```sh
python3 scripts/check_nginx_documents.py --nginx /path/to/nginx --effective-config /tmp/portfolio-nginx-effective.conf
```

This runs `nginx -t` and `nginx -T` on the unmodified repository configuration
in a test wrapper, then stages temporary paths and tests actual GET/HEAD responses
against synthetic files and a synthetic upstream. It blocks direct public/restricted
document paths, including encoded and normalized variants, and checks canonical
document routing, image renditions, originals, other media and static files.
Only filesystem aliases, the listen address/port and the upstream address are
substituted with temporary paths and loopback services. The access rules are
unchanged. The emitted configuration is the effective **local test** configuration,
not evidence about a deployed proxy or Cloudflare's cache.

The CI `nginx` job also checks the unmodified repository config with `nginx -t`
and `nginx -T` inside the same `nginx:1.29-alpine` image family used by Compose,
then runs the HTTP regression check there. Python is installed only as a test
tool in that disposable container; application dependencies are unchanged.
If Nginx or the disposable container runtime is unavailable, report that check
as blocked. No production container, media volume or backup is used.

## Phase 2B: dependency and build validation

See [DEPENDENCIES.md](DEPENDENCIES.md) for the dated advisory inventory, exposure
assessment, remaining frontend advisories, lock regeneration command and local
verification results. CI exercises both Python versions with the hashed lock,
runs audits, and builds/tests the application container without production config.

After changing dependencies, repeat all checks above and `python -m pip check`,
then run these audits (from the repository root, in a disposable tooling venv
with pip-audit 2.10.1 installed):

```sh
pip-audit --strict --require-hashes --no-deps --disable-pip -r app/requirements.txt
cd app
npm audit
npm audit --omit=dev
```

The full npm audit currently exits 1 for two documented build-only advisories;
inspect its output for new findings. Do not use `npm audit fix --force`. Builds
must use `npm ci --ignore-scripts` and the committed lock. Build CSS into `/tmp`
as shown above, then compare it with the previous build before accepting visual
changes. Container base/service digests must be refreshed deliberately.
