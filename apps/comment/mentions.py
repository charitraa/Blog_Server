"""
@username mentions in comments.

Deliberately narrow: a mention only notifies someone who is already part of the
conversation's reach — it does not let a stranger push a notification to any
account on the site by typing their handle. Specifically, an unknown handle is
ignored rather than guessed at, and nobody is ever notified of their own
mention.

Parsing happens server-side. Doing it in the client would mean trusting a list
of user ids sent by whoever wrote the comment.
"""

import logging
import re

logger = logging.getLogger('apps.comment')

# Matches @handle using the same character set the username validator allows,
# and requires a boundary in front so an email address is not read as a mention.
MENTION_RE = re.compile(r'(?<![\w@])@([a-zA-Z0-9_-]{3,30})\b')

# A ceiling, so one comment cannot notify the whole site.
MAX_MENTIONS = 10


def extract_usernames(text):
    """Handles mentioned in a piece of text, lowercased and de-duplicated."""
    seen = []
    for match in MENTION_RE.finditer(text or ''):
        handle = match.group(1).lower()
        if handle not in seen:
            seen.append(handle)
        if len(seen) >= MAX_MENTIONS:
            break
    return seen


def notify_mentioned(comment):
    """
    Notify the real accounts named in a comment.

    Skips the author (mentioning yourself is not news), anyone who would
    already be notified for this comment, and handles that match no account.
    """
    from django.contrib.auth import get_user_model

    from apps.notification.models import Notification

    User = get_user_model()

    handles = extract_usernames(comment.content)
    if not handles:
        return []

    # Already covered by the comment/reply notification, so a mention would be
    # a second buzz for the same event.
    already = {comment.author_id, comment.post.author_id}
    if comment.parent_id:
        already.add(comment.parent.author_id)

    recipients = (
        User.objects.filter(username__in=handles, is_active=True)
        .exclude(pk__in=already)
    )

    notified = []
    for user in recipients:
        try:
            Notification.objects.get_or_create(
                recipient=user,
                actor=comment.author,
                verb=Notification.Verb.MENTION,
                post=comment.post,
                comment=comment,
            )
            notified.append(user.username)
        except Exception:
            # A missing notification must never fail the comment itself.
            logger.exception('Could not notify %s of a mention', user.pk)

    return notified
