# Phase 2B: dependency security and reproducible builds

Reviewed on 2026-10-08 on `refactor/architecture-cleanup`. No deployment,
production environment, backup, database schema, or migration changes were used.

## Audit results

| Audit | Before | After |
| --- | --- | --- |
| Python, pip-audit 2.10.1 / PyPI | 68 advisory records in 9 packages; 39 distinct advisory IDs | No known vulnerabilities |
| npm, entire lockfile | 14 affected packages (12 high, 2 moderate); 24 distinct advisories | 8 affected packages (5 high, 3 moderate); 2 distinct advisories |
| npm, excluding development dependencies | No application runtime npm dependencies | No known vulnerabilities |

Repeated Python records share advisory IDs and aliases; they are not independent
vulnerabilities. npm also counts affected parent packages, so eight packages do
not mean eight independent vulnerabilities. All npm packages are build/development
dependencies. The runtime image copies the generated CSS, not Node or node_modules.
Audits describe the locked application packages, not the operating system packages
inside images or every possible application vulnerability.

The baseline Python audit used `pip-audit -r app/requirements.txt`. The final
audit used the complete hashed lock with `--strict --require-hashes --no-deps
--disable-pip`. npm audits used `npm audit --json` and `npm audit --omit=dev`.
Audits contacted only public package/advisory services; tooling was installed in
disposable environments under `/tmp`.

## Python fixes and exposure

Severity comes from the linked GitHub advisories. Exploitability below is a code
review assessment of this repository, not a claim that production was tested.

| Package | Change | Severity | Role and exploitability |
| --- | --- | --- | --- |
| Django | 5.2.17 -> 5.2.18 | Low/moderate | Direct, production. HTTP header parsing is exposed to requests; formsets are used in the CMS. No GeoDjango spatial lookups are configured. |
| Pillow | 10.4.0 -> 12.3.0 | High/moderate | Transitive, production image processing. Malicious uploads can reach decoders; specific PSD/FITS/font/PDF/Windows paths depend on accepted formats and APIs. Windows viewer and font-conversion paths are not used here. |
| pillow-heif | 0.22.0 -> 1.8.0 | Moderate | Transitive via Wagtail's Willow HEIF extra, production. Native encoder buffer validation issue; no direct arbitrary encoder buffer API is exposed here. |
| requests | 2.32.5 -> 2.34.2 | Moderate | Direct, production HTTP integrations. Vulnerability concerns local predictable temporary certificate-file reuse; ordinary HTTP alone does not trigger it. |
| urllib3 | 2.5.0 -> 2.8.0 | High | Transitive via Requests, production. Malicious compressed/chunked responses, redirects, and HTTPS proxy configuration are conditional risks. External integrations use Requests; no direct low-level streaming or HTTPS proxy configuration exists in application code. |
| idna | 3.11 -> 3.20 | Moderate | Transitive via Requests, production. Oversized attacker-controlled hostnames cause expensive normalization; integrations normally use configured hostnames. |
| soupsieve | 2.8 -> 2.10 | High/moderate | Transitive via Beautiful Soup, production. Requires attacker-controlled CSS selectors; application selectors are fixed. |
| sqlparse | 0.5.3 -> 0.6.0 | High/moderate | Transitive via Django, production. Crafted SQL can exhaust parser/formatter resources; no raw SQL formatting endpoint or generated Python/PHP snippet execution exists here. |
| python-dotenv | 1.0.1 -> 1.2.4 | Moderate | Direct, production. Vulnerability requires rewriting a symlinked environment file; application uses `load_dotenv`, not `set_key`/`unset_key`. |
| bleach | 4.1.0 -> removed | Moderate/low | Previously installed in production, unused. Wagtail Markdown 0.14.1 depends on nh3; no application import or remaining dependency requires Bleach. |

Pillow and pillow-heif require newer major versions because their old lines have
no fixes for the reported advisories. Their new versions satisfy Wagtail 8 and
Willow's active dependency constraints. Django stays on 5.2; Wagtail stays on 8.0.
No framework replacement or schema update is included.

