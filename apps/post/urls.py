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
    path('posts/<str:slug>/bookmark/', views.PostBookmarkView.as_view(), name='post-bookmark'),
    path('posts/<str:slug>/related/', views.RelatedPostListView.as_view(), name='post-related'),
    path('posts/<str:slug>/preview/', views.PostPreviewView.as_view(), name='post-preview'),
    path('posts/<str:slug>/preview-token/', views.PostPreviewTokenView.as_view(), name='post-preview-token'),

    path('bookmarks/', views.BookmarkListView.as_view(), name='bookmark-list'),
    path('uploads/images/', views.EditorImageUploadView.as_view(), name='editor-image-upload'),
    path('uploads/images/mine/', views.MyEditorImageListView.as_view(), name='editor-image-mine'),

    path('categories/', views.CategoryListView.as_view(), name='category-list'),
    path('categories/<slug:slug>/', views.CategoryDetailView.as_view(), name='category-detail'),

    path('tags/', views.TagListView.as_view(), name='tag-list'),
]
