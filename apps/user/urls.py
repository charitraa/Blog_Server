from django.urls import path

from apps.post.views import AuthorAnalyticsView, AuthorPostListView

from . import views

# Profile endpoints, mounted at /api/users/.
urlpatterns = [
    path('', views.UserListView.as_view(), name='user-list'),
    path('me/', views.MeView.as_view(), name='user-me'),
    path('me/avatar/', views.MeAvatarView.as_view(), name='user-me-avatar'),
    path('me/password/', views.MePasswordView.as_view(), name='user-me-password'),
    path('me/email/', views.MeEmailView.as_view(), name='user-me-email'),
    path('me/dashboard/', views.MeDashboardView.as_view(), name='user-me-dashboard'),
    path('me/analytics/', AuthorAnalyticsView.as_view(), name='user-me-analytics'),

    path('<str:username>/', views.UserDetailView.as_view(), name='user-detail'),
    path('<str:username>/posts/', AuthorPostListView.as_view(), name='user-posts'),
    path('<str:username>/follow/', views.FollowView.as_view(), name='user-follow'),
    path('<str:username>/followers/', views.UserFollowersView.as_view(), name='user-followers'),
    path('<str:username>/following/', views.UserFollowingView.as_view(), name='user-following'),
]
