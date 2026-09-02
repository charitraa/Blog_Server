"""Author and post analytics."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.comment.models import Comment
from apps.post.models import Bookmark, Like, Post, PostView, ReadingHistory

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule.'


def make_user(email='writer@example.com', username='writer', **extra):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Ada', last_name='Lovelace', is_verified=True, **extra
    )


class PostAnalyticsTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.reader = make_user('r@example.com', 'reader')
        self.post = Post.objects.create(
            title='Measured', content=BODY, author=self.author,
            status=Post.Status.PUBLISHED, view_count=12,
        )
        self.url = f'/api/posts/{self.post.slug}/analytics/'

    def test_analytics_need_a_sign_in(self):
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_a_stranger_cannot_read_them(self):
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)

    def test_an_editor_can_read_them(self):
        editor = make_user('e@example.com', 'editor', role='editor')
        self.client.force_authenticate(editor)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)

    def test_the_public_view_count_is_the_one_reported(self):
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get(self.url).data['total_views'], 12)

    def test_unique_viewers_deduplicates_fingerprints(self):
        PostView.objects.create(post=self.post, fingerprint='a' * 64)
        PostView.objects.create(post=self.post, fingerprint='b' * 64)
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get(self.url).data['unique_viewers'], 2)

    def test_engagement_counters(self):
        Like.objects.create(post=self.post, user=self.reader)
        Bookmark.objects.create(post=self.post, user=self.reader)
        Comment.objects.create(post=self.post, author=self.reader, content='Nice')

        self.client.force_authenticate(self.author)
        data = self.client.get(self.url).data
        self.assertEqual(data['likes'], 1)
        self.assertEqual(data['bookmarks'], 1)
        self.assertEqual(data['comments'], 1)

    def test_hidden_comments_are_not_counted(self):
        Comment.objects.create(post=self.post, author=self.reader, content='Spam',
                               is_hidden=True)
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get(self.url).data['comments'], 0)

    def test_completion_rate(self):
        other = make_user('o@example.com', 'other')
        ReadingHistory.objects.create(user=self.reader, post=self.post, progress=100,
                                      is_finished=True)
        ReadingHistory.objects.create(user=other, post=self.post, progress=30)

        self.client.force_authenticate(self.author)
        data = self.client.get(self.url).data
        self.assertEqual(data['readers'], 2)
        self.assertEqual(data['finished_readers'], 1)
        self.assertEqual(data['completion_rate'], 50.0)

    def test_completion_rate_is_zero_with_no_readers(self):
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get(self.url).data['completion_rate'], 0.0)

    def test_the_daily_series_fills_quiet_days(self):
        self.client.force_authenticate(self.author)
        series = self.client.get(self.url, {'days': 7}).data['daily_views']
        self.assertEqual(len(series), 7)
        self.assertTrue(all(entry['count'] == 0 for entry in series))

    def test_the_window_is_capped(self):
        self.client.force_authenticate(self.author)
        series = self.client.get(self.url, {'days': '99999'}).data['daily_views']
        self.assertEqual(len(series), 365)


class AuthorAnalyticsTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.reader = make_user('r@example.com', 'reader')
        self.url = '/api/users/me/analytics/'

        self.live = Post.objects.create(
            title='Live', content=BODY, author=self.author,
            status=Post.Status.PUBLISHED, view_count=100,
        )
        Post.objects.create(title='Draft', content=BODY, author=self.author,
                            status=Post.Status.DRAFT)
        Post.objects.create(
            title='Later', content=BODY, author=self.author,
            status=Post.Status.SCHEDULED, scheduled_for=timezone.now() + timedelta(days=2),
        )

    def test_analytics_need_a_sign_in(self):
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_counts_by_state(self):
        self.client.force_authenticate(self.author)
        data = self.client.get(self.url).data
        self.assertEqual(data['total_posts'], 3)
        self.assertEqual(data['published_posts'], 1)
        self.assertEqual(data['draft_posts'], 1)
        self.assertEqual(data['scheduled_posts'], 1)

    def test_views_sum_across_published_posts(self):
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get(self.url).data['total_views'], 100)

    def test_deleted_posts_are_excluded(self):
        self.live.soft_delete()
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get(self.url).data['total_posts'], 2)

    def test_top_posts_are_ranked_by_views(self):
        Post.objects.create(title='Quiet', content=BODY, author=self.author,
                            status=Post.Status.PUBLISHED, view_count=1)
        self.client.force_authenticate(self.author)
        top = self.client.get(self.url).data['top_posts']
        self.assertEqual(top[0]['slug'], self.live.slug)

    def test_one_author_never_sees_anothers_numbers(self):
        other = make_user('o@example.com', 'other')
        Post.objects.create(title='Theirs', content=BODY, author=other,
                            status=Post.Status.PUBLISHED, view_count=999)

        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get(self.url).data['total_views'], 100)

    def test_engagement_totals(self):
        Like.objects.create(post=self.live, user=self.reader)
        Bookmark.objects.create(post=self.live, user=self.reader)
        Comment.objects.create(post=self.live, author=self.reader, content='Hi')

        self.client.force_authenticate(self.author)
        data = self.client.get(self.url).data
        self.assertEqual(data['total_likes'], 1)
        self.assertEqual(data['total_bookmarks'], 1)
        self.assertEqual(data['total_comments'], 1)
