import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from blog_server.validators import validate_image_upload

username_validator = RegexValidator(
    regex=r'^[a-zA-Z0-9_-]{3,30}$',
    message='Username may only contain letters, numbers, underscores and hyphens (3-30 characters).',
)


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set.')
        email = self.normalize_email(email)
        extra_fields.setdefault('is_active', True)
        user = self.model(email=email, **extra_fields)
        if not user.username:
            user.username = User.generate_username(email)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_verified', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    AUTH_PROVIDERS = {
        'email': 'email',
        'github': 'github',
        'google': 'google',
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    # Public handle. Unique so profiles can be addressed as /users/<username>/.
    username = models.CharField(
        max_length=30,
        unique=True,
        validators=[username_validator],
        help_text='Public handle used in profile URLs.',
    )
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    photo = models.ImageField(
        upload_to='user_photos/',
        default='user_photos/default.jpg',
        validators=[validate_image_upload],
        blank=True,
    )
    bio = models.CharField(max_length=280, blank=True)
    headline = models.CharField(max_length=120, blank=True, help_text='Short title shown under the name.')
    district = models.CharField(max_length=50, blank=True)
    city = models.CharField(max_length=50, blank=True)

    # Optional links surfaced on the public author profile.
    website = models.URLField(max_length=200, blank=True)
    twitter = models.URLField(max_length=200, blank=True)
    github = models.URLField(max_length=200, blank=True)
    linkedin = models.URLField(max_length=200, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    auth_provider = models.CharField(max_length=30, default='email', blank=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        ordering = ['-date_joined']
        indexes = [
            models.Index(fields=['username']),
        ]

    def __str__(self):
        return self.full_name or self.username or self.email

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    @property
    def display_name(self):
        """Name to show in the UI, never empty."""
        return self.full_name or self.username

    @staticmethod
    def generate_username(email):
        """Derive a unique handle from an email local part."""
        import re
        import secrets

        base = re.sub(r'[^a-zA-Z0-9_-]', '', (email or '').split('@')[0])[:24] or 'user'
        if len(base) < 3:
            base = f'{base}user'[:24]

        candidate = base
        while User.objects.filter(username__iexact=candidate).exists():
            candidate = f'{base[:24]}-{secrets.token_hex(2)}'
        return candidate

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        if not self.username:
            self.username = User.generate_username(self.email)
        super().save(*args, **kwargs)


class Follow(models.Model):
    """`follower` follows `following`. One row per pair."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    follower = models.ForeignKey(User, on_delete=models.CASCADE, related_name='following_set')
    following = models.ForeignKey(User, on_delete=models.CASCADE, related_name='follower_set')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # The database, not the frontend, prevents duplicate follows.
            models.UniqueConstraint(fields=['follower', 'following'], name='unique_follow'),
            models.CheckConstraint(
                condition=~models.Q(follower=models.F('following')),
                name='no_self_follow',
            ),
        ]
        indexes = [
            models.Index(fields=['following', 'created_at']),
        ]

    def __str__(self):
        return f'{self.follower} -> {self.following}'


class LoginCode(models.Model):
    """One-time numeric code emailed to confirm an address."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='login_codes')
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_used']),
        ]

    def __str__(self):
        return f'{self.user.email} - {self.code}'

    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_usable(self):
        return not self.is_used and not self.is_expired()


class PasswordResetToken(models.Model):
    """
    A single-use token emailed to someone who has forgotten their password.

    Only the SHA-256 of the token is stored, so a leaked database dump cannot be
    used to reset anybody's password — the plain token exists only in the email.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'used_at']),
        ]

    def __str__(self):
        return f'password reset for {self.user.email}'

    @staticmethod
    def hash_token(raw_token):
        import hashlib
        return hashlib.sha256(raw_token.encode()).hexdigest()

    @classmethod
    def issue(cls, user, ttl_minutes):
        """Invalidate any outstanding tokens and return a fresh plain one."""
        import secrets
        from datetime import timedelta

        cls.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())

        raw_token = secrets.token_urlsafe(32)
        cls.objects.create(
            user=user,
            token_hash=cls.hash_token(raw_token),
            expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
        )
        return raw_token

    @property
    def is_usable(self):
        return self.used_at is None and timezone.now() <= self.expires_at

    def consume(self):
        self.used_at = timezone.now()
        self.save(update_fields=['used_at'])
