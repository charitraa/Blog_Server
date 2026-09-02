"""
reCAPTCHA verification and the endpoints it guards.

Google is mocked throughout — these assert our handling of each answer it can
give, including the two judgement calls: failing open when the verifier is
unreachable, and treating a missing score as a v2 pass rather than a zero.
"""

from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, override_settings
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from blog_server import captcha

User = get_user_model()

WITH_CAPTCHA = override_settings(
    RECAPTCHA_ENABLED=True,
    RECAPTCHA_SECRET_KEY='test-secret',
    RECAPTCHA_SITE_KEY='test-site-key',
    RECAPTCHA_MIN_SCORE=0.5,
)
NO_VERIFICATION = override_settings(REQUIRE_EMAIL_VERIFICATION=False)


def google_says(payload, ok=True):
    response = Mock()
    response.status_code = 200 if ok else 500
    response.json.return_value = payload
    return response


class EnabledTests(APITestCase):
    def test_disabled_without_a_secret(self):
        with override_settings(RECAPTCHA_SECRET_KEY=''):
            self.assertFalse(captcha.is_enabled())

    @WITH_CAPTCHA
    def test_enabled_with_a_secret(self):
        self.assertTrue(captcha.is_enabled())

    @override_settings(RECAPTCHA_ENABLED=False, RECAPTCHA_SECRET_KEY='x')
    def test_the_switch_overrides_a_present_secret(self):
        self.assertFalse(captcha.is_enabled())

    def test_verification_passes_when_disabled(self):
        with override_settings(RECAPTCHA_SECRET_KEY=''):
            ok, reason = captcha.verify('')
            self.assertTrue(ok)
            self.assertEqual(reason, 'disabled')


@WITH_CAPTCHA
class VerifyTests(APITestCase):
    def test_a_missing_token_fails_without_calling_google(self):
        with patch('blog_server.captcha.requests.post') as mocked:
            ok, reason = captcha.verify('')
            self.assertFalse(ok)
            self.assertEqual(reason, 'missing-token')
            mocked.assert_not_called()

    @patch('blog_server.captcha.requests.post')
    def test_a_v2_success_has_no_score_and_passes(self, mocked):
        mocked.return_value = google_says({'success': True})
        ok, reason = captcha.verify('token')
        self.assertTrue(ok)
        self.assertEqual(reason, 'ok')

    @patch('blog_server.captcha.requests.post')
    def test_a_good_v3_score_passes(self, mocked):
        mocked.return_value = google_says({'success': True, 'score': 0.9})
        self.assertTrue(captcha.verify('token')[0])

    @patch('blog_server.captcha.requests.post')
    def test_a_low_v3_score_fails(self, mocked):
        mocked.return_value = google_says({'success': True, 'score': 0.1})
        ok, reason = captcha.verify('token')
        self.assertFalse(ok)
        self.assertIn('low-score', reason)

    @patch('blog_server.captcha.requests.post')
    def test_a_score_exactly_at_the_threshold_passes(self, mocked):
        mocked.return_value = google_says({'success': True, 'score': 0.5})
        self.assertTrue(captcha.verify('token')[0])

    @patch('blog_server.captcha.requests.post')
    def test_a_rejected_token_fails(self, mocked):
        mocked.return_value = google_says({
            'success': False, 'error-codes': ['invalid-input-response'],
        })
        ok, reason = captcha.verify('token')
        self.assertFalse(ok)
        self.assertIn('invalid-input-response', reason)

    @patch('blog_server.captcha.requests.post')
    def test_our_own_bad_secret_is_logged_as_an_error(self, mocked):
        mocked.return_value = google_says({
            'success': False, 'error-codes': ['invalid-input-secret'],
        })
        with self.assertLogs('django', level='ERROR') as logs:
            ok, _ = captcha.verify('token')
        self.assertFalse(ok)
        self.assertTrue(any('secret key' in line for line in logs.output))

    @patch('blog_server.captcha.requests.post', side_effect=Exception('boom'))
    def test_an_unexpected_error_does_not_escape(self, mocked):
        """Any failure here must not become a 500 on somebody's sign-up."""
        with self.assertRaises(Exception):
            captcha.verify('token')

    @patch('blog_server.captcha.requests.post')
    def test_it_fails_open_when_google_is_unreachable(self, mocked):
        """
        A CAPTCHA outage must not become a site outage.

        The throttles still apply, so failing open costs far less than locking
        every visitor out of registering.
        """
        import requests as real_requests

        mocked.side_effect = real_requests.RequestException('down')
        ok, reason = captcha.verify('token')
        self.assertTrue(ok)
        self.assertEqual(reason, 'verifier-unreachable')

    @patch('blog_server.captcha.requests.post')
    def test_it_fails_open_on_a_verifier_error(self, mocked):
        mocked.return_value = google_says({}, ok=False)
        self.assertTrue(captcha.verify('token')[0])

    @patch('blog_server.captcha.requests.post')
    def test_the_client_ip_is_forwarded_as_a_hint(self, mocked):
        mocked.return_value = google_says({'success': True})
        captcha.verify('token', '203.0.113.9')
        self.assertEqual(mocked.call_args.kwargs['data']['remoteip'], '203.0.113.9')

    def test_client_ip_prefers_the_forwarded_header(self):
        request = RequestFactory().get('/', HTTP_X_FORWARDED_FOR='203.0.113.9, 10.0.0.1')
        self.assertEqual(captcha.client_ip(request), '203.0.113.9')

    def test_client_ip_falls_back_to_remote_addr(self):
        request = RequestFactory().get('/', REMOTE_ADDR='198.51.100.4')
        self.assertEqual(captcha.client_ip(request), '198.51.100.4')

    @patch('blog_server.captcha.requests.post')
    def test_check_raises_a_validation_error_with_neutral_wording(self, mocked):
        mocked.return_value = google_says({'success': False, 'error-codes': ['timeout-or-duplicate']})
        request = RequestFactory().post('/api/auth/register/')
        with self.assertRaises(ValidationError) as caught:
            captcha.check(request, 'token')
        # The reason goes to the log, never to the response — telling a bot why
        # it failed is free tuning advice.
        self.assertNotIn('timeout-or-duplicate', str(caught.exception.detail))


