from django.urls import path

from .views import (
    CommentDetailView,
    CommentLikeView,
    CommentPinView,
    CommentReportView,
    MyCommentListView,
    PostCommentListCreateView,
)

urlpatterns = [
    path('posts/<str:slug>/comments/', PostCommentListCreateView.as_view(), name='post-comments'),
    path('comments/mine/', MyCommentListView.as_view(), name='comment-mine'),
    path('comments/<uuid:pk>/', CommentDetailView.as_view(), name='comment-detail'),
    path('comments/<uuid:pk>/report/', CommentReportView.as_view(), name='comment-report'),
    path('comments/<uuid:pk>/like/', CommentLikeView.as_view(), name='comment-like'),
    path('comments/<uuid:pk>/pin/', CommentPinView.as_view(), name='comment-pin'),
]
