"""
Author-facing analytics.

Everything here is derived from data the site already records — the view
ledger, likes, bookmarks, comments and reading progress. Nothing new is tracked
about readers to produce it, which is why there are no referrer, country or
device breakdowns: the server has never collected those, and inventing columns
to fill a dashboard would mean starting to profile people who did not ask for it.
"""

from datetime import timedelta

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import Bookmark, Like, Post, PostView, ReadingHistory


def _daily_series(queryset, days, field='created_at'):
    """
    Counts per day, with empty days filled in.

    A chart that silently skips quiet days implies traffic it did not have, so
    the gaps are materialised as zeroes here rather than in the client.
    """
    start = (timezone.now() - timedelta(days=days - 1)).date()

    rows = (
        queryset.annotate(day=TruncDate(field))
        .values('day')
        .annotate(total=Count('id'))
        .order_by('day')
    )
    counts = {row['day']: row['total'] for row in rows if row['day'] and row['day'] >= start}

    return [
        {
            'date': (start + timedelta(days=offset)).isoformat(),
            'count': counts.get(start + timedelta(days=offset), 0),
        }
        for offset in range(days)
    ]


def post_analytics(post, days=30):
    """Everything the per-post analytics panel shows."""
    since = timezone.now() - timedelta(days=days)
    views = PostView.objects.filter(post=post)

    reading = ReadingHistory.objects.filter(post=post).aggregate(
        readers=Count('id'),
        finished=Count('id', filter=Q(is_finished=True)),
        average=Avg('progress'),
    )

    return {
        'slug': post.slug,
        'title': post.title,
        'published_at': post.published_at,
        # The denormalised counter is the number shown publicly, so analytics
        # reports the same figure rather than a second, slightly different one.
        'total_views': post.view_count,
        'unique_viewers': views.values('fingerprint').distinct().count(),
        'views_in_period': views.filter(created_at__gte=since).count(),
        'likes': Like.objects.filter(post=post).count(),
        'bookmarks': Bookmark.objects.filter(post=post).count(),
        'comments': post.comments.filter(is_hidden=False).count(),
        'readers': reading['readers'] or 0,
        'finished_readers': reading['finished'] or 0,
        'average_progress': round(reading['average'] or 0),
        'completion_rate': round(
            100 * (reading['finished'] or 0) / reading['readers'], 1
        ) if reading['readers'] else 0.0,
        'reading_time': post.reading_time,
        'daily_views': _daily_series(views, days),
    }


def author_analytics(user, days=30):
    """Totals across everything one author has published, plus their top posts."""
    posts = Post.objects.filter(author=user, deleted_at__isnull=True)
    published = posts.filter(status=Post.Status.PUBLISHED)
    since = timezone.now() - timedelta(days=days)

    views = PostView.objects.filter(post__author=user)

    top = list(
        published.annotate(
            like_total=Count('likes', distinct=True),
            comment_total=Count('comments', distinct=True),
        )
        .order_by('-view_count')[:10]
        .values('slug', 'title', 'view_count', 'like_total', 'comment_total')
    )

    return {
        'total_posts': posts.count(),
        'published_posts': published.count(),
        'draft_posts': posts.filter(status=Post.Status.DRAFT).count(),
        'scheduled_posts': posts.filter(status=Post.Status.SCHEDULED).count(),
        'total_views': published.aggregate(total=Sum('view_count'))['total'] or 0,
        'unique_viewers': views.values('fingerprint').distinct().count(),
        'views_in_period': views.filter(created_at__gte=since).count(),
        'total_likes': Like.objects.filter(post__author=user).count(),
        'total_comments': posts.aggregate(
            total=Count('comments', filter=Q(comments__is_hidden=False))
        )['total'] or 0,
        'total_bookmarks': Bookmark.objects.filter(post__author=user).count(),
        'followers': user.follower_set.count(),
        'daily_views': _daily_series(views, days),
        'top_posts': [
            {
                'slug': row['slug'],
                'title': row['title'],
                'views': row['view_count'],
                'likes': row['like_total'],
                'comments': row['comment_total'],
            }
            for row in top
        ],
    }
