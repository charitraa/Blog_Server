from django.urls import path

from .views import (
    CommentDetailView,
    CommentReportView,
    MyCommentListView,
    PostCommentListCreateView,
)

urlpatterns = [
    path('posts/<str:slug>/comments/', PostCommentListCreateView.as_view(), name='post-comments'),
    path('comments/mine/', MyCommentListView.as_view(), name='comment-mine'),
    path('comments/<uuid:pk>/', CommentDetailView.as_view(), name='comment-detail'),
    path('comments/<uuid:pk>/report/', CommentReportView.as_view(), name='comment-report'),
]
