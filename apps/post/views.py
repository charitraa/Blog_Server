import logging

from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from blog_server.pagination import StandardPagination
from blog_server.permission import IsAuthorOrReadOnly

from .filters import PostFilter
from .models import Category, Like, Post, PostView, Tag
from .serializers import (
    CategorySerializer,
    LikeStateSerializer,
    PostDetailSerializer,
    PostListSerializer,
    PostWriteSerializer,
    TagSerializer,
)
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
        queryset = queryset.annotate(is_liked=Exists(liked))
    return queryset


class PostListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/posts/   list published posts (plus your own drafts)
    POST /api/posts/   create a post as the signed-in user
    """

    permission_classes = [IsAuthorOrReadOnly]
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

    permission_classes = [IsAuthorOrReadOnly]
    lookup_field = 'slug'

    def get_throttles(self):
        if self.request.method in ('PATCH', 'PUT', 'DELETE'):
            self.throttle_scope = 'write'
        return super().get_throttles()

    def get_serializer_class(self):
        if self.request.method in ('PATCH', 'PUT'):
            return PostWriteSerializer
        return PostDetailSerializer

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
        return Response(self.get_serializer(post).data)

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

    def perform_destroy(self, instance):
        instance.delete()


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
