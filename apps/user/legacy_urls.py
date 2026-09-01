"""
The original /user/ routes, kept working.

Every path here is an alias onto the same views that serve /api/, so clients
written against the old API keep functioning while new work targets /api/.
"""

from django.urls import path

from . import views

urlpatterns = [
    path('create/', views.RegisterView.as_view(), name='legacy-user-create'),
    path('login/', views.LoginView.as_view(), name='legacy-user-login'),
    path('verify/', views.VerifyEmailView.as_view(), name='legacy-user-verify'),
    path('me/', views.MeView.as_view(), name='legacy-user-me'),
    path('details/', views.UserListView.as_view(), name='legacy-user-detail'),
    path('details/update/', views.MeView.as_view(), name='legacy-user-update'),
    path('photo/update/', views.MeAvatarView.as_view(), name='legacy-user-photo-update'),
]
