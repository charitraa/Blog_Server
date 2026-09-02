from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.post.models import Post
from blog_server.pagination import LargePagination
from blog_server.permission import IsAuthorOrReadOnly

from .models import Comment, CommentReport
from .serializers import CommentReportSerializer, CommentSerializer, CommentWriteSerializer


class PostCommentListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/posts/<slug>/comments/   read a post's thread (public)
    POST /api/posts/<slug>/comments/   add a comment or a reply (sign-in required)
    """

    queryset = Comment.objects.none()  # for schema generation only
    pagination_class = LargePagination
    ordering_fields = ['created_at']
    ordering = ['-created_at']

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

    def get_queryset(self):
        # Only top-level comments are paginated; replies ride along prefetched,
        # so a full thread costs two queries regardless of its size.
        replies = Comment.objects.select_related('author').order_by('created_at')
        return (
            Comment.objects.visible()
            .filter(post=self.get_post_object(), parent__isnull=True)
            .select_related('author')
            .prefetch_related(Prefetch('replies', queryset=replies))
        )

    def perform_create(self, serializer):
        serializer.save(author=self.request.user, post=self.get_post_object())


class CommentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE /api/comments/<id>/

    `IsAuthorOrReadOnly` is enforced against the stored object, so a user can
    only ever change their own comment. Staff may moderate any of them.
    """

    permission_classes = [IsAuthorOrReadOnly]

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
