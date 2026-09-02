"""
Brevo integration: the email backend, contact sync and campaigns.

The API is mocked throughout — these assert the contract around Brevo (which
backend is chosen, who may send a campaign, what happens when Brevo is down),
not Brevo's own behaviour.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.newsletter.brevo import BrevoError
from apps.newsletter.models import Campaign, NewsletterSubscriber

User = get_user_model()

WITH_BREVO = override_settings(
    BREVO_API_KEY='test-key',
    EMAIL_BACKEND='apps.newsletter.backends.BrevoEmailBackend',
)


def make_user(email='a@example.com', username='admin', role='admin'):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Ada', last_name='Lovelace', is_verified=True, role=role,
    )


class BackendSelectionTests(APITestCase):
    def test_the_console_backend_is_used_without_credentials(self):
        """A fresh checkout must run and show you the emails."""
        from django.conf import settings

        if not settings.BREVO_API_KEY and not settings.EMAIL_HOST_USER:
            self.assertIn('console', settings.EMAIL_BACKEND)

    @WITH_BREVO
    @patch('apps.newsletter.backends.send_transactional', return_value='msg-1')
    def test_brevo_sends_ordinary_django_mail(self, mocked):
        """Existing send_mail calls route through Brevo with no change."""
        sent = mail.send_mail('Subject', 'Body', 'from@example.com', ['to@example.com'])
        self.assertEqual(sent, 1)
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs['to_email'], 'to@example.com')

    @WITH_BREVO
    @patch('apps.newsletter.backends.send_transactional', side_effect=BrevoError('down'))
    def test_a_brevo_outage_does_not_raise_when_silenced(self, mocked):
        sent = mail.send_mail('S', 'B', 'f@example.com', ['t@example.com'],
                              fail_silently=True)
        self.assertEqual(sent, 0)

    @WITH_BREVO
    @patch('apps.newsletter.backends.send_transactional', return_value='msg-1')
    def test_each_recipient_is_sent_separately(self, mocked):
        """One address per call, so a bad one cannot spoil the batch."""
        mail.send_mail('S', 'B', 'f@example.com', ['a@example.com', 'b@example.com'])
        self.assertEqual(mocked.call_count, 2)


class ContactSyncTests(APITestCase):
    @WITH_BREVO
    @patch('apps.newsletter.brevo.upsert_contact')
    def test_confirming_adds_the_contact_to_brevo(self, mocked):
        subscriber = NewsletterSubscriber.objects.create(email='r@example.com')
        response = self.client.post('/api/newsletter/confirm/',
                                    {'token': subscriber.token}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mocked.assert_called_once_with('r@example.com')

    @WITH_BREVO
    @patch('apps.newsletter.brevo.upsert_contact', side_effect=BrevoError('down'))
    def test_a_brevo_failure_still_confirms_locally(self, mocked):
        """The local record is authoritative; Brevo can be re-synced later."""
        subscriber = NewsletterSubscriber.objects.create(email='r@example.com')
        response = self.client.post('/api/newsletter/confirm/',
                                    {'token': subscriber.token}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        subscriber.refresh_from_db()
        self.assertTrue(subscriber.is_confirmed)

    @WITH_BREVO
    @patch('apps.newsletter.brevo.remove_from_list')
    def test_unsubscribing_removes_them_from_brevo(self, mocked):
        subscriber = NewsletterSubscriber.objects.create(email='r@example.com')
        subscriber.confirm()
        self.client.post('/api/newsletter/unsubscribe/',
                         {'token': subscriber.token}, format='json')
        mocked.assert_called_once_with('r@example.com')


class CampaignTests(APITestCase):
    def setUp(self):
        self.admin = make_user()
        self.reader = make_user('r@example.com', 'reader', role='author')
        self.campaign = Campaign.objects.create(
            name='March', subject='What we published', html='<p>' + 'x' * 40 + '</p>',
        )

    def test_campaigns_are_staff_only(self):
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/newsletter/campaigns/').status_code,
                         status.HTTP_403_FORBIDDEN)

    def test_staff_can_list_campaigns(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/newsletter/campaigns/')
        self.assertEqual(response.data['count'], 1)

    def test_creating_a_draft_records_the_author(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post('/api/newsletter/campaigns/', {
            'name': 'April', 'subject': 'Hello', 'html': '<p>' + 'y' * 40 + '</p>',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Campaign.objects.get(name='April').created_by, self.admin)

    def test_an_empty_body_is_rejected(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post('/api/newsletter/campaigns/', {
            'name': 'Empty', 'subject': 'Hi', 'html': ' ',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(BREVO_API_KEY='')
    def test_sending_without_brevo_says_so(self):
        NewsletterSubscriber.objects.create(email='r@example.com').confirm()
        self.client.force_authenticate(self.admin)
        response = self.client.post(f'/api/newsletter/campaigns/{self.campaign.id}/send/')
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @WITH_BREVO
    def test_sending_with_no_subscribers_is_refused(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(f'/api/newsletter/campaigns/{self.campaign.id}/send/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('no confirmed subscribers', response.data['detail'])

    @WITH_BREVO
    @patch('apps.newsletter.brevo.send_campaign')
    @patch('apps.newsletter.brevo.create_campaign', return_value={'id': 42})
    def test_a_successful_send(self, created, sent):
        NewsletterSubscriber.objects.create(email='r@example.com').confirm()
        self.client.force_authenticate(self.admin)

        response = self.client.post(f'/api/newsletter/campaigns/{self.campaign.id}/send/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, 'sent')
        self.assertEqual(self.campaign.provider_campaign_id, '42')
        self.assertIsNotNone(self.campaign.sent_at)
        sent.assert_called_once_with(42)

    @WITH_BREVO
    @patch('apps.newsletter.brevo.create_campaign', side_effect=BrevoError('rejected'))
    def test_a_failed_send_is_recorded_as_failed(self, mocked):
        NewsletterSubscriber.objects.create(email='r@example.com').confirm()
        self.client.force_authenticate(self.admin)

        response = self.client.post(f'/api/newsletter/campaigns/{self.campaign.id}/send/')
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, 'failed')

    @WITH_BREVO
    def test_a_campaign_cannot_be_sent_twice(self):
        self.campaign.status = Campaign.Status.SENT
        self.campaign.save()
        self.client.force_authenticate(self.admin)
        response = self.client.post(f'/api/newsletter/campaigns/{self.campaign.id}/send/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_sent_campaign_cannot_be_edited(self):
        """The emails are already in inboxes; the record must match them."""
        self.campaign.status = Campaign.Status.SENT
        self.campaign.save()
        self.client.force_authenticate(self.admin)
        response = self.client.patch(f'/api/newsletter/campaigns/{self.campaign.id}/',
                                     {'subject': 'Rewritten'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_sent_campaign_cannot_be_deleted(self):
        self.campaign.status = Campaign.Status.SENT
        self.campaign.save()
        self.client.force_authenticate(self.admin)
        response = self.client.delete(f'/api/newsletter/campaigns/{self.campaign.id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CampaignStatsTests(APITestCase):
    def setUp(self):
        self.admin = make_user()
        self.campaign = Campaign.objects.create(
            name='March', subject='S', html='<p>' + 'x' * 40 + '</p>',
            status=Campaign.Status.SENT, provider_campaign_id='42',
        )

    @WITH_BREVO
    @patch('apps.newsletter.brevo.campaign_stats')
    def test_stats_are_fetched_and_stored(self, mocked):
        mocked.return_value = {
            'status': 'sent', 'sent': 100, 'delivered': 98,
            'opens': 49, 'clicks': 10, 'open_rate': 50.0, 'click_rate': 10.2,
        }
        self.client.force_authenticate(self.admin)
        response = self.client.get(f'/api/newsletter/campaigns/{self.campaign.id}/stats/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['open_rate'], 50.0)
        self.assertEqual(response.data['click_rate'], 10.2)

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.stats['delivered'], 98)
        self.assertIsNotNone(self.campaign.stats_updated_at)

    @WITH_BREVO
    @patch('apps.newsletter.brevo.campaign_stats', side_effect=BrevoError('down'))
    def test_stale_figures_are_kept_when_brevo_is_down(self, mocked):
        """Stale numbers beat an error page."""
        self.campaign.stats = {'open_rate': 33.3}
        self.campaign.save()

        self.client.force_authenticate(self.admin)
        response = self.client.get(f'/api/newsletter/campaigns/{self.campaign.id}/stats/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['open_rate'], 33.3)

    def test_a_draft_has_no_stats_to_fetch(self):
        draft = Campaign.objects.create(name='D', subject='S', html='<p>' + 'x' * 40 + '</p>')
        self.assertEqual(draft.refresh_stats(), {})

    def test_stats_are_staff_only(self):
        reader = make_user('r@example.com', 'reader', role='author')
        self.client.force_authenticate(reader)
        response = self.client.get(f'/api/newsletter/campaigns/{self.campaign.id}/stats/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
