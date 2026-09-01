from django.urls import path

from .views import CommentDetailView, MyCommentListView, PostCommentListCreateView

urlpatterns = [
    path('posts/<str:slug>/comments/', PostCommentListCreateView.as_view(), name='post-comments'),
    path('comments/mine/', MyCommentListView.as_view(), name='comment-mine'),
    path('comments/<uuid:pk>/', CommentDetailView.as_view(), name='comment-detail'),
]