class SiteConfigTests(APITestCase):
    def test_the_config_endpoint_is_public(self):
        self.assertEqual(self.client.get('/api/config/').status_code, status.HTTP_200_OK)

    @WITH_CAPTCHA
    def test_it_exposes_the_site_key_but_never_the_secret(self):
        body = self.client.get('/api/config/').json()
        self.assertTrue(body['recaptcha_enabled'])
        self.assertEqual(body['recaptcha_site_key'], 'test-site-key')
        self.assertNotIn('test-secret', str(body))
        self.assertNotIn('secret', str(body).lower())

    @override_settings(RECAPTCHA_SECRET_KEY='', RECAPTCHA_SITE_KEY='leftover-key')
    def test_no_site_key_is_offered_when_the_guard_is_off(self):
        """Rendering a widget the server will not check would be theatre."""
        body = self.client.get('/api/config/').json()
        self.assertFalse(body['recaptcha_enabled'])
        self.assertEqual(body['recaptcha_site_key'], '')


@WITH_CAPTCHA
@NO_VERIFICATION
class GuardedEndpointTests(APITestCase):
    REGISTRATION = {
        'first_name': 'Ada', 'last_name': 'Lovelace',
        'email': 'new@example.com', 'password': 'StrongPass!234',
        'confirm_password': 'StrongPass!234',
    }

    @patch('blog_server.captcha.requests.post')
    def test_registration_is_refused_without_a_captcha(self, mocked):
        mocked.return_value = google_says({'success': False, 'error-codes': ['missing']})
        response = self.client.post('/api/auth/register/', self.REGISTRATION, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('captcha', response.data)
        self.assertFalse(User.objects.filter(email='new@example.com').exists())

    @patch('blog_server.captcha.requests.post')
    def test_registration_succeeds_with_a_valid_one(self, mocked):
        mocked.return_value = google_says({'success': True})
        response = self.client.post(
            '/api/auth/register/', {**self.REGISTRATION, 'captcha': 'token'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email='new@example.com').exists())

    @patch('blog_server.captcha.requests.post')
    def test_the_captcha_is_checked_before_field_validation(self, mocked):
        """Otherwise the field errors would reveal which emails are taken."""
        mocked.return_value = google_says({'success': False, 'error-codes': ['missing']})
        response = self.client.post('/api/auth/register/', {}, format='json')
        self.assertEqual(list(response.data.keys()), ['captcha', 'status_code'])

    @patch('blog_server.captcha.requests.post')
    def test_password_reset_is_guarded(self, mocked):
        mocked.return_value = google_says({'success': False, 'error-codes': ['missing']})
        response = self.client.post('/api/auth/password-reset/',
                                    {'email': 'a@example.com'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('blog_server.captcha.requests.post')
    def test_newsletter_subscribe_is_guarded(self, mocked):
        mocked.return_value = google_says({'success': False, 'error-codes': ['missing']})
        response = self.client.post('/api/newsletter/subscribe/',
                                    {'email': 'a@example.com'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('blog_server.captcha.requests.post')
    def test_sign_in_is_deliberately_not_guarded(self, mocked):
        """A throttle covers password guessing; a puzzle would cost more than it saves."""
        mocked.return_value = google_says({'success': False, 'error-codes': ['missing']})
        User.objects.create_user(
            email='known@example.com', username='known', password='StrongPass!234',
            first_name='K', last_name='N', is_verified=True,
        )
        response = self.client.post('/api/auth/login/', {
            'email': 'known@example.com', 'password': 'StrongPass!234',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
