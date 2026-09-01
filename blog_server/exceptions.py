"""Project-wide DRF exception handling.

Every error leaves the API in one predictable shape:

    {"detail": "You do not have permission to perform this action.", "status_code": 403}

Field validation errors keep DRF's per-field mapping so the frontend can show
messages inline, with the status code added alongside:

    {"title": ["This field is required."], "status_code": 400}
"""

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import IntegrityError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger('django')


def custom_exception_handler(exc, context):
    if isinstance(exc, IntegrityError):
        # A race that slipped past a serializer check (e.g. two simultaneous
        # likes). Report it as a conflict rather than a 500.
        logger.warning('Integrity error on %s', context.get('request'), exc_info=exc)
        return Response(
            {'detail': 'That action conflicts with existing data.', 'status_code': status.HTTP_409_CONFLICT},
            status=status.HTTP_409_CONFLICT,
        )

    response = exception_handler(exc, context)

    if response is None:
        # Anything DRF does not recognise is a server fault. The real cause goes
        # to the logs; the client never sees internals or a stack trace.
        logger.error('Unhandled server error', exc_info=exc)
        return Response(
            {'detail': 'A server error occurred. Please try again later.',
             'status_code': status.HTTP_500_INTERNAL_SERVER_ERROR},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, ValidationError):
        # Keep the field -> [messages] mapping untouched.
        if isinstance(response.data, dict):
            response.data['status_code'] = response.status_code
        else:
            response.data = {'detail': response.data, 'status_code': response.status_code}
        return response

    if isinstance(exc, (Http404, DjangoPermissionDenied, APIException)) and isinstance(response.data, dict):
        detail = response.data.get('detail')
        if detail is not None:
            # `message` is kept as an alias because the original API used it.
            response.data = {
                'detail': detail,
                'message': detail,
                'status_code': response.status_code,
            }
            return response

    if isinstance(response.data, dict):
        response.data['status_code'] = response.status_code

    return response
