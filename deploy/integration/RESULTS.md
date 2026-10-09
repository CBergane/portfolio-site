# Phase 4A verification results

Tested 2026-10-08 on Ubuntu 22.04.5/WSL2, branch
`refactor/architecture-cleanup`, starting from commit `17424c5`. The local engine
initially had no containers or volumes. Production configuration, application
code, frontend files and migration files were not changed. Production credentials,
media and backups were not used.
No commit, push or deployment was performed.

**Application integration passed. Unattended operation on this Podman 3.4.4
environment is NO-GO until the native restart/health limitations below are resolved.**

## Runtime and build

| Component | Verified version/result |
| --- | --- |
| Local Podman | `/usr/bin/podman` 3.4.4, rootless, local engine |
| Podman Compose | 1.6.0, explicit local backend, separate containers rather than a pod |
| Python | 3.11.16 |
| Django / Wagtail | 5.2.18 / 8.0 |
| Gunicorn / psycopg | 22.0.0 / 3.2.3 |
| Node build stage | 24.21.0; exact pinned image also returned `v24.21.0` |
| PostgreSQL server | 16.15 |
| Redis | 7.4.11 |
| Nginx | 1.29.8 |
| App PostgreSQL CLI | 15.19; normal SQL connections to server 16 worked |

The existing Dockerfile built successfully from scratch. Its Python install used
`--require-hashes --only-binary=:all:` and `pip check` passed. `npm ci
--ignore-scripts` and the Tailwind build succeeded. A subsequent Compose build
reused the same image:

```text
localhost/portfolio-phase4a-web:integration
4d541209077417258c29ce424a3443f51830ace87db52823eb8b78aae39126c3
```

The runtime package versions matched every applicable pinned requirement.
Python, Node, PostgreSQL, Redis and Nginx base/service image digests remain those
already pinned in the repository. Debian packages installed with `apt-get` are
not independently locked, so this does not establish bit-identical future images.

Generated CSS was 18,936 bytes, SHA-256
`0904595e0cd79f4d1c7be7cf7a9d7237f71b0ecdc246350ea2749f7e4a2751dc`, exactly
matching both Phase 3C build snapshots. The checked-in `output.css` is an older
generated file; comparing it with fresh Tailwind output was an incorrect initial
test assertion. No CSS was rewritten. Collected CSS matched the image's generated
CSS; served custom CSS and navigation JavaScript matched their source files.

## Verified behavior

| Check | Result |
| --- | --- |
| All four services running and healthy | PASS after gated startup and again after recovery |
| Automatic health checks | PASS initially and in final verification; stalled during earlier restarts |
| Container networking | PASS: only `portfolio_phase4a_network`, `10.77.44.0/24`; `db` and `redis` DNS resolution worked |
| Host port isolation | PASS: only Nginx `127.0.0.1:8088`; DB, Redis and Gunicorn had no published host ports |
| PostgreSQL connection and migrations | PASS: actual entrypoint applied existing migrations to the empty synthetic database |
| Django system checks | PASS: no issues |
| Migration drift | PASS: `makemigrations --check --dry-run --noinput`, no changes detected |
| Locked runtime dependencies | PASS: installed versions and `pip check` |
| Non-root filesystem access | PASS: app UID 1000 wrote static/media; Nginx mounted both read-only |
| Static collection | PASS: manifest present; 252 files copied, 686 post-processed during initial startup |
| HTTP | PASS: `/healthz` 200/`OK`, homepage 200, missing route 404 |
| Static/media through Nginx | PASS: CSS/JS 200 with cache headers; synthetic media readable |
| Real Wagtail document access | PASS: direct paths 403; public canonical download 200; inherited private restriction redirects anonymous users and permits the synthetic authenticated reader |
| Encoded/normalized document paths | PASS: GET/HEAD, query string, duplicate slash, encoded directory/separator and traversal variants blocked |
| Public document response security | PASS: attachment, `nosniff`, CSP `default-src 'none'` |
| External application integrations | PASS: empty credentials and blocked HTTP before DNS/network I/O |
| PostgreSQL/Redis/web restarts | PASS: database documents, sessions and media preserved |
| Redis persistence policy | PASS: cache marker vanished after restart; `/data` now uses tmpfs |
| Dependency outages | PASS: application readiness failed with PostgreSQL/Redis stopped and passed after their recovery |
| Gunicorn termination | PASS: `unless-stopped` restarted PID 1 automatically; HTTP recovered |
| Compose recreation without volume deletion | PASS: documents, authenticated session and media marker survived; private/direct-document rules remained enforced |
| Native Nginx restart | **FAIL**: orphan rootless port helper retained port 8088; guarded recovery restored HTTP |
| Full Django suite, SQLite | **200 passed**, 15.274 seconds, inside the actual image |
| Full Django suite, PostgreSQL 16 | **200 passed**, 26.860 seconds, separate `test_phase4a` database created/destroyed |
| Nginx / Python / JavaScript / shell syntax | PASS |
| Ownership guard self-checks | PASS: unrelated project/volume rejected before process signaling or cleanup |

## Confirmed limitations and corrections

1. **Compose networking arguments are incompatible with Podman 3.4.4.**
   Compose 1.6 emitted `--network=portfolio_phase4a_network:alias=db`. Containers
   instead used the default `podman` network, and `db` DNS resolution failed.
   The isolated runner creates containers without starting, connects them with
   `network connect --alias`, removes default-network attachments and verifies the
   final network membership. Production Compose is unchanged.
