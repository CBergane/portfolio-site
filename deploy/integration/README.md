# Isolated Podman integration tests

Run from the repository root on the Ubuntu/WSL host. These tests use the actual
application Dockerfile and entrypoint, PostgreSQL 16, Redis 7 and Nginx. They do
not load the production `.env`, mount existing media or backups, or connect a
Cloudflare tunnel. All database credentials, users and documents are synthetic.
Application webhook, Turnstile and HTB credentials are empty; the test settings
also block outgoing `requests` HTTP calls before network I/O.
Database credentials deliberately contain URL-reserved characters and a literal
dollar sign. The web container uses the production readiness module to check
PostgreSQL, Redis and local Gunicorn, with the same bounded probe as production.

Requirements: Python 3.9 or newer, `/usr/bin/podman` 3.4.4, Podman Compose 1.6.0,
`ss` (Ubuntu's iproute2 package), and the CNI `dnsname` plugin. Image downloads and
the first build need internet access. Run Python without `-O`; test and ownership
assertions must be enabled.
Do not run these tests as root or against a remote Podman service.

```sh
python3 deploy/integration/run.py build
python3 deploy/integration/run.py up
python3 deploy/integration/run.py verify
python3 deploy/integration/run.py recover
python3 deploy/integration/run.py tests
python3 deploy/integration/run.py logs
```

Open <http://127.0.0.1:8088/> while the stack is running. This is an HTTP-only
local test; HTTPS redirect is disabled only in this configuration. Secure session
cookies remain enabled. The document test supplies a synthetic session directly
to verify authorized downloads without changing cookie security settings.

`verify` checks network and port isolation, configured health checks, migrations,
Django system checks, locked package versions, volume permissions, static assets,
and public/private Wagtail documents through Nginx. It creates two documents and
an authenticated reader session in the test database. Restricted documents inherit
their restriction from a parent collection. Direct `/media/documents/` access must
return 403, including encoded and normalized paths, GET/HEAD and authenticated
requests. Canonical Wagtail downloads must enforce collection access controls.

`recover` deliberately restarts each service, interrupts PostgreSQL and Redis,
terminates Gunicorn to test its restart policy, and recreates the Compose stack
without deleting volumes. Do not run other commands against this project during
that test.

On the tested engine, native Nginx restart fails with an orphan `rootlessport`
helper occupying port 8088. The runner reports that failure, performs narrowly
guarded recovery, finishes with restored HTTP, and **still exits nonzero**.
During earlier restarts, automatic health scheduling also stalled for Django and
Nginx. Container recreation restored scheduling, and final verification passed.
`verify` detects stalled timestamps and exits nonzero even when manually invoked
probes and HTTP tests pass. Reliable restart behavior requires engine-level resolution.

Startup and cleanup can release the same stale port helper only when port 8088
belongs to a process named `containers-rootlessport`, its executable is exactly
`/usr/bin/podman`, it belongs to the current user, Nginx is stopped/absent, and all
local containers belong to this project. Otherwise recovery refuses to signal it.
The process is held by a Linux PID descriptor to avoid PID-reuse races. Do not
replace these guards with `pkill` or stop unrelated services.

`tests` runs the complete existing Django suite inside the built image, first
against SQLite, then against PostgreSQL 16 in a separate `test_phase4a` database.
Django creates and destroys that test database; the synthetic integration content
stays in `phase4a_db`. Both runs reuse the repository's isolated test settings
with local cache/mail/files and blocked external integrations.

## Isolation and compatibility

The runner always invokes Compose with:

```sh
podman-compose --podman-path /usr/bin/podman \
  --podman-args=--cgroup-manager=cgroupfs --in-pod=false \
  --env-file /dev/null -p portfolio_phase4a \
  -f deploy/integration/compose.yml
```

Use the runner for startup. Podman Compose 1.6.0 emits `network:alias=...`
arguments that Podman 3.4.4 does not support and skips `service_healthy`
dependency waits on Podman versions below 4.6. The runner creates containers
without starting them, attaches them using `podman network connect --alias`,
removes accidental default-network attachments and gates startup with explicit
health checks. It asserts that running containers use only the isolated network.

Ubuntu's installed firewall CNI plugin rejects newly generated `cniVersion: 1.0.0`
configuration. The runner changes **only** the project-owned
`portfolio_phase4a_network.conflist` to CNI 0.4.0 after verifying its project label.
This file lives in the rootless user's CNI configuration directory. No other
network or engine configuration is changed. The network uses `10.77.44.0/24`
with gateway/DNS resolver `10.77.44.1`; that subnet must be free locally.

The project uses fixed container names `portfolio_phase4a_{db,redis,web,nginx}`,
network `portfolio_phase4a_network`, and named volumes `portfolio_phase4a_postgres`,
`portfolio_phase4a_static`, and `portfolio_phase4a_media`. Only Nginx publishes
`127.0.0.1:8088`; PostgreSQL, Redis and Gunicorn have no host ports. Nginx mounts
static/media volumes read-only. Redis uses `/data` on tmpfs with persistence
disabled, avoiding anonymous image volumes. Images are pinned to the same digests
as the production configuration.

The isolated Nginx template copies production rules with only the upstream
container name changed. Both use the pinned image's native resolver substitution;
startup rejects any other drift. The runner does not modify production configuration.

Host resource failures, including dnsmasq/inotify exhaustion before startup, block
networking and recovery checks. Do not change global kernel limits or signal
unrelated processes as part of these tests. See [../PHASE6A.md](../PHASE6A.md) for
the current verification results; earlier restart failures remain historical evidence.

## Safe cleanup

Stop and remove the isolated containers, keeping data for another run:

```sh
python3 deploy/integration/run.py stop
```

Delete **only this test project's** containers, volumes and network:

```sh
python3 deploy/integration/run.py clean
```

Cleanup uses the fixed project/configuration and checks ownership labels. Never
substitute the production Compose file, run global prune commands, or run
`podman-compose down -v` outside this isolated project. Images and build caches
are kept. Logs redact the synthetic database/Django credentials; document-test
session tokens are kept in memory and are not printed. Do not run `fixtures.py`
directly for log collection because its JSON contains the test session token.

See [RESULTS.md](RESULTS.md) for Phase 4A results and [../README.md](../README.md)
for the separate production deployment and rollback checklist.
