from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.user.serializers import AuthorSerializer

from .models import Comment, CommentReport


class CommentSerializer(serializers.ModelSerializer):
    """
    Read shape for a comment.

    Top-level comments carry their replies inline so the thread renders from a
    single request; a reply itself serializes with an empty `replies` list.
    """

    author = AuthorSerializer(read_only=True)
    replies = serializers.SerializerMethodField()
    reply_count = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            'id', 'post', 'parent', 'author', 'content',
            'is_edited', 'is_hidden', 'created_at', 'updated_at',
            'replies', 'reply_count', 'can_edit',
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_replies(self, obj):
        if obj.parent_id is not None:
            return []
        # `replies` is prefetched by the view, so this does not hit the database.
        # Filtering in Python rather than the query keeps that prefetch intact.
        replies = sorted(
            (reply for reply in obj.replies.all() if not reply.is_hidden),
            key=lambda reply: reply.created_at,
        )
        return CommentSerializer(replies, many=True, context=self.context).data

    @extend_schema_field(serializers.IntegerField())
    def get_reply_count(self, obj):
        if obj.parent_id is not None:
            return 0
        return sum(1 for reply in obj.replies.all() if not reply.is_hidden)

    @extend_schema_field(serializers.BooleanField())
    def get_can_edit(self, obj):
        """Convenience flag for the UI. The server re-checks on every write."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.author_id == request.user.id or request.user.is_staff


class CommentWriteSerializer(serializers.ModelSerializer):
    """Create/update payload. `post` and `author` are set by the view."""

    class Meta:
        model = Comment
        fields = ['id', 'content', 'parent']
        read_only_fields = ['id']

    def validate_content(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Comment cannot be empty.')
        if len(value) > 2000:
            raise serializers.ValidationError('Comment must be 2000 characters or fewer.')
        return value

    def validate_parent(self, value):
        if value is None:
            return value
        post = self.context.get('post')
        if post is not None and value.post_id != post.id:
            raise serializers.ValidationError('The parent comment belongs to a different post.')
        return value

    def to_representation(self, instance):
        return CommentSerializer(instance, context=self.context).data


class CommentReportSerializer(serializers.ModelSerializer):
    """
    Body of `POST /api/comments/<id>/report/`.

    `comment`, `reporter` and `status` are set by the view — a reporter cannot
    file a report as somebody else or mark their own report reviewed.
    """

    class Meta:
        model = CommentReport
        fields = ['id', 'reason', 'detail', 'status', 'created_at']
        read_only_fields = ['id', 'status', 'created_at']

    def validate_detail(self, value):
        return (value or '').strip()[:500]
