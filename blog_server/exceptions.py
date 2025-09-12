# apps/core/exceptions.py
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import APIException
import logging

logger = logging.getLogger("django")  # Uses same logging config

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        # Unhandled server errors
        logger.error("Unhandled server error", exc_info=exc)
        return Response(
            {"message": "This is a server fault. Please try again later."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    response.data["status_code"] = response.status_code
    # Change 'detail' to 'message' for all DRF exceptions
    if isinstance(exc, APIException) and "detail" in response.data:
        response.data = {"message": response.data["detail"], "status_code": response.status_code}

    return response
