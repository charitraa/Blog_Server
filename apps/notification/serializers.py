from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.user.serializers import AuthorSerializer

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """
    Everything the notification bell renders, resolved server-side.

    `message` and `url` are built here rather than in the client so the wording
    and the link shape only ever live in one place.
    """

    actor = AuthorSerializer(read_only=True)
    message = serializers.CharField(read_only=True)
    url = serializers.CharField(source='target_url', read_only=True)
    post_slug = serializers.SlugField(source='post.slug', read_only=True, default=None)
    post_title = serializers.CharField(source='post.title', read_only=True, default=None)

    class Meta:
        model = Notification
        fields = [
            'id', 'verb', 'actor', 'message', 'url',
            'post_slug', 'post_title', 'is_read', 'created_at',
        ]
        read_only_fields = fields


class UnreadCountSerializer(serializers.Serializer):
    """Response of `GET /api/notifications/unread-count/`."""

    unread = serializers.IntegerField()


class MarkReadSerializer(serializers.Serializer):
    """
    Body of `POST /api/notifications/read/`.

    Omitting `ids` marks the whole inbox read, which is what the "mark all as
    read" button sends.
    """

    ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True,
    )
