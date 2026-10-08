"""Create only synthetic documents, pages and a session in the isolated database."""
import json
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'integration_settings')
django.setup()
from django.conf import settings
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY, get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from wagtail.documents import get_document_model
from wagtail.models import Collection, CollectionViewRestriction, Site

assert getattr(settings, 'PHASE4A_ISOLATED', False)
database = settings.DATABASES['default']
assert (database['HOST'], database['NAME'], database['USER']) == ('db', 'phase4a_db', 'phase4a_user')
assert Site.objects.get(is_default_site=True).hostname == '127.0.0.1'
root = Collection.get_first_root_node()
private = Collection.objects.filter(name='Phase 4A restricted documents').first()
if private is None:
    private = root.add_child(name='Phase 4A restricted documents')
child = Collection.objects.filter(name='Phase 4A inherited restriction').first()
if child is None:
    child = private.add_child(name='Phase 4A inherited restriction')
CollectionViewRestriction.objects.get_or_create(collection=private, restriction_type='login')
Document = get_document_model()
documents = {}
for key, collection in (('public', root), ('private', child)):
    content = f'phase4a synthetic {key} document bytes'.encode()
    document = Document.objects.filter(title=f'Phase 4A {key} document').first()
    if document is None:
        document = Document.objects.create(
            title=f'Phase 4A {key} document', collection=collection,
            file=ContentFile(content, name=f'phase4a-{key}.txt'),
        )
    documents[key] = {'url': document.url, 'direct': document.file.url, 'content': content.decode()}
reader, _ = get_user_model().objects.get_or_create(username='phase4a-synthetic-reader')
session = SessionStore()
session[SESSION_KEY] = str(reader.pk)
session[BACKEND_SESSION_KEY] = 'django.contrib.auth.backends.ModelBackend'
session[HASH_SESSION_KEY] = reader.get_session_auth_hash()
session.save()
marker = 'phase4a/persistent-marker.txt'
if not default_storage.exists(marker):
    default_storage.save(marker, ContentFile(b'phase4a synthetic persistent media'))
assert default_storage.open(marker).read() == b'phase4a synthetic persistent media'
print(json.dumps({'documents': documents, 'cookie': f'{settings.SESSION_COOKIE_NAME}={session.session_key}', 'marker': marker}))
