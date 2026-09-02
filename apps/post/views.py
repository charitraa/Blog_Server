import logging

from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from blog_server.pagination import StandardPagination
from blog_server.permission import IsAuthorOrEditor

from .filters import PostFilter
from .models import (
    Bookmark, Category, EditorImage, Like, Post, PostRevision, PostView,
    ReadingHistory, Series, SeriesPost, SeriesProgress, Tag,
)
from .serializers import (
    BookmarkStateSerializer,
    CategorySerializer,
    EditorImageSerializer,
    LikeStateSerializer,
    PostAuthorDetailSerializer,
    PostDetailSerializer,
    PostListSerializer,
    AuthorAnalyticsSerializer,
    PostAnalyticsSerializer,
    PostRevisionListSerializer,
    PostRevisionSerializer,
    PostWriteSerializer,
    ReadingHistorySerializer,
    ReadingProgressSerializer,
    SeriesDetailSerializer,
    SeriesSerializer,
    SeriesWriteSerializer,
    TagSerializer,
)
from .analytics import author_analytics, post_analytics
from .utils import viewer_fingerprint

logger = logging.getLogger('apps.post')

# Ordering keys a client may ask for. Anything else is rejected by DRF rather
# than passed through to the ORM.
ALLOWED_ORDERING = [
    'published_at', '-published_at',
    'created_at', '-created_at',
    'view_count', '-view_count',
    'like_count', '-like_count',
    'comment_count', '-comment_count',
    'title', '-title',
]


def annotated_posts(request):
    """
    Base queryset for every post endpoint.

    Visibility, join prefetching, counters and the per-user `is_liked` flag are
    all resolved in a single query so list pages never issue N+1 lookups.
    """
    queryset = Post.objects.visible_to(request.user).with_related().with_counts()

    if request.user.is_authenticated:
        liked = Like.objects.filter(post=OuterRef('pk'), user=request.user)
        bookmarked = Bookmark.objects.filter(post=OuterRef('pk'), user=request.user)
        queryset = queryset.annotate(
            is_liked=Exists(liked),
            is_bookmarked=Exists(bookmarked),
        )
    return queryset


class PostListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/posts/   list published posts (plus your own drafts)
    POST /api/posts/   create a post as the signed-in user
    """

    permission_classes = [IsAuthorOrEditor]
    pagination_class = StandardPagination
    filterset_class = PostFilter
    search_fields = ['title', 'excerpt', 'content', 'author__username',
                     'author__first_name', 'author__last_name',
                     'category__name', 'tags__name']
    ordering_fields = ALLOWED_ORDERING
    ordering = ['-published_at', '-created_at']

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated()]
        return [AllowAny()]

    def get_throttles(self):
        if self.request.method == 'POST':
            self.throttle_scope = 'write'
        return super().get_throttles()

    def get_serializer_class(self):
        return PostWriteSerializer if self.request.method == 'POST' else PostListSerializer

    def get_queryset(self):
        queryset = annotated_posts(self.request)
        # `?search=` across tags can multiply rows; collapse them.
        if self.request.query_params.get('search') or self.request.query_params.get('tag'):
            queryset = queryset.distinct()
        return queryset


class PostDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE /api/posts/<slug>/

    `slug` also accepts a post's UUID, so links built against the original
    id-based routes keep resolving.
    """

    permission_classes = [IsAuthorOrEditor]
    lookup_field = 'slug'

    def get_throttles(self):
        if self.request.method in ('PATCH', 'PUT', 'DELETE'):
            self.throttle_scope = 'write'
        return super().get_throttles()

    def get_serializer_class(self):
        if self.request.method in ('PATCH', 'PUT'):
            return PostWriteSerializer
        return PostDetailSerializer

    def author_aware_serializer(self, post):
        """Only the post's own author (or staff) is shown the preview token."""
        user = self.request.user
        if user.is_authenticated and (post.author_id == user.id or user.is_staff):
            return PostAuthorDetailSerializer(post, context=self.get_serializer_context())
        return PostDetailSerializer(post, context=self.get_serializer_context())

    def get_queryset(self):
        return annotated_posts(self.request)

    def get_object(self):
        identifier = self.kwargs['slug']
        queryset = self.get_queryset()

        lookup = Q(slug=identifier)
        # A 36-character identifier is a UUID from the legacy routes.
        if len(identifier) == 36 and identifier.count('-') == 4:
            lookup |= Q(pk=identifier)

        post = get_object_or_404(queryset, lookup)
        self.check_object_permissions(self.request, post)
        return post

    def retrieve(self, request, *args, **kwargs):
        post = self.get_object()
        self.record_view(request, post)
        return Response(self.author_aware_serializer(post).data)

    def record_view(self, request, post):
        """
        Count a reader once.

        `PostView` has a unique (post, fingerprint) constraint, so repeated
        requests — a refresh, React re-rendering, two tabs — insert nothing and
        leave the counter alone. The author's own visits are not counted.
        """
        if post.author_id == getattr(request.user, 'id', None):
            return
        if not post.is_published:
            return

        fingerprint = viewer_fingerprint(request)
        try:
            with transaction.atomic():
                PostView.objects.create(
                    post=post,
                    user=request.user if request.user.is_authenticated else None,
                    fingerprint=fingerprint,
                )
        except IntegrityError:
            return  # Already counted for this viewer.

        # F() so concurrent readers cannot overwrite each other's increment.
        Post.objects.filter(pk=post.pk).update(view_count=F('view_count') + 1)
        post.view_count += 1

    def perform_update(self, serializer):
        """Record what the post said before this edit, so it can be rolled back."""
        PostRevision.snapshot(self.get_object(), self.request.user)
        serializer.save()

    def perform_destroy(self, instance):
        """
        Delete is a soft delete.

        The row survives in the author's trash, which keeps the comments and
        likes attached to it and makes a misclick recoverable. Staff can purge
        for real from the Django admin.
        """
        instance.soft_delete()


