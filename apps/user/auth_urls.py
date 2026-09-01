"""Authentication endpoints, mounted at /api/auth/."""

from django.urls import path

from . import views

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='auth-register'),
    path('login/', views.LoginView.as_view(), name='auth-login'),
    path('logout/', views.LogoutView.as_view(), name='auth-logout'),
    path('refresh/', views.RefreshView.as_view(), name='auth-refresh'),
    path('verify/', views.VerifyEmailView.as_view(), name='auth-verify'),
    path('resend-code/', views.ResendCodeView.as_view(), name='auth-resend-code'),
    path('me/', views.MeView.as_view(), name='auth-me'),
]
