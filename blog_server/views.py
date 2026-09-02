from django.http import JsonResponse
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView


class CheckView(APIView):
    """Liveness probe. Also the original root route, so it stays where it was."""

    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: {'type': 'object', 'properties': {'message': {'type': 'string'}}}},
        summary='Health check',
    )
    def get(self, request):
        return JsonResponse({'message': 'Welcome to my server!'})


class RobotsView(APIView):
    """
    `/robots.txt`.

    The API itself has nothing worth indexing, so crawlers are pointed at the
    frontend's sitemap and kept out of the endpoints.
    """

    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def get(self, request):
        from django.conf import settings
        from django.http import HttpResponse

        lines = [
            'User-agent: *',
            'Disallow: /api/',
            'Disallow: /admin/',
            'Allow: /',
            '',
            f'Sitemap: {request.build_absolute_uri("/sitemap.xml")}',
            f'Host: {settings.FRONTEND_URL.rstrip("/")}',
            '',
        ]
        return HttpResponse('\n'.join(lines), content_type='text/plain')


class SiteConfigView(APIView):
    """
    `GET /api/config/` — public settings the frontend needs before sign-in.

    A single place for "what is switched on here", so the client does not need
    a matching set of build-time environment variables that can drift out of
    step with the server.

    Only ever public values. The reCAPTCHA **site** key belongs here — it ships
    in the HTML of every site that uses reCAPTCHA — while the secret never
    leaves this server.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: {'type': 'object', 'properties': {
            'site_name': {'type': 'string'},
            'recaptcha_enabled': {'type': 'boolean'},
            'recaptcha_site_key': {'type': 'string'},
        }}},
        summary='Public site configuration',
    )
    def get(self, request):
        from django.conf import settings

        from blog_server import captcha

        enabled = captcha.is_enabled()
        return JsonResponse({
            'site_name': settings.SITE_NAME,
            'recaptcha_enabled': enabled,
            # Empty unless the guard is actually on, so the widget is never
            # rendered against a key the server will not check.
            'recaptcha_site_key': settings.RECAPTCHA_SITE_KEY if enabled else '',
        })
