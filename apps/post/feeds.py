"""
RSS and Atom feeds.

Every link points at the frontend rather than at this API, because a feed
reader's job is to send the reader to the article page a person can read, not
to a JSON document.
"""

from django.conf import settings
from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404
from django.utils.feedgenerator import Atom1Feed

from apps.user.models import User

from .models import Category, Post
from .utils import plain_text

FEED_LIMIT = 25


def frontend_url(path=''):
    return f'{settings.FRONTEND_URL.rstrip("/")}/{path.lstrip("/")}'


class BasePostFeed(Feed):
    """Shared item rendering. Subclasses only choose which posts to include."""

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.excerpt or plain_text(item.content)[:300]

    def item_link(self, item):
        return frontend_url(f'post/{item.slug}')

    def item_author_name(self, item):
        return item.author.display_name

    def item_pubdate(self, item):
        return item.published_at

    def item_updateddate(self, item):
        return item.updated_at

    def item_categories(self, item):
        names = [tag.name for tag in item.tags.all()]
        if item.category:
            names.insert(0, item.category.name)
        return names


class LatestPostsFeed(BasePostFeed):
    """/feed/ — the most recent published posts across the whole blog."""

    title = f'{settings.SITE_NAME} — latest posts'
    link = frontend_url('explore')
    description = f'New articles published on {settings.SITE_NAME}.'

    def items(self):
        return Post.objects.published().with_related()[:FEED_LIMIT]


class LatestPostsAtomFeed(LatestPostsFeed):
    """/feed/atom/ — the same content, for readers that prefer Atom."""

    feed_type = Atom1Feed
    subtitle = LatestPostsFeed.description


class CategoryFeed(BasePostFeed):
    """/feed/category/<slug>/"""

    def get_object(self, request, slug):
        return get_object_or_404(Category, slug=slug)

    def title(self, obj):
        return f'{settings.SITE_NAME} — {obj.name}'

    def link(self, obj):
        return frontend_url(f'explore?category={obj.slug}')

    def description(self, obj):
        return obj.description or f'Posts filed under {obj.name}.'

    def items(self, obj):
        return Post.objects.published().filter(category=obj).with_related()[:FEED_LIMIT]


class AuthorFeed(BasePostFeed):
    """/feed/author/<username>/"""

    def get_object(self, request, username):
        return get_object_or_404(User, username__iexact=username, is_active=True)

    def title(self, obj):
        return f'{settings.SITE_NAME} — posts by {obj.display_name}'

    def link(self, obj):
        return frontend_url(f'author/{obj.username}')

    def description(self, obj):
        return obj.bio or f'Articles written by {obj.display_name}.'

    def items(self, obj):
        return Post.objects.published().filter(author=obj).with_related()[:FEED_LIMIT]
