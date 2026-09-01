"""Request/response logging.

Two things this deliberately does *not* do:

* read `request.body` — that consumes the stream and breaks multipart uploads,
  and it would write credentials straight into `logs/errors.log`;
* log any value belonging to a sensitive key. Only the field *names* are
  recorded, so a failing request is still debuggable without leaking secrets.
"""

import json
import logging
import time

logger = logging.getLogger('django')

# Field names whose values must never reach the logs.
SENSITIVE_KEYS = {
    'password',
    'confirm_password',
    'current_password',
    'new_password',
    'new_password_confirm',
    'token',
    'access',
    'refresh',
    'access_token',
    'refresh_token',
    'code',
    'authorization',
}


def _redact(payload):
    """Return `payload` with the value of every sensitive key masked."""
    if not isinstance(payload, dict):
        return payload
    return {
        key: '[redacted]' if key.lower() in SENSITIVE_KEYS else value
        for key, value in payload.items()
    }


class APILoggingMiddleware:
    """Logs one line per request plus its outcome and duration."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.monotonic()

        if request.method in ('GET', 'DELETE') and request.GET:
            logger.info('%s %s params=%s', request.method, request.path,
                        json.dumps(_redact(request.GET.dict())))
        else:
            logger.info('%s %s', request.method, request.path)

        response = self.get_response(request)

        duration_ms = (time.monotonic() - started) * 1000
        message = '%s %s -> %s (%.0fms)'
        args = (request.method, request.path, response.status_code, duration_ms)

        if response.status_code >= 500:
            logger.error(message, *args)
        elif response.status_code >= 400:
            logger.warning(message, *args)
        else:
            logger.info(message, *args)

        return response
