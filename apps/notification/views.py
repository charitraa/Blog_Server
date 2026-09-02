from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from blog_server.pagination import LargePagination

from .models import Notification
from .serializers import MarkReadSerializer, NotificationSerializer, UnreadCountSerializer


class NotificationListView(generics.ListAPIView):
    """
    GET /api/notifications/ — the signed-in user's inbox.

    `?unread=true` narrows it to what has not been seen yet.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = LargePagination
    filter_backends = []

    def get_queryset(self):
        queryset = Notification.objects.filter(recipient=self.request.user).with_related()
        if self.request.query_params.get('unread') in ('true', '1'):
            queryset = queryset.unread()
        return queryset


class UnreadCountView(APIView):
    """GET /api/notifications/unread-count/ — the number on the bell."""

    permission_classes = [IsAuthenticated]
    serializer_class = UnreadCountSerializer

    @extend_schema(responses={200: UnreadCountSerializer})
    def get(self, request):
        unread = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({'unread': unread})


class MarkReadView(APIView):
    """POST /api/notifications/read/ — mark some, or all, as read."""

    permission_classes = [IsAuthenticated]
    serializer_class = MarkReadSerializer

    @extend_schema(request=MarkReadSerializer, responses={200: UnreadCountSerializer})
    def post(self, request):
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Always scoped to the recipient, so passing someone else's id does nothing.
        queryset = Notification.objects.filter(recipient=request.user, is_read=False)
        ids = serializer.validated_data.get('ids')
        if ids:
            queryset = queryset.filter(id__in=ids)
        updated = queryset.update(is_read=True)

        return Response({
            'updated': updated,
            'unread': Notification.objects.filter(recipient=request.user, is_read=False).count(),
        })


class NotificationDeleteView(generics.DestroyAPIView):
    """DELETE /api/notifications/<uuid>/ — dismiss one."""

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)
