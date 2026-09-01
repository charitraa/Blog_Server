import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from blog_server.validators import validate_image_upload

from .utils import build_excerpt, reading_time_minutes, sanitize_html, unique_slug


class Category(models.Model):
    """Broad topic a post belongs to. A post has at most one."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=80, unique=True, blank=True)
    description = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'categories'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Category, self.name, self)
        super().save(*args, **kwargs)


class Tag(models.Model):
    """Free-form label. A post may carry several."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=40, unique=True)
    slug = models.SlugField(max_length=60, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Tag, self.name, self)
        super().save(*args, **kwargs)

    @classmethod
    def get_or_create_by_name(cls, name):
        """Match an existing tag case-insensitively before creating a new one."""
        cleaned = ' '.join(name.split())[:40]
        if not cleaned:
            return None
        existing = cls.objects.filter(name__iexact=cleaned).first()
        if existing:
            return existing
        return cls.objects.create(name=cleaned, slug=unique_slug(cls, cleaned))


class PostQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Post.Status.PUBLISHED, published_at__lte=timezone.now())

    def visible_to(self, user):
        """Published posts, plus the requesting user's own drafts."""
        if user and user.is_authenticated:
            if user.is_staff:
                return self
            return self.filter(
                models.Q(status=Post.Status.PUBLISHED, published_at__lte=timezone.now())
                | models.Q(author=user)
            )
        return self.published()

    def with_related(self):
        """Everything a list or detail serializer touches, in one round trip."""
        return self.select_related('author', 'category').prefetch_related('tags')

    def with_counts(self):
        return self.annotate(
            like_count=models.Count('likes', distinct=True),
            comment_count=models.Count('comments', distinct=True),
        )


class Post(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=200)
    # Readable URL key. Generated once and then left alone so links stay valid.
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    excerpt = models.CharField(max_length=300, blank=True)
    content = models.TextField()

    photo = models.ImageField(
        upload_to='user_post/',
        default='user_post/default.png',
        validators=[validate_image_upload],
        blank=True,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='author_post',
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posts',
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name='posts')

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    # Denormalised so trending queries do not have to count rows on every read.
    view_count = models.PositiveIntegerField(default=0)
    # Minutes, derived from `content` on every save.
    reading_time = models.PositiveSmallIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Null until the post is first published.
    published_at = models.DateTimeField(null=True, blank=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ['-published_at', '-created_at']
        indexes = [
            models.Index(fields=['status', '-published_at']),
            models.Index(fields=['author', 'status']),
            models.Index(fields=['slug']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return self.title

    @property
    def is_published(self):
        return self.status == self.Status.PUBLISHED and self.published_at is not None

    def save(self, *args, **kwargs):
        self.content = sanitize_html(self.content)

        if not self.slug:
            self.slug = unique_slug(Post, self.title, self)
        if not self.excerpt:
            self.excerpt = build_excerpt(self.content)
        self.reading_time = reading_time_minutes(self.content)

        # Stamp the publication date the first time a post goes live, and clear
        # it again if the author pulls the post back to draft.
        if self.status == self.Status.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        elif self.status == self.Status.DRAFT:
            self.published_at = None

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f'/blog/{self.slug}'


class Like(models.Model):
    """One row per (user, post). The unique constraint is what makes likes idempotent."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['post', 'user'], name='unique_post_like'),
        ]
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f'{self.user} likes {self.post}'


class PostView(models.Model):
    """
    Deduplication ledger for `Post.view_count`.

    `fingerprint` is a salted SHA-256 of the viewer's IP and user agent, so a
    reader can be recognised across a short window without the server storing
    anything that identifies them.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='views')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='post_views',
    )
    fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['post', 'fingerprint'], name='unique_post_view'),
        ]
        indexes = [
            models.Index(fields=['post', 'created_at']),
        ]

    def __str__(self):
        return f'view of {self.post}'


class Bookmark(models.Model):
    """A reader's save-for-later list. One row per (user, post)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='bookmarks')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookmarks')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # Saving twice is a no-op, enforced by the database rather than the client.
            models.UniqueConstraint(fields=['post', 'user'], name='unique_post_bookmark'),
        ]
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f'{self.user} saved {self.post}'


class EditorImage(models.Model):
    """
    An image uploaded from inside the post editor and referenced by its URL in
    the article body.

    Tracked rather than written loose to disk so uploads have an owner, can be
    rate limited per author, and can be cleaned up later if a post is removed.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    image = models.ImageField(upload_to='post_content/', validators=[validate_image_upload])
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='editor_images',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['uploaded_by', '-created_at']),
        ]

    def __str__(self):
        return self.image.name
