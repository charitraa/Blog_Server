"""JWT authentication that accepts a header *or* the legacy cookie."""

import logging

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError

logger = logging.getLogger('django')


class CookieOrHeaderJWTAuthentication(JWTAuthentication):
    """
    Reads the access token from `Authorization: Bearer <token>` first, falling
    back to the `access_token` cookie that the original login view set.

    Keeping both means existing cookie-based clients keep working while the SPA
    can use the header, which avoids third-party-cookie restrictions when the
    frontend and API live on different domains.

    The two credentials are treated differently on failure, and that asymmetry
    is the whole point of the class. A header is *asserted*: the caller chose to
    send it for this request, so a bad one is an error and says so. A cookie is
    *ambient*: the browser attaches it to every request to this origin, whether
    or not the endpoint has anything to do with authentication. Raising on a bad
    cookie therefore fails endpoints that never asked for a user at all — a
    stale cookie 401s the public config endpoint, the frontend cannot read its
    own settings, and the site is down for that visitor. Worse, the cookie is
    httpOnly, so no amount of client-side code can clear it; the only escape is
    the visitor knowing to wipe their site data by hand. An unusable ambient
    credential is simply absent, so that is how this treats it.
    """

    def authenticate(self, request):
        header_result = super().authenticate(request)
        if header_result is not None:
            return header_result

        raw_token = request.COOKIES.get(getattr(settings, 'AUTH_COOKIE_NAME', 'access_token'))
        if not raw_token:
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token
        except (TokenError, AuthenticationFailed) as exc:
            # Expired, malformed, signed by a rotated SECRET_KEY, or naming a
            # user the database no longer has. The request continues as
            # anonymous: protected views then answer with a plain "credentials
            # were not provided", which is the 401 a client knows how to fix by
            # refreshing, and public views keep working as they should.
            logger.debug('Ignoring an unusable access_token cookie: %s', exc)
            return None
