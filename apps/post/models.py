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
    def alive(self):
        """Everything that has not been soft-deleted."""
        return self.filter(deleted_at__isnull=True)

    def published(self):
        """
        Live posts.

        A scheduled post whose date has passed counts as published even if the
        `publish_scheduled` command has not run yet, so a missed cron tick
        delays tidying up rather than the article itself.
        """
        now = timezone.now()
        return self.alive().filter(
            models.Q(status=Post.Status.PUBLISHED, published_at__lte=now)
            | models.Q(status=Post.Status.SCHEDULED, scheduled_for__lte=now)
        ).exclude(visibility=Post.Visibility.PRIVATE).filter(is_archived=False)

    def readable_by(self, user):
        """`published()` narrowed to what this particular viewer may open."""
        queryset = self.published()
        if user and user.is_authenticated:
            return queryset
        # A members-only post is listed but its body is withheld from guests;
        # that decision lives in the serializer, not here.
        return queryset

    def visible_to(self, user):
        """
        Published posts, plus the requesting user's own work.

        Anyone who may edit other people's work (editor and above) sees every
        draft too — reviewing submissions is the whole job, and hiding them
        would make a contributor's post unreachable rather than merely
        unpublishable. Soft-deleted posts are excluded for everybody; they are
        reached through the author's own trash instead.
        """
        if user and user.is_authenticated:
            if getattr(user, 'can_edit_others', False) or user.is_staff:
                return self.alive()
            return self.alive().filter(
                models.Q(id__in=self.published().values('id')) | models.Q(author=user)
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


def live_posts_q(prefix='posts'):
    """
    `PostQuerySet.published()` as a Q over a reverse relation, for counting.

    Category and tag cards annotate their post count with a join rather than a
    queryset, so the rule that decides what a visitor can open has to be
    expressed twice. Keeping the second copy here means a count can never drift
    from the list it labels — a trashed or archived post used to be counted by
    the card and then be missing from the page it led to.

    `visibility` is matched positively instead of excluding `private`, because
    a negated Q inside an aggregate filter makes Django emit a subquery.
    """
    now = timezone.now()

    def field(name):
        return f'{prefix}__{name}'

    return (
        models.Q(**{field('deleted_at__isnull'): True})
        & models.Q(**{field('is_archived'): False})
        & models.Q(**{field('visibility__in'): (
            Post.Visibility.PUBLIC, Post.Visibility.MEMBERS)})
        & (
            models.Q(**{field('status'): Post.Status.PUBLISHED,
                        field('published_at__lte'): now})
            | models.Q(**{field('status'): Post.Status.SCHEDULED,
                          field('scheduled_for__lte'): now})
        )
    )


class Post(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        # Written by a contributor and waiting for someone who can publish.
        IN_REVIEW = 'in_review', 'In review'
        # Dated for the future. Becomes readable on its own once the date
        # passes, with or without a scheduler running.
        SCHEDULED = 'scheduled', 'Scheduled'
        PUBLISHED = 'published', 'Published'

    class Visibility(models.TextChoices):
        PUBLIC = 'public', 'Everyone'
        MEMBERS = 'members', 'Members only'
        PRIVATE = 'private', 'Only me'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=300, blank=True)
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

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    visibility = models.CharField(
        max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC,
    )

    # When a scheduled post should go live. The queryset treats a past date as
    # published, so scheduling works even if no cron job is running.
    scheduled_for = models.DateTimeField(null=True, blank=True)

    is_featured = models.BooleanField(default=False)

    # Archived posts stay readable by their author but leave every public list.
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    # Soft delete: the row survives so the author can undo, and so comments and
    # likes are not destroyed by a misclick. A purge job can remove old ones.
    deleted_at = models.DateTimeField(null=True, blank=True)

    # --- SEO overrides. Blank means "derive it from the post". ---
    seo_title = models.CharField(max_length=70, blank=True)
    seo_description = models.CharField(max_length=200, blank=True)
    canonical_url = models.URLField(max_length=300, blank=True)

    # An editor's feedback when a submission is sent back. Kept on the post so
    # the writer sees why the moment they open it, rather than having to find a
    # notification.
    review_note = models.CharField(max_length=500, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_posts',
    )

    # Unguessable key that lets an author share a draft for review without
    # publishing it. Rotating it revokes every link handed out so far.
    preview_token = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)

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
        # it again if the author pulls the post back to a pre-published state.
        if self.status == self.Status.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        elif self.status == self.Status.SCHEDULED:
            # The scheduled date *is* the publication date, so a post that goes
            # live on its own already carries the right timestamp.
            self.published_at = self.scheduled_for
        elif self.status in (self.Status.DRAFT, self.Status.IN_REVIEW):
            self.published_at = None

        super().save(*args, **kwargs)

    # --- Lifecycle transitions ------------------------------------------

    def archive(self):
        """Take a post out of every public list without deleting it."""
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save(update_fields=['is_archived', 'archived_at'])

    def unarchive(self):
        self.is_archived = False
        self.archived_at = None
        self.save(update_fields=['is_archived', 'archived_at'])

    def soft_delete(self):
        """
        Move the post to the author's trash.

        The row stays, so the comments and likes attached to it survive and the
        author can change their mind.
        """
        self.deleted_at = timezone.now()
        self.save(update_fields=['deleted_at'])

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=['deleted_at'])

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def is_live(self):
        """Whether a reader could open this right now."""
        if self.deleted_at or self.is_archived or self.visibility == self.Visibility.PRIVATE:
            return False
        if self.status == self.Status.PUBLISHED:
            return self.published_at is not None and self.published_at <= timezone.now()
        if self.status == self.Status.SCHEDULED:
            return self.scheduled_for is not None and self.scheduled_for <= timezone.now()
        return False

    def duplicate(self, author=None):
        """
        Copy this post into a fresh draft.

        Counters, dates and the share token are deliberately not carried over —
        the copy is a new piece of work, not a second view of this one.
        """
        copy = Post.objects.create(
            title=f'{self.title} (copy)'[:200],
            subtitle=self.subtitle,
            excerpt=self.excerpt,
            content=self.content,
            photo=self.photo,
            author=author or self.author,
            category=self.category,
            status=Post.Status.DRAFT,
            visibility=self.visibility,
            seo_title=self.seo_title,
            seo_description=self.seo_description,
        )
        copy.tags.set(self.tags.all())
        return copy

    @property
    def meta_title(self):
        return self.seo_title or self.title

    @property
    def meta_description(self):
        return self.seo_description or self.excerpt

    def get_absolute_url(self):
        return f'/post/{self.slug}'

    def preview_url(self):
        """Shareable link to an unpublished draft."""
        return f'/post/{self.slug}?preview={self.preview_token}'


