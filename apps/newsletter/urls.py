from django.urls import path

from . import views
from .views import ConfirmView, SubscribeView, UnsubscribeView

urlpatterns = [
    path('newsletter/subscribe/', SubscribeView.as_view(), name='newsletter-subscribe'),
    path('newsletter/confirm/', ConfirmView.as_view(), name='newsletter-confirm'),
    path('newsletter/unsubscribe/', UnsubscribeView.as_view(), name='newsletter-unsubscribe'),

    # Staff only: a campaign reaches every confirmed subscriber.
    path('newsletter/campaigns/', views.CampaignListCreateView.as_view(),
         name='newsletter-campaigns'),
    path('newsletter/campaigns/<uuid:pk>/', views.CampaignDetailView.as_view(),
         name='newsletter-campaign-detail'),
    path('newsletter/campaigns/<uuid:pk>/send/', views.CampaignSendView.as_view(),
         name='newsletter-campaign-send'),
    path('newsletter/campaigns/<uuid:pk>/stats/', views.CampaignStatsView.as_view(),
         name='newsletter-campaign-stats'),
]
