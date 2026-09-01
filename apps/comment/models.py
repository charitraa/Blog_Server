import uuid

from django.conf import settings
from django.db import models

from apps.post.models import Post


class CommentQuerySet(models.QuerySet):
    def top_level(self):
        return self.filter(parent__isnull=True)

    def with_related(self):
        return self.select_related('author', 'post')


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
