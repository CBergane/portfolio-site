# Production deployment and rollback

This is an operator checklist for the separate Proxmox Linux host. Nothing here
has been executed against production. Local WSL2/Podman 3.4.4 failures do not
establish production failures. Use a planned maintenance window: one web
container and shared static storage do not provide zero-downtime deployment.

## Host prerequisites and boundaries

- Verify `/usr/bin/podman`, the installed Compose executable and `/usr/bin/python3`.
  Always use `podman-compose --podman-path /usr/bin/podman`. The sample systemd
  unit uses `/bin/podman-compose`; correct that path if the host installs it elsewhere.
- The existing system unit is **rootful**. Its commands unset `XDG_RUNTIME_DIR`.
  Confirm this matches the existing containers before installing it. Do not switch
  between rootful and rootless storage while deploying. A rootless host needs its
  existing user-service setup reviewed separately.
- Keep the existing Compose project identity and working directory. Record only
  container image IDs, project labels, named-volume mounts and network metadata;
  whole `inspect` and `compose config` output can contain credentials.
- PostgreSQL 16 and Redis have no host ports. Nginx binds only `127.0.0.1:80`.
  Cloudflare Tunnel remains outside this Compose stack. Check its service ordering
  and actual routing on the host; `Before=cloudflared.service` alone does not make
  Cloudflare depend on successful portfolio startup.
- Validate the host's actual Podman/Compose/CNI or Netavark combination. Compose
  health dependencies are useful ordering hints, not the only readiness gate.
  Do not copy the isolated runner's legacy CNI/port-recovery workarounds into production.

## Configuration and readiness

Compose passes `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER` and
`POSTGRES_PASSWORD` separately. Django and the entrypoint use the same settings.
Reserved characters therefore need no URL encoding in these fields. Store them
using the host's protected Compose environment-file mechanism; verify literal
dollar signs and quoting with synthetic values first. Do not source that file as
a shell script or print its rendered configuration. An explicitly supplied
`DATABASE_URL` remains supported outside this Compose configuration and takes
precedence; URL components must be percent-encoded.

Database connection attempts have a three-second connection timeout. The entrypoint
wait defaults to 60 seconds, with a one-second forced-kill allowance, and fails
without logging connection details. `DB_TIMEOUT_SEC` accepts integers 1–3600.
Redis connection/socket timeouts are two seconds.

The web health command checks `SELECT 1`, a fresh short-lived cache write/read and
the local Gunicorn `/healthz` response. Its own wall-clock limit is 10 seconds
(plus one second for forced termination), below Podman's 12-second health timeout.
`/healthz` remains the existing lightweight liveness response. Nginx verifies
upstream HTTP separately. The host readiness helper probes all four services and
accepts both `.State.Health` and `.State.Healthcheck`, with an overall 150-second
deadline and bounded CLI calls. It does not print inspection JSON or probe errors.
This is a startup gate. `unless-stopped` restarts an exited process; an unhealthy
status alone does not restart a container. Verify periodic probe scheduling and
recovery on the actual host rather than relying on one successful startup probe.

Nginx now mounts `nginx.conf` as `/etc/nginx/templates/default.conf.template`.
The pinned image's native entrypoint obtains resolvers from `/etc/resolv.conf` and
substitutes only `NGINX_LOCAL_RESOLVERS`; Nginx variables and document-denial rules
remain intact. Verify the rendered resolver and `portfolio_web` DNS on the host.
Recreate Nginx when changing the template mount; reloading an old container is insufficient.

## Before the maintenance window

1. Privately resolve the three tracked backup files' classification/exposure.
   Do not use their age or size as evidence of a current recoverable backup.
2. Record the exact `postgres_data`, `media_files` and `static_files` volume names
   currently mounted, including their Compose prefix. Keep them unchanged.
   App UID 1000 needs write access to media/static; Nginx mounts both read-only.
   Redis is deliberately ephemeral; its `/data` now uses tmpfs. Do not remove old
   anonymous volumes until their ownership is independently verified.
3. Take a current protected database/media backup and privately verify restore
   capability. Use PostgreSQL 16 backup tooling, preferably from the database
   image: the app image's PostgreSQL 15 client is not suitable for dumping server 16.
   Record the recovery point and how post-backup writes would be handled.
4. Retain the running app image by ID and a unique rollback tag **before building**.
   Retain the matching Compose/Nginx/unit files in protected release storage.
   Do not prune these images while rollback remains needed.
5. Build the reviewed source using the current Dockerfile and hashed lock. Use a
   unique release tag, for example `localhost/portfolio-web:release-<revision>`.
   Record the resulting image ID; do not rebuild that tag after verification.