class PostLikeView(APIView):
    """
    POST   /api/posts/<slug>/like/   like
    DELETE /api/posts/<slug>/like/   unlike

    Both are idempotent: the unique (post, user) constraint means a double tap
    can never create a second like, whatever the client does.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = LikeStateSerializer

    def get_post(self, slug):
        return get_object_or_404(Post.objects.visible_to(self.request.user), slug=slug)

    def _state(self, post, is_liked):
        return Response(LikeStateSerializer({
            'is_liked': is_liked,
            'like_count': Like.objects.filter(post=post).count(),
        }).data)

    @extend_schema(request=None, responses={200: LikeStateSerializer})
    def post(self, request, slug):
        post = self.get_post(slug)
        try:
            Like.objects.get_or_create(post=post, user=request.user)
        except IntegrityError:
            pass  # Won a race with another request from the same user.
        return self._state(post, True)

    @extend_schema(request=None, responses={200: LikeStateSerializer})
    def delete(self, request, slug):
        post = self.get_post(slug)
        Like.objects.filter(post=post, user=request.user).delete()
        return self._state(post, False)


class TrendingPostListView(generics.ListAPIView):
    """
    GET /api/posts/trending/

    Ranked by real engagement, never by a fabricated score:

        trend = likes*3 + comments*2 + views*0.5

    Likes weigh most because they cost the reader a deliberate action, comments
    next, views least since they are the cheapest signal. The window is limited
    to recent posts (`?days=`, 30 by default) so the list keeps moving instead
    of permanently pinning whatever did well once.
    """

    serializer_class = PostListSerializer
    permission_classes = [AllowAny]
    pagination_class = StandardPagination

    def get_queryset(self):
        from datetime import timedelta

        try:
            days = min(max(int(self.request.query_params.get('days', 30)), 1), 365)
        except (TypeError, ValueError):
            days = 30

        since = timezone.now() - timedelta(days=days)
        queryset = annotated_posts(self.request).filter(
            status=Post.Status.PUBLISHED, published_at__gte=since
        )
        return queryset.annotate(
            trend_score=F('like_count') * 3 + F('comment_count') * 2 + F('view_count') * 0.5
        ).order_by('-trend_score', '-published_at')


class AuthorPostListView(generics.ListAPIView):
    """
    GET /api/users/<username>/posts/

    A visitor sees only published work. Authors see their own drafts here too,
    and `?status=draft` is filtered against the already-narrowed queryset, so
    one author can never enumerate another's drafts.
    """

    queryset = Post.objects.none()  # for schema generation only
    serializer_class = PostListSerializer
    permission_classes = [AllowAny]
    pagination_class = StandardPagination
    filterset_class = PostFilter
    ordering_fields = ALLOWED_ORDERING
    ordering = ['-published_at', '-created_at']

    def get_queryset(self):
        from django.contrib.auth import get_user_model

        author = get_object_or_404(
            get_user_model(), username__iexact=self.kwargs['username'], is_active=True
        )
        return annotated_posts(self.request).filter(author=author)


class MyPostListView(generics.ListAPIView):
    """GET /api/posts/mine/ — the signed-in author's own posts, drafts included."""

    queryset = Post.objects.none()  # for schema generation only
    serializer_class = PostListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filterset_class = PostFilter
    ordering_fields = ALLOWED_ORDERING
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = Post.objects.filter(author=self.request.user).with_related().with_counts()
        liked = Like.objects.filter(post=OuterRef('pk'), user=self.request.user)
        return queryset.annotate(is_liked=Exists(liked))


