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
