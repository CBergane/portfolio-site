# Phase 6A verification — 2026-10-09

Worktree: `refactor/architecture-cleanup`, based on `68c7a3a`. No production host,
credentials, data volumes or backup contents were accessed. No models,
migrations, CMS content or visual assets changed. Nothing was committed or deployed.

## Confirmed defects corrected

- The host readiness helper assumed `.State.Health` and omitted Redis. It now
  accepts `.State.Health` or `.State.Healthcheck`, checks all four containers and
  runs fresh native probes before accepting healthy state. Its monotonic deadline
  and individual Podman-call timeouts prevent unattended startup from hanging.
- Compose constructed an unescaped database URL; URL-reserved credentials could
  change its meaning. Compose now passes separate PostgreSQL fields, and Django
  preserves them verbatim. Explicit, correctly encoded `DATABASE_URL` values
  remain supported outside Compose and take precedence.
- The entrypoint's URL path waited indefinitely, and its alternate path could
  select credentials different from Django's. It now queries through Django's
  configured connection, under a validated wall-clock deadline. Probe failures
  cannot continue into migrations/static collection/Gunicorn or print credentials.
- A successful TCP connection did not establish database/cache/application
  readiness. The private production probe checks SQL, a fresh Redis write/read
  and the local Gunicorn response, with bounded execution and generic failure logs.
  The isolated stack reuses this probe and the host readiness helper.
- Nginx assumed a fixed DNS gateway. The pinned image's native template entrypoint
  now obtains the actual container resolvers. Substitution is restricted to the
  resolver placeholder, preserving Nginx variables and existing access rules.
- The systemd unit selected the default Podman executable and did not clean up
  failed startup through its normal stop action. It now names `/usr/bin/podman`
  and uses bounded `ExecStopPost` cleanup for shutdown and startup failure.
  The unit starts prepared containers; it does not build/recreate them.
- Production restarts automatically applied migrations. Production Compose now
  sets `RUN_MIGRATIONS=0`; the documented process requires an explicitly reviewed
  one-off migration step. A configurable release image tag supports retained
  rollback images. Redis's intentionally ephemeral `/data` uses tmpfs.

## Verified locally

| Check | Result |
| --- | --- |
| Python 3.11.16 / SQLite | 238 passed, 14.370 s |
| Python 3.13.15 / SQLite | 238 passed, 14.069 s |
| Python 3.11.16 / PostgreSQL 16.14 | 238 passed, 23.256 s |
| Python 3.13.15 / PostgreSQL 16.14 | 238 passed, 23.015 s |
| Current application image / SQLite | 238 passed, 14.956 s |
| Django system checks and migration drift | Passed on both host Python/backend combinations and in the image |
| Host readiness/entrypoint regressions | 10 passed |
| PostgreSQL reserved-character credentials | Direct fields and percent-encoded URL authenticated; wrong passwords rejected under SCRAM |
| Production and isolated Compose parsing | Passed with synthetic/cleared environments and `/dev/null` environment files; reserved credentials and volume keys preserved |
| Pinned Nginx native template entrypoint | `nginx -T` passed with a synthetic resolver fixture |
| Nginx HTTP/document access regressions | Passed GET/HEAD, normalized/encoded paths, cookies, canonical routing and other media/static |
| Python / JavaScript / shell syntax | 69 Python files including the extensionless helper, 4 JavaScript files and 1 shell file passed |
| CI workflow | actionlint passed |
| Git whitespace check | `git diff --check` passed |

All 228 existing Django tests remain, with 10 new focused tests. PostgreSQL ran
in a new temporary loopback-only cluster with synthetic roles/databases and
SCRAM host authentication; it was stopped and removed afterward. It was not the
Compose PostgreSQL service. Reserved characters included `@ : / # ? % + & =`,
spaces, a dollar sign, quotes and a backslash.

The actual Dockerfile build succeeded, including a fresh Node 24 Tailwind build.
Existing hashed Python dependency and base-system layers were reused from cache;
this run was not a fresh dependency-download verification. The tested image is:

```text
localhost/portfolio-phase4a-web:integration
sha256:8df500b154240ccab3b3534b6dc15579f3637e04b553c69f0ff1a6dbe1db4cef
```

Its generated CSS SHA-256 remains
`0904595e0cd79f4d1c7be7cf7a9d7237f71b0ecdc246350ea2749f7e4a2751dc`.
Build output still contains the existing Browserslist data-age warning.

## Commands used

From the repository root (the local `rtk proxy` prefix transparently wraps commands):

