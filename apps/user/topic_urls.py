"""Topic follows, mounted at /api/topics/."""

from django.urls import path

from . import views

urlpatterns = [
    path('following/', views.MyTopicsView.as_view(), name='topic-following'),
    path('<str:kind>/<slug:slug>/follow/', views.TopicFollowView.as_view(), name='topic-follow'),
]
