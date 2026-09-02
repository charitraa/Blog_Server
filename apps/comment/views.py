from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.post.models import Post
from blog_server.pagination import LargePagination
from blog_server.permission import CanModerate, IsAuthorOrEditor

from .models import Comment, CommentLike, CommentReport
from .serializers import CommentReportSerializer, CommentSerializer, CommentWriteSerializer


class PostCommentListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/posts/<slug>/comments/   read a post's thread (public)
    POST /api/posts/<slug>/comments/   add a comment or a reply (sign-in required)
    """

    queryset = Comment.objects.none()  # for schema generation only
    pagination_class = LargePagination
    # Ordering is owned by `?sort=` below. Leaving DRF's OrderingFilter in place
    # would re-sort the queryset afterwards and drop pinned comments back down.
    filter_backends = []

    def get_permissions(self):
        # Reading comments must not require an account: the article page is public.
        if self.request.method == 'POST':
            return [IsAuthenticated()]
        return [AllowAny()]

    def get_throttles(self):
        if self.request.method == 'POST':
            self.throttle_scope = 'write'
        return super().get_throttles()

    def get_serializer_class(self):
        return CommentWriteSerializer if self.request.method == 'POST' else CommentSerializer

    def get_post_object(self):
        if not hasattr(self, '_post'):
            identifier = self.kwargs['slug']
            lookup = Q(slug=identifier)
            if len(identifier) == 36 and identifier.count('-') == 4:
                lookup |= Q(pk=identifier)
            self._post = get_object_or_404(Post.objects.visible_to(self.request.user), lookup)
        return self._post

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['post'] = self.get_post_object()
        return context

    # `?sort=` — newest by default, because a discussion reads chronologically.
    SORTS = {
        'newest': ['-is_pinned', '-created_at'],
        'oldest': ['-is_pinned', 'created_at'],
        'popular': ['-is_pinned', '-like_total', '-created_at'],
    }

    def get_queryset(self):
        # Only top-level comments are paginated; replies ride along prefetched,
        # so a full thread costs two queries regardless of its size.
        replies = (
            Comment.objects.visible()
            .select_related('author')
            .annotate(like_total=Count('likes', distinct=True))
            .order_by('created_at')
        )
        queryset = (
            Comment.objects.visible()
            .filter(post=self.get_post_object(), parent__isnull=True)
            .select_related('author')
            .annotate(like_total=Count('likes', distinct=True))
            .prefetch_related(Prefetch('replies', queryset=replies))
        )

        if self.request.user.is_authenticated:
            mine = CommentLike.objects.filter(comment=OuterRef('pk'), user=self.request.user)
            queryset = queryset.annotate(liked_by_me=Exists(mine))

        sort = self.request.query_params.get('sort', 'newest')
        return queryset.order_by(*self.SORTS.get(sort, self.SORTS['newest']))

    def perform_create(self, serializer):
        serializer.save(author=self.request.user, post=self.get_post_object())


class CommentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE /api/comments/<id>/

    `IsAuthorOrEditor` is enforced against the stored object, so a user can
    only ever change their own comment. An editor and above may change any.
    """

    permission_classes = [IsAuthorOrEditor]

    def get_serializer_class(self):
        return CommentWriteSerializer if self.request.method in ('PATCH', 'PUT') else CommentSerializer

    def get_queryset(self):
        replies = Comment.objects.select_related('author').order_by('created_at')
        return Comment.objects.select_related('author', 'post').prefetch_related(
            Prefetch('replies', queryset=replies)
        )

    def perform_update(self, serializer):
        # `parent` and `post` are not writable here: an edit changes text only.
        serializer.save(is_edited=True)


class MyCommentListView(generics.ListAPIView):
    """GET /api/comments/mine/ — the signed-in user's own comments."""

    queryset = Comment.objects.none()  # for schema generation only
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = LargePagination

    def get_queryset(self):
        return (
            Comment.objects.filter(author=self.request.user)
            .select_related('author', 'post')
            .prefetch_related('replies')
        )


class CommentReportView(APIView):
    """
    POST /api/comments/<id>/report/ — flag a comment for a moderator.

    A report never hides anything by itself; it queues the comment for review.
    Reporting the same comment twice updates the existing report rather than
    filing a second one, which keeps the moderation queue honest.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = 'write'
    serializer_class = CommentReportSerializer

    @extend_schema(request=CommentReportSerializer, responses={201: CommentReportSerializer})
    def post(self, request, pk):
        comment = get_object_or_404(Comment, pk=pk)
        if comment.author_id == request.user.id:
            return Response(
                {'detail': 'You cannot report your own comment.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CommentReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        report, created = CommentReport.objects.update_or_create(
            comment=comment,
            reporter=request.user,
            defaults={
                'reason': serializer.validated_data.get('reason', CommentReport.Reason.OTHER),
                'detail': serializer.validated_data.get('detail', ''),
                'status': CommentReport.Status.OPEN,
            },
        )
        return Response(
            CommentReportSerializer(report).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class CommentLikeView(APIView):
    """
    POST   /api/comments/<id>/like/   like
    DELETE /api/comments/<id>/like/   unlike

    Idempotent in both directions, the same way post likes are.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CommentSerializer

    def get_comment(self, pk):
        return get_object_or_404(Comment.objects.visible(), pk=pk)

    def _state(self, comment, liked):
        return Response({'is_liked': liked, 'like_count': comment.likes.count()})

    @extend_schema(request=None, responses={200: None})
    def post(self, request, pk):
        comment = self.get_comment(pk)
        CommentLike.objects.get_or_create(comment=comment, user=request.user)
        return self._state(comment, True)

    @extend_schema(request=None, responses={200: None})
    def delete(self, request, pk):
        comment = self.get_comment(pk)
        CommentLike.objects.filter(comment=comment, user=request.user).delete()
        return self._state(comment, False)


class CommentPinView(APIView):
    """
    POST   /api/comments/<id>/pin/   pin to the top of the thread
    DELETE /api/comments/<id>/pin/   unpin

    Pinning belongs to the post's author — it is their conversation — or to a
    moderator. Only one comment per post is pinned at a time, because a thread
    with four pinned comments has no top.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CommentSerializer

    def get_comment(self, request, pk):
        comment = get_object_or_404(Comment, pk=pk)
        allowed = (
            comment.post.author_id == request.user.id or request.user.can_moderate
        )
        if not allowed:
            return None
        if comment.parent_id is not None:
            return False  # replies cannot be pinned
        return comment

    @extend_schema(request=None, responses={200: CommentSerializer})
    def post(self, request, pk):
        comment = self.get_comment(request, pk)
        if comment is None:
            return Response({'detail': 'You do not have permission to perform this action.'},
                            status=status.HTTP_403_FORBIDDEN)
        if comment is False:
            return Response({'detail': 'Only a top-level comment can be pinned.'},
                            status=status.HTTP_400_BAD_REQUEST)

        Comment.objects.filter(post=comment.post, is_pinned=True).update(is_pinned=False)
        comment.is_pinned = True
        comment.save(update_fields=['is_pinned'])
        return Response(CommentSerializer(comment, context={'request': request}).data)

    @extend_schema(request=None, responses={200: CommentSerializer})
    def delete(self, request, pk):
        comment = self.get_comment(request, pk)
        if comment in (None, False):
            return Response({'detail': 'You do not have permission to perform this action.'},
                            status=status.HTTP_403_FORBIDDEN)
        comment.is_pinned = False
        comment.save(update_fields=['is_pinned'])
        return Response(CommentSerializer(comment, context={'request': request}).data)
