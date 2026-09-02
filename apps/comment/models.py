import uuid

from django.conf import settings
from django.db import models

from apps.post.models import Post


class CommentQuerySet(models.QuerySet):
    def top_level(self):
        return self.filter(parent__isnull=True)

    def with_related(self):
        return self.select_related('author', 'post')

    def visible(self):
        """Everything a reader should see: hidden comments are moderated away."""
        return self.filter(is_hidden=False)


class Comment(models.Model):
    """
    A comment on a post, optionally a reply to another comment.

    Threading is deliberately one level deep: replying to a reply attaches the
    new comment to the top-level parent (see `save`), which keeps the UI
    readable and the queries flat.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comments')
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies',
    )
    content = models.TextField(max_length=2000)
    is_edited = models.BooleanField(default=False)
    # Set by a moderator. A hidden comment stays in the database (so its replies
    # and reports survive) but is filtered out of every public thread.
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CommentQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['post', 'parent', '-created_at']),
            models.Index(fields=['author', '-created_at']),
        ]

    def __str__(self):
        return f'Comment by {self.author} on {self.post}'

    def save(self, *args, **kwargs):
        # Flatten deeper nesting onto the top-level thread.
        if self.parent is not None and self.parent.parent_id is not None:
            self.parent = self.parent.parent
        # A reply always belongs to the same post as its parent.
        if self.parent is not None:
            self.post = self.parent.post
        super().save(*args, **kwargs)


class CommentReport(models.Model):
    """
    A reader flagging a comment for a moderator.

    Reports are advisory: they never hide a comment on their own. A moderator
    sets `Comment.is_hidden` after reviewing, which is the only thing that
    actually removes a comment from public threads.
    """

    class Reason(models.TextChoices):
        SPAM = 'spam', 'Spam or advertising'
        ABUSE = 'abuse', 'Harassment or hate'
        OFF_TOPIC = 'off_topic', 'Off topic'
        OTHER = 'other', 'Something else'

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        REVIEWED = 'reviewed', 'Reviewed'
        DISMISSED = 'dismissed', 'Dismissed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='reports')
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='comment_reports',
    )
    reason = models.CharField(max_length=20, choices=Reason.choices, default=Reason.OTHER)
    detail = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # One report per person per comment; reporting twice changes nothing.
            models.UniqueConstraint(fields=['comment', 'reporter'], name='unique_comment_report'),
        ]
        indexes = [
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f'{self.get_reason_display()} report on {self.comment_id}'
