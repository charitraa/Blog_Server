from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from blog_server.views import CheckView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', CheckView.as_view(), name='health-check'),

    # ---- Current API ----------------------------------------------------
    path('api/auth/', include('apps.user.auth_urls')),
    path('api/users/', include('apps.user.urls')),
    path('api/', include('apps.post.urls')),
    path('api/', include('apps.comment.urls')),

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
