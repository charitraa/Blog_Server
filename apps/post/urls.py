from django.urls import path

from . import views

# Mounted under /api/ (see blog_server/urls.py). The legacy /post/ prefix is
# mounted at the same views so existing clients keep working.
urlpatterns = [
    path('posts/', views.PostListCreateView.as_view(), name='post-list'),
    path('posts/mine/', views.MyPostListView.as_view(), name='post-mine'),
    path('posts/trending/', views.TrendingPostListView.as_view(), name='post-trending'),
    path('posts/<str:slug>/', views.PostDetailView.as_view(), name='post-detail'),
    path('posts/<str:slug>/like/', views.PostLikeView.as_view(), name='post-like'),
    path('posts/<str:slug>/related/', views.RelatedPostListView.as_view(), name='post-related'),

    path('categories/', views.CategoryListView.as_view(), name='category-list'),
    path('categories/<slug:slug>/', views.CategoryDetailView.as_view(), name='category-detail'),

    path('tags/', views.TagListView.as_view(), name='tag-list'),
]
