"""Newsletter double opt-in tests."""

from django.core import mail
from rest_framework import status
from rest_framework.test import APITestCase

from .models import NewsletterSubscriber


class NewsletterTests(APITestCase):
    def test_subscribe_creates_an_unconfirmed_row_and_emails(self):
        response = self.client.post('/api/newsletter/subscribe/',
                                    {'email': 'reader@example.com'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        subscriber = NewsletterSubscriber.objects.get(email='reader@example.com')
        self.assertFalse(subscriber.is_confirmed)
        self.assertEqual(len(mail.outbox), 1)

    def test_confirm_activates_the_subscription(self):
        self.client.post('/api/newsletter/subscribe/', {'email': 'reader@example.com'}, format='json')
        subscriber = NewsletterSubscriber.objects.get(email='reader@example.com')

        response = self.client.post('/api/newsletter/confirm/',
                                    {'token': subscriber.token}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        subscriber.refresh_from_db()
        self.assertTrue(subscriber.is_confirmed)

    def test_unsubscribe_deactivates_without_deleting(self):
        self.client.post('/api/newsletter/subscribe/', {'email': 'reader@example.com'}, format='json')
        subscriber = NewsletterSubscriber.objects.get(email='reader@example.com')
        subscriber.confirm()

        response = self.client.post('/api/newsletter/unsubscribe/',
                                    {'token': subscriber.token}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        subscriber.refresh_from_db()
        self.assertFalse(subscriber.is_active)
        self.assertTrue(NewsletterSubscriber.objects.filter(email='reader@example.com').exists())

    def test_subscribing_twice_does_not_duplicate(self):
        for _ in range(2):
            self.client.post('/api/newsletter/subscribe/', {'email': 'reader@example.com'}, format='json')
        self.assertEqual(NewsletterSubscriber.objects.filter(email='reader@example.com').count(), 1)

    def test_confirmed_address_is_not_re_emailed(self):
        self.client.post('/api/newsletter/subscribe/', {'email': 'reader@example.com'}, format='json')
        NewsletterSubscriber.objects.get(email='reader@example.com').confirm()
        mail.outbox.clear()

        self.client.post('/api/newsletter/subscribe/', {'email': 'reader@example.com'}, format='json')
        self.assertEqual(len(mail.outbox), 0)

    def test_bad_token_is_rejected(self):
        response = self.client.post('/api/newsletter/confirm/', {'token': 'nope'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_email_is_rejected(self):
        response = self.client.post('/api/newsletter/subscribe/', {'email': 'not-an-email'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
