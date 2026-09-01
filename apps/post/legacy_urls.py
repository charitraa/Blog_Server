"""
The original /post/ routes, kept working.

They are aliases onto the current views, so responses are the improved shape
but no existing URL 404s.
"""

from django.urls import path

from . import views

urlpatterns = [
    path('posts/', views.PostListCreateView.as_view(), name='legacy-post-list'),
    path('posts/user/<uuid:user_id>/', views.LegacyAuthorPostListView.as_view(),
         name='legacy-posts-by-user'),
    path('posts/count/<uuid:user_id>/', views.LegacyAuthorPostCountView.as_view(),
         name='legacy-post-count'),
    # Registered last so the more specific patterns above win.
    path('posts/<str:slug>/', views.PostDetailView.as_view(), name='legacy-post-detail'),
]