class CategoryListView(generics.ListAPIView):
    """GET /api/categories/ — every category with its published post count."""

    serializer_class = CategorySerializer
    permission_classes = [AllowAny]
    pagination_class = None  # Small, fixed set; the UI wants it in one call.
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'post_count']
    ordering = ['name']

    def get_queryset(self):
        return Category.objects.annotate(
            post_count=Count('posts', filter=Q(posts__status=Post.Status.PUBLISHED), distinct=True)
        )


class CategoryDetailView(generics.RetrieveAPIView):
    """GET /api/categories/<slug>/"""

    serializer_class = CategorySerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        return Category.objects.annotate(
            post_count=Count('posts', filter=Q(posts__status=Post.Status.PUBLISHED), distinct=True)
        )


class TagListView(generics.ListAPIView):
    """GET /api/tags/ — tags that are actually in use, most used first."""

    serializer_class = TagSerializer
    permission_classes = [AllowAny]
    pagination_class = StandardPagination
    search_fields = ['name']
    ordering_fields = ['name', 'post_count']
    ordering = ['-post_count', 'name']

    def get_queryset(self):
        return Tag.objects.annotate(
            post_count=Count('posts', filter=Q(posts__status=Post.Status.PUBLISHED), distinct=True)
        ).filter(post_count__gt=0)


class RelatedPostListView(generics.ListAPIView):
    """
    GET /api/posts/<slug>/related/

    Posts sharing the category or any tag, most recent first. Falls back to the
    latest published posts when a post has neither, so the section is never empty.
    """

    queryset = Post.objects.none()  # for schema generation only
    serializer_class = PostListSerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        post = get_object_or_404(Post.objects.published(), slug=self.kwargs['slug'])
        base = annotated_posts(self.request).filter(status=Post.Status.PUBLISHED).exclude(pk=post.pk)

        related = base.filter(
            Q(category__isnull=False, category_id=post.category_id) | Q(tags__in=post.tags.all())
        ).distinct()[:3]

        results = list(related)
        if len(results) < 3:
            seen = {item.pk for item in results} | {post.pk}
            filler = base.exclude(pk__in=seen)[: 3 - len(results)]
            results.extend(filler)
        return results


# ---------------------------------------------------------------------------
# Legacy compatibility
# ---------------------------------------------------------------------------
# The original API addressed authors by primary key under /post/posts/user/<id>/.
# These views keep those URLs answering, now with the same visibility rules as
# the rest of the API, so an old client cannot see drafts it should not.

class LegacyAuthorPostListView(generics.ListAPIView):
    """GET /post/posts/user/<user_id>/ — posts by author primary key."""

    queryset = Post.objects.none()  # for schema generation only
    serializer_class = PostListSerializer
    permission_classes = [AllowAny]
    pagination_class = StandardPagination

    def get_queryset(self):
        return annotated_posts(self.request).filter(author_id=self.kwargs['user_id'])


