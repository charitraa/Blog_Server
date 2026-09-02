"""Text preparation shared by the AI tasks."""

import re

TAG_RE = re.compile(r'<[^>]+>')
WHITESPACE_RE = re.compile(r'\s+')


def plain_text_excerpt(value, limit):
    """
    Strip markup and clamp to a character budget.

    Sending raw HTML wastes context on tags the model does not need, and an
    unbounded article would blow the model's window on a long post.
    """
    text = TAG_RE.sub(' ', value or '')
    text = WHITESPACE_RE.sub(' ', text).strip()
    if len(text) <= limit:
        return text
    # Cut on a word boundary so the model is not handed half a word.
    return text[:limit].rsplit(' ', 1)[0] + '…'