class Like(models.Model):
    """
    A reader's reaction to a post. One row per (user, post).

    Kept as a single row with a `kind` rather than one table per reaction, and
    one row per person rather than one per reaction: choosing "insightful"
    replaces "like" instead of stacking, so the total is always the number of
    people who reacted. A post showing 40 reactions from 12 readers would be
    a vanity metric, not a signal.

    The model is still called Like, and `likes` is still the related name, so
    every existing query, counter and API field keeps working.
    """

    class Kind(models.TextChoices):
        LIKE = 'like', '👍 Like'
        LOVE = 'love', '❤️ Love'
        INSIGHTFUL = 'insightful', '💡 Insightful'
        FUNNY = 'funny', '😄 Funny'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='likes')
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.LIKE)
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


class PostRevision(models.Model):
    """
    A snapshot of a post's text at a point in time.

    Stored on every meaningful edit so an author can see what changed and roll
    back. Only the fields a writer actually edits are kept — counters and
    timestamps would make every diff noisy without saying anything useful.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='revisions')
    # Null once the editing account is deleted; the history itself survives.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='post_revisions',
    )

    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=300, blank=True)
    excerpt = models.CharField(max_length=300, blank=True)
    content = models.TextField()
    note = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['post', '-created_at']),
        ]

    def __str__(self):
        return f'{self.post.title} @ {self.created_at:%Y-%m-%d %H:%M}'

    @classmethod
    def snapshot(cls, post, user=None, note=''):
        """
        Record the post's current text, unless it is identical to the newest
        revision — an autosave that changed nothing should not fill the history.
        """
        latest = cls.objects.filter(post=post).first()
        if latest and (latest.title, latest.subtitle, latest.content) == (
            post.title, post.subtitle, post.content
        ):
            return None
        return cls.objects.create(
            post=post,
            created_by=user,
            title=post.title,
            subtitle=post.subtitle,
            excerpt=post.excerpt,
            content=post.content,
            note=note,
        )

    def restore_onto(self, post, user=None):
        """Put this revision's text back, after snapshotting what is there now."""
        PostRevision.snapshot(post, user, note='Before restore')
        post.title = self.title
        post.subtitle = self.subtitle
        post.excerpt = self.excerpt
        post.content = self.content
        post.save()
        return post


