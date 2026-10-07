"""Synthetic notifications must retain behavior without logging private data."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from io import StringIO
import os
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import ContactSubmission
from .views import send_discord_notification


WEBHOOK_URL = 'https://discord.example.invalid/api/webhooks/123456789/synthetic-webhook-token'
PRIVATE_VALUES = (
    WEBHOOK_URL, '123456789', 'synthetic-webhook-token', 'Synthetic Sender',
    'sender@example.invalid', 'Synthetic private subject', 'Synthetic private message',
    '192.0.2.44', 'synthetic-private-user-agent',
)


class WebhookLogAssertions:
    def assert_private_data_absent(self, logs, stdout, stderr, outcome):
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(stderr.getvalue(), '')
        self.assertEqual(len(logs.records), 1)
        record = logs.records[0]
        self.assertEqual(record.event, 'discord_webhook')
        self.assertEqual(record.outcome, outcome)
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.stack_info)
        self.assertFalse(record.args)
        for value in PRIVATE_VALUES:
            self.assertNotIn(value, '\n'.join(logs.output))
            self.assertNotIn(value, repr(record.__dict__))


class DiscordWebhookLoggingTests(WebhookLogAssertions, SimpleTestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'DISCORD_WEBHOOK_URL': WEBHOOK_URL}))
        self.post = self.enterContext(patch('home.views.requests.post'))
        self.post.return_value = requests.Response()
        self.post.return_value.status_code = 204
        self.submission = SimpleNamespace(
            name='Synthetic Sender', email='sender@example.invalid',
            subject='Synthetic private subject', message='Synthetic private message',
            submitted_at=datetime(2026, 1, 1), ip_address='192.0.2.44',
        )

    def test_success_keeps_the_existing_payload_and_logs_only_the_outcome(self):
        stdout, stderr = StringIO(), StringIO()
        with self.assertLogs('home.views', level='INFO') as logs, redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertTrue(send_discord_notification(self.submission))
        self.assert_private_data_absent(logs, stdout, stderr, 'sent')
        self.assertEqual(logs.records[0].levelname, 'INFO')
        self.post.assert_called_once()
        args, kwargs = self.post.call_args
        self.assertEqual(args, (WEBHOOK_URL,))
        self.assertEqual(kwargs['timeout'], 10)
        self.assertEqual([field['value'] for field in kwargs['json']['embeds'][0]['fields']], [
            self.submission.name, self.submission.email, self.submission.subject,
            self.submission.message, '2026-01-01 00:00:00', self.submission.ip_address,
        ])

    def test_unconfigured_webhook_is_skipped_without_an_http_request(self):
        stdout, stderr = StringIO(), StringIO()
        with patch.dict(os.environ, {'DISCORD_WEBHOOK_URL': ''}):
            with self.assertLogs('home.views', level='INFO') as logs, redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertFalse(send_discord_notification(self.submission))
        self.post.assert_not_called()
        self.assert_private_data_absent(logs, stdout, stderr, 'not_configured')

    def test_http_failure_logs_neither_exception_text_nor_attached_request_data(self):
        request = requests.Request('POST', WEBHOOK_URL, json={'private': list(PRIVATE_VALUES)}).prepare()
        response = requests.Response()
        response.status_code = 401
        response.url = WEBHOOK_URL
        response.request = request
        response._content = ' '.join(PRIVATE_VALUES).encode()
        self.post.return_value = response
        stdout, stderr = StringIO(), StringIO()
        with self.assertLogs('home.views', level='WARNING') as logs, redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertFalse(send_discord_notification(self.submission))
        self.assert_private_data_absent(logs, stdout, stderr, 'failed')
        self.assertEqual(logs.records[0].error_type, 'HTTPError')

    def test_transport_failures_log_only_the_exception_class(self):
        for error in (requests.Timeout, requests.ConnectionError, requests.TooManyRedirects):
            with self.subTest(error=error.__name__):
                self.post.side_effect = error(' '.join(PRIVATE_VALUES))
                stdout, stderr = StringIO(), StringIO()
                with self.assertLogs('home.views', level='WARNING') as logs, redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertFalse(send_discord_notification(self.submission))
                self.assert_private_data_absent(logs, stdout, stderr, 'failed')
                self.assertEqual(logs.records[0].error_type, error.__name__)


class ContactWebhookFailureTests(WebhookLogAssertions, TestCase):
    def test_webhook_failure_preserves_the_submission_and_success_response(self):
        cache.clear()
        self.addCleanup(cache.clear)
        stdout, stderr = StringIO(), StringIO()
        with (
            patch.dict(os.environ, {'DISCORD_WEBHOOK_URL': WEBHOOK_URL}),
            patch('home.views.verify_turnstile', return_value=True),
            patch('home.views.requests.post', side_effect=requests.Timeout(' '.join(PRIVATE_VALUES))),
            self.assertLogs('home.views', level='WARNING') as logs,
            redirect_stdout(stdout), redirect_stderr(stderr),
        ):
            response = self.client.post(reverse('contact_submit'), {
                'name': 'Synthetic Sender', 'email': 'sender@example.invalid',
                'subject': 'Synthetic private subject', 'message': 'Synthetic private message',
                'cf-turnstile-response': 'synthetic-token',
            }, REMOTE_ADDR='192.0.2.44', HTTP_USER_AGENT='synthetic-private-user-agent')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        submission = ContactSubmission.objects.get()
        self.assertEqual(submission.email, 'sender@example.invalid')
        self.assertEqual(submission.message, 'Synthetic private message')
        self.assertEqual(submission.ip_address, '192.0.2.44')
        self.assertEqual(submission.user_agent, 'synthetic-private-user-agent')
        self.assertIn('last_contact_submission', self.client.session)
        self.assert_private_data_absent(logs, stdout, stderr, 'failed')
