"""Local validation with an in-memory database and temporary media storage."""
import tempfile

from .settings import *  # noqa: F403

globals().pop('STATICFILES_STORAGE', None)

SECRET_KEY = 'local-validation-only'
DEBUG = True
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
SECURE_SSL_REDIRECT = False
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
_test_media = tempfile.TemporaryDirectory(prefix='nordic-signal-test-media-')
MEDIA_ROOT = _test_media.name
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
