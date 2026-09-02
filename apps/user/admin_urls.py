"""Administration endpoints, mounted at /api/admin/."""

from django.urls import path

from . import admin_views as views

urlpatterns = [
    path('stats/', views.AdminStatsView.as_view(), name='admin-stats'),

    path('users/', views.AdminUserListView.as_view(), name='admin-user-list'),
    path('users/<str:username>/role/', views.AdminUserRoleView.as_view(), name='admin-user-role'),
    path('users/<str:username>/suspend/', views.AdminUserSuspendView.as_view(),
         name='admin-user-suspend'),

    path('reports/', views.ModerationQueueView.as_view(), name='admin-report-list'),
    path('reports/<uuid:pk>/action/', views.ModerationActionView.as_view(),
         name='admin-report-action'),
]