class LegacyAuthorPostCountView(APIView):
    """GET /post/posts/count/<user_id>/ — number of visible posts by that author."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: None})
    def get(self, request, user_id):
        count = Post.objects.visible_to(request.user).filter(author_id=user_id).count()
        return Response({'post_count': count})


# ---------------------------------------------------------------------------
# Bookmarks, uploads and draft previews
# ---------------------------------------------------------------------------

class PostBookmarkView(APIView):
    """
    POST   /api/posts/<slug>/bookmark/   save for later
    DELETE /api/posts/<slug>/bookmark/   remove from the reading list

    Idempotent in both directions: the unique constraint on (post, user) means
    a double-tap cannot create two rows, and removing something that was never
    saved is a no-op rather than a 404.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = BookmarkStateSerializer

    def get_post(self, slug):
        return get_object_or_404(Post.objects.visible_to(self.request.user), slug=slug)

    @extend_schema(request=None, responses={200: BookmarkStateSerializer})
    def post(self, request, slug):
        post = self.get_post(slug)
        Bookmark.objects.get_or_create(post=post, user=request.user)
        return Response({'is_bookmarked': True})

    @extend_schema(request=None, responses={200: BookmarkStateSerializer})
    def delete(self, request, slug):
        post = self.get_post(slug)
        Bookmark.objects.filter(post=post, user=request.user).delete()
        return Response({'is_bookmarked': False})


class BookmarkListView(generics.ListAPIView):
    """
    GET /api/bookmarks/ — the signed-in reader's saved posts.

    Ordered by when they were saved, not when the post was published, because
    that is the order the reader built the list in.
    """

    serializer_class = PostListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filterset_class = PostFilter
    search_fields = ['title', 'excerpt', 'author__username']
    queryset = Post.objects.none()  # for schema generation only

    def get_queryset(self):
        return (
            annotated_posts(self.request)
            .filter(bookmarks__user=self.request.user)
            .order_by('-bookmarks__created_at')
        )


class EditorImageUploadView(generics.CreateAPIView):
    """
    POST /api/uploads/images/ — multipart upload for images used inside a post
    body.

    Answers with the absolute URL the editor inserts into the article. Rate
    limited under the `write` scope so an account cannot be used to fill the
    disk.
    """

    serializer_class = EditorImageSerializer
    permission_classes = [IsAuthenticated]
    throttle_scope = 'write'
    queryset = EditorImage.objects.none()  # for schema generation only


class MyEditorImageListView(generics.ListAPIView):
    """GET /api/uploads/images/mine/ — images this author has uploaded."""

    serializer_class = EditorImageSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = []

    def get_queryset(self):
        return EditorImage.objects.filter(uploaded_by=self.request.user)


