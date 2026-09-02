"""
Staff-only administration endpoints, mounted at /api/admin/.

Authority is checked with the capability permissions in
`blog_server.permission`, never by comparing role names here, so the ladder in
`apps.user.models.Role` stays the single source of truth.
"""

import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.comment.models import Comment, CommentReport
from apps.newsletter.models import NewsletterSubscriber
from apps.post.models import Like, Post
from blog_server.pagination import StandardPagination
from blog_server.permission import CanManageUsers, CanModerate

from .admin_serializers import (
    AdminStatsSerializer,
    AdminUserSerializer,
    ModerationActionSerializer,
    ModerationReportSerializer,
    RoleUpdateSerializer,
    SuspendSerializer,
)
from .models import ROLE_RANK, Role

logger = logging.getLogger('apps.user')
User = get_user_model()


class AdminStatsView(APIView):
    """GET /api/admin/stats/ — the numbers on the admin dashboard."""

    permission_classes = [CanModerate]
    serializer_class = AdminStatsSerializer

    @extend_schema(responses={200: AdminStatsSerializer})
    def get(self, request):
        week_ago = timezone.now() - timedelta(days=7)

        # One aggregate per table rather than a count per statistic.
        posts = Post.objects.aggregate(
            total=Count('id'),
            published=Count('id', filter=Q(status=Post.Status.PUBLISHED)),
            drafts=Count('id', filter=Q(status=Post.Status.DRAFT)),
            views=Sum('view_count'),
        )
        users = User.objects.aggregate(
            total=Count('id'),
            recent=Count('id', filter=Q(date_joined__gte=week_ago)),
            suspended=Count('id', filter=Q(is_suspended=True)),
        )
        comments = Comment.objects.aggregate(
            total=Count('id'),
            hidden=Count('id', filter=Q(is_hidden=True)),
        )

        roles = dict(
            User.objects.values_list('role').annotate(n=Count('id')).values_list('role', 'n')
        )

        return Response(AdminStatsSerializer({
            'total_users': users['total'],
            'new_users_this_week': users['recent'],
            'suspended_users': users['suspended'],
            'total_posts': posts['total'],
            'published_posts': posts['published'],
            'draft_posts': posts['drafts'],
            'total_comments': comments['total'],
            'hidden_comments': comments['hidden'],
            'open_reports': CommentReport.objects.filter(status=CommentReport.Status.OPEN).count(),
            'total_views': posts['views'] or 0,
            'total_likes': Like.objects.count(),
            'newsletter_subscribers': NewsletterSubscriber.objects.filter(
                is_confirmed=True, is_active=True
            ).count(),
            'roles': roles,
        }).data)


class AdminUserListView(generics.ListAPIView):
    """
    GET /api/admin/users/ — every account, including ones with nothing published.

    Unlike the public author directory this exposes emails and roles, which is
    why it sits behind `CanManageUsers`.
    """

    serializer_class = AdminUserSerializer
    permission_classes = [CanManageUsers]
    pagination_class = StandardPagination
    search_fields = ['username', 'email', 'first_name', 'last_name']
    ordering_fields = ['date_joined', 'username', 'role', 'post_count']
    ordering = ['-date_joined']

    def get_queryset(self):
        queryset = User.objects.annotate(post_count=Count('author_post', distinct=True))

        role = self.request.query_params.get('role')
        if role:
            queryset = queryset.filter(role=role)

        state = self.request.query_params.get('state')
        if state == 'suspended':
            queryset = queryset.filter(is_suspended=True)
        elif state == 'unverified':
            queryset = queryset.filter(is_verified=False)
        return queryset


