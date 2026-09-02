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