```sh
rtk proxy python3 -B scripts/test_deployment.py
rtk proxy python3 -B deploy/integration/run.py build
rtk proxy python3 -B deploy/integration/run.py up
rtk proxy /usr/bin/podman --cgroup-manager=cgroupfs run --rm --network none \
  -e DJANGO_SETTINGS_MODULE=config.test_settings \
  localhost/portfolio-phase4a-web:integration \
  bash -ec 'python manage.py check && python manage.py makemigrations --check --dry-run --noinput && python manage.py test --noinput'
rtk proxy /tmp/portfolio-phase2b-locked311/bin/python -B scripts/check_nginx_documents.py \
  --nginx /tmp/portfolio-phase2a-nginx/nginx-1.29.4/objs/nginx \
  --effective-config /tmp/portfolio-phase6a-nginx.conf
rtk proxy /tmp/portfolio-phase2b-actionlint/actionlint .github/workflows/ci.yml
rtk proxy systemd-analyze verify deploy/systemd/portfolio.service
rtk proxy python3 -B deploy/integration/run.py clean
rtk proxy git diff --check
```

From `app/`, both `/tmp/portfolio-phase2b-locked311/bin/python` and
`/tmp/portfolio-phase2b-locked313/bin/python` ran:

```sh
DJANGO_SETTINGS_MODULE=config.test_settings <python> -B manage.py check
DJANGO_SETTINGS_MODULE=config.test_settings <python> -B manage.py makemigrations --check --dry-run --noinput
DJANGO_SETTINGS_MODULE=config.test_settings <python> -B manage.py test --noinput
```

For PostgreSQL these commands additionally set `TEST_DATABASE_ENGINE=postgresql`
and `TEST_POSTGRES_PORT=39633` for the disposable cluster. One-off verification
scripts `/tmp/portfolio-phase6a-postgres-check.py` and
`/tmp/portfolio-phase6a-container-check.py` authenticated synthetic credentials,
parsed Compose without printing its environment and checked native Nginx template
rendering/CSS. `/tmp/portfolio-phase6a-final-check.py` confirmed isolated credential
interpolation and complete test-resource cleanup. See [../TESTING.md](../TESTING.md) for repeatable backend setup and
[integration/README.md](integration/README.md) for the reusable isolated stack.

## Blocked checks and engine limits

`run.py up` failed before PostgreSQL could start: local dnsmasq reported
`failed to create inotify: Too many open files`. A direct host inotify allocation
also failed with `EMFILE`; the configured per-user instance limit is 128 while
the process file-descriptor limit is 1048576. No global limits were changed and
no unrelated processes were stopped. This is a local resource failure, not
evidence of an application defect or of the production engine's behavior.

Consequently this phase did **not** verify live four-service DNS/aliases,
automatic health scheduling, container restarts/outage recovery, Nginx-to-Gunicorn
HTTP, or persistence/ownership across container recreation. The readiness helper
did reject the stopped isolated containers within its two-second test deadline.
Ownership-checked `run.py clean` removed the failed project's containers, volumes
and network; images/build caches were retained.

Podman 3.4.4 creates no `/etc/resolv.conf` in the tested network-disabled Nginx
container. The offline template check mounted a synthetic resolver file; it
verifies entrypoint rendering and syntax, not real DNS resolution. The separate
HTTP regression used a temporary host Nginx and synthetic upstream/files.

`systemd-analyze verify` exited 1: local watch allocation failed, and the production
helper is intentionally not installed at `/usr/local/sbin/portfolio-wait-healthy`.
It also reported unrelated local system-unit warnings. Actual systemd startup,
failure cleanup, shutdown and reboot remain production-host acceptance checks.

Earlier Phase 4A evidence about Podman 3.4.4 alias arguments, CNI versions,
stalled health timers and orphan port helpers remains in
[integration/RESULTS.md](integration/RESULTS.md). Those restart failures were not
reproduced in this phase. Existing compatibility handling stays confined to the
isolated runner; no additional legacy-engine workaround was added to production.

## Release decision and remaining actions

**NO-GO for production deployment until the acceptance gates are satisfied.**
Code tests pass; successful tests do not establish production compatibility.

1. Verify the real host's engine/Compose versions, rootful/user context, executable
   paths, prepared-container startup, shutdown/failure cleanup and reboot.
2. Run the current image's isolated integration suite on a functioning intended
   engine. Confirm aliases, rendered DNS, health timestamps, all service restarts,
   DB/Redis outages, changed web IP resolution and volume permissions/persistence.
3. Privately classify the three tracked backups from the prior audit and resolve
   any exposure/credential response. Their contents were not inspected here.
4. Establish a current protected backup/restore procedure, retained rollback image,
   unchanged actual volume identities and reviewed production migration plan.
5. Verify Cloudflare Tunnel routing, forwarded-header/client-IP boundaries and
   document caching through the real ingress. Review existing dependency advisory
   acceptance and scan the final release image.

Follow [README.md](README.md) for the maintenance deployment and rollback steps.
An unhealthy status alone does not restart a container; the startup gate does not
replace host health-scheduling and recovery verification.
