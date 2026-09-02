from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from apps.post.feeds import AuthorFeed, CategoryFeed, LatestPostsAtomFeed, LatestPostsFeed
from blog_server.sitemaps import SITEMAPS
from blog_server.views import CheckView, RobotsView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', CheckView.as_view(), name='health-check'),

    # ---- Current API ----------------------------------------------------
    path('api/auth/', include('apps.user.auth_urls')),
    path('api/users/', include('apps.user.urls')),
    path('api/admin/', include('apps.user.admin_urls')),
    path('api/topics/', include('apps.user.topic_urls')),
    path('api/ai/', include('apps.ai.urls')),
    path('api/', include('apps.post.urls')),
    path('api/', include('apps.comment.urls')),
    path('api/', include('apps.notification.urls')),
    path('api/', include('apps.newsletter.urls')),

    # ---- Syndication & SEO ----------------------------------------------
    path('feed/', LatestPostsFeed(), name='feed-rss'),
    path('feed/atom/', LatestPostsAtomFeed(), name='feed-atom'),
    path('feed/category/<slug:slug>/', CategoryFeed(), name='feed-category'),
    path('feed/author/<str:username>/', AuthorFeed(), name='feed-author'),
    path('sitemap.xml', sitemap, {'sitemaps': SITEMAPS}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', RobotsView.as_view(), name='robots'),

    # ---- Documentation --------------------------------------------------
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # ---- Legacy routes, kept so existing clients do not break -----------
    path('user/', include('apps.user.legacy_urls')),
    path('post/', include('apps.post.legacy_urls')),
    path('comment/', include('apps.comment.legacy_urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
