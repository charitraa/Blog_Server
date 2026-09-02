from django.urls import path, re_path

from . import views

# Mounted under /api/ (see blog_server/urls.py). The legacy /post/ prefix is
# mounted at the same views so existing clients keep working.
urlpatterns = [
    path('posts/', views.PostListCreateView.as_view(), name='post-list'),
    path('posts/mine/', views.MyPostListView.as_view(), name='post-mine'),
    path('posts/trending/', views.TrendingPostListView.as_view(), name='post-trending'),
    # Fixed segments must precede posts/<slug>/, or 'trash' is read as a slug.
    path('posts/trash/', views.TrashListView.as_view(), name='post-trash'),
    path('posts/feed/', views.FeedView.as_view(), name='post-feed'),
    path('posts/recommended/', views.RecommendedPostsView.as_view(), name='post-recommended'),
    path('posts/<str:slug>/', views.PostDetailView.as_view(), name='post-detail'),
    path('posts/<str:slug>/like/', views.PostLikeView.as_view(), name='post-like'),
    path('posts/<str:slug>/bookmark/', views.PostBookmarkView.as_view(), name='post-bookmark'),
    path('posts/<str:slug>/related/', views.RelatedPostListView.as_view(), name='post-related'),
    path('posts/<str:slug>/preview/', views.PostPreviewView.as_view(), name='post-preview'),
    path('posts/<str:slug>/preview-token/', views.PostPreviewTokenView.as_view(), name='post-preview-token'),

    # Lifecycle
    path('posts/<str:slug>/revisions/', views.PostRevisionListView.as_view(),
         name='post-revisions'),
    path('posts/<str:slug>/revisions/<uuid:pk>/', views.PostRevisionDetailView.as_view(),
         name='post-revision-detail'),
    path('posts/<str:slug>/progress/', views.ReadingProgressView.as_view(),
         name='post-progress'),
    path('posts/<str:slug>/analytics/', views.PostAnalyticsView.as_view(),
         name='post-analytics'),
    # The action is pinned to a fixed set rather than <str:action>, which would
    # also swallow sibling routes like posts/<slug>/comments/.
    re_path(
        r'^posts/(?P<slug>[^/]+)/(?P<action>archive|unarchive|restore|duplicate)/$',
        views.PostLifecycleView.as_view(),
        name='post-lifecycle',
    ),

    # Series
    path('series/', views.SeriesListCreateView.as_view(), name='series-list'),
    path('series/<slug:slug>/', views.SeriesDetailView.as_view(), name='series-detail'),
    path('series/<slug:slug>/posts/', views.SeriesEntryView.as_view(), name='series-posts'),
    path('series/<slug:slug>/reorder/', views.SeriesReorderView.as_view(), name='series-reorder'),
    path('series/<slug:slug>/progress/', views.SeriesProgressView.as_view(),
         name='series-progress'),

    # Reading history
    path('reading-history/', views.ReadingHistoryListView.as_view(), name='reading-history'),
    path('reading-history/clear/', views.ReadingHistoryClearView.as_view(),
         name='reading-history-clear'),

    path('bookmarks/', views.BookmarkListView.as_view(), name='bookmark-list'),
    path('uploads/images/', views.EditorImageUploadView.as_view(), name='editor-image-upload'),
    path('uploads/images/mine/', views.MyEditorImageListView.as_view(), name='editor-image-mine'),

    path('categories/', views.CategoryListView.as_view(), name='category-list'),
    path('categories/<slug:slug>/', views.CategoryDetailView.as_view(), name='category-detail'),

    path('tags/', views.TagListView.as_view(), name='tag-list'),
]
