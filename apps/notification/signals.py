"""
Receivers that turn domain events into notifications.

Every rule here is the same shape: work out who should hear about it, refuse to
notify somebody about their own action, and use `get_or_create` so a repeated
event (unlike then like again) does not stack up duplicates.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.comment.models import Comment
from apps.post.models import Like
from apps.user.models import Follow

from .models import Notification

logger = logging.getLogger('apps.notification')


def _notify(recipient_id, actor_id, verb, post=None, comment=None):
    """Create a notification unless it would be self-directed or a duplicate."""
    if not recipient_id or recipient_id == actor_id:
        return None
    try:
        notification, _ = Notification.objects.get_or_create(
            recipient_id=recipient_id,
            actor_id=actor_id,
            verb=verb,
            post=post,
            comment=comment,
        )
        return notification
    except Exception:
        # A notification is never important enough to fail the action that
        # triggered it.
        logger.exception('Could not create a %s notification', verb)
        return None


@receiver(post_save, sender=Like, dispatch_uid='notify_on_like')
def notify_on_like(sender, instance, created, **kwargs):
    if not created:
        return
    _notify(instance.post.author_id, instance.user_id, Notification.Verb.LIKE, post=instance.post)


@receiver(post_save, sender=Comment, dispatch_uid='notify_on_comment')
def notify_on_comment(sender, instance, created, **kwargs):
    if not created:
        return

    # Anyone named with @handle, minus the people already notified below.
    from apps.comment.mentions import notify_mentioned

    notify_mentioned(instance)

    if instance.parent_id:
        # A reply notifies the parent comment's author, not the post's.
        _notify(
            instance.parent.author_id,
            instance.author_id,
            Notification.Verb.REPLY,
            post=instance.post,
            comment=instance,
        )
        return

    _notify(
        instance.post.author_id,
        instance.author_id,
        Notification.Verb.COMMENT,
        post=instance.post,
        comment=instance,
    )


@receiver(post_save, sender=Follow, dispatch_uid='notify_on_follow')
def notify_on_follow(sender, instance, created, **kwargs):
    if not created:
        return
    _notify(instance.following_id, instance.follower_id, Notification.Verb.FOLLOW)
