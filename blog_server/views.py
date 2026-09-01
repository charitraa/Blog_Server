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
