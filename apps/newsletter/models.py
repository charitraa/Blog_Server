import logging
import secrets
import uuid

from django.db import models
from django.utils import timezone


class NewsletterSubscriber(models.Model):
    """
    An email address subscribed to the newsletter.

    Double opt-in: subscribing stores the address as unconfirmed and emails a
    link. Only a confirmed row should ever receive a send. Every row carries an
    unguessable token used for both confirming and unsubscribing, so neither
    action needs the person to have an account.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    is_confirmed = models.BooleanField(default=False)
    # Set when someone unsubscribes; the row is kept so a later resubscribe
    # cannot be used to spam an address that asked to be left alone.
    is_active = models.BooleanField(default=True)
    token = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['is_confirmed', 'is_active']),
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.lower().strip()
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def confirm(self):
        if not self.is_confirmed:
            self.is_confirmed = True
            self.confirmed_at = timezone.now()
        self.is_active = True
        self.unsubscribed_at = None
        self.save(update_fields=['is_confirmed', 'confirmed_at', 'is_active', 'unsubscribed_at'])

    def unsubscribe(self):
        self.is_active = False
        self.unsubscribed_at = timezone.now()
        self.save(update_fields=['is_active', 'unsubscribed_at'])


class Campaign(models.Model):
    """
    One newsletter send.

    Brevo owns the sending and the statistics; this row is the local record of
    what was sent, when, and which Brevo campaign to ask for figures. Keeping
    the id here is what lets open and click rates be shown in the admin
    dashboard instead of on a separate website.
    """

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, help_text='Internal name. Readers never see it.')
    subject = models.CharField(max_length=200)
    html = models.TextField(help_text='The email body.')

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    # Brevo's id for this campaign. Null until it has been created there.
    provider_campaign_id = models.CharField(max_length=64, blank=True, null=True, unique=True)

    created_by = models.ForeignKey(
        'user.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='campaigns',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    # Last figures fetched from Brevo, so the dashboard has something to show
    # without calling the API on every page load.
    stats = models.JSONField(default=dict, blank=True)
    stats_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f'{self.name} ({self.status})'

    @property
    def open_rate(self):
        return (self.stats or {}).get('open_rate', 0.0)

    @property
    def click_rate(self):
        return (self.stats or {}).get('click_rate', 0.0)

    def refresh_stats(self):
        """Pull the latest figures from Brevo. Safe to call on a draft."""
        from .brevo import BrevoError, campaign_stats

        if not self.provider_campaign_id:
            return self.stats

        try:
            self.stats = campaign_stats(self.provider_campaign_id)
        except BrevoError:
            # Stale numbers beat an error page; the caller can try again.
            logging.getLogger('apps.newsletter').exception(
                'Could not refresh stats for campaign %s', self.pk,
            )
            return self.stats

        self.stats_updated_at = timezone.now()
        self.save(update_fields=['stats', 'stats_updated_at'])
        return self.stats
