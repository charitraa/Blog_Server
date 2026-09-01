from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.user.serializers import AuthorSerializer

from .models import Comment


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
            'is_edited', 'created_at', 'updated_at',
            'replies', 'reply_count', 'can_edit',
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_replies(self, obj):
        if obj.parent_id is not None:
            return []
        # `replies` is prefetched by the view, so this does not hit the database.
        replies = sorted(obj.replies.all(), key=lambda reply: reply.created_at)
        return CommentSerializer(replies, many=True, context=self.context).data

    @extend_schema_field(serializers.IntegerField())
    def get_reply_count(self, obj):
        if obj.parent_id is not None:
            return 0
        return len(obj.replies.all())

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
