"""GitHub OAuth helper.

Credentials come from the environment (`GITHUB_CLIENT_ID` / `GITHUB_SECRET`);
they are never hard-coded here.
"""

import logging

import requests
from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger('apps.user')

TOKEN_URL = 'https://github.com/login/oauth/access_token'
USER_URL = 'https://api.github.com/user'
EMAILS_URL = 'https://api.github.com/user/emails'
TIMEOUT = 10


class Github:
    @staticmethod
    def _credentials():
        client_id = settings.GITHUB_CLIENT_ID
        client_secret = settings.GITHUB_SECRET
        if not client_id or not client_secret:
            raise AuthenticationFailed('GitHub sign-in is not configured on this server.')
        return client_id, client_secret

    @staticmethod
    def exchange_code_for_token(code):
        client_id, client_secret = Github._credentials()

        response = requests.post(
            TOKEN_URL,
            data={'client_id': client_id, 'client_secret': client_secret, 'code': code},
            headers={'Accept': 'application/json'},
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            # The upstream body may echo the code back; keep it out of the response.
            logger.warning('GitHub token exchange failed with status %s', response.status_code)
            raise AuthenticationFailed('Could not complete GitHub sign-in.')

        payload = response.json()
        if 'error' in payload:
            logger.warning('GitHub token exchange error: %s', payload.get('error'))
            raise AuthenticationFailed('Could not complete GitHub sign-in.')

        token = payload.get('access_token')
        if not token:
            raise AuthenticationFailed('Could not complete GitHub sign-in.')
        return token

    @staticmethod
    def get_github_user(access_token):
        headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'}

        response = requests.get(USER_URL, headers=headers, timeout=TIMEOUT)
        if response.status_code != 200:
            logger.warning('GitHub user lookup failed with status %s', response.status_code)
            raise AuthenticationFailed('Could not read your GitHub profile.')

        user_data = response.json()
        if not isinstance(user_data, dict):
            raise AuthenticationFailed('Could not read your GitHub profile.')

        # A private primary email is not included in the profile response.
        if not user_data.get('email'):
            emails = requests.get(EMAILS_URL, headers=headers, timeout=TIMEOUT)
            if emails.status_code != 200:
                raise AuthenticationFailed('Could not read your GitHub email address.')
            user_data['email'] = next(
                (
                    entry['email']
                    for entry in emails.json()
                    if entry.get('primary') and entry.get('verified')
                ),
                None,
            )

        if not user_data.get('email'):
            raise AuthenticationFailed('No verified email address found on your GitHub account.')

        return user_data
