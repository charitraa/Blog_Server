"""The original /comment/ routes, aliased onto the current views."""

from django.urls import path

from .views import CommentDetailView, PostCommentListCreateView

urlpatterns = [
    path('posts/<str:slug>/comments/', PostCommentListCreateView.as_view(),
         name='legacy-post-comments'),
    path('comments/<uuid:pk>/', CommentDetailView.as_view(), name='legacy-comment-detail'),
]
