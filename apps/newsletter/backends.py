"""
A Django email backend that sends through Brevo's API.

Slotting in at the backend layer means every existing `send_mail` call —
verification codes, password resets, newsletter confirmations — goes through
Brevo without a single call site changing.

Why the API rather than Brevo's SMTP relay: the API returns a message id per
send, which is what turns "I never got the code" into something you can
actually look up.
"""

import logging

from django.core.mail.backends.base import BaseEmailBackend

from .brevo import BrevoError, is_configured, send_transactional

logger = logging.getLogger('apps.newsletter')


class BrevoEmailBackend(BaseEmailBackend):
    """
    Sends via Brevo, honouring `fail_silently` like every Django backend.

    Callers in this project already wrap sends in try/except and treat a
    failure as non-fatal, so a Brevo outage degrades to "the email did not
    arrive" rather than a 500 in someone's face.
    """

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        if not is_configured():
            if not self.fail_silently:
                raise BrevoError('Brevo is not configured on this server.')
            logger.error('Brevo backend is selected but BREVO_API_KEY is not set.')
            return 0

        sent = 0
        for message in email_messages:
            # An HTML alternative is used when one was attached; otherwise
            # Brevo receives the plain text alone.
            html = None
            for content, mimetype in getattr(message, 'alternatives', []) or []:
                if mimetype == 'text/html':
                    html = content
                    break

            # Deliberately NOT message.from_email. Brevo only accepts a
            # sender address that has been verified in the account, and
            # DEFAULT_FROM_EMAIL is usually whatever the SMTP fallback would
            # send as -- a different address entirely. Passing that through
            # earns a 400 on every send, so the verified sender configured for
            # Brevo wins, and `send_transactional` fills it in from
            # BREVO_SENDER_EMAIL when it is None.
            sender = None

            for recipient in message.recipients():
                try:
                    send_transactional(
                        subject=message.subject,
                        text=message.body,
                        to_email=recipient,
                        html=html,
                        sender=sender,
                    )
                    sent += 1
                except BrevoError:
                    # One bad address must not stop the rest of the batch.
                    logger.exception('Brevo could not send to a recipient.')
                    if not self.fail_silently:
                        raise

        return sent
