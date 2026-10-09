# Home tests

Run from `app/` using the isolated test settings. These settings skip `.env`,
use synthetic credentials, local storage/cache/email, and block unmocked HTTP.

```sh
python manage.py test --noinput --settings=config.test_settings
python manage.py test home.tests.test_contact --settings=config.test_settings
TEST_DATABASE_ENGINE=postgresql python manage.py test --noinput --settings=config.test_settings
```

The PostgreSQL command expects the synthetic local database configured in
`config/test_settings.py`; it does not use the application's production database.

| Modules | Coverage |
| --- | --- |
| `test_baseline` | Model identities, relationships, templates and Wagtail registrations |
| `test_homepage`, `test_project_listing` | Editorial selection, visibility, filters and ordering |
| `test_navigation`, `test_reading` | Site ownership, index resolution, neighbors and reading time |
| `test_contact`, `test_webhook_logging` | Validation, proxy trust, rate limits, Turnstile and safe logging |
| `test_document_security`, `test_error_pages` | Protected downloads and accessible error responses |
| `test_lab`, `test_lab_entries`, `test_project_case_study` | Rendering, editor constraints and migration compatibility |
| `test_queries` | Rendered query budgets and bulk relation loading |
| `test_isolation` | Test configuration and external-service isolation |

Keep class and method names when moving tests so discovery comparisons can
distinguish module moves from lost coverage. Test modules are not re-exported
from `__init__.py`, which would make discovery collect them twice.
