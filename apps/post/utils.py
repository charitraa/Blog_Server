"""Helpers shared by the post models and serializers."""

import hashlib
import re

import bleach
from django.conf import settings
from django.utils.html import strip_tags
from django.utils.text import slugify

# Tags a writer may use. Anything else (script, iframe, object, style, ...) is
# stripped, which is what stops stored XSS.
ALLOWED_TAGS = [
    'p', 'br', 'hr',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'strong', 'b', 'em', 'i', 'u', 's', 'mark', 'sub', 'sup',
    'ul', 'ol', 'li',
    'blockquote', 'pre', 'code',
    'a', 'img', 'figure', 'figcaption',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'span', 'div',
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height', 'loading'],
    'code': ['class'],      # language-xxx for syntax highlighting
    'pre': ['class'],
    'span': ['class'],
    'div': ['class'],
    'th': ['colspan', 'rowspan', 'scope'],
    'td': ['colspan', 'rowspan'],
}

# `javascript:` and friends are absent by design.
ALLOWED_PROTOCOLS = ['http', 'https', 'mailto', 'data']

WORDS_PER_MINUTE = 200

# `bleach` strips a disallowed tag but keeps its text, which would leave the
# body of a <script> sitting in the article as visible prose. Drop these blocks
# whole instead.
_SCRIPT_BLOCK_RE = re.compile(
    r'<\s*(script|style|template|noscript)\b[^>]*>.*?<\s*/\s*\1\s*>',
    re.IGNORECASE | re.DOTALL,
)
# An unclosed opener would otherwise smuggle its payload through as text.
_DANGLING_SCRIPT_RE = re.compile(
    r'<\s*(script|style|template|noscript)\b[^>]*>.*',
    re.IGNORECASE | re.DOTALL,
)


def sanitize_html(html):
    """Strip everything that could execute in a reader's browser."""
    if not html:
        return ''
    html = _SCRIPT_BLOCK_RE.sub('', html)
    html = _DANGLING_SCRIPT_RE.sub('', html)
    cleaned = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    # Outbound links open safely.
    return bleach.linkify(cleaned, callbacks=[_add_link_safety], skip_tags=['pre', 'code'])


def _add_link_safety(attrs, new=False):
    attrs[(None, 'rel')] = 'noopener noreferrer nofollow'
    return attrs


def plain_text(html):
    """Readable text with tags and collapsed whitespace removed."""
    return re.sub(r'\s+', ' ', strip_tags(html or '')).strip()


def reading_time_minutes(html):
    """
    Minutes to read, at 200 words per minute, rounded up and never below 1.

    Computed server-side so every client shows the same number.
    """
    words = len(plain_text(html).split())
    if words == 0:
        return 1
    return max(1, -(-words // WORDS_PER_MINUTE))


def build_excerpt(html, limit=200):
    """First `limit` characters of the body, cut on a word boundary."""
    text = plain_text(html)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(' ', 1)[0].rstrip('.,;:') + '…'


def unique_slug(model, value, instance=None, max_length=240):
    """
    A URL-safe slug for `value` that no other row of `model` uses.

    Collisions get a `-2`, `-3`, ... suffix so slugs stay readable.
    """
    base = slugify(value)[:max_length] or 'post'
    candidate = base
    suffix = 2
    queryset = model.objects.all()
    if instance is not None and instance.pk:
        queryset = queryset.exclude(pk=instance.pk)

    while queryset.filter(slug=candidate).exists():
        tail = f'-{suffix}'
        candidate = f'{base[:max_length - len(tail)]}{tail}'
        suffix += 1
    return candidate


def viewer_fingerprint(request):
    """
    Stable, non-reversible identifier for a viewer, used only to avoid counting
    the same reader twice.

    Raw IP addresses are never stored: the address is salted with SECRET_KEY and
    hashed, so the value cannot be turned back into a person.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    ip = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', '')
    agent = request.META.get('HTTP_USER_AGENT', '')[:200]
    raw = f'{settings.SECRET_KEY}:{ip}:{agent}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
