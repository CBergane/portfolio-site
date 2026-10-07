"""Wagtail download permissions; Nginx access is checked separately."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from wagtail.documents import get_document_model
from wagtail.models import Collection, CollectionViewRestriction


class DocumentSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        root = Collection.get_first_root_node()
        cls.private_collection = root.add_child(name='Synthetic private documents')
        child = cls.private_collection.add_child(name='Inherited restriction')
        Document = get_document_model()
        cls.public = Document.objects.create(
            title='Synthetic public document', collection=root,
            file=SimpleUploadedFile('public.txt', b'synthetic public document bytes'),
        )
        cls.private = Document.objects.create(
            title='Synthetic private document', collection=child,
            file=SimpleUploadedFile('private.txt', b'synthetic private document bytes'),
        )
        cls.private.get_file_hash()
        cls.reader = get_user_model().objects.create_user(username='synthetic-reader')

    def restrict(self, restriction_type, **kwargs):
        return CollectionViewRestriction.objects.create(
            collection=self.private_collection, restriction_type=restriction_type, **kwargs,
        )

    def assert_document_bytes(self, response, content):
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)
        self.addCleanup(response.close)
        self.assertEqual(b''.join(response.streaming_content), content)
        self.assertNotIn('Location', response)
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['Content-Security-Policy'], "default-src 'none'")

    def test_public_url_still_streams_the_document_with_security_headers(self):
        self.assertEqual(settings.WAGTAILDOCS_SERVE_METHOD, 'serve_view')
        self.assertEqual(self.public.file.field.upload_to, 'documents')
        self.assertEqual(self.public.url, f'/documents/{self.public.pk}/{self.public.filename}')
        response = self.client.get(self.public.url)
        self.assert_document_bytes(response, b'synthetic public document bytes')
        self.assertTrue(response['Content-Disposition'].startswith('attachment;'))

    def test_login_restriction_is_inherited_and_does_not_affect_public_documents(self):
        self.restrict('login')
        response = self.client.get(self.private.url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(response.streaming)
        self.assertNotIn(self.private.file.url, response['Location'])
        self.assertNotIn(b'synthetic private document bytes', response.content)
        self.assert_document_bytes(self.client.get(self.public.url), b'synthetic public document bytes')

    def test_logged_in_reader_can_download_a_login_restricted_document(self):
        self.restrict('login')
        self.client.force_login(self.reader)
        self.assert_document_bytes(self.client.get(self.private.url), b'synthetic private document bytes')

    def test_group_restriction_denies_nonmembers_and_allows_members(self):
        restriction = self.restrict('groups')
        group = Group.objects.create(name='Synthetic document readers')
        restriction.groups.add(group)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(self.private.url).status_code, 302)
        self.reader.groups.add(group)
        self.assert_document_bytes(self.client.get(self.private.url), b'synthetic private document bytes')

    def test_password_restriction_requires_the_correct_password_before_streaming(self):
        restriction = self.restrict('password', password='synthetic-document-password')
        response = self.client.get(self.private.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.streaming)
        self.assertTemplateUsed(response, 'wagtaildocs/password_required.html')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotIn(b'synthetic private document bytes', response.content)
        url = reverse('wagtaildocs_authenticate_with_password', args=[restriction.pk])
        self.client.post(url, {'password': 'wrong', 'return_url': self.private.url})
        self.assertFalse(self.client.get(self.private.url).streaming)
        response = self.client.post(url, {
            'password': 'synthetic-document-password', 'return_url': self.private.url,
        })
        self.assertRedirects(response, self.private.url, fetch_redirect_response=False)
        self.assert_document_bytes(self.client.get(self.private.url), b'synthetic private document bytes')

    def test_head_and_known_etag_cannot_bypass_restrictions(self):
        self.restrict('login')
        self.client.force_login(self.reader)
        response = self.client.get(self.private.url)
        etag = response['ETag']
        self.assert_document_bytes(response, b'synthetic private document bytes')
        anonymous = Client()
        for method in (anonymous.get, anonymous.head):
            with self.subTest(method=method.__name__):
                response = method(self.private.url, HTTP_IF_NONE_MATCH=etag)
                self.assertEqual(response.status_code, 302)
                self.assertFalse(response.streaming)
