"""
Sitemaps for search engines.

The URLs describe the frontend, not this API, so every sitemap overrides the
site Django would otherwise take from the request. Without that, a crawler
would be handed the API's domain and index JSON.
"""

from urllib.parse import urlparse

from django.conf import settings
from django.contrib.sitemaps import Sitemap

from apps.post.models import Category, Post, Tag
from apps.user.models import User


class FrontendSite:
    """Minimal stand-in for `django.contrib.sites.models.Site`."""

    def __init__(self, url):
        parsed = urlparse(url)
        self.domain = parsed.netloc or 'localhost'
        self.scheme = parsed.scheme or 'https'

    def __str__(self):
        return self.domain


class FrontendSitemap(Sitemap):
    def get_urls(self, page=1, site=None, protocol=None):
        frontend = FrontendSite(settings.FRONTEND_URL)
        return super().get_urls(page=page, site=frontend, protocol=frontend.scheme)


class PostSitemap(FrontendSitemap):
    changefreq = 'weekly'
    priority = 0.8
    limit = 2000

    def items(self):
        return Post.objects.published().only('slug', 'updated_at')

    def location(self, obj):
        return f'/post/{obj.slug}'

    def lastmod(self, obj):
        return obj.updated_at


class CategorySitemap(FrontendSitemap):
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return Category.objects.all()

    def location(self, obj):
        return f'/explore?category={obj.slug}'


class TagSitemap(FrontendSitemap):
    changefreq = 'weekly'
    priority = 0.4

    def items(self):
        return Tag.objects.all()

    def location(self, obj):
        return f'/explore?tag={obj.slug}'


class AuthorSitemap(FrontendSitemap):
    changefreq = 'weekly'
    priority = 0.5

    def items(self):
        # Only authors with something published are worth indexing.
        return User.objects.filter(
            is_active=True, author_post__status=Post.Status.PUBLISHED
        ).distinct()

    def location(self, obj):
        return f'/author/{obj.username}'


class StaticSitemap(FrontendSitemap):
    changefreq = 'monthly'
    priority = 1.0

    def items(self):
        return ['', 'explore', 'trending', 'about']

    def location(self, item):
        return f'/{item}'


SITEMAPS = {
    'static': StaticSitemap,
    'posts': PostSitemap,
    'categories': CategorySitemap,
    'tags': TagSitemap,
    'authors': AuthorSitemap,
}
