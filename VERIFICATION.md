# Phase 2C: security and build verification

Reviewed on 2026-10-08 on `refactor/architecture-cleanup`. The review covers
Phase 2A commit `ee8dfbc` and the uncommitted Phase 2B changes, compared with
the Phase 1 baseline `da82dbb`. Generated dependency hashes were checked by
regeneration and installation as well as by inspecting the dependency changes.

**Recommendation: NO-GO for starting the model-organization refactor yet.**
Application checks pass, but the requested container gate is blocked: Podman
cannot connect to its configured VM socket, and Docker is absent. Build the
images and validate a disposable Podman Compose stack, including volume ownership
and proxy networking, before accepting Phase 2C. The existing tracked backups
also need a separate repository-data review; their contents were not examined.

**Confirmed defects and corrections**

1. All five CI jobs used complete repository checkouts. Git's path list contains
   `data_backup.json`, `media_backup.tar.gz`, and `portfolio_backup.sql.gz`, so
   those artifacts entered CI workspaces even though tests did not import them.
   Each checkout now uses non-cone sparse checkout with `/*` and `!/*_backup.*`.
   [actions/checkout v6](https://github.com/actions/checkout/blob/v6/src/git-source-provider.ts)
   uses a `blob:none` partial fetch when sparse checkout is requested. A synthetic
   Git index containing the same path names proved that the rules exclude all
   three backups and retain all 122 other tracked paths. No backup was opened,
   copied, removed, or altered. `.gitignore` now also excludes new root backup
   artifacts; it does not untrack existing files or remove their history.
2. Compose initialized PostgreSQL using `${POSTGRES_USER}` and `${POSTGRES_DB}`
   but hardcoded `portfolio_user` and `portfolio_db` in the application's URL.
   Parsing a temporary Compose copy with alternate synthetic names reproduced
   the mismatch. `DATABASE_URL` now uses the same variables. Podman Compose's
   parser confirmed that the identities agree after the correction. Existing
   installations using the original names retain the same URL and behavior.

No application, model, migration, template, JavaScript, or stylesheet changes
were needed during Phase 2C.

**Verification results**

| Check | Result |
| --- | --- |
| Python 3.11.16 / SQLite | All 191 Django tests passed |
| Python 3.13.15 / SQLite | All 191 Django tests passed |
| Python 3.11.16 / PostgreSQL 16.14 | All 191 Django tests passed |
| Python 3.13.15 / PostgreSQL 16.14 | All 191 Django tests passed |
| Django system checks | Passed on all four combinations |
| Migration drift | No changes detected on all four combinations |
| Production security system checks | Passed with a clean synthetic environment and dotenv loading patched out |
| Clean Python dependency installation | Hash-verified, wheel-only, offline installs passed on both Python versions; pip check passed |
| Hash enforcement | pip rejected a deliberately incorrect hash and a missing hash |
| Lock completeness | 53 exact pins with SHA256 hashes; every requirements.in pin agrees; 51 packages active on Linux |
| Lock reproduction | uv 0.12.15 regenerated identical bytes in a temporary copy while retaining the existing lock |
| Python vulnerability audit | pip-audit 2.10.1 queried PyPI: zero findings across 51 active packages |
| Full npm vulnerability audit | Eight affected dependency entries: five high, three moderate, representing the two advisories below; expected exit 1 |
| Runtime npm audit | `npm audit --omit=dev`: zero findings |
| Frontend installation/build | `npm ci --ignore-scripts` and CSS build passed on Node 24.21.0 / npm 12.0.2 |
| Design preservation | Built CSS equals the pre-update build after the Tailwind version banner |
| Syntax | All tracked JavaScript and 43 Python files passed; tracked shell scripts and the extensionless deployment health script passed |
| Workflow validation | actionlint 1.7.12 and YAML parsing passed; git diff --check passed |
| Compose configuration | Podman Compose parsed a temporary copy with a synthetic env file; database interpolation, pins and mounts checked |
| Image pins | All five distinct image digests match official registry metadata obtained on the review date and include Linux amd64/arm64 manifests |
| Wagtail image processing | Willow decoded/resized PNG, JPEG, WebP and HEIF to JPEG successfully |
| Wagtail document permissions | Login, group, password, inherited restrictions, authorized downloads, HEAD/ETag and response-header tests passed |
| Actual Nginx document access | Local Nginx 1.29.4 passed nginx -t/-T and GET/HEAD tests for raw, encoded and normalized document paths; other media and canonical routing passed |
| Actual Nginx proxy headers | Host and real-IP overwrite, forwarded-for append, and Django client-IP resolution passed with synthetic loopback requests |
| CI checkout exclusion | All five jobs have identical exclusions; Git applied the patterns successfully to synthetic path-only fixtures |
| CI/test fixture privacy | Isolated settings and mocked HTTP tests passed; reviewed CI/test files contain synthetic contact records and reserved-domain emails, no production credentials |
| Container build/runtime, live Redis and volume permissions | BLOCKED: Podman VM socket unavailable; no Docker binary |
| Optional browser layout checks | BLOCKED: Playwright and Chrome/Chromium are unavailable; their Python syntax was checked |

All database runs used the existing disposable PostgreSQL 16.14 cluster under
`/tmp`, synthetic credentials, and loopback port 55432. It was stopped after
verification. This source-built test server does not validate the Alpine
PostgreSQL image. No production service, environment file, media volume, or
backup contents were used. Local Nginx tests substituted only temporary paths,
ports and the upstream; they do not establish deployed configuration or cache
state. No remote CI execution was triggered.

**Python and container reproducibility**

The Dockerfile enforces `--require-hashes --only-binary=:all:` when installing
into a venv created with `--without-pip`, then runs pip check. The tested
installer pattern uses an external pip with `--python` to populate that venv;
no unpinned installer is seeded into it. Both Python stages use the same pinned
3.11.16 Bookworm image. The build stage uses pinned Node 24.21.0, npm's committed
lock and disabled installation scripts. Only its generated CSS crosses into
the final image; Node and node_modules do not.

Compose retains PostgreSQL 16, Redis 7 and Nginx 1.29 with digest pins. The web
image still runs as uid 1000 and owns its image directories. It writes the
named static/media volumes; Nginx mounts both read-only. Image directory
ownership does not prove that existing or rootless Podman volumes are writable.
UID mapping, copy-up, SELinux labeling, service health ordering, live Redis
compatibility and DNS resolution remain unverified without a working engine.

The Nginx resolver is hardcoded to `10.89.0.1`, and the Compose bridge has no
explicit subnet. Verify its actual gateway/DNS and proxy addresses in the
disposable stack. A successful YAML parse is not evidence that those addresses
match Podman's network. Runtime APT packages, CI's APK-installed test Python,
runner images, action tags and audit-tool dependencies are not fully frozen;
the project does not claim byte-identical container or CI builds.

**Remaining npm advisories and actual exposure**

| Advisory | Severity / packages | Exposure and reason unresolved |
| --- | --- | --- |
| [GHSA-vfj7-8cjw-p6xm / CVE-2026-93687](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) | High; braces 3.0.3 through the Tailwind glob/watch graph | Deeply nested brace patterns can exhaust Node's stack. Content globs are fixed in tailwind.config.js; HTTP requests and CMS content do not supply build glob patterns. No patched braces version is published. |
| [GHSA-rj75-hqrm-r3gf / CVE-2026-104844](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) | Moderate; postcss-selector-parser 6.1.4 and typography's 6.0.10 | Crafted long flat selectors can exhaust build CPU. Repository CSS and Tailwind-generated selectors reach these parsers; production requests do not. The fix is 7.1.6, outside the current dependencies' permitted 6.x versions. |

This exposure assessment follows the checked-in build inputs and dependency
call sites. An untrusted pull request can change CSS, configuration or generated
selectors and fail or stall its own CI build. Build-only does not mean harmless
for arbitrary build inputs. No force fix, cross-major override, Tailwind
replacement, or new framework was introduced. The full npm audit remains
informational in CI, so newly introduced development advisories would also be
nonblocking; inspect its output on future dependency updates.

**Reverse-proxy boundaries**

The published Nginx port binds only to host loopback. The Django container has
no published port, but peers on the Compose bridge can reach it. Nginx
overwrites Host, X-Forwarded-Host and X-Real-IP and appends its direct peer to
X-Forwarded-For. The shared client-IP helper ignores forwarding from untrusted
peers and walks trusted chains from right to left. Spoofed leftmost addresses
were ignored in both Django regression tests and the actual Nginx header probe.
Rate limiting, stored contact IP and Turnstile use the same helper.

The default trusted networks include all of `10.89.0.0/16` and loopback, rather
than individual proxy addresses. Local processes and containers within that
trusted boundary can supply forwarded identities. Nginx preserves an incoming
X-Forwarded-Proto value; a local HTTP request carrying `https` or `https,http`
was consequently considered secure by Django. The scheme boundary therefore
depends on the outer TLS proxy stripping/setting the header and on loopback
ingress remaining restricted, as required by
[Django's proxy-header guidance](https://docs.djangoproject.com/en/5.2/ref/settings/#secure-proxy-ssl-header).
The outer proxy configuration was not available for verification.

Gunicorn's forwarded_allow_ips defaults to 127.0.0.1; it does not establish
trust for a bridge-address Nginx peer. Django independently uses
SECURE_PROXY_SSL_HEADER, so tightening Gunicorn alone would not validate that
header. No proxy setting was changed without evidence of the actual deployment
chain. Previously cached raw documents at an external CDN were not checked.

**Modified files and diff scope**

Phase 2C changed `.github/workflows/ci.yml`, `.gitignore`, and
`docker-compose.yml`, and added this report. Temporary verification scripts,
wheels, synthetic configuration and test logs remain under `/tmp`.

The complete uncommitted worktree also contains the Phase 2B changes:

```text
M .github/workflows/ci.yml
M .gitignore
M README.md
M TESTING.md
M app/Dockerfile
M app/home/test_document_security.py
M app/package-lock.json
M app/package.json
M app/requirements.txt
M docker-compose.yml
D package-lock.json
? DEPENDENCIES.md
? VERIFICATION.md
? app/requirements.in
```

The Phase 2A comparison additionally includes `app/config/settings.py`,
`app/home/test_webhook_logging.py`, `app/home/views.py`, `nginx.conf`, and
`scripts/check_nginx_documents.py`. Models and migration files are unchanged.
Use `git diff --stat` for tracked uncommitted changes and
`git diff da82dbb --stat` for tracked changes across both earlier phases;
these commands omit the three new untracked files listed above.

```text
git diff --stat: 11 files, 902 insertions(+), 118 deletions(-)
git diff da82dbb --stat: 16 files, 1369 insertions(+), 120 deletions(-)
```

No changes were committed, pushed, deployed, or staged. The model-organization
refactor has not started. Backup files and Git history remain untouched, so this
review cannot establish that their contents contain no credentials or personal
data. CI checkout exclusion prevents their normal inclusion in the proposed
workflow; it does not repair previous checkouts or repository disclosure.
