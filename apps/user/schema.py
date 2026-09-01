"""drf-spectacular hooks so the generated docs describe the real auth scheme."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class CookieOrHeaderJWTScheme(OpenApiAuthenticationExtension):
    """Documents `CookieOrHeaderJWTAuthentication` as HTTP bearer auth."""

    target_class = 'apps.user.authentication.CookieOrHeaderJWTAuthentication'
    name = 'jwtAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
            'description': (
                'Send `Authorization: Bearer <access token>`. The same token is also '
                'accepted from the httpOnly `access_token` cookie set at login.'
            ),
        }
