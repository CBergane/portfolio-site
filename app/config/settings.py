import os, dj_database_url
from pathlib import Path
from dotenv import load_dotenv

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").lower() in ("1", "true", "yes")

# -------------------------------------------------
# Paths & env
# -------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv()  # läs .env om den finns

# -------------------------------------------------
# Core security / debug
# -------------------------------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

# När du kör bakom proxy (HAProxy/Traefik/nginx) – korrekt host/https-upptäckt
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# Styr https-redirect via env; default = på i prod (dvs när DEBUG=False)
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# HSTS endast i prod
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# -------------------------------------------------
# Internationalization / timezone
# -------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# -------------------------------------------------
# Apps
# -------------------------------------------------
INSTALLED_APPS = [
    "home",

    # Tagging & cluster relations (REQUIRED for Wagtail tags)
    "modelcluster",
    "taggit",

    # Wagtail
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail.contrib.settings",
    "wagtail.contrib.sitemaps",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail",

    # 3rd party
    "wagtailmarkdown",
    "django_htmx",

    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # måste ligga tidigt
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "wagtail.contrib.redirects.middleware.RedirectMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "home" / "templates"],
        "APP_DIRS": True,  # viktigt
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# -------------------------------------------------
# Database (PostgreSQL via env)
# -------------------------------------------------
#DATABASES = {
#    "default": {
#        "ENGINE": "django.db.backends.postgresql",
#        "NAME": os.getenv("POSTGRES_DB"),
#        "USER": os.getenv("POSTGRES_USER"),
#        "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
#        "HOST": os.getenv("POSTGRES_HOST", "localhost"),  # 'db' i docker
#        "PORT": os.getenv("POSTGRES_PORT", "5432"),
#    }
#}
import os, dj_database_url
DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv("DATABASE_URL", "postgres://portfolio_user:@db:5432/portfolio_db"),
        conn_max_age=600,
    )
}



# -------------------------------------------------
# Auth validators
# -------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -------------------------------------------------
# Wagtail
# -------------------------------------------------
WAGTAIL_SITE_NAME = "Christian Bergane Portfolio"
WAGTAILADMIN_BASE_URL = os.getenv("WAGTAILADMIN_BASE_URL", "http://localhost:8000")

# -------------------------------------------------
# Static / Media (WhiteNoise i prod)
# -------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]  # ok även om mappen är tom

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

if not DEBUG:
    # Hashade & komprimerade statiska filer i prod
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# -------------------------------------------------
# CSRF-trusted origins (lägg till egen domän när du kör live)
# -------------------------------------------------
_default_csrf = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
_extra_csrf = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS_EXTRA", "").split(",")
    if origin.strip()
]
CSRF_TRUSTED_ORIGINS = _default_csrf + _extra_csrf

# -------------------------------------------------
# Misc
# -------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
