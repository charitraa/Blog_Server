from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from blog_server.views import CheckView
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', CheckView.as_view()),
    path('user/',include('apps.user.urls')),
    path('post/',include('apps.post.urls')),
    path('comment/',include('apps.comment.urls')),

]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)