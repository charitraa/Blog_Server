from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Follow, username_validator

User = get_user_model()


def absolute_url(request, file_field):
    """Absolute URL for a FileField, or None when nothing is stored."""
    if not file_field:
        return None
    try:
        url = file_field.url
    except ValueError:
        return None
    return request.build_absolute_uri(url) if request else url


class AuthorSerializer(serializers.ModelSerializer):
    """
    Compact author block embedded in posts and comments.

    Only public fields: an email must never leak through a nested author.
    """

    name = serializers.CharField(source='display_name', read_only=True)
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'name', 'avatar', 'headline']
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_avatar(self, obj):
        return absolute_url(self.context.get('request'), obj.photo)


class UserPublicSerializer(AuthorSerializer):
    """Public author profile, including the counters the profile page shows."""

    post_count = serializers.SerializerMethodField()
    follower_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    total_likes = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()

    class Meta(AuthorSerializer.Meta):
        fields = AuthorSerializer.Meta.fields + [
            'first_name', 'last_name', 'bio', 'city', 'district', 'date_joined',
            'website', 'twitter', 'github', 'linkedin',
            'post_count', 'follower_count', 'following_count', 'total_likes', 'is_following',
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.IntegerField())
    def get_post_count(self, obj):
        # Views annotate this; the fallback keeps the serializer usable anywhere.
        cached = getattr(obj, 'post_count', None)
        if cached is not None:
            return cached
        return obj.author_post.filter(status='published').count()

    @extend_schema_field(serializers.IntegerField())
    def get_follower_count(self, obj):
        cached = getattr(obj, 'follower_count', None)
        if cached is not None:
            return cached
        return obj.follower_set.count()

    @extend_schema_field(serializers.IntegerField())
    def get_following_count(self, obj):
        cached = getattr(obj, 'following_count', None)
        if cached is not None:
            return cached
        return obj.following_set.count()

    @extend_schema_field(serializers.IntegerField())
    def get_total_likes(self, obj):
        cached = getattr(obj, 'total_likes', None)
        if cached is not None:
            return cached
        from apps.post.models import Like
        return Like.objects.filter(post__author=obj, post__status='published').count()

    @extend_schema_field(serializers.BooleanField())
    def get_is_following(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated or request.user.pk == obj.pk:
            return False
        return Follow.objects.filter(follower=request.user, following=obj).exists()


class UserMeSerializer(UserPublicSerializer):
    """The signed-in user's own record: public fields plus private ones."""

    class Meta(UserPublicSerializer.Meta):
        fields = UserPublicSerializer.Meta.fields + [
            'email', 'date_of_birth', 'is_verified', 'is_staff', 'auth_provider',
        ]
        read_only_fields = fields


class UserCreateSerializer(serializers.ModelSerializer):
    """Registration."""

    first_name = serializers.CharField(required=True, max_length=30)
    last_name = serializers.CharField(required=True, max_length=30)
    username = serializers.CharField(required=False, allow_blank=True, max_length=30,
                                     validators=[username_validator])
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    confirm_password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'password', 'confirm_password']
        read_only_fields = ['id']

    def validate_email(self, value):
        value = value.lower().strip()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_username(self, value):
        value = (value or '').strip()
        if value and User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('This username is already taken.')
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})

        # Run Django's validators with the user's own data so they can catch
        # passwords that merely repeat the email or name.
        candidate = User(
            email=attrs['email'],
            username=attrs.get('username') or '',
            first_name=attrs['first_name'],
            last_name=attrs['last_name'],
        )
        validate_password(attrs['password'], user=candidate)
        return attrs

    def create(self, validated_data):
        validated_data.pop('confirm_password')
        username = (validated_data.pop('username', '') or '').strip()
        return User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            username=username or User.generate_username(validated_data['email']),
        )


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Profile edit.

    The field list is an explicit allowlist: `is_staff`, `is_superuser`,
    `is_verified` and `password` are simply not assignable here, which closes
    the mass-assignment path.
    """

    username = serializers.CharField(required=False, max_length=30, validators=[username_validator])

    class Meta:
        model = User
        fields = [
            'username', 'first_name', 'last_name', 'bio', 'headline',
            'date_of_birth', 'district', 'city',
            'website', 'twitter', 'github', 'linkedin',
        ]

    def validate_username(self, value):
        value = value.strip()
        if User.objects.filter(username__iexact=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('This username is already taken.')
        return value


class EmailChangeSerializer(serializers.Serializer):
    """Changing an email is separate: it needs re-verification."""

    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        value = value.lower().strip()
        user = self.context['request'].user
        if value == user.email:
            raise serializers.ValidationError('This is already your email address.')
        if User.objects.filter(email__iexact=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError('This email is already in use.')
        return value


class UserPhotoUpdateSerializer(serializers.ModelSerializer):
    photo = serializers.ImageField(required=True)

    class Meta:
        model = User
        fields = ['photo']

    def validate_photo(self, value):
        from blog_server.validators import validate_image_upload
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            validate_image_upload(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value


class PasswordUpdateSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True)
    new_password_confirm = serializers.CharField(write_only=True, required=True)

    def validate_current_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({'new_password_confirm': 'New passwords do not match.'})
        validate_password(attrs['new_password'], user=self.context['request'].user)
        return attrs

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password'])
        return user


class LoginSerializer(serializers.Serializer):
    """Accepts an email or a username under `email`, or an explicit `username`."""

    email = serializers.CharField(required=False, allow_blank=True)
    username = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    def validate(self, attrs):
        identifier = (attrs.get('email') or attrs.get('username') or '').strip()
        if not identifier:
            raise serializers.ValidationError({'email': 'Email or username is required.'})
        attrs['identifier'] = identifier
        return attrs


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    code = serializers.CharField(required=True, min_length=6, max_length=6)


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=False, allow_blank=True)


class DashboardSerializer(serializers.Serializer):
    """Shape of `GET /api/users/me/dashboard/`. Read-only."""

    total_posts = serializers.IntegerField()
    published_posts = serializers.IntegerField()
    draft_posts = serializers.IntegerField()
    total_views = serializers.IntegerField()
    total_likes = serializers.IntegerField()
    total_comments = serializers.IntegerField()
    follower_count = serializers.IntegerField()
    following_count = serializers.IntegerField()


class SocialAuthSerializer(serializers.Serializer):
    """
    Body of `POST /api/auth/social/<provider>/`.

    The frontend never sees a token: it forwards the short-lived `code` the
    provider handed it, and the server does the exchange with the client secret.
    """

    code = serializers.CharField(required=True, trim_whitespace=True)
    # Providers verify this against the one registered for the app, so it has to
    # match whatever the frontend sent when it started the flow.
    redirect_uri = serializers.CharField(required=False, allow_blank=True)


class SocialProviderSerializer(serializers.Serializer):
    """One entry of `GET /api/auth/providers/`."""

    name = serializers.CharField()
    authorize_url = serializers.CharField()
    client_id = serializers.CharField()


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        return value.lower().strip()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(required=True, max_length=128)
    new_password = serializers.CharField(write_only=True, required=True)
    new_password_confirm = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({'new_password_confirm': 'New passwords do not match.'})
        # The strength rules are the same ones registration enforces. The user
        # they are checked against is attached by the view once the token
        # resolves, so a reset cannot use a password that is just the email.
        return attrs
