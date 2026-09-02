"""OAuth providers for social sign-in.

Each provider exchanges the short-lived `code` the frontend receives for an
access token, then reads a verified email address. Credentials come from the
environment; a provider with no credentials configured reports itself as
unavailable rather than failing mysteriously.
"""

import logging

import requests
from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger('apps.user')

TIMEOUT = 10


class SocialProfile:
    """Normalised result of a social lookup."""

    def __init__(self, email, first_name='', last_name='', username='', provider=''):
        self.email = (email or '').lower().strip()
        self.first_name = first_name or ''
        self.last_name = last_name or ''
        self.username = username or ''
        self.provider = provider


def _split_name(full_name):
    parts = (full_name or '').strip().split()
    if not parts:
        return '', ''
    return parts[0], ' '.join(parts[1:])


class GithubProvider:
    name = 'github'
    TOKEN_URL = 'https://github.com/login/oauth/access_token'
    USER_URL = 'https://api.github.com/user'
    EMAILS_URL = 'https://api.github.com/user/emails'

    @classmethod
    def is_configured(cls):
        return bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_SECRET)

    @classmethod
    def exchange(cls, code, redirect_uri=None):
        if not cls.is_configured():
            raise AuthenticationFailed('GitHub sign-in is not configured on this server.')

        payload = {
            'client_id': settings.GITHUB_CLIENT_ID,
            'client_secret': settings.GITHUB_SECRET,
            'code': code,
        }
        if redirect_uri:
            payload['redirect_uri'] = redirect_uri

        response = requests.post(
            cls.TOKEN_URL, data=payload,
            headers={'Accept': 'application/json'}, timeout=TIMEOUT,
        )
        if response.status_code != 200:
            logger.warning('GitHub token exchange failed with status %s', response.status_code)
            raise AuthenticationFailed('Could not complete GitHub sign-in.')

        body = response.json()
        if 'error' in body or not body.get('access_token'):
            logger.warning('GitHub token exchange error: %s', body.get('error'))
            raise AuthenticationFailed('Could not complete GitHub sign-in.')
        return body['access_token']

    @classmethod
    def profile(cls, access_token):
        headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'}

        response = requests.get(cls.USER_URL, headers=headers, timeout=TIMEOUT)
        if response.status_code != 200:
            raise AuthenticationFailed('Could not read your GitHub profile.')
        data = response.json()
        if not isinstance(data, dict):
            raise AuthenticationFailed('Could not read your GitHub profile.')

        email = data.get('email')
        if not email:
            # A private primary address is not included in the profile response.
            emails = requests.get(cls.EMAILS_URL, headers=headers, timeout=TIMEOUT)
            if emails.status_code == 200:
                email = next(
                    (e['email'] for e in emails.json()
                     if e.get('primary') and e.get('verified')),
                    None,
                )

        if not email:
            raise AuthenticationFailed('No verified email address found on your GitHub account.')

        first, last = _split_name(data.get('name'))
        return SocialProfile(email, first, last, data.get('login', ''), cls.name)


class GoogleProvider:
    name = 'google'
    TOKEN_URL = 'https://oauth2.googleapis.com/token'
    USER_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'

    @classmethod
    def is_configured(cls):
        return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_SECRET)

    @classmethod
    def exchange(cls, code, redirect_uri=None):
        if not cls.is_configured():
            raise AuthenticationFailed('Google sign-in is not configured on this server.')

        response = requests.post(
            cls.TOKEN_URL,
            data={
                'client_id': settings.GOOGLE_CLIENT_ID,
                'client_secret': settings.GOOGLE_SECRET,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': redirect_uri or settings.GOOGLE_REDIRECT_URI,
            },
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            logger.warning('Google token exchange failed with status %s', response.status_code)
            raise AuthenticationFailed('Could not complete Google sign-in.')

        body = response.json()
        if not body.get('access_token'):
            raise AuthenticationFailed('Could not complete Google sign-in.')
        return body['access_token']

    @classmethod
    def profile(cls, access_token):
        response = requests.get(
            cls.USER_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            raise AuthenticationFailed('Could not read your Google profile.')

        data = response.json()
        # Google reports whether it has verified the address. An unverified one
        # must never be trusted to match an existing account, or anybody could
        # take over that account by signing up with the same address elsewhere.
        if not data.get('email') or not data.get('email_verified'):
            raise AuthenticationFailed('No verified email address found on your Google account.')

        return SocialProfile(
            data['email'],
            data.get('given_name', ''),
            data.get('family_name', ''),
            (data.get('email') or '').split('@')[0],
            cls.name,
        )


PROVIDERS = {
    GithubProvider.name: GithubProvider,
    GoogleProvider.name: GoogleProvider,
}


def available_providers():
    """Providers this deployment actually has credentials for."""
    return [name for name, provider in PROVIDERS.items() if provider.is_configured()]
