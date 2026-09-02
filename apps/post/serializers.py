from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.user.serializers import AuthorSerializer, absolute_url
from blog_server.validators import validate_image_upload

from .models import (
    Bookmark, Category, EditorImage, Like, Post, PostRevision,
    ReadingHistory, Series, SeriesPost, Tag,
)
from .utils import build_excerpt, plain_text, sanitize_html


class CategorySerializer(serializers.ModelSerializer):
    post_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'post_count']
        read_only_fields = ['id', 'slug', 'post_count']


class TagSerializer(serializers.ModelSerializer):
    post_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Tag
        fields = ['id', 'name', 'slug', 'post_count']
        read_only_fields = ['id', 'slug', 'post_count']


@extend_schema_field(serializers.CharField(allow_null=True))
class CategoryRelatedField(serializers.Field):
    """
    Reads as a nested object, writes from either a slug or a UUID.

    Accepting both means the editor can post whatever it has on hand without
    the frontend needing a lookup round trip.
    """

    default_error_messages = {'no_match': 'No category matches "{value}".'}

    def to_representation(self, value):
        return CategorySerializer(value).data

    def to_internal_value(self, data):
        if data in (None, '', 'null'):
            return None
        category = Category.objects.filter(slug=str(data)).first()
        if category is None:
            try:
                category = Category.objects.filter(pk=data).first()
            except (ValueError, TypeError, DjangoValidationError):
                category = None
        if category is None:
            self.fail('no_match', value=data)
        return category


@extend_schema_field(serializers.ListField(child=serializers.CharField()))
class TagListField(serializers.Field):
    """Reads as nested tag objects, writes from a list of plain names."""

    MAX_TAGS = 8

    def to_representation(self, value):
        return TagSerializer(value.all(), many=True).data

    def to_internal_value(self, data):
        if isinstance(data, str):
            data = [part for part in data.split(',')]
        if not isinstance(data, (list, tuple)):
            raise serializers.ValidationError('Expected a list of tag names.')

        names, seen = [], set()
        for raw in data:
            name = ' '.join(str(raw).split())[:40]
            key = name.lower()
            if not name or key in seen:
                continue
            seen.add(key)
            names.append(name)

        if len(names) > self.MAX_TAGS:
            raise serializers.ValidationError(f'A post may have at most {self.MAX_TAGS} tags.')
        return names


