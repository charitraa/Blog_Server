"""JWT authentication that accepts a header *or* the legacy cookie."""

from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieOrHeaderJWTAuthentication(JWTAuthentication):
    """
    Reads the access token from `Authorization: Bearer <token>` first, falling
    back to the `access_token` cookie that the original login view set.

    Keeping both means existing cookie-based clients keep working while the SPA
    can use the header, which avoids third-party-cookie restrictions when the
    frontend and API live on different domains.
    """

    def authenticate(self, request):
        header_result = super().authenticate(request)
        if header_result is not None:
            return header_result

        raw_token = request.COOKIES.get(getattr(settings, 'AUTH_COOKIE_NAME', 'access_token'))
        if not raw_token:
            return None

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token
