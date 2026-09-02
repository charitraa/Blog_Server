"""Serializers for the staff-only administration endpoints."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import ROLE_RANK, Role
from .serializers import AuthorSerializer

User = get_user_model()


class AdminUserSerializer(serializers.ModelSerializer):
    """
    A user as an administrator sees them: the public profile plus the fields
    that only staff have any business reading.
    """

    name = serializers.CharField(source='display_name', read_only=True)
    post_count = serializers.IntegerField(read_only=True, required=False)
    is_currently_suspended = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'name', 'email', 'role', 'is_active', 'is_verified',
            'is_suspended', 'is_currently_suspended', 'suspended_until',
            'suspension_reason', 'auth_provider', 'date_joined', 'post_count',
        ]
        read_only_fields = fields


class RoleUpdateSerializer(serializers.Serializer):
    """Body of `PATCH /api/admin/users/<username>/role/`."""

    role = serializers.ChoiceField(choices=Role.choices)


class SuspendSerializer(serializers.Serializer):
    """
    Body of `POST /api/admin/users/<username>/suspend/`.

    Omitting `until` suspends indefinitely; the reason is shown to the person
    when they next try to sign in, so it should be readable.
    """

    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)
    until = serializers.DateTimeField(required=False, allow_null=True)


class AdminStatsSerializer(serializers.Serializer):
    """Shape of `GET /api/admin/stats/`. Read-only."""

    total_users = serializers.IntegerField()
    new_users_this_week = serializers.IntegerField()
    suspended_users = serializers.IntegerField()
    total_posts = serializers.IntegerField()
    published_posts = serializers.IntegerField()
    draft_posts = serializers.IntegerField()
    total_comments = serializers.IntegerField()
    hidden_comments = serializers.IntegerField()
    open_reports = serializers.IntegerField()
    total_views = serializers.IntegerField()
    total_likes = serializers.IntegerField()
    newsletter_subscribers = serializers.IntegerField()
    roles = serializers.DictField(child=serializers.IntegerField())


class ModerationReportSerializer(serializers.ModelSerializer):
    """A queued comment report, with enough context to decide without a second request."""

    reporter = AuthorSerializer(read_only=True)
    comment_author = AuthorSerializer(source='comment.author', read_only=True)
    comment_content = serializers.CharField(source='comment.content', read_only=True)
    comment_is_hidden = serializers.BooleanField(source='comment.is_hidden', read_only=True)
    post_slug = serializers.SlugField(source='comment.post.slug', read_only=True)
    post_title = serializers.CharField(source='comment.post.title', read_only=True)

    class Meta:
        # Imported lazily to keep this module free of a hard app dependency.
        from apps.comment.models import CommentReport

        model = CommentReport
        fields = [
            'id', 'reason', 'detail', 'status', 'created_at', 'resolved_at',
            'reporter', 'comment', 'comment_content', 'comment_author',
            'comment_is_hidden', 'post_slug', 'post_title',
        ]
        read_only_fields = fields


class ModerationActionSerializer(serializers.Serializer):
    """Body of `POST /api/admin/reports/<id>/action/`."""

    action = serializers.ChoiceField(choices=['hide', 'unhide', 'dismiss'])