class Series(models.Model):
    """
    An ordered run of posts — "Web Hacking, part 3 of 7".

    Membership lives on `SeriesPost` rather than a plain many-to-many so the
    order is a real, editable column instead of an accident of insertion.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    description = models.TextField(max_length=1000, blank=True)
    cover = models.ImageField(
        upload_to='series/',
        validators=[validate_image_upload],
        blank=True,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='series',
    )
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'series'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['author', '-created_at']),
            models.Index(fields=['slug']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Series, self.title, self)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f'/series/{self.slug}'

    @property
    def post_count(self):
        return self.entries.count()

    def next_position(self):
        last = self.entries.order_by('-position').first()
        return (last.position + 1) if last else 1


class SeriesPost(models.Model):
    """One post's place in a series."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    series = models.ForeignKey(Series, on_delete=models.CASCADE, related_name='entries')
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='series_entries')
    position = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ['position']
        constraints = [
            # A post appears at most once in a given series, and two posts
            # cannot claim the same slot.
            models.UniqueConstraint(fields=['series', 'post'], name='unique_series_post'),
            models.UniqueConstraint(fields=['series', 'position'], name='unique_series_position'),
        ]
        indexes = [
            models.Index(fields=['series', 'position']),
        ]

    def __str__(self):
        return f'{self.series.title} #{self.position}'


class SeriesProgress(models.Model):
    """
    Which parts of a series a reader has finished.

    One row per (user, post) rather than a counter, so completing part 4 before
    part 3 is recorded honestly instead of being rounded into "4 of 7 done".
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='series_progress',
    )
    series = models.ForeignKey(Series, on_delete=models.CASCADE, related_name='progress')
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='series_progress')
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-completed_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'series', 'post'], name='unique_series_progress',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'series']),
        ]

    def __str__(self):
        return f'{self.user} finished {self.post}'


class ReadingHistory(models.Model):
    """
    What a reader has opened, and how far they got.

    Distinct from `PostView`, which is an anonymous de-duplication ledger for
    the public counter. This one belongs to a signed-in reader and powers
    "continue reading".
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reading_history',
    )
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='reading_history')
    # 0-100. Written by the client as the reader scrolls.
    progress = models.PositiveSmallIntegerField(default=0)
    is_finished = models.BooleanField(default=False)
    last_read_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-last_read_at']
        constraints = [
            # Re-reading updates the row rather than adding another.
            models.UniqueConstraint(fields=['user', 'post'], name='unique_reading_history'),
        ]
        indexes = [
            models.Index(fields=['user', '-last_read_at']),
        ]

    def __str__(self):
        return f'{self.user} read {self.post}'


class PostEmbedding(models.Model):
    """
    A post's meaning, as a vector, for semantic search and related posts.

    Kept in its own table rather than a column on `Post` so that loading a post
    never drags two thousand floats along with it — the vectors are only ever
    wanted in bulk, by the search code.

    `content_hash` is what makes regeneration cheap: an edit that changed only
    the tags leaves the hash alone, so the embedding is not re-bought from the
    provider for nothing.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.OneToOneField(Post, on_delete=models.CASCADE, related_name='embedding')

    vector = models.JSONField(default=list)
    # Stored so a model change can be detected and the index rebuilt, rather
    # than silently comparing vectors from two different models.
    model = models.CharField(max_length=100)
    content_hash = models.CharField(max_length=64)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['model']),
        ]

    def __str__(self):
        return f'embedding of {self.post.title}'

    @staticmethod
    def source_text(post):
        """
        What actually gets embedded.

        Title and subtitle carry disproportionate meaning for their length, so
        they lead. The body is truncated: embedding models have a context limit,
        and the opening of an article is where its subject is established.
        """
        from .utils import plain_text

        parts = [post.title, post.subtitle, post.excerpt, plain_text(post.content)[:4000]]
        return '\n\n'.join(part for part in parts if part)

    @staticmethod
    def hash_for(post):
        import hashlib

        return hashlib.sha256(PostEmbedding.source_text(post).encode()).hexdigest()

    @property
    def is_stale(self):
        """True when the post has changed, or the model has."""
        from django.conf import settings

        if self.model != settings.NVIDIA_EMBED_MODEL:
            return True
        return self.content_hash != PostEmbedding.hash_for(self.post)