class AdminUserRoleView(APIView):
    """
    PATCH /api/admin/users/<username>/role/

    Two rules the client cannot be trusted with: nobody may grant authority they
    do not hold themselves, and nobody may change the role of an account senior
    to their own. Together those stop an admin promoting themselves to super
    admin or demoting one.
    """

    permission_classes = [CanManageUsers]
    serializer_class = RoleUpdateSerializer

    @extend_schema(request=RoleUpdateSerializer, responses={200: AdminUserSerializer})
    def patch(self, request, username):
        target = get_object_or_404(User, username__iexact=username)

        serializer = RoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_role = serializer.validated_data['role']

        if target.pk == request.user.pk:
            return Response(
                {'detail': 'You cannot change your own role.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if ROLE_RANK.get(target.role, 0) >= ROLE_RANK.get(request.user.role, 0) \
                and request.user.role != Role.SUPER_ADMIN:
            return Response(
                {'detail': 'You cannot change the role of an account at or above your own level.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not request.user.may_assign_role(new_role):
            return Response(
                {'detail': 'You cannot grant a role more senior than your own.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        previous = target.role
        target.role = new_role
        target.save(update_fields=['role', 'is_staff'])
        logger.info('%s changed role of %s from %s to %s',
                    request.user.username, target.username, previous, new_role)

        return Response(AdminUserSerializer(target).data)


class AdminUserSuspendView(APIView):
    """
    POST   /api/admin/users/<username>/suspend/   suspend
    DELETE /api/admin/users/<username>/suspend/   lift the suspension

    Suspension is reversible and keeps the account's content, which is what
    makes it the right default response to a problem rather than deletion.
    """

    permission_classes = [CanModerate]
    serializer_class = SuspendSerializer

    def _target(self, request, username):
        target = get_object_or_404(User, username__iexact=username)
        if target.pk == request.user.pk:
            return None, Response({'detail': 'You cannot suspend yourself.'},
                                  status=status.HTTP_400_BAD_REQUEST)
        if ROLE_RANK.get(target.role, 0) >= ROLE_RANK.get(request.user.role, 0):
            return None, Response(
                {'detail': 'You cannot suspend an account at or above your own level.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return target, None

    @extend_schema(request=SuspendSerializer, responses={200: AdminUserSerializer})
    def post(self, request, username):
        target, error = self._target(request, username)
        if error:
            return error

        serializer = SuspendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target.is_suspended = True
        target.suspension_reason = serializer.validated_data.get('reason', '')
        target.suspended_until = serializer.validated_data.get('until')
        target.save(update_fields=['is_suspended', 'suspension_reason', 'suspended_until'])
        logger.info('%s suspended %s', request.user.username, target.username)

        return Response(AdminUserSerializer(target).data)

    @extend_schema(request=None, responses={200: AdminUserSerializer})
    def delete(self, request, username):
        target, error = self._target(request, username)
        if error:
            return error

        target.is_suspended = False
        target.suspension_reason = ''
        target.suspended_until = None
        target.save(update_fields=['is_suspended', 'suspension_reason', 'suspended_until'])
        logger.info('%s lifted the suspension on %s', request.user.username, target.username)

        return Response(AdminUserSerializer(target).data)


class ModerationQueueView(generics.ListAPIView):
    """
    GET /api/admin/reports/ — reported comments awaiting a decision.

    Defaults to open reports, because that is the queue; `?status=` widens it.
    """

    serializer_class = ModerationReportSerializer
    permission_classes = [CanModerate]
    pagination_class = StandardPagination
    filter_backends = []

    def get_queryset(self):
        queryset = CommentReport.objects.select_related(
            'reporter', 'comment', 'comment__author', 'comment__post'
        )
        requested = self.request.query_params.get('status', CommentReport.Status.OPEN)
        if requested != 'all':
            queryset = queryset.filter(status=requested)
        return queryset


class ModerationActionView(APIView):
    """
    POST /api/admin/reports/<id>/action/

    `hide` removes the comment from public threads and closes the report;
    `unhide` puts it back; `dismiss` closes the report and leaves it visible.
    The comment row is never deleted, so a decision can be revisited.
    """

    permission_classes = [CanModerate]
    serializer_class = ModerationActionSerializer

    @extend_schema(request=ModerationActionSerializer, responses={200: ModerationReportSerializer})
    def post(self, request, pk):
        report = get_object_or_404(
            CommentReport.objects.select_related('comment'), pk=pk
        )
        serializer = ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data['action']

        comment = report.comment
        if action == 'hide':
            comment.is_hidden = True
            report.status = CommentReport.Status.REVIEWED
        elif action == 'unhide':
            comment.is_hidden = False
            report.status = CommentReport.Status.DISMISSED
        else:
            report.status = CommentReport.Status.DISMISSED

        comment.save(update_fields=['is_hidden'])
        report.resolved_at = timezone.now()
        report.save(update_fields=['status', 'resolved_at'])
        logger.info('%s applied "%s" to report %s', request.user.username, action, report.pk)

        report.refresh_from_db()
        return Response(ModerationReportSerializer(report).data)
