"""
Google reCAPTCHA verification.

Guards the unauthenticated endpoints that cost something to abuse: creating an
account, and the two that send email to an address the requester chose. Rate
limiting already caps how fast one client can hammer those; a CAPTCHA is what
raises the cost of doing it from a thousand clients at once.

Written to handle **v2 and v3 with the same code**. v3 returns a `score` and v2
does not, so a score is checked when present and ignored when absent. That way
swapping the key type is a configuration change, not a code change.

Deliberately not applied to sign-in: a 20/hour throttle already covers password
guessing, and putting a puzzle in front of every returning reader costs more in
abandoned logins than it saves in blocked attempts.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger('django')

VERIFY_URL = 'https://www.google.com/recaptcha/api/siteverify'
TIMEOUT = 10


def is_enabled():
    """CAPTCHA is off unless a secret is configured, so development needs none."""
    return bool(settings.RECAPTCHA_ENABLED and settings.RECAPTCHA_SECRET_KEY)


def client_ip(request):
    """
    Best-effort client address, passed to Google as a weak extra signal.

    `X-Forwarded-For` is only trustworthy behind a proxy that sets it, which is
    why this is a hint to Google rather than anything this server decides with.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def verify(token, remote_ip=None):
    """
    Check a token with Google.

    Returns `(ok, reason)`. `reason` is for the log, never for the response —
    telling a bot precisely why it failed is free tuning advice.
    """
    if not is_enabled():
        return True, 'disabled'

    if not token:
        return False, 'missing-token'

    payload = {'secret': settings.RECAPTCHA_SECRET_KEY, 'response': token}
    if remote_ip:
        payload['remoteip'] = remote_ip

    try:
        response = requests.post(VERIFY_URL, data=payload, timeout=TIMEOUT)
    except requests.RequestException as exc:
        # Google being unreachable must not lock everyone out of registering.
        # Failing open is the right trade here: the throttles still apply, and
        # a CAPTCHA outage turning into a site outage is the worse failure.
        logger.warning('reCAPTCHA unreachable, allowing the request: %s', exc)
        return True, 'verifier-unreachable'

    if response.status_code != 200:
        logger.warning('reCAPTCHA returned %s, allowing the request', response.status_code)
        return True, 'verifier-error'

    try:
        body = response.json()
    except ValueError:
        logger.warning('reCAPTCHA returned an unparseable body, allowing the request')
        return True, 'verifier-error'

    if not body.get('success'):
        codes = body.get('error-codes') or []
        # A misconfigured secret is our bug, not the visitor's, and would
        # otherwise look like every visitor failing the challenge.
        if 'invalid-input-secret' in codes or 'bad-request' in codes:
            logger.error('reCAPTCHA rejected our secret key: %s', codes)
        return False, ','.join(codes) or 'rejected'

    # v3 scores 0.0 (almost certainly a bot) to 1.0 (almost certainly human).
    # v2 sends no score at all, so its absence is a pass, not a zero.
    score = body.get('score')
    if score is not None and score < settings.RECAPTCHA_MIN_SCORE:
        logger.info('reCAPTCHA score %.2f below threshold %.2f',
                    score, settings.RECAPTCHA_MIN_SCORE)
        return False, f'low-score:{score}'

    return True, 'ok'


def check(request, token):
    """
    Verify, and raise the DRF error a view should surface on failure.

    Kept separate from `verify` so the pure function stays testable without a
    request, and so every guarded endpoint gives the same wording.
    """
    from rest_framework.exceptions import ValidationError

    ok, reason = verify(token, client_ip(request))
    if not ok:
        logger.info('reCAPTCHA rejected a request to %s (%s)', request.path, reason)
        raise ValidationError({
            'captcha': 'That verification failed. Please tick the box and try again.'
        })