class PostPreviewView(APIView):
    """
    GET /api/posts/<slug>/preview/?token=<uuid>

    Reads an unpublished draft without signing in, for sharing with an editor
    or reviewer. The token is the entire authorisation, so it is compared in
    full and a wrong one is indistinguishable from a missing post.
    """

    permission_classes = [AllowAny]
    serializer_class = PostDetailSerializer

    @extend_schema(
        parameters=[OpenApiParameter('token', str, required=True,
                                     description='The post\'s preview_token.')],
        responses={200: PostDetailSerializer},
    )
    def get(self, request, slug):
        token = request.query_params.get('token', '')
        if not token:
            return Response(
                {'detail': 'A preview token is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Deliberately not `visible_to`: a valid token is what grants access.
        post = Post.objects.with_related().with_counts().filter(slug=slug).first()
        if post is None or str(post.preview_token) != str(token):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        # A preview is not a real readership signal, so it is not counted.
        return Response(PostDetailSerializer(post, context={'request': request}).data)


class PostPreviewTokenView(APIView):
    """
    POST /api/posts/<slug>/preview-token/ — rotate the draft's preview token,
    which revokes every share link handed out so far.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PostAuthorDetailSerializer

    @extend_schema(request=None, responses={200: PostAuthorDetailSerializer})
    def post(self, request, slug):
        import uuid as uuid_module

        post = get_object_or_404(Post, slug=slug)
        if post.author_id != request.user.id and not request.user.is_staff:
            return Response(
                {'detail': 'You do not have permission to perform this action.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        post.preview_token = uuid_module.uuid4()
        post.save(update_fields=['preview_token'])
        return Response(PostAuthorDetailSerializer(post, context={'request': request}).data)


# ---------------------------------------------------------------------------
# Post lifecycle: archive, trash, duplicate, revisions
# ---------------------------------------------------------------------------

class PostLifecycleView(APIView):
    """
    POST /api/posts/<slug>/<action>/ where action is archive, unarchive,
    restore or duplicate.

    Grouped into one view because they share the same ownership check and all
    answer with the post afterwards, so the client can drop the result straight
    into its cache.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PostAuthorDetailSerializer

    ACTIONS = ('archive', 'unarchive', 'restore', 'duplicate')

    def get_post(self, request, slug):
        # Deliberately not `visible_to`: archived and trashed posts are exactly
        # the ones these actions operate on.
        post = get_object_or_404(Post.objects.all(), slug=slug)
        if post.author_id != request.user.id and not request.user.can_edit_others:
            return None
        return post

    @extend_schema(request=None, responses={200: PostAuthorDetailSerializer})
    def post(self, request, slug, action):
        if action not in self.ACTIONS:
            return Response({'detail': f'Unknown action "{action}".'},
                            status=status.HTTP_400_BAD_REQUEST)

        post = self.get_post(request, slug)
        if post is None:
            return Response({'detail': 'You do not have permission to perform this action.'},
                            status=status.HTTP_403_FORBIDDEN)

        if action == 'archive':
            post.archive()
        elif action == 'unarchive':
            post.unarchive()
        elif action == 'restore':
            post.restore()
        else:
            post = post.duplicate(author=request.user)

        return Response(
            PostAuthorDetailSerializer(post, context={'request': request}).data,
            status=status.HTTP_201_CREATED if action == 'duplicate' else status.HTTP_200_OK,
        )


class TrashListView(generics.ListAPIView):
    """GET /api/posts/trash/ — the author's soft-deleted posts."""

    serializer_class = PostListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = []
    queryset = Post.objects.none()  # for schema generation only

    def get_queryset(self):
        return (
            Post.objects.filter(author=self.request.user, deleted_at__isnull=False)
            .with_related()
            .with_counts()
            .order_by('-deleted_at')
        )


class PostRevisionListView(generics.ListAPIView):
    """GET /api/posts/<slug>/revisions/ — the edit history, newest first."""

    serializer_class = PostRevisionListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = []
    queryset = PostRevision.objects.none()  # for schema generation only

    def get_queryset(self):
        post = get_object_or_404(Post.objects.all(), slug=self.kwargs['slug'])
        user = self.request.user
        if post.author_id != user.id and not user.can_edit_others:
            return PostRevision.objects.none()
        return PostRevision.objects.filter(post=post).select_related('created_by')


class PostRevisionDetailView(APIView):
    """
    GET  /api/posts/<slug>/revisions/<id>/          read one revision in full
    POST /api/posts/<slug>/revisions/<id>/restore/  put its text back
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PostRevisionSerializer

    def get_objects(self, request, slug, pk):
        post = get_object_or_404(Post.objects.all(), slug=slug)
        if post.author_id != request.user.id and not request.user.can_edit_others:
            return None, None
        revision = get_object_or_404(PostRevision, pk=pk, post=post)
        return post, revision

    @extend_schema(responses={200: PostRevisionSerializer})
    def get(self, request, slug, pk):
        post, revision = self.get_objects(request, slug, pk)
        if post is None:
            return Response({'detail': 'You do not have permission to perform this action.'},
                            status=status.HTTP_403_FORBIDDEN)
        return Response(PostRevisionSerializer(revision, context={'request': request}).data)

    @extend_schema(request=None, responses={200: PostAuthorDetailSerializer})
    def post(self, request, slug, pk):
        post, revision = self.get_objects(request, slug, pk)
        if post is None:
            return Response({'detail': 'You do not have permission to perform this action.'},
                            status=status.HTTP_403_FORBIDDEN)

        revision.restore_onto(post, request.user)
        return Response(PostAuthorDetailSerializer(post, context={'request': request}).data)


# ---------------------------------------------------------------------------
# Reading history
# ---------------------------------------------------------------------------

class ReadingProgressView(APIView):
    """
    POST /api/posts/<slug>/progress/ — record how far the reader has got.

    Called as someone scrolls, so it updates a single row per (reader, post)
    rather than appending, and never fails loudly: losing a scroll position is
    not worth an error in the reader's face.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ReadingProgressSerializer

    @extend_schema(request=ReadingProgressSerializer, responses={200: None})
    def post(self, request, slug):
        post = get_object_or_404(Post.objects.visible_to(request.user), slug=slug)

        serializer = ReadingProgressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        progress = serializer.validated_data['progress']
        ReadingHistory.objects.update_or_create(
            user=request.user,
            post=post,
            defaults={
                'progress': progress,
                # Reaching the end counts as finished even if the client did not say so.
                'is_finished': serializer.validated_data.get('is_finished') or progress >= 95,
            },
        )
        return Response({'progress': progress})


class ReadingHistoryListView(generics.ListAPIView):
    """GET /api/reading-history/ — what this reader has opened, most recent first."""

    serializer_class = ReadingHistorySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = []
    queryset = ReadingHistory.objects.none()  # for schema generation only

    def get_queryset(self):
        queryset = ReadingHistory.objects.filter(user=self.request.user).select_related(
            'post', 'post__author', 'post__category'
        ).prefetch_related('post__tags')

        if self.request.query_params.get('unfinished') in ('true', '1'):
            # "Continue reading": started, not finished.
            queryset = queryset.filter(is_finished=False, progress__gt=0)
        return queryset


class ReadingHistoryClearView(APIView):
    """DELETE /api/reading-history/ — forget everything, or one post."""

    permission_classes = [IsAuthenticated]
    serializer_class = ReadingHistorySerializer

    @extend_schema(request=None, responses={204: None})
    def delete(self, request):
        queryset = ReadingHistory.objects.filter(user=request.user)
        slug = request.query_params.get('post')
        if slug:
            queryset = queryset.filter(post__slug=slug)
        removed, _ = queryset.delete()
        return Response({'removed': removed}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

def annotated_series(request):
    """Series with the counters the cards render, in one query."""
    queryset = Series.objects.select_related('author').annotate(
        entry_count=Count('entries', distinct=True),
    )
    if request.user.is_authenticated:
        queryset = queryset.annotate(
            completed_count=Count(
                'progress', filter=Q(progress__user=request.user), distinct=True,
            )
        )
    return queryset


class SeriesListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/series/   published series
    POST /api/series/   start one (anybody who can write)
    """

    permission_classes = [AllowAny]
    pagination_class = StandardPagination
    search_fields = ['title', 'description', 'author__username']
    ordering_fields = ['created_at', 'title', 'entry_count']
    ordering = ['-created_at']

    def get_permissions(self):
        return [IsAuthenticated()] if self.request.method == 'POST' else [AllowAny()]

    def get_serializer_class(self):
        return SeriesWriteSerializer if self.request.method == 'POST' else SeriesSerializer

    def get_queryset(self):
        queryset = annotated_series(self.request)
        user = self.request.user
        if user.is_authenticated:
            # An author always sees their own unpublished series.
            return queryset.filter(Q(is_published=True) | Q(author=user))
        return queryset.filter(is_published=True)


class SeriesDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/series/<slug>/"""

    permission_classes = [IsAuthorOrEditor]
    lookup_field = 'slug'

    def get_serializer_class(self):
        if self.request.method in ('PATCH', 'PUT'):
            return SeriesWriteSerializer
        return SeriesDetailSerializer

    def get_queryset(self):
        # Parts are ordered by position and carry everything the row renders.
        entries = SeriesPost.objects.select_related(
            'post', 'post__author', 'post__category'
        ).prefetch_related('post__tags').order_by('position')
        return annotated_series(self.request).prefetch_related(
            Prefetch('entries', queryset=entries)
        )


class SeriesEntryView(APIView):
    """
    POST   /api/series/<slug>/posts/   add a post, optionally at a position
    DELETE /api/series/<slug>/posts/   remove one (`post` in the body or query)

    Positions are compacted after a removal so a series never shows "part 4"
    with no part 3.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SeriesDetailSerializer

    def get_series(self, request, slug):
        series = get_object_or_404(Series, slug=slug)
        if series.author_id != request.user.id and not request.user.can_edit_others:
            return None
        return series

    def _respond(self, series, request):
        series = self.get_queryset_detail(request).get(pk=series.pk)
        return Response(SeriesDetailSerializer(series, context={'request': request}).data)

    def get_queryset_detail(self, request):
        entries = SeriesPost.objects.select_related(
            'post', 'post__author', 'post__category'
        ).prefetch_related('post__tags').order_by('position')
        return annotated_series(request).prefetch_related(Prefetch('entries', queryset=entries))

    @extend_schema(request=None, responses={200: SeriesDetailSerializer})
    def post(self, request, slug):
        series = self.get_series(request, slug)
        if series is None:
            return Response({'detail': 'You do not have permission to perform this action.'},
                            status=status.HTTP_403_FORBIDDEN)

        post = get_object_or_404(
            Post.objects.visible_to(request.user), slug=request.data.get('post', '')
        )
        entry, created = SeriesPost.objects.get_or_create(
            series=series, post=post, defaults={'position': series.next_position()},
        )
        if not created and 'position' in request.data:
            entry.position = int(request.data['position'])
            entry.save(update_fields=['position'])

        return self._respond(series, request)

    @extend_schema(request=None, responses={200: SeriesDetailSerializer})
    def delete(self, request, slug):
        series = self.get_series(request, slug)
        if series is None:
            return Response({'detail': 'You do not have permission to perform this action.'},
                            status=status.HTTP_403_FORBIDDEN)

        slug_to_remove = request.data.get('post') or request.query_params.get('post', '')
        SeriesPost.objects.filter(series=series, post__slug=slug_to_remove).delete()

        # Close the gap the removal left.
        for index, entry in enumerate(series.entries.order_by('position'), start=1):
            if entry.position != index:
                entry.position = index
                entry.save(update_fields=['position'])

        return self._respond(series, request)


class SeriesReorderView(APIView):
    """
    POST /api/series/<slug>/reorder/ with `{"slugs": [...]}`.

    Takes the whole running order rather than a move-one instruction, which
    makes drag-and-drop a single request and cannot leave a half-applied order.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SeriesDetailSerializer

    @extend_schema(request=None, responses={200: SeriesDetailSerializer})
    def post(self, request, slug):
        series = get_object_or_404(Series, slug=slug)
        if series.author_id != request.user.id and not request.user.can_edit_others:
            return Response({'detail': 'You do not have permission to perform this action.'},
                            status=status.HTTP_403_FORBIDDEN)

        order = request.data.get('slugs') or []
        if not isinstance(order, list):
            return Response({'detail': 'Expected a list of post slugs.'},
                            status=status.HTTP_400_BAD_REQUEST)

        entries = {entry.post.slug: entry for entry in series.entries.select_related('post')}
        with transaction.atomic():
            # Park everything above the real range first: positions are unique
            # per series, so assigning in place would collide mid-way.
            offset = len(entries) + 1000
            for index, entry in enumerate(entries.values()):
                SeriesPost.objects.filter(pk=entry.pk).update(position=offset + index)

            position = 1
            for post_slug in order:
                entry = entries.get(post_slug)
                if entry is None:
                    continue
                SeriesPost.objects.filter(pk=entry.pk).update(position=position)
                position += 1

            # Anything the client did not mention keeps a stable slot at the end.
            for post_slug, entry in entries.items():
                if post_slug not in order:
                    SeriesPost.objects.filter(pk=entry.pk).update(position=position)
                    position += 1

        series.refresh_from_db()
        detail = SeriesEntryView().get_queryset_detail(request).get(pk=series.pk)
        return Response(SeriesDetailSerializer(detail, context={'request': request}).data)


class SeriesProgressView(APIView):
    """
    POST   /api/series/<slug>/progress/   mark a part finished
    DELETE /api/series/<slug>/progress/   mark it unfinished again
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SeriesDetailSerializer

    def _post_in_series(self, slug, post_slug):
        series = get_object_or_404(Series, slug=slug)
        entry = get_object_or_404(SeriesPost, series=series, post__slug=post_slug)
        return series, entry.post

    @extend_schema(request=None, responses={200: None})
    def post(self, request, slug):
        series, post = self._post_in_series(slug, request.data.get('post', ''))
        SeriesProgress.objects.get_or_create(user=request.user, series=series, post=post)
        return Response({
            'completed': SeriesProgress.objects.filter(user=request.user, series=series).count(),
        })

    @extend_schema(request=None, responses={200: None})
    def delete(self, request, slug):
        post_slug = request.data.get('post') or request.query_params.get('post', '')
        series, post = self._post_in_series(slug, post_slug)
        SeriesProgress.objects.filter(user=request.user, series=series, post=post).delete()
        return Response({
            'completed': SeriesProgress.objects.filter(user=request.user, series=series).count(),
        })


class FeedView(generics.ListAPIView):
    """
    GET /api/posts/feed/ — posts from the authors, categories and tags this
    reader follows.

    Deliberately chronological rather than ranked: the reader chose these
    subscriptions, so reordering them would be second-guessing an explicit
    instruction. `?days=` narrows the window.
    """

    serializer_class = PostListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filterset_class = PostFilter
    ordering_fields = ALLOWED_ORDERING
    ordering = ['-published_at']
    queryset = Post.objects.none()  # for schema generation only

    @extend_schema(
        parameters=[OpenApiParameter('days', int, required=False,
                                     description='Only posts from the last N days.')],
        responses={200: PostListSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        from apps.user.models import Follow, TopicFollow

        user = self.request.user
        authors = Follow.objects.filter(follower=user).values('following_id')
        categories = TopicFollow.objects.filter(
            user=user, category__isnull=False
        ).values('category_id')
        tags = TopicFollow.objects.filter(user=user, tag__isnull=False).values('tag_id')

        queryset = annotated_posts(self.request).filter(
            Q(author_id__in=authors)
            | Q(category_id__in=categories)
            | Q(tags__id__in=tags)
        ).exclude(author=user).distinct()

        days = self.request.query_params.get('days')
        if days and days.isdigit():
            queryset = queryset.filter(
                published_at__gte=timezone.now() - timedelta(days=int(days))
            )
        return queryset


class RecommendedPostsView(generics.ListAPIView):
    """
    GET /api/posts/recommended/ — "because you read X".

    Content-based rather than collaborative: the signal is the categories and
    tags of what this reader has actually liked, bookmarked or finished. That
    works from the first article, where a collaborative model would need a
    population of similar readers before it could say anything.
    """

    serializer_class = PostListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = []
    queryset = Post.objects.none()  # for schema generation only

    def get_queryset(self):
        user = self.request.user

        # Everything the reader has shown an interest in.
        engaged = Post.objects.filter(
            Q(likes__user=user) | Q(bookmarks__user=user)
            | Q(reading_history__user=user, reading_history__is_finished=True)
        ).distinct()

        category_ids = list(
            engaged.exclude(category__isnull=True).values_list('category_id', flat=True)
        )
        tag_ids = list(engaged.values_list('tags__id', flat=True))
        seen_ids = list(engaged.values_list('id', flat=True))

        queryset = annotated_posts(self.request).exclude(author=user)
        if not category_ids and not tag_ids:
            # Nothing to go on yet: fall back to what is doing well, which is a
            # better cold start than an empty page.
            return queryset.order_by('-view_count', '-published_at')

        # Rank by how many of the reader's interests a post matches, so a post
        # sharing both a category and two tags outranks one sharing a tag.
        return (
            queryset.filter(Q(category_id__in=category_ids) | Q(tags__id__in=tag_ids))
            .exclude(id__in=seen_ids)
            .annotate(
                overlap=Count('tags', filter=Q(tags__id__in=tag_ids), distinct=True)
            )
            .distinct()
            .order_by('-overlap', '-like_count', '-published_at')
        )


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def _requested_days(request, default=30, maximum=365):
    raw = request.query_params.get('days', '')
    if raw.isdigit():
        return max(1, min(int(raw), maximum))
    return default


class PostAnalyticsView(APIView):
    """
    GET /api/posts/<slug>/analytics/?days=30

    Only the post's author (or an editor) may read it: view counts and
    completion rates are the author's business, not a public metric.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PostAnalyticsSerializer

    @extend_schema(
        parameters=[OpenApiParameter('days', int, required=False)],
        responses={200: PostAnalyticsSerializer},
    )
    def get(self, request, slug):
        post = get_object_or_404(Post.objects.all(), slug=slug)
        if post.author_id != request.user.id and not request.user.can_edit_others:
            return Response({'detail': 'You do not have permission to perform this action.'},
                            status=status.HTTP_403_FORBIDDEN)

        data = post_analytics(post, _requested_days(request))
        return Response(PostAnalyticsSerializer(data).data)


class AuthorAnalyticsView(APIView):
    """GET /api/users/me/analytics/?days=30 — totals across everything you publish."""

    permission_classes = [IsAuthenticated]
    serializer_class = AuthorAnalyticsSerializer

    @extend_schema(
        parameters=[OpenApiParameter('days', int, required=False)],
        responses={200: AuthorAnalyticsSerializer},
    )
    def get(self, request):
        data = author_analytics(request.user, _requested_days(request))
        return Response(AuthorAnalyticsSerializer(data).data)
