"""Contact behavior and regression tests."""
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from ..models import ContactSubmission


@override_settings(TURNSTILE_SITE_KEY='test-site-key', TURNSTILE_SECRET_KEY='test-secret-key')
class ContactSubmissionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.siteverify = self.enterContext(patch('home.views.requests.post'))
        self.siteverify.return_value.json.return_value = {
            'success': True, 'hostname': 'cbergane.se', 'action': 'contact',
        }

    def valid_payload(self):
        return {
            'name': 'Ada Lovelace',
            'email': 'ada@example.com',
            'subject': 'Systems review',
            'message': 'I would like to discuss a systems review.',
            'cf-turnstile-response': 'test-token',
        }

    @patch('home.views.send_discord_notification')
    def test_valid_contact_submission_is_stored_and_notified(self, notify):
        response = self.client.post(
            reverse('contact_submit'),
            self.valid_payload(),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)
        submission = ContactSubmission.objects.get()
        self.assertEqual(submission.email, 'ada@example.com')
        notify.assert_called_once_with(submission)
        self.assertIn('last_contact_submission', self.client.session)
        self.siteverify.assert_called_once_with(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={'secret': 'test-secret-key', 'response': 'test-token', 'remoteip': '127.0.0.1'},
            timeout=5,
        )

    @patch('home.views.send_discord_notification')
    def test_short_message_returns_errors_without_creating_submission(self, notify):
        payload = self.valid_payload()
        payload['message'] = 'Too short'

        response = self.client.post(
            reverse('contact_submit'),
            payload,
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['success'], False)
        self.assertIn('message', response.json()['errors'])
        self.siteverify.assert_not_called()
        self.assertFalse(ContactSubmission.objects.exists())
        notify.assert_not_called()

    @patch('home.views.send_discord_notification')
    def test_trusted_proxy_uses_forwarded_client_ip(self, notify):
        response = self.client.post(
            reverse('contact_submit'),
            self.valid_payload(),
            secure=True,
            REMOTE_ADDR='10.89.0.4',
            HTTP_X_FORWARDED_FOR='203.0.113.10, 10.89.0.1',
        )

        self.assertEqual(response.status_code, 200)
        submission = ContactSubmission.objects.get()
        self.assertEqual(submission.ip_address, '203.0.113.10')
        self.assertEqual(self.siteverify.call_args.kwargs['data']['remoteip'], '203.0.113.10')
        notify.assert_called_once_with(submission)

    @patch('home.views.send_discord_notification')
    def test_untrusted_client_cannot_spoof_forwarded_ip(self, notify):
        response = self.client.post(
            reverse('contact_submit'),
            self.valid_payload(),
            secure=True,
            REMOTE_ADDR='198.51.100.25',
            HTTP_X_FORWARDED_FOR='203.0.113.99',
        )

        self.assertEqual(response.status_code, 200)
        submission = ContactSubmission.objects.get()
        self.assertEqual(submission.ip_address, '198.51.100.25')
        self.assertEqual(self.siteverify.call_args.kwargs['data']['remoteip'], '198.51.100.25')
        notify.assert_called_once_with(submission)

    @patch('home.views.send_discord_notification')
    def test_trusted_proxy_ignores_spoofed_leftmost_forwarded_ip(self, notify):
        response = self.client.post(
            reverse('contact_submit'),
            self.valid_payload(),
            secure=True,
            REMOTE_ADDR='10.89.0.4',
            HTTP_X_FORWARDED_FOR=(
                '192.0.2.123, 203.0.113.10, 10.89.0.1'
            ),
        )

        self.assertEqual(response.status_code, 200)
        submission = ContactSubmission.objects.get()
        self.assertEqual(submission.ip_address, '203.0.113.10')
        self.assertEqual(self.siteverify.call_args.kwargs['data']['remoteip'], '203.0.113.10')
        notify.assert_called_once_with(submission)

    @patch('home.views.send_discord_notification')
    def test_url_in_name_is_rejected(self, notify):
        payload = self.valid_payload()
        payload['name'] = 'Dear http://cbergane.se/fekal0911 Admin'

        response = self.client.post(
            reverse('contact_submit'),
            payload,
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['success'], False)
        self.assertIn('name', response.json()['errors'])
        self.assertFalse(ContactSubmission.objects.exists())
        notify.assert_not_called()

    @patch('home.views.send_discord_notification')
    def test_honeypot_is_silently_discarded(self, notify):
        payload = self.valid_payload()
        payload['website'] = 'https://spam.example/'
        payload.pop('cf-turnstile-response')

        response = self.client.post(
            reverse('contact_submit'),
            payload,
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)
        self.assertFalse(ContactSubmission.objects.exists())
        notify.assert_not_called()
        self.siteverify.assert_not_called()

    @patch('home.views.send_discord_notification')
    def test_rate_limit_is_per_real_client_ip(self, notify):
        url = reverse('contact_submit')

        for _ in range(3):
            client = Client()
            response = client.post(
                url,
                self.valid_payload(),
                secure=True,
                REMOTE_ADDR='10.89.0.4',
                HTTP_X_FORWARDED_FOR='203.0.113.20, 10.89.0.1',
            )
            self.assertEqual(response.status_code, 200)

        fourth_client = Client()
        response = fourth_client.post(
            url,
            self.valid_payload(),
            secure=True,
            REMOTE_ADDR='10.89.0.4',
            HTTP_X_FORWARDED_FOR='203.0.113.20, 10.89.0.1',
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(ContactSubmission.objects.count(), 3)
        self.assertEqual(self.siteverify.call_count, 3)

        other_client = Client()
        response = other_client.post(
            url,
            self.valid_payload(),
            secure=True,
            REMOTE_ADDR='10.89.0.4',
            HTTP_X_FORWARDED_FOR='203.0.113.21, 10.89.0.1',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactSubmission.objects.count(), 4)
        self.assertEqual(self.siteverify.call_count, 4)

    def assert_verification_rejected(self, payload=None):
        with patch('home.views.send_discord_notification') as notify:
            response = self.client.post(
                reverse('contact_submit'),
                self.valid_payload() if payload is None else payload,
                secure=True,
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {
            'success': False,
            'errors': {'__all__': ['Verification failed. Please try again.']},
        })
        self.assertFalse(ContactSubmission.objects.exists())
        self.assertNotIn('last_contact_submission', self.client.session)
        notify.assert_not_called()

    def test_missing_token_is_rejected_without_siteverify(self):
        payload = self.valid_payload()
        payload.pop('cf-turnstile-response')
        self.assert_verification_rejected(payload)
        self.siteverify.assert_not_called()

    def test_blank_or_oversized_tokens_are_rejected_without_siteverify(self):
        for token in ('   ', 'x' * 2049):
            with self.subTest(token_length=len(token)):
                payload = self.valid_payload()
                payload['cf-turnstile-response'] = token
                self.assert_verification_rejected(payload)
        self.siteverify.assert_not_called()

    @override_settings(TURNSTILE_SECRET_KEY='')
    def test_missing_secret_fails_closed_without_siteverify(self):
        self.assert_verification_rejected()
        self.siteverify.assert_not_called()

    def test_unsuccessful_challenge_is_rejected(self):
        self.siteverify.return_value.json.return_value = {
            'success': False, 'error-codes': ['timeout-or-duplicate'],
        }
        self.assert_verification_rejected()

    def test_incorrect_hostname_is_rejected(self):
        self.siteverify.return_value.json.return_value['hostname'] = 'www.cbergane.se'
        self.assert_verification_rejected()

    def test_incorrect_action_is_rejected(self):
        self.siteverify.return_value.json.return_value['action'] = 'login'
        self.assert_verification_rejected()

    def test_timeout_fails_closed(self):
        self.siteverify.side_effect = requests.Timeout('private upstream details')
        self.assert_verification_rejected()

    def test_network_error_fails_closed(self):
        self.siteverify.side_effect = requests.ConnectionError('private upstream details')
        self.assert_verification_rejected()

    def test_http_error_fails_closed(self):
        self.siteverify.return_value.raise_for_status.side_effect = requests.HTTPError('503')
        self.assert_verification_rejected()

    def test_invalid_json_fails_closed(self):
        self.siteverify.return_value.json.side_effect = ValueError('invalid upstream JSON')
        self.assert_verification_rejected()

    def test_malformed_response_shapes_and_missing_claims_fail_closed(self):
        for result in (None, [], 'success', {}, {'success': True},
                       {'success': True, 'hostname': 'cbergane.se'},
                       {'success': True, 'action': 'contact'},
                       {'success': 'true', 'hostname': 'cbergane.se', 'action': 'contact'},
                       {'success': 1, 'hostname': 'cbergane.se', 'action': 'contact'}):
            with self.subTest(result=result):
                cache.clear()
                self.siteverify.return_value.json.return_value = result
                self.assert_verification_rejected()

    @patch('home.views.send_discord_notification')
    def test_session_cooldown_skips_siteverify(self, notify):
        url = reverse('contact_submit')
        self.assertEqual(self.client.post(url, self.valid_payload(), secure=True).status_code, 200)
        response = self.client.post(url, self.valid_payload(), secure=True)
        self.assertEqual(response.status_code, 429)
        self.assertIn('Please wait', response.json()['errors']['__all__'][0])
        self.assertEqual(ContactSubmission.objects.count(), 1)
        self.siteverify.assert_called_once()
        notify.assert_called_once()

    @patch('home.views.send_discord_notification')
    def test_failed_verification_can_retry_with_new_token(self, notify):
        self.siteverify.return_value.json.return_value['success'] = False
        self.assert_verification_rejected()
        self.siteverify.return_value.json.return_value['success'] = True
        payload = self.valid_payload()
        payload['cf-turnstile-response'] = 'fresh-test-token'
        response = self.client.post(reverse('contact_submit'), payload, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactSubmission.objects.count(), 1)
        self.assertEqual(self.siteverify.call_args.kwargs['data']['response'], 'fresh-test-token')
        notify.assert_called_once()
