# core/middleware.py (or anywhere)
from django.utils.deprecation import MiddlewareMixin
from django.http import HttpResponse

class AllowOptionsMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.method == "OPTIONS":
            response = HttpResponse()
            response["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
            response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
            response["Access-Control-Allow-Headers"] = request.headers.get("Access-Control-Request-Headers", "*")
            response["Access-Control-Allow-Credentials"] = "true"
            return response
        return None