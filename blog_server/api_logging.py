import json
import logging
from colorama import Fore, Style, init

init(autoreset=True)  # Automatically reset color after each print

logger = logging.getLogger("django")

class APILoggingMiddleware:
    """
    Logs incoming requests and outgoing responses in a clean, colored terminal output.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Log request info
        try:
            body = request.body.decode("utf-8")
            try:
                body_json = json.loads(body) if body else {}
            except Exception:
                body_json = body
        except Exception:
            body_json = {}
        if isinstance(body_json, dict):
            pretty_body = json.dumps(body_json, indent=4)
        else:
            pretty_body = str(body_json)
            
        if request.method in ["POST", "PUT", "PATCH"]:
            logger.info(f"{request.method} {request.path}")
            logger.info(Fore.CYAN + f"INFO Request Body:\n{pretty_body}")
        else:
            logger.info(f"{request.method} {request.path}")
            logger.info(Fore.CYAN + f"INFO Query Params:\n{json.dumps(request.GET.dict(), indent=4)}")


        # Get response
        response = self.get_response(request)

        # Log response info
        if response.status_code >= 500:
            logger.error(f"{request.method} {request.path}")
            logger.error(f"Response Status: {response.status_code}")

        elif response.status_code >= 400:
            logger.warning(f"{request.method} {request.path}")
            logger.warning(f"Response Status: {response.status_code}")

        else:
            logger.info(f"{request.method} {request.path}")
            logger.info(f"Response Status: {response.status_code}")

        return response
