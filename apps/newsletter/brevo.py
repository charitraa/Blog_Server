"""
Brevo (formerly Sendinblue) API client.

Used through `requests` rather than the vendor SDK: the three endpoints this
project needs are trivial, and the SDK pulls dependencies for features we do
not use. This also keeps it in the same shape as `apps/ai/client.py`.

Two distinct jobs live here:

  * **Transactional mail** — verification codes, password resets. These go
    through Brevo so they are actually delivered and traceable, rather than
    landing in spam from a bare SMTP server.
  * **Campaigns** — the newsletter. Open and click rates are only possible
    because Brevo does the sending; a plain SMTP server cannot report them,
    since tracking requires rewriting links and embedding a pixel.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger('apps.newsletter')

BASE_URL = 'https://api.brevo.com/v3'
TIMEOUT = 30


class BrevoError(Exception):
    """Brevo refused or could not be reached."""


def is_configured():
    return bool(settings.BREVO_API_KEY)


def _headers():
    return {
        'api-key': settings.BREVO_API_KEY,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def _request(method, path, **kwargs):
    if not is_configured():
        raise BrevoError('Brevo is not configured on this server.')

    try:
        response = requests.request(
            method, f'{BASE_URL}{path}', headers=_headers(), timeout=TIMEOUT, **kwargs,
        )
    except requests.RequestException as exc:
        logger.warning('Brevo unreachable on %s %s: %s', method, path, exc)
        raise BrevoError('The email service could not be reached.') from exc

    if response.status_code == 401:
        # Never logged with the key itself.
        logger.error('Brevo rejected our API key.')
        raise BrevoError('The email service credentials are not valid.')

    if response.status_code >= 400:
        logger.warning('Brevo %s %s returned %s: %s',
                       method, path, response.status_code, response.text[:300])
        raise BrevoError('The email service returned an error.')

    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


# ---------------------------------------------------------------------------
# Transactional mail
# ---------------------------------------------------------------------------

def send_transactional(subject, text, to_email, to_name='', html=None, sender=None):
    """
    One transactional email. Returns Brevo's message id.

    The message id is worth keeping: it is what turns "the user says they never
    got the code" into something answerable.
    """
    sender = sender or {
        'email': settings.BREVO_SENDER_EMAIL or settings.DEFAULT_FROM_EMAIL,
        'name': settings.BREVO_SENDER_NAME or settings.SITE_NAME,
    }

    payload = {
        'sender': sender,
        'to': [{'email': to_email, **({'name': to_name} if to_name else {})}],
        'subject': subject,
        'textContent': text,
    }
    if html:
        payload['htmlContent'] = html

    body = _request('POST', '/smtp/email', json=payload)
    return body.get('messageId')


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

def upsert_contact(email, list_ids=None, attributes=None):
    """
    Add or update a contact.

    `updateEnabled` means a second call for a known address updates it rather
    than failing, so confirming twice is harmless.
    """
    payload = {
        'email': email,
        'updateEnabled': True,
        'listIds': list_ids or ([settings.BREVO_LIST_ID] if settings.BREVO_LIST_ID else []),
    }
    if attributes:
        payload['attributes'] = attributes
    return _request('POST', '/contacts', json=payload)


def remove_from_list(email, list_id=None):
    """
    Take a contact off the mailing list.

    Removal from the list rather than deletion of the contact: Brevo keeps its
    own unsubscribe record, and deleting the contact would lose that.
    """
    list_id = list_id or settings.BREVO_LIST_ID
    if not list_id:
        return {}
    return _request('POST', f'/contacts/lists/{list_id}/contacts/remove',
                    json={'emails': [email]})


# ---------------------------------------------------------------------------
# Campaigns — where open and click rates come from
# ---------------------------------------------------------------------------

def create_campaign(name, subject, html, list_ids=None, scheduled_at=None):
    """Create a draft campaign. Nothing is sent until `send_campaign`."""
    payload = {
        'name': name,
        'subject': subject,
        'sender': {
            'email': settings.BREVO_SENDER_EMAIL or settings.DEFAULT_FROM_EMAIL,
            'name': settings.BREVO_SENDER_NAME or settings.SITE_NAME,
        },
        'htmlContent': html,
        'recipients': {
            'listIds': list_ids or ([settings.BREVO_LIST_ID] if settings.BREVO_LIST_ID else []),
        },
    }
    if scheduled_at:
        payload['scheduledAt'] = scheduled_at
    return _request('POST', '/emailCampaigns', json=payload)


def send_campaign(campaign_id):
    """Send a draft campaign immediately."""
    return _request('POST', f'/emailCampaigns/{campaign_id}/sendNow')


def campaign_stats(campaign_id):
    """
    Delivery, open and click figures for one campaign.

    Rates are computed here from the raw counts rather than trusting a
    percentage field, so "opens" and "open rate" can never disagree.
    """
    body = _request('GET', f'/emailCampaigns/{campaign_id}')
    stats = ((body.get('statistics') or {}).get('globalStats')) or {}

    sent = stats.get('sent') or 0
    delivered = stats.get('delivered') or 0
    opens = stats.get('uniqueViews') or stats.get('viewed') or 0
    clicks = stats.get('uniqueClicks') or stats.get('clickers') or 0

    def rate(part, whole):
        return round(100 * part / whole, 1) if whole else 0.0

    return {
        'status': body.get('status', ''),
        'sent': sent,
        'delivered': delivered,
        'hard_bounces': stats.get('hardBounces') or 0,
        'soft_bounces': stats.get('softBounces') or 0,
        'unsubscribed': stats.get('unsubscriptions') or 0,
        'opens': opens,
        'clicks': clicks,
        # Rates are against delivered, not sent: a bounce was never an
        # opportunity to open, so counting it as one understates the campaign.
        'open_rate': rate(opens, delivered),
        'click_rate': rate(clicks, delivered),
    }
