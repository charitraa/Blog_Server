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

    # Forgotten passwords
    path('password-reset/', views.PasswordResetRequestView.as_view(), name='auth-password-reset'),
    path('password-reset/confirm/', views.PasswordResetConfirmView.as_view(),
         name='auth-password-reset-confirm'),

    # Social sign-in
    path('providers/', views.SocialProvidersView.as_view(), name='auth-providers'),
    path('social/<str:provider>/', views.SocialAuthView.as_view(), name='auth-social'),
]
