"""
Chat client for the configured AI provider.

NVIDIA NIM speaks the OpenAI chat-completions dialect, so one small client
covers it and anything else that does the same. The provider is chosen by
`AI_PREFERRED_PROVIDER`, which leaves room for a second one later without the
call sites knowing.

Two behaviours worth knowing about:

  * Reasoning models return their working in a separate `reasoning_content`
    field. That is dropped — an author asked for a title, not a monologue.
  * Nothing here raises a bare exception at the caller. A provider outage
    surfaces as `AIUnavailable`, which the views turn into a 503 with a
    sentence a person can act on.
"""

import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger('apps.ai')

TIMEOUT = 90


class AIUnavailable(Exception):
    """The provider could not be reached, or is not configured."""


class AIError(Exception):
    """The provider answered, but not with something usable."""


def is_configured():
    return bool(settings.AI_ENABLED and settings.NVIDIA_API_KEY)


def _endpoint(path):
    return f'{settings.NVIDIA_BASE_URL.rstrip("/")}/{path.lstrip("/")}'


def chat(messages, model=None, max_tokens=1500, temperature=0.4, json_only=False,
         _retry=True):
    """
    One chat completion. Returns the assistant's text.

    `json_only` adds an instruction rather than relying on a provider-specific
    response-format flag, because not every model on the endpoint supports one.

    The default budget is generous because the configured models reason before
    answering, and that reasoning is billed against `max_tokens`. Too small a
    budget is spent entirely on thinking and returns an empty `content` — so a
    truncated answer is retried once with double the room rather than surfaced
    as a failure.
    """
    if not is_configured():
        raise AIUnavailable(
            'AI features are not configured on this server.'
        )

    if json_only:
        messages = [
            {'role': 'system',
             'content': 'Reply with valid JSON only. No prose, no code fences.'}
        ] + list(messages)

    payload = {
        'model': model or settings.NVIDIA_MODEL,
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': temperature,
    }

    try:
        response = requests.post(
            _endpoint('/chat/completions'),
            headers={
                'Authorization': f'Bearer {settings.NVIDIA_API_KEY}',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning('AI provider unreachable: %s', exc)
        raise AIUnavailable('The AI service could not be reached. Please try again.') from exc

    if response.status_code == 401:
        # Logged without the key itself; a 401 is a server misconfiguration,
        # not something the author did.
        logger.error('AI provider rejected our credentials.')
        raise AIUnavailable('AI features are misconfigured on this server.')

    if response.status_code == 429:
        raise AIUnavailable('The AI service is busy right now. Please try again shortly.')

    if response.status_code >= 400:
        logger.warning('AI provider returned %s: %s', response.status_code,
                       response.text[:300])
        raise AIUnavailable('The AI service returned an error. Please try again.')

    try:
        body = response.json()
        message = body['choices'][0]['message']
    except (ValueError, KeyError, IndexError) as exc:
        logger.warning('Unexpected AI response shape: %s', response.text[:300])
        raise AIError('The AI service returned something unexpected.') from exc

    # `content` is the answer; `reasoning_content` is the model thinking aloud
    # and is deliberately discarded — an author asked for a title, not a monologue.
    text = (message.get('content') or '').strip()

    if not text:
        finish = body['choices'][0].get('finish_reason')
        thought = bool(message.get('reasoning_content') or message.get('reasoning'))

        # Ran out of room mid-thought: the same request with more headroom
        # usually lands, so try once before giving up.
        if _retry and (finish == 'length' or thought):
            logger.info('AI answer was truncated by the token budget; retrying larger.')
            return chat(messages, model=model, max_tokens=max_tokens * 2,
                        temperature=temperature, json_only=json_only, _retry=False)

        raise AIError('The AI service returned an empty answer. Please try again.')

    return text


def chat_json(messages, model=None, max_tokens=1500, temperature=0.2):
    """
    A completion parsed as JSON.

    Models sometimes wrap JSON in a fenced block despite being told not to, so
    the fence is stripped before parsing rather than failing the request over
    formatting.
    """
    raw = chat(messages, model=model, max_tokens=max_tokens,
               temperature=temperature, json_only=True)

    cleaned = raw.strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.split('```')[1]
        if cleaned.lstrip().lower().startswith('json'):
            cleaned = cleaned.lstrip()[4:]
    cleaned = cleaned.strip()

    # A model may still add a sentence before the object; take the outermost
    # braces rather than giving up.
    if not cleaned.startswith(('{', '[')):
        start = min(
            (i for i in (cleaned.find('{'), cleaned.find('[')) if i != -1),
            default=-1,
        )
        if start != -1:
            cleaned = cleaned[start:]

    try:
        return json.loads(cleaned)
    except ValueError as exc:
        logger.warning('AI returned unparseable JSON: %s', raw[:300])
        raise AIError('The AI service returned a malformed answer. Please try again.') from exc