2. **Ubuntu's firewall CNI plugin rejects generated CNI 1.0.0 configuration.**
   The runner verifies ownership and changes only this test network's configuration
   to 0.4.0. Networking then worked. Global engine/default-network settings were not changed.
3. **Healthy Compose dependency conditions are skipped with Podman below 4.6.**
   This was confirmed in installed Compose 1.6 source. The runner explicitly gates
   DB/Redis, then Django, then Nginx with their configured health checks.
4. **Native rootless HTTP restart/recreation leaks the port helper.**
   Nginx restart, subsequent start, and `podman container cleanup` failed to release
   port 8088. The port holder was verified as the current user's
   `containers-rootlessport` process executing `/usr/bin/podman`. Targeted termination
   restored HTTP. The reusable runner includes the same ownership/port/process/PID
   guards; `recover` still fails overall to preserve the native failure result.
5. **Automatic health scheduling stalled during earlier service restarts.**
   Django/Nginx timestamps stopped advancing while their directly invoked probes
   passed; PostgreSQL/Redis checks continued. Container recreation restored all
   four schedules, and final `verify` exited 0. The cause is not established;
   reliable health scheduling across restarts is not proven.
6. **The existing production readiness helper's inspect template is incompatible.**
   Podman 3.4 exposes JSON `.State.Healthcheck`; `.State.Health.Status` produced
   a template error (the CLI unexpectedly returned 0). The production helper uses
   `.State.Health` and would not recognize healthy containers on this engine.
   The isolated runner handles both JSON fields. The production helper was left
   unchanged for a separate reviewed correction; it also omits Redis readiness.
7. **Redis's image creates an anonymous `/data` volume by default.**
   Two such volumes were created during early test iterations. The isolated
   configuration now explicitly uses tmpfs, preventing future anonymous volumes.
   Cleanup removes only the known early test volumes, never global unused volumes.

The test helper import path was corrected to `/integration:/app`. Podman's null
`EXPOSE` port entries were correctly distinguished from published port bindings.
These were corrections to the new test harness, not application defects.

## Exact commands and evidence

Commands were prefixed with `rtk` in this workspace. The runner prints exact child
commands, including the absolute Compose file and explicit `/usr/bin/podman`.

```sh
rtk /usr/bin/podman --cgroup-manager=cgroupfs build \
  --tag localhost/portfolio-phase4a-web:integration --file app/Dockerfile app
rtk python3 deploy/integration/run.py up
rtk python3 deploy/integration/run.py verify
rtk python3 deploy/integration/run.py tests > /tmp/portfolio-phase4a-tests.log 2>&1
rtk python3 deploy/integration/run.py build > /tmp/portfolio-phase4a-build.log 2>&1
rtk python3 deploy/integration/run.py verify > /tmp/portfolio-phase4a-verification.log 2>&1
rtk python3 deploy/integration/run.py logs > /tmp/portfolio-phase4a-services.log 2>&1
rtk python3 deploy/integration/run.py clean
```

Completed recovery was invoked by a Python diagnostic importing `run.py`, calling
`release_stale_test_port()`, starting/waiting for isolated Nginx, then `recover()`.
Its exact child-command transcript is in
`/tmp/portfolio-phase4a-recovery-transcript.log`. It exited 1 solely for the retained
native Nginx restart failure after the other recovery checks passed. Earlier
failed iterations are recorded in `/tmp/portfolio-phase4a-recovery*.log` and
`/tmp/portfolio-phase4a-up-final.log`; all data is synthetic and credentials are redacted.
Final verification exited 0; the final service snapshot had four healthy/running
services, with only the intended loopback HTTP binding.

An initial `podman-compose --version` probe incorrectly tried the default backend
and failed before connecting. Every actual build/start/test/cleanup command
explicitly selected the local engine. Socket inspection initially blocked by the
sandbox was repeated with approval; container checks were not assumed compatible.

Not tested: host/WSL reboot recovery, production HTTPS/Cloudflare routing, real
external notifications, load/stress behavior, or backup/restore operations.
Production secrets and backup contents were not accessed.

## Files and final state

All changes are new files in `deploy/integration/`:

- `compose.yml`
- `nginx.integration.conf`
- `integration_settings.py`
- `integration_test_settings.py`
- `healthcheck.py`
- `fixtures.py`
- `verify_runtime.py`
- `run.py`
- `README.md`
- `RESULTS.md`

Git summary: 10 new files, 966 insertions; existing tracked files unchanged.
No files were staged. `git diff --stat` is empty because the new files are untracked;
the count includes the complete new integration directory.

Final cleanup **passed**: no containers or volumes remain, the isolated network
was removed, and port 8088 has no listener. Images/build caches were retained.
The two early anonymous Redis volumes were removed explicitly after checking
their identities and anonymous/empty-label metadata:

```sh
rtk /usr/bin/podman --cgroup-manager=cgroupfs volume rm 7390d937628f538f24919a61cd04bb0a42f77bde350f4cf9afb029e5918b8ddd
rtk /usr/bin/podman --cgroup-manager=cgroupfs volume rm b801c9547e198158c96cbba64b9ba57f64a8775b04fe78d6024e2943140e11e2
```

`/tmp/portfolio-phase4a-cleanup.log` records the project-scoped `down -v` and
guarded port-helper cleanup. No global pruning or production cleanup was run.