6. Run the image's isolated SQLite tests with `DJANGO_SETTINGS_MODULE=config.test_settings`
   and no production mounts. Verify PostgreSQL, networking, health scheduling,
   restarts and recovery in staging on the intended host engine. Scan the final image.

## Deploy the prepared release

Run these actions as the owner in the **existing** engine/project context. Commands
below use `pc` as shorthand for the explicit Compose command, not a new script:
`podman-compose --podman-path /usr/bin/podman -p <existing-project> -f /opt/portfolio/docker-compose.yml`.

1. Enter maintenance and suspend CMS/contact writes. Stop the portfolio unit.
   Its `ExecStopPost` stops containers on normal shutdown and failed startup,
   allowing 45 seconds for graceful container stops and preserving all volumes.
2. Install the approved code/configuration in the existing working directory.
   Set protected `PORTFOLIO_WEB_IMAGE` to the verified release tag or digest.
   The `localhost/portfolio-web:local` default is for local builds, not production.
3. Start database/cache containers (`pc up -d --no-build db redis`) and verify
   their readiness. Changing PostgreSQL environment variables does not update
   users/passwords in an already initialized database; verify existing-role compatibility.
4. Run one-off checks with the new image: `pc run --rm --no-deps web python manage.py check --deploy`,
   `makemigrations --check --dry-run --noinput` and `migrate --plan`.
   Expect no new `home` migrations. Stop for any unexpected pending migration,
   including dependency migrations. Never generate migrations on production.
5. Only if a reviewed migration is required, run it explicitly once using
   `pc run --rm --no-deps web python manage.py migrate --noinput`, after backup
   approval. Production Compose sets `RUN_MIGRATIONS=0`; boots/restarts do not
   apply unreviewed database changes. The isolated empty-database stack still
   applies existing migrations for its synthetic fixtures.
6. Prepare containers with `pc up --no-start --no-build`. Confirm image IDs,
   network membership, existing volume mounts and the new Nginx template mount.
   This is the reviewed creation/recreation step; systemd `start` never builds
   images or recreates containers. Install the helper executable and unit in
   their documented paths, run `systemd-analyze verify` and `systemctl daemon-reload`.
7. Start the portfolio unit. The entrypoint collects static files into the
   existing volume (`--clear`), so keep maintenance active during this step.
   Check the readiness gate and advancing automatic health timestamps.
8. Verify the homepage and each section, filtered/paginated listings, static assets,
   canonical/SEO metadata, `/sitemap.xml` and `/robots.txt` through the real ingress.
   Verify raw document GET/HEAD denial, anonymous private-download denial and
   authorized downloads. Confirm document cache policies at Cloudflare.
9. Verify HTTPS/host header normalization, forged forwarded-header rejection and
   correct visitor IP resolution. Observe logs without printing webhook URLs or
   request bodies. Leave maintenance only after acceptance succeeds.

## Rollback

1. Keep or re-enter maintenance and suspend writes; stop the portfolio unit.
2. Select the retained rollback app image and compatible reviewed configuration.
   Preserve raw-document denial, safe webhook logging and dependency security
   fixes. A blind rollback to `origin/main` is not security-equivalent.
3. Recreate only the affected web/Nginx containers with the same project/volume
   mappings and `--no-build`. Do not change the PostgreSQL major version or use
   `down -v`, volume deletion or global prune commands. Regenerate static assets
   from the rollback image during its startup and verify its manifest/assets.
4. Start the unit and repeat readiness, HTTP, privacy, proxy and persistence checks.
   This schema-neutral release normally needs an application/configuration rollback,
   not a database restore or reverse migrations. Inspect the actual migration state;
   do not reverse migrations automatically.
5. Restore data only for a demonstrated data-recovery need through the separately
   verified restore procedure. Account for writes since the backup. CMS editorial
   revisions are separate from code deployment and must not be overwritten blindly.

## Production-host acceptance required

- Installed engine/Compose versions, executable paths and rootful/user context.
- Actual service startup, failure cleanup, graceful shutdown and host reboot.
- DNS aliases and rendered Nginx resolver; web recreation with an IP change.
- Automatic health scheduling and DB/Redis outages, recovery and Gunicorn/Nginx restarts.
- Persistent database/media preservation, UID mapping and unchanged volume identities.
- Cloudflare Tunnel ordering, HTTPS/forwarded headers, client IPs and document caching.
- Protected backup restore evidence, retained rollback image and migration plan.

See [PHASE6A.md](PHASE6A.md) for local verification and its limitations.
