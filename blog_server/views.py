from django.http import JsonResponse
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

class CheckView(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        return JsonResponse({"message": "Welcome to my server!"})