class PostListSerializer(serializers.ModelSerializer):
    """
    Card-sized representation: everything the blog list UI renders, and nothing
    that would make it fetch the full article body.
    """

    author = AuthorSerializer(read_only=True)
    category = CategorySerializer(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    cover_image = serializers.SerializerMethodField()
    like_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    is_liked = serializers.SerializerMethodField()
    is_bookmarked = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'title', 'subtitle', 'slug', 'excerpt', 'cover_image',
            'author', 'category', 'tags', 'status', 'visibility',
            'published_at', 'scheduled_for', 'created_at', 'updated_at',
            'is_featured', 'is_archived',
            'reading_time', 'like_count', 'comment_count', 'view_count',
            'is_liked', 'is_bookmarked',
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_cover_image(self, obj):
        return absolute_url(self.context.get('request'), obj.photo)

    @extend_schema_field(serializers.BooleanField())
    def get_is_liked(self, obj):
        # Annotated by the view for lists; the fallback covers single objects.
        annotated = getattr(obj, 'is_liked', None)
        if annotated is not None:
            return bool(annotated)
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return Like.objects.filter(post=obj, user=request.user).exists()

    @extend_schema_field(serializers.BooleanField())
    def get_is_bookmarked(self, obj):
        annotated = getattr(obj, 'is_bookmarked', None)
        if annotated is not None:
            return bool(annotated)
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return Bookmark.objects.filter(post=obj, user=request.user).exists()


class PostDetailSerializer(PostListSerializer):
    """List fields plus the sanitized article body."""

    class Meta(PostListSerializer.Meta):
        fields = PostListSerializer.Meta.fields + ['content']
        read_only_fields = fields


class PostAuthorDetailSerializer(PostDetailSerializer):
    """
    What the author sees on their own post.

    Adds the draft preview link, which must never appear in a public response —
    anyone holding it can read an unpublished draft.
    """

    preview_token = serializers.UUIDField(read_only=True)

    class Meta(PostDetailSerializer.Meta):
        fields = PostDetailSerializer.Meta.fields + [
            'preview_token', 'seo_title', 'seo_description', 'canonical_url',
        ]
        read_only_fields = fields


class PostWriteSerializer(serializers.ModelSerializer):
    """
    Create/update payload.

    `author`, counters, `slug` and `reading_time` are intentionally absent — the
    view and the model own them, so a client cannot set them.
    """

    category = CategoryRelatedField(required=False, allow_null=True)
    tags = TagListField(required=False)
    cover_image = serializers.ImageField(source='photo', required=False, allow_null=True)

    class Meta:
        model = Post
        fields = [
            'id', 'title', 'subtitle', 'excerpt', 'content', 'cover_image',
            'category', 'tags', 'status', 'visibility', 'scheduled_for',
            'seo_title', 'seo_description', 'canonical_url',
        ]
        read_only_fields = ['id']

    def validate_scheduled_for(self, value):
        """A schedule that is already in the past is almost certainly a mistake."""
        from django.utils import timezone

        if value and value <= timezone.now():
            raise serializers.ValidationError(
                'Pick a time in the future, or publish the post now instead.'
            )
        return value

    def validate_title(self, value):
        value = ' '.join(value.split())
        if len(value) < 3:
            raise serializers.ValidationError('Title must be at least 3 characters long.')
        return value

    def validate_content(self, value):
        # Sanitize before length checks so a body of pure markup is rejected.
        cleaned = sanitize_html(value)
        if len(plain_text(cleaned)) < 20:
            raise serializers.ValidationError('Content must be at least 20 characters long.')
        return cleaned

    def validate_cover_image(self, value):
        if value in (None, ''):
            return value
        try:
            validate_image_upload(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate_status(self, value):
        """
        Publishing is a capability, not something the client decides.

        A contributor can save drafts all day; asking for `published` is
        refused here rather than silently downgraded, so the editor can tell
        the writer what happened.
        """
        request = self.context.get('request')
        going_live = value in (Post.Status.PUBLISHED, Post.Status.SCHEDULED)
        if going_live and request and request.user.is_authenticated:
            if not request.user.can_publish:
                raise serializers.ValidationError(
                    'Your account can save drafts but cannot publish them. '
                    'Ask an editor to review and publish this post.'
                )
        return value

    def validate(self, attrs):
        status = attrs.get('status', getattr(self.instance, 'status', Post.Status.DRAFT))

        if status == Post.Status.SCHEDULED:
            when = attrs.get('scheduled_for', getattr(self.instance, 'scheduled_for', None))
            if when is None:
                raise serializers.ValidationError(
                    {'scheduled_for': 'Choose when this post should go live.'}
                )

        if status == Post.Status.PUBLISHED:
            content = attrs.get('content', getattr(self.instance, 'content', ''))
            if len(plain_text(content)) < 20:
                raise serializers.ValidationError(
                    {'content': 'A published post needs a body of at least 20 characters.'}
                )
        return attrs

    def _apply_tags(self, post, names):
        tags = [tag for tag in (Tag.get_or_create_by_name(name) for name in names) if tag]
        post.tags.set(tags)

    def create(self, validated_data):
        tag_names = validated_data.pop('tags', None)
        if not validated_data.get('excerpt'):
            validated_data['excerpt'] = build_excerpt(validated_data.get('content', ''))
        post = Post.objects.create(author=self.context['request'].user, **validated_data)
        if tag_names is not None:
            self._apply_tags(post, tag_names)
        return post

    def update(self, instance, validated_data):
        tag_names = validated_data.pop('tags', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if tag_names is not None:
            self._apply_tags(instance, tag_names)
        return instance

    def to_representation(self, instance):
        # Answer writes with the same shape reads use, so the client can drop
        # the response straight into its cache.
        return PostDetailSerializer(instance, context=self.context).data


class LikeStateSerializer(serializers.Serializer):
    """Response of the like/unlike endpoints."""

    is_liked = serializers.BooleanField()
    like_count = serializers.IntegerField()


class BookmarkStateSerializer(serializers.Serializer):
    """Response of the bookmark/unbookmark endpoints."""

    is_bookmarked = serializers.BooleanField()


class EditorImageSerializer(serializers.ModelSerializer):
    """
    An inline image uploaded from the post editor.

    The response carries the absolute `url` the editor drops straight into the
    article body.
    """

    url = serializers.SerializerMethodField()

    class Meta:
        model = EditorImage
        fields = ['id', 'image', 'url', 'created_at']
        read_only_fields = ['id', 'url', 'created_at']
        extra_kwargs = {'image': {'write_only': True}}

    def validate_image(self, value):
        try:
            validate_image_upload(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    @extend_schema_field(serializers.URLField())
    def get_url(self, obj):
        return absolute_url(self.context.get('request'), obj.image)

    def create(self, validated_data):
        return EditorImage.objects.create(
            uploaded_by=self.context['request'].user, **validated_data
        )


class PostRevisionSerializer(serializers.ModelSerializer):
    """One entry in a post's history. The body is included so the UI can diff."""

    created_by = AuthorSerializer(read_only=True)

    class Meta:
        model = PostRevision
        fields = ['id', 'title', 'subtitle', 'excerpt', 'content', 'note',
                  'created_by', 'created_at']
        read_only_fields = fields


class PostRevisionListSerializer(serializers.ModelSerializer):
    """
    History list without the bodies.

    A post with fifty revisions would otherwise send fifty copies of the
    article just to render a list of dates.
    """

    created_by = AuthorSerializer(read_only=True)
    word_count = serializers.SerializerMethodField()

    class Meta:
        model = PostRevision
        fields = ['id', 'title', 'note', 'created_by', 'created_at', 'word_count']
        read_only_fields = fields

    @extend_schema_field(serializers.IntegerField())
    def get_word_count(self, obj):
        return len(plain_text(obj.content).split())


class SeriesEntrySerializer(serializers.ModelSerializer):
    """A post's slot in a series, with just enough of the post to render a row."""

    post = PostListSerializer(read_only=True)

    class Meta:
        model = SeriesPost
        fields = ['id', 'position', 'post']
        read_only_fields = fields


class SeriesSerializer(serializers.ModelSerializer):
    """
    A series without its parts, for lists.

    `progress` is the signed-in reader's own completion count, which is what
    makes "3 of 7" possible without a second request.
    """

    author = AuthorSerializer(read_only=True)
    cover_image = serializers.SerializerMethodField()
    post_count = serializers.SerializerMethodField()
    completed_count = serializers.SerializerMethodField()

    class Meta:
        model = Series
        fields = [
            'id', 'title', 'slug', 'description', 'cover_image', 'author',
            'is_published', 'post_count', 'completed_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'slug', 'author', 'post_count', 'completed_count',
                            'created_at', 'updated_at']

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_cover_image(self, obj):
        return absolute_url(self.context.get('request'), obj.cover)

    @extend_schema_field(serializers.IntegerField())
    def get_post_count(self, obj):
        annotated = getattr(obj, 'entry_count', None)
        return annotated if annotated is not None else obj.entries.count()

    @extend_schema_field(serializers.IntegerField())
    def get_completed_count(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 0
        annotated = getattr(obj, 'completed_count', None)
        if annotated is not None:
            return annotated
        return obj.progress.filter(user=request.user).count()


class SeriesDetailSerializer(SeriesSerializer):
    """A series with its ordered parts and the reader's place in it."""

    entries = SeriesEntrySerializer(many=True, read_only=True)
    completed_post_ids = serializers.SerializerMethodField()
    next_post_slug = serializers.SerializerMethodField()

    class Meta(SeriesSerializer.Meta):
        fields = SeriesSerializer.Meta.fields + [
            'entries', 'completed_post_ids', 'next_post_slug',
        ]

    @extend_schema_field(serializers.ListField(child=serializers.UUIDField()))
    def get_completed_post_ids(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return []
        return [str(pk) for pk in obj.progress.filter(user=request.user)
                .values_list('post_id', flat=True)]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_next_post_slug(self, obj):
        """The first part the reader has not finished — where 'continue' goes."""
        done = set(self.get_completed_post_ids(obj))
        for entry in obj.entries.all():
            if str(entry.post_id) not in done:
                return entry.post.slug
        return None


class SeriesWriteSerializer(serializers.ModelSerializer):
    """Create/update a series. The author comes from the request."""

    cover_image = serializers.ImageField(source='cover', required=False, allow_null=True)

    class Meta:
        model = Series
        fields = ['id', 'title', 'description', 'cover_image', 'is_published']
        read_only_fields = ['id']

    def validate_title(self, value):
        value = ' '.join(value.split())
        if len(value) < 3:
            raise serializers.ValidationError('Give the series a name of at least 3 characters.')
        return value

    def create(self, validated_data):
        return Series.objects.create(author=self.context['request'].user, **validated_data)

    def to_representation(self, instance):
        return SeriesSerializer(instance, context=self.context).data


class ReadingHistorySerializer(serializers.ModelSerializer):
    """One row of "recently read", with the post it points at."""

    post = PostListSerializer(read_only=True)

    class Meta:
        model = ReadingHistory
        fields = ['id', 'post', 'progress', 'is_finished', 'last_read_at']
        read_only_fields = fields


class ReadingProgressSerializer(serializers.Serializer):
    """Body of `POST /api/posts/<slug>/progress/`."""

    progress = serializers.IntegerField(min_value=0, max_value=100)
    is_finished = serializers.BooleanField(required=False, default=False)


class DailyCountSerializer(serializers.Serializer):
    """One day of a time series. Quiet days are present with a zero."""

    date = serializers.DateField()
    count = serializers.IntegerField()


class TopPostSerializer(serializers.Serializer):
    slug = serializers.SlugField()
    title = serializers.CharField()
    views = serializers.IntegerField()
    likes = serializers.IntegerField()
    comments = serializers.IntegerField()


class PostAnalyticsSerializer(serializers.Serializer):
    """Shape of `GET /api/posts/<slug>/analytics/`. Read-only."""

    slug = serializers.SlugField()
    title = serializers.CharField()
    published_at = serializers.DateTimeField(allow_null=True)
    total_views = serializers.IntegerField()
    unique_viewers = serializers.IntegerField()
    views_in_period = serializers.IntegerField()
    likes = serializers.IntegerField()
    bookmarks = serializers.IntegerField()
    comments = serializers.IntegerField()
    readers = serializers.IntegerField()
    finished_readers = serializers.IntegerField()
    average_progress = serializers.IntegerField()
    completion_rate = serializers.FloatField()
    reading_time = serializers.IntegerField()
    daily_views = DailyCountSerializer(many=True)


class AuthorAnalyticsSerializer(serializers.Serializer):
    """Shape of `GET /api/users/me/analytics/`. Read-only."""

    total_posts = serializers.IntegerField()
    published_posts = serializers.IntegerField()
    draft_posts = serializers.IntegerField()
    scheduled_posts = serializers.IntegerField()
    total_views = serializers.IntegerField()
    unique_viewers = serializers.IntegerField()
    views_in_period = serializers.IntegerField()
    total_likes = serializers.IntegerField()
    total_comments = serializers.IntegerField()
    total_bookmarks = serializers.IntegerField()
    followers = serializers.IntegerField()
    daily_views = DailyCountSerializer(many=True)
    top_posts = TopPostSerializer(many=True)
