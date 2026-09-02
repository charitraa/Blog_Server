"""AI assistant endpoints, mounted at /api/ai/."""

from django.urls import path

from . import views

urlpatterns = [
    path('status/', views.AIStatusView.as_view(), name='ai-status'),
    path('titles/', views.SuggestTitlesView.as_view(), name='ai-titles'),
    path('seo/', views.SuggestSeoView.as_view(), name='ai-seo'),
    path('summary/', views.SummarizeView.as_view(), name='ai-summary'),
    path('outline/', views.OutlineView.as_view(), name='ai-outline'),
    path('rewrite/', views.RewriteView.as_view(), name='ai-rewrite'),
    path('proofread/', views.ProofreadView.as_view(), name='ai-proofread'),
    path('social/', views.SocialPostView.as_view(), name='ai-social'),
    path('translate/', views.TranslateView.as_view(), name='ai-translate'),
]