The PyPI audit feed did not yet list Django's October 6 fixes when this review ran.
The [official Django 5.2.18 release notes](https://docs.djangoproject.com/en/5.2/releases/5.2.18/)
identify CVE-2026-77050 (language cache DoS, low), CVE-2026-84429 (header parsing
DoS, moderate), CVE-2026-87890 (spatial byte-value request forgery, moderate),
CVE-2026-87975 (editable-primary-key formset privilege abuse, moderate), and an
incomplete geometry-depth mitigation for CVE-2026-15830. The patch is included
despite that feed lag. Spatial paths are unused; formset exposure depends on the
particular form and permissions.

## npm fixes and remaining advisories

Direct packages are pinned to Tailwind 3.4.19 and typography 0.5.20. Compatible
transitive updates fix the reported advisories in brace-expansion, glob, minimatch,
nanoid, picomatch, postcss, source-map-js, and the selector-parser recursion fix.
No `npm audit fix --force`, cross-major override, or package replacement was used.

All findings in the following table concern the build toolchain. Exploitation
requires malicious inputs to the relevant build API or CLI; visitors cannot send
input to a Node runtime because it is absent from the application runtime image.

| Remaining advisory | Severity | Affected packages / path | Why unresolved |
| --- | --- | --- | --- |
| [GHSA-vfj7-8cjw-p6xm / CVE-2026-93687](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) | High | braces 3.0.3, through chokidar/micromatch/fast-glob/Tailwind. Deeply nested glob patterns exhaust the parser stack. | No patched braces release is published. npm suggests Tailwind 4, which is outside this phase. Templates and glob configuration are repository-controlled; untrusted build inputs remain a risk. |
| [GHSA-rj75-hqrm-r3gf / CVE-2026-104844](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) | Moderate | postcss-selector-parser 6.1.4 and typography's 6.0.10, also through postcss-nested/Tailwind. Very long flat selectors cause quadratic parsing. | Fix is in 7.1.6, outside Tailwind 3's 6.x range and typography's exact 6.0.10 dependency. npm suggests a typography downgrade or Tailwind 4. Trusted repository CSS is the current input; cross-major overrides need separate compatibility review. |

The full npm audit exits 1 for these findings. CI prints this audit with
`continue-on-error`; it is informational, including for future development-only
advisories, until compatible fixes are available. Runtime npm and Python audits
are blocking. Review the full npm output on each dependency update; do not treat
the informational step as a clean audit.

## Unnecessary and outdated dependencies

Removed unused Bleach, l18n, pytz, six, and webencodings after checking application
imports and package metadata. The latter four supported the obsolete Bleach/l18n
branches, not the current Django/Wagtail graph. The empty root package-lock.json
was also removed; app/package-lock.json is the actual frontend lock.

The lock now records previously floating dj-database-url 2.3.0 and Redis client
6.4.0, plus Wagtail 8's previously unpinned django-ninja, modelsearch, pydantic,
pydantic-core, swapper, nh3 and typing-inspection. Redis server stays on 7;
PostgreSQL server stays on 16.

Outdated does not necessarily mean vulnerable. Unaffected versions are retained
to keep behavior stable. The inventory below compares the baseline graph with
public PyPI's latest releases on the review date; major or calendar-version jumps
are not approved upgrades. Gunicorn 22 is behind the current 26 line, but this
audit found no advisory affecting 22; its future upgrade needs separate HTTP
compatibility review. npm warns that glob 10.5.0 is deprecated; it is the patched
10.x version permitted by Sucrase. Browserslist warns that its browser dataset is
old; refreshing that dataset is a separate rendering-target change.

| Python package | Role | Baseline | Final | Latest upstream |
| --- | --- | --- | --- | --- |
| asgiref | Transitive | 3.10.0 | 3.10.0 | 3.12.1 |
| beautifulsoup4 | Direct | 4.13.4 | 4.13.4 | 4.15.0 |
| bleach | Unused, removed | 4.1.0 | removed | 6.4.0 |
| certifi | Transitive | 2025.10.5 | 2025.10.5 | 2026.7.22 |
| charset-normalizer | Transitive | 3.4.4 | 3.4.4 | 3.5.2 |
| dj-database-url | Direct | 2.3.0 | 2.3.0 | 3.1.2 |
| django | Direct | 5.2.17 | 5.2.18 | 6.1.2 |
| django-filter | Transitive | 24.3 | 24.3 | 26.2 |
| django-htmx | Direct | 1.19.0 | 1.19.0 | 1.29.0 |
| django-stubs-ext | Transitive | 5.2.7 | 5.2.7 | 6.1.2 |
| django-taggit | Direct | 5.0.1 | 5.0.1 | 6.1.0 |
| django-treebeard | Transitive | 5.3.1 | 5.3.1 | 7.0.2 |
| djangorestframework | Transitive | 3.18.0 | 3.18.0 | 3.18.3 |
| gunicorn | Direct | 22.0.0 | 22.0.0 | 26.2.0 |
| idna | Transitive | 3.11 | 3.20 | 3.20 |
| markdown | Direct | 3.9 | 3.9 | 3.11 |
| packaging | Transitive | 25.0 | 25.0 | 26.3 |
| pillow | Transitive | 10.4.0 | 12.3.0 | 12.3.0 |
| pillow-heif | Transitive | 0.22.0 | 1.8.0 | 1.8.0 |
| psycopg | Direct | 3.2.3 | 3.2.3 | 3.3.6 |
| psycopg-binary | Transitive | 3.2.3 | 3.2.3 | 3.3.6 |
| pydantic-core | Transitive | 2.46.5 | 2.46.5 | 2.49.0 |
| python-dotenv | Direct | 1.0.1 | 1.2.4 | 1.2.4 |
| pytz | Unused, removed | 2025.2 | removed | 2026.5 |
| redis | Direct | 6.4.0 | 6.4.0 | 8.1.0 |
| requests | Direct | 2.32.5 | 2.34.2 | 2.34.2 |
| soupsieve | Transitive | 2.8 | 2.10 | 2.10 |
| sqlparse | Transitive | 0.5.3 | 0.6.0 | 0.6.0 |
| typing-extensions | Transitive | 4.15.0 | 4.15.0 | 4.16.0 |
| urllib3 | Transitive | 2.5.0 | 2.8.0 | 2.8.0 |
| wagtail-markdown | Direct | 0.14.1 | 0.14.1 | 0.15.0 |
| webencodings | Unused, removed | 0.5.1 | removed | 0.6.1 |
| whitenoise | Direct | 6.7.0 | 6.7.0 | 6.12.0 |
| willow | Transitive | 1.11.0 | 1.11.0 | 1.12.0 |

Outdated npm packages after the fixes (`npm outdated --all`):

| npm package | Locked versions | Compatible wanted versions | Latest upstream |
| --- | --- | --- | --- |
| @alloc/quick-lru | 5.2.0 | 5.3.0 | 5.3.0 |
| @isaacs/cliui | 8.0.2 | 8.0.2 | 9.0.0 |
| @jridgewell/sourcemap-codec | 1.5.5 | 1.6.0 | 1.6.0 |
| @nodelib/fs.scandir | 2.1.5 | 2.1.5 | 4.0.1 |
| @nodelib/fs.stat | 2.0.5 | 2.0.5 | 4.0.0 |
| @nodelib/fs.walk | 1.2.8 | 1.2.8 | 3.0.1 |
| ansi-regex | 5.0.1, 6.2.2 | 5.0.1, 6.4.0 | 6.4.0 |
| ansi-styles | 4.3.0, 6.2.3 | 4.3.0, 6.2.3 | 7.0.0 |
| balanced-match | 1.0.2 | 1.0.2 | 4.0.4 |
| binary-extensions | 2.3.0 | 2.3.0 | 3.2.0 |
| brace-expansion | 2.1.7 | 2.1.7 | 5.0.12 |
| chokidar | 3.6.0 | 3.6.0 | 5.0.0 |
| color-convert | 2.0.1 | 2.0.1 | 3.1.3 |
| color-name | 1.1.4 | 1.1.4 | 2.1.1 |
| commander | 4.1.1 | 4.1.1 | 15.0.0 |
| eastasianwidth | 0.2.0 | 0.2.0 | 0.3.0 |
| emoji-regex | 8.0.0, 9.2.2 | 8.0.0, 9.2.2 | 11.0.0 |
| fastq | 1.19.1 | 1.20.3 | 1.20.3 |
| foreground-child | 3.3.1 | 3.3.1 | 4.0.3 |
| glob | 10.5.0 | 10.5.0 | 13.0.6 |
| glob-parent | 5.1.2 | 5.1.2 | 6.0.2 |
| hasown | 2.0.2 | 2.0.4 | 2.0.4 |
| is-binary-path | 2.1.0 | 2.1.0 | 3.0.0 |
| is-core-module | 2.16.1 | 2.17.0 | 2.17.0 |
| is-fullwidth-code-point | 3.0.0 | 3.0.0 | 5.1.0 |
| isexe | 2.0.0 | 2.0.0 | 4.0.0 |
| jackspeak | 3.4.3 | 3.4.3 | 4.2.3 |
| jiti | 1.21.7 | 1.21.7, 2.7.0 | 2.7.0 |
| lines-and-columns | 1.2.4 | 1.2.4 | 2.0.4 |
| lru-cache | 10.4.3 | 10.4.3 | 11.5.3 |
| minimatch | 9.0.9 | 9.0.9 | 10.2.6 |
| minipass | 7.1.2 | 7.1.3 | 7.1.3 |
| nanoid | 3.3.20 | 3.3.20 | 6.0.2 |
| path-key | 3.1.1 | 3.1.1 | 4.0.0 |
| path-scurry | 1.11.1 | 1.11.1 | 2.0.2 |
| picomatch | 2.3.2 | 2.3.2 | 4.0.7 |
| pify | 2.3.0 | 2.3.0 | 6.1.0 |
| postcss-import | 15.1.0 | 15.1.0 | 17.0.0 |
| postcss-js | 4.1.0 | 4.1.0 | 5.1.0 |
| postcss-nested | 6.2.0 | 6.2.0 | 8.0.1 |
| postcss-selector-parser | 6.0.10, 6.1.4 | 6.0.10, 6.1.4 | 7.1.6 |
| read-cache | 1.0.0 | 1.0.2 | 1.0.2 |
| readdirp | 3.6.0 | 3.6.0 | 5.1.1 |
| resolve | 1.22.11 | 1.22.13 | 1.22.13 |
| shebang-regex | 3.0.0 | 3.0.0 | 4.0.0 |
| string-width | 4.2.3, 5.1.2 | 4.2.3, 5.1.2 | 8.3.0 |
| string-width-cjs:string-width@^4.2.0 | 4.2.3 | 4.2.3 | 8.3.0 |
| strip-ansi | 6.0.1, 7.1.2 | 6.0.1, 7.2.0 | 7.2.0 |
| strip-ansi-cjs:strip-ansi@^6.0.1 | 6.0.1 | 6.0.1 | 7.2.0 |
| sucrase | 3.35.0 | 3.35.1 | 3.35.1 |
| tailwindcss | 3.4.19 | 3.4.19 (application range) | 4.3.3 |
| ts-interface-checker | 0.1.13 | 0.1.13 | 1.0.2 |
| which | 2.0.2 | 2.0.2 | 7.0.0 |
| wrap-ansi | 8.1.0 | 8.1.0 | 10.0.2 |
| wrap-ansi-cjs:wrap-ansi@^7.0.0 | 7.0.0 | 7.0.0 | 10.0.2 |

Both frontend direct packages are used: Tailwind builds CSS and typography is
loaded by tailwind.config.js. The transitive packages are required by that
build graph; none is removed speculatively. Uninstalled optional peers are
excluded from the inventory. Unaffected outdated packages remain locked.

## Reproducibility

`app/requirements.in` records application requirements and explicit security
pins. `app/requirements.txt` is the generated full dependency graph with exact
versions, platform markers, and SHA256 distribution hashes. Regenerate with
uv 0.12.15, retaining the existing lock to preserve unaffected versions:

```sh
uv pip compile app/requirements.in --python-version 3.11 --universal --generate-hashes --no-build --output-file app/requirements.txt
```

Install with:

```sh
python -m pip install --require-hashes --only-binary=:all: -r app/requirements.txt
```

Missing platform wheels fail closed instead of compiling
with unpinned build dependencies. The supported container targets are Linux
amd64/arm64; other architectures may lack wheels.

The Python builder uses a venv without pip and the base image's pip with
`--python /opt/venv`; this avoids copying a newly seeded, unpinned pip/setuptools
into the application venv. Both Python stages use the same Python 3.11.16
Bookworm image digest. Node 24.21.0 replaces the
[end-of-life Node 20 build stage](https://nodejs.org/en/about/eol) and is pinned to
an official Alpine image digest. Python builder compiler/libpq build packages
were removed because installation is wheel-only. Runtime psql/libpq remain for
the existing database readiness check.

Compose PostgreSQL 16, Redis 7, Nginx 1.29, and CI's matching service images use
verified official multi-platform image digests. Refresh digests deliberately to
take future security fixes. Image pins and package locks improve repeatability;
runtime APT packages still come from live Debian repositories, and build metadata
can vary. This does not claim byte-identical container images.

CI checks Python 3.11 and 3.13 against SQLite and disposable PostgreSQL 16, hashes,
dependency compatibility, Python syntax, migrations, Django tests, frontend
builds and audits. A separate job builds the application image and runs isolated
Django checks/tests using `config.test_settings`; it uses no production services.

## Verification performed locally

| Check | Result |
| --- | --- |
| Clean hash-verified wheel-only installs | Passed, Python 3.11.16 and 3.13.15; pip check reports no broken requirements |
| SQLite full Django suite | 191 tests passed on each Python version |
| PostgreSQL 16.14 full Django suite | 191 tests passed on each Python version |
| Django system checks | Passed on both Python versions and both databases |
| Migration drift | No changes detected on both Python versions and both databases |
| Frontend | Clean npm ci and CSS build passed on Node 24.21.0; CSS is byte-identical after the Tailwind version banner |
| Syntax | All tracked JavaScript and 43 Python files passed; tracked shell files and the extensionless deployment health script passed |
| Configuration | Compose/CI YAML parsed; service digests and Python matrix consistency asserted; actionlint 1.7.12 passed |
| Image-library compatibility | Willow decoded/resized PNG, JPEG, WebP and HEIF to JPEG with correct dimensions |
| ARM64 dependency availability | All active pinned distributions downloaded as hash-verified Linux ARM64 wheels; runtime execution not tested on ARM64 |
| Lock regeneration | Identical output with uv 0.12.15 |
| Repeated dependency audits | Python: no known vulnerabilities; npm runtime: none; full npm: the two documented advisories remain |
| Full container build/runtime | Blocked locally: Docker is absent and Podman's configured VM socket is unavailable; CI job added but not run here |

PostgreSQL 16.14 was built from official source under `/tmp` after verifying its
published SHA256 checksum. Its synthetic cluster listened only on loopback port
55432 and a dedicated temporary socket, used no production Compose configuration,
and was stopped after validation. The test build omitted optional ICU, readline
and compression libraries; it verifies SQL/backend compatibility, not the
distribution-specific container environment.

The first PostgreSQL run exposed five errors in the existing document tests,
also reproduced with the original dependencies. Their shared helper registered
`response.close` as a cleanup after Django's test client had already closed the
consumed stream. The second close emitted request-finished signals that closed
the PostgreSQL TestCase transaction. The redundant cleanup was removed and
replaced by an assertion that consuming the stream closed the response. All
download permission/header assertions remain; application document handling is
unchanged. Both complete suites passed again on both database backends.

## Baseline advisory inventory

These tables list distinct baseline advisories, including fixes removed from the
final lock. Python severity is the GitHub advisory classification (medium means
moderate); npm severity is its audit classification. Package exposure is assessed
above. Advisory identifiers and CVE aliases can refer to the same vulnerability.

| Python package | Advisory / CVE | Severity | Outcome |
| --- | --- | --- | --- |
| bleach | [GHSA-gj48-438w-jh9v](https://github.com/advisories/GHSA-gj48-438w-jh9v) | moderate | Removed unused dependency |
| bleach | [GHSA-8rfp-98v4-mmr6](https://github.com/advisories/GHSA-8rfp-98v4-mmr6) | low | Removed unused dependency |
| idna | [GHSA-65pc-fj4g-8rjx](https://github.com/advisories/GHSA-65pc-fj4g-8rjx) / CVE-2026-45409 | moderate | Fixed |
| pillow | [GHSA-cfh3-3jmp-rvhc](https://github.com/advisories/GHSA-cfh3-3jmp-rvhc) / CVE-2026-25990 | high | Fixed |
| pillow | [GHSA-whj4-6x5x-4v2j](https://github.com/advisories/GHSA-whj4-6x5x-4v2j) / CVE-2026-40192 | high | Fixed |
| pillow | [GHSA-wjx4-4jcj-g98j](https://github.com/advisories/GHSA-wjx4-4jcj-g98j) / CVE-2026-42308 | moderate | Fixed |
| pillow | [GHSA-r73j-pqj5-w3x7](https://github.com/advisories/GHSA-r73j-pqj5-w3x7) / CVE-2026-42310 | moderate | Fixed |
| pillow | [GHSA-pwv6-vv43-88gr](https://github.com/advisories/GHSA-pwv6-vv43-88gr) / CVE-2026-42311 | high | Fixed |
| pillow | [GHSA-8v84-f9pq-wr9x](https://github.com/advisories/GHSA-8v84-f9pq-wr9x) / CVE-2026-54059 | high | Fixed |
| pillow | [GHSA-45hq-cxwh-f6vc](https://github.com/advisories/GHSA-45hq-cxwh-f6vc) / CVE-2026-55379 | high | Fixed |
| pillow | [GHSA-4x4j-2g7c-83w6](https://github.com/advisories/GHSA-4x4j-2g7c-83w6) / CVE-2026-55798 | moderate | Fixed |
| pillow | [GHSA-phj9-mv4w-65pm](https://github.com/advisories/GHSA-phj9-mv4w-65pm) / CVE-2026-55380 | high | Fixed |
| pillow | [GHSA-5x94-69rx-g8h2](https://github.com/advisories/GHSA-5x94-69rx-g8h2) / CVE-2026-54060 | high | Fixed |
| pillow | [GHSA-9hw9-ch79-4vh6](https://github.com/advisories/GHSA-9hw9-ch79-4vh6) / CVE-2026-59205 | high | Fixed |
| pillow | [GHSA-6r8x-57c9-28j4](https://github.com/advisories/GHSA-6r8x-57c9-28j4) / CVE-2026-59199 | high | Fixed |
| pillow | [GHSA-62p4-gmf7-7g93](https://github.com/advisories/GHSA-62p4-gmf7-7g93) / CVE-2026-54058 | high | Fixed |
| pillow | [GHSA-xj96-63gp-2gmr](https://github.com/advisories/GHSA-xj96-63gp-2gmr) / CVE-2026-59197 | high | Fixed |
| pillow | [GHSA-fj7v-r99m-22gq](https://github.com/advisories/GHSA-fj7v-r99m-22gq) / CVE-2026-59198 | moderate | Fixed |
| pillow | [GHSA-jjj6-mw9f-p565](https://github.com/advisories/GHSA-jjj6-mw9f-p565) / CVE-2026-59200 | high | Fixed |
| pillow | [GHSA-vjc4-5qp5-m44j](https://github.com/advisories/GHSA-vjc4-5qp5-m44j) / CVE-2026-59204 | high | Fixed |
| pillow-heif | [GHSA-5gjj-6r7v-ph3x](https://github.com/advisories/GHSA-5gjj-6r7v-ph3x) / CVE-2026-28231 | moderate | Fixed |
| python-dotenv | [GHSA-mf9w-mj56-hr94](https://github.com/advisories/GHSA-mf9w-mj56-hr94) / CVE-2026-28684 | moderate | Fixed |
| requests | [GHSA-gc5v-m9x4-r6x2](https://github.com/advisories/GHSA-gc5v-m9x4-r6x2) / CVE-2026-25645 | moderate | Fixed |
| soupsieve | [GHSA-836r-79rf-4m37](https://github.com/advisories/GHSA-836r-79rf-4m37) / CVE-2026-49477 | high | Fixed |
| soupsieve | [GHSA-2wc2-fm75-p42x](https://github.com/advisories/GHSA-2wc2-fm75-p42x) / CVE-2026-49476 | high | Fixed |
| soupsieve | [GHSA-gjv8-xp57-g29c](https://github.com/advisories/GHSA-gjv8-xp57-g29c) / CVE-2026-86000 | moderate | Fixed |
| soupsieve | [GHSA-j934-xhv5-fg8f](https://github.com/advisories/GHSA-j934-xhv5-fg8f) / CVE-2026-85999 | moderate | Fixed |
| sqlparse | [GHSA-f2ff-p2ww-7p4p](https://github.com/advisories/GHSA-f2ff-p2ww-7p4p) / CVE-2026-71491 | high | Fixed |
| sqlparse | [GHSA-3496-9g83-7v6x](https://github.com/advisories/GHSA-3496-9g83-7v6x) / CVE-2026-59894 | moderate | Fixed |
| sqlparse | [GHSA-prg7-hcfm-mfcr](https://github.com/advisories/GHSA-prg7-hcfm-mfcr) / CVE-2026-59893 | high | Fixed |
| sqlparse | [GHSA-pwgv-4x5q-6m9f](https://github.com/advisories/GHSA-pwgv-4x5q-6m9f) / CVE-2026-54284 | high | Fixed |
| sqlparse | [GHSA-cfqr-cjx5-5jcm](https://github.com/advisories/GHSA-cfqr-cjx5-5jcm) / CVE-2026-84305 | moderate | Fixed |
| sqlparse | [GHSA-27jp-wm6q-gp25](https://github.com/advisories/GHSA-27jp-wm6q-gp25) | moderate | Fixed |
| urllib3 | [GHSA-gm62-xv2j-4w53](https://github.com/advisories/GHSA-gm62-xv2j-4w53) / CVE-2025-66418 | high | Fixed |
| urllib3 | [GHSA-2xpw-w6gg-jr37](https://github.com/advisories/GHSA-2xpw-w6gg-jr37) / CVE-2025-66471 | high | Fixed |
| urllib3 | [GHSA-38jv-5279-wg99](https://github.com/advisories/GHSA-38jv-5279-wg99) / CVE-2026-21441 | high | Fixed |
| urllib3 | [GHSA-qccp-gfcp-xxvc](https://github.com/advisories/GHSA-qccp-gfcp-xxvc) / CVE-2026-44431 | high | Fixed |
| urllib3 | [GHSA-vxq7-64xx-v4gw](https://github.com/advisories/GHSA-vxq7-64xx-v4gw) / CVE-2026-97689 | high | Fixed |
| urllib3 | [GHSA-8988-9cw3-xx77](https://github.com/advisories/GHSA-8988-9cw3-xx77) / CVE-2026-97687 | high | Fixed |

| npm package | Advisory | Severity | Exposure and outcome |
| --- | --- | --- | --- |
| brace-expansion | [GHSA-3jxr-9vmj-r5cp](https://github.com/advisories/GHSA-3jxr-9vmj-r5cp) | high | Build-only; fixed |
| brace-expansion | [GHSA-6j4f-fj2g-mc7p](https://github.com/advisories/GHSA-6j4f-fj2g-mc7p) | high | Build-only; fixed |
| brace-expansion | [GHSA-f886-m6hf-6m8v](https://github.com/advisories/GHSA-f886-m6hf-6m8v) | moderate | Build-only; fixed |
| brace-expansion | [GHSA-mh99-v99m-4gvg](https://github.com/advisories/GHSA-mh99-v99m-4gvg) | high | Build-only; fixed |
| brace-expansion | [GHSA-q2hr-2g5m-vwhr](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr) | moderate | Build-only; fixed |
| brace-expansion | [GHSA-qhr7-859c-m2p7](https://github.com/advisories/GHSA-qhr7-859c-m2p7) | high | Build-only; fixed |
| brace-expansion | [GHSA-rgw5-rvv9-x895](https://github.com/advisories/GHSA-rgw5-rvv9-x895) | high | Build-only; fixed |
| braces | [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) | high | Build-only; unresolved (see above) |
| glob | [GHSA-5j98-mcp5-4vw2](https://github.com/advisories/GHSA-5j98-mcp5-4vw2) | high | Build-only; fixed |
| minimatch | [GHSA-23c5-xmqv-rm74](https://github.com/advisories/GHSA-23c5-xmqv-rm74) | high | Build-only; fixed |
| minimatch | [GHSA-3ppc-4f35-3m26](https://github.com/advisories/GHSA-3ppc-4f35-3m26) | high | Build-only; fixed |
| minimatch | [GHSA-7r86-cg39-jmmj](https://github.com/advisories/GHSA-7r86-cg39-jmmj) | high | Build-only; fixed |
| nanoid | [GHSA-28wg-ghj8-5hjv](https://github.com/advisories/GHSA-28wg-ghj8-5hjv) | high | Build-only; fixed |
| nanoid | [GHSA-2v37-7h3g-55p8](https://github.com/advisories/GHSA-2v37-7h3g-55p8) | high | Build-only; fixed |
| nanoid | [GHSA-xwg4-73v4-xw9w](https://github.com/advisories/GHSA-xwg4-73v4-xw9w) | high | Build-only; fixed |
| picomatch | [GHSA-3v7f-55p6-f55p](https://github.com/advisories/GHSA-3v7f-55p6-f55p) | moderate | Build-only; fixed |
| picomatch | [GHSA-c2c7-rcm5-vvqj](https://github.com/advisories/GHSA-c2c7-rcm5-vvqj) | high | Build-only; fixed |
| postcss | [GHSA-6g55-p6wh-862q](https://github.com/advisories/GHSA-6g55-p6wh-862q) | high | Build-only; fixed |
| postcss | [GHSA-fxqj-rqcc-2cmp](https://github.com/advisories/GHSA-fxqj-rqcc-2cmp) | moderate | Build-only; fixed |
| postcss | [GHSA-qx2v-qp2m-jg93](https://github.com/advisories/GHSA-qx2v-qp2m-jg93) | moderate | Build-only; fixed |
| postcss | [GHSA-r28c-9q8g-f849](https://github.com/advisories/GHSA-r28c-9q8g-f849) | high | Build-only; fixed |
| postcss-selector-parser | [GHSA-rj75-hqrm-r3gf](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) | moderate | Build-only; unresolved (see above) |
| postcss-selector-parser | [GHSA-w9m9-85wc-3x92](https://github.com/advisories/GHSA-w9m9-85wc-3x92) | low | Build-only; fixed |
| source-map-js | [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q) | high | Build-only; fixed |
