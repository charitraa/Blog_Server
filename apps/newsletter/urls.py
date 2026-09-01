from django.urls import path

from .views import ConfirmView, SubscribeView, UnsubscribeView

urlpatterns = [
    path('newsletter/subscribe/', SubscribeView.as_view(), name='newsletter-subscribe'),
    path('newsletter/confirm/', ConfirmView.as_view(), name='newsletter-confirm'),
    path('newsletter/unsubscribe/', UnsubscribeView.as_view(), name='newsletter-unsubscribe'),
]
