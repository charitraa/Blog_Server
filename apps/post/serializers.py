from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.user.serializers import AuthorSerializer, absolute_url
from blog_server.validators import validate_image_upload

from .models import Category, Like, Post, Tag
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

    class Meta:
        model = Post
        fields = [
            'id', 'title', 'slug', 'excerpt', 'cover_image',
            'author', 'category', 'tags', 'status',
            'published_at', 'created_at', 'updated_at',
            'reading_time', 'like_count', 'comment_count', 'view_count', 'is_liked',
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


class PostDetailSerializer(PostListSerializer):
    """List fields plus the sanitized article body."""

    class Meta(PostListSerializer.Meta):
        fields = PostListSerializer.Meta.fields + ['content']
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
        fields = ['id', 'title', 'excerpt', 'content', 'cover_image', 'category', 'tags', 'status']
        read_only_fields = ['id']

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

    def validate(self, attrs):
        status = attrs.get('status', getattr(self.instance, 'status', Post.Status.DRAFT))
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
