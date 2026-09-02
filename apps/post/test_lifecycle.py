"""Scheduling, archiving, revisions, duplication, series and reading history."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.post.models import (
    Post, PostRevision, ReadingHistory, Series, SeriesPost, SeriesProgress,
)

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule.'


def make_user(email='writer@example.com', username='writer', **extra):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Ada', last_name='Lovelace', is_verified=True, **extra
    )


def make_post(author, title='A published post', **extra):
    extra.setdefault('content', BODY)
    extra.setdefault('status', Post.Status.PUBLISHED)
    return Post.objects.create(title=title, author=author, **extra)


class ScheduledPublishingTests(APITestCase):
    def setUp(self):
        self.author = make_user()

    def test_a_future_post_is_not_public_yet(self):
        make_post(self.author, title='Tomorrow', status=Post.Status.SCHEDULED,
                  scheduled_for=timezone.now() + timedelta(days=1))
        response = self.client.get('/api/posts/')
        self.assertEqual(response.data['count'], 0)

    def test_a_scheduled_post_goes_live_on_its_own_once_due(self):
        post = make_post(self.author, title='Due', status=Post.Status.SCHEDULED,
                         scheduled_for=timezone.now() + timedelta(days=1))
        # Move the clock forward without running any scheduler.
        Post.objects.filter(pk=post.pk).update(scheduled_for=timezone.now() - timedelta(minutes=1))

        response = self.client.get('/api/posts/')
        self.assertEqual(response.data['count'], 1)

    def test_the_command_promotes_due_posts(self):
        from django.core.management import call_command

        post = make_post(self.author, title='Due', status=Post.Status.SCHEDULED,
                         scheduled_for=timezone.now() + timedelta(days=1))
        Post.objects.filter(pk=post.pk).update(scheduled_for=timezone.now() - timedelta(minutes=1))

        call_command('publish_scheduled')
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.PUBLISHED)

    def test_the_promised_date_survives_promotion(self):
        from django.core.management import call_command

        due_at = timezone.now() - timedelta(hours=2)
        post = make_post(self.author, status=Post.Status.SCHEDULED,
                         scheduled_for=timezone.now() + timedelta(days=1))
        Post.objects.filter(pk=post.pk).update(scheduled_for=due_at, published_at=due_at)

        call_command('publish_scheduled')
        post.refresh_from_db()
        self.assertEqual(post.published_at, due_at)

    def test_scheduling_needs_a_date(self):
        self.client.force_authenticate(self.author)
        response = self.client.post('/api/posts/', {
            'title': 'No date', 'content': BODY, 'status': 'scheduled',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_past_date_is_rejected(self):
        self.client.force_authenticate(self.author)
        response = self.client.post('/api/posts/', {
            'title': 'Backdated', 'content': BODY, 'status': 'scheduled',
            'scheduled_for': (timezone.now() - timedelta(days=1)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_contributor_cannot_schedule_either(self):
        contributor = make_user('c@example.com', 'contrib', role='contributor')
        self.client.force_authenticate(contributor)
        response = self.client.post('/api/posts/', {
            'title': 'Sneaky', 'content': BODY, 'status': 'scheduled',
            'scheduled_for': (timezone.now() + timedelta(days=1)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class VisibilityAndArchiveTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.post = make_post(self.author)

    def test_archiving_removes_a_post_from_public_lists(self):
        self.client.force_authenticate(self.author)
        response = self.client.post(f'/api/posts/{self.post.slug}/archive/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/posts/').data['count'], 0)

    def test_unarchiving_puts_it_back(self):
        self.post.archive()
        self.client.force_authenticate(self.author)
        self.client.post(f'/api/posts/{self.post.slug}/unarchive/')

        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/posts/').data['count'], 1)

    def test_a_private_post_is_not_listed_publicly(self):
        self.post.visibility = Post.Visibility.PRIVATE
        self.post.save()
        self.assertEqual(self.client.get('/api/posts/').data['count'], 0)

    def test_only_the_author_may_archive(self):
        stranger = make_user('s@example.com', 'stranger')
        self.client.force_authenticate(stranger)
        response = self.client.post(f'/api/posts/{self.post.slug}/archive/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_an_unknown_action_is_rejected(self):
        self.client.force_authenticate(self.author)
        response = self.client.post(f'/api/posts/{self.post.slug}/explode/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class DuplicateTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.post = make_post(self.author, title='Original', subtitle='A subtitle')

    def test_duplicating_makes_a_draft_copy(self):
        self.client.force_authenticate(self.author)
        response = self.client.post(f'/api/posts/{self.post.slug}/duplicate/')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'draft')
        self.assertIn('copy', response.data['title'].lower())
        self.assertEqual(response.data['subtitle'], 'A subtitle')
        self.assertEqual(Post.objects.count(), 2)

    def test_the_copy_starts_with_clean_counters(self):
        self.post.view_count = 500
        self.post.save()

        self.client.force_authenticate(self.author)
        response = self.client.post(f'/api/posts/{self.post.slug}/duplicate/')
        self.assertEqual(response.data['view_count'], 0)

    def test_the_copy_gets_its_own_slug(self):
        self.client.force_authenticate(self.author)
        response = self.client.post(f'/api/posts/{self.post.slug}/duplicate/')
        self.assertNotEqual(response.data['slug'], self.post.slug)


class RevisionTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.post = make_post(self.author, title='First title')

    def test_editing_records_the_previous_text(self):
        self.client.force_authenticate(self.author)
        self.client.patch(f'/api/posts/{self.post.slug}/', {'title': 'Second title'},
                          format='json')

        revisions = PostRevision.objects.filter(post=self.post)
        self.assertEqual(revisions.count(), 1)
        self.assertEqual(revisions.first().title, 'First title')

    def test_an_edit_that_changes_nothing_adds_no_revision(self):
        PostRevision.snapshot(self.post, self.author)
        PostRevision.snapshot(self.post, self.author)
        self.assertEqual(PostRevision.objects.filter(post=self.post).count(), 1)

    def test_the_history_is_listed_without_bodies(self):
        self.client.force_authenticate(self.author)
        self.client.patch(f'/api/posts/{self.post.slug}/', {'title': 'Second'}, format='json')

        response = self.client.get(f'/api/posts/{self.post.slug}/revisions/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertNotIn('content', response.data['results'][0])
        self.assertIn('word_count', response.data['results'][0])

    def test_a_stranger_cannot_read_the_history(self):
        PostRevision.snapshot(self.post, self.author)
        stranger = make_user('s@example.com', 'stranger')
        self.client.force_authenticate(stranger)
        response = self.client.get(f'/api/posts/{self.post.slug}/revisions/')
        self.assertEqual(response.data['count'], 0)

    def test_restoring_puts_the_old_text_back(self):
        self.client.force_authenticate(self.author)
        self.client.patch(f'/api/posts/{self.post.slug}/', {'title': 'Second title'},
                          format='json')
        revision = PostRevision.objects.filter(post=self.post).first()

        response = self.client.post(
            f'/api/posts/{self.post.slug}/revisions/{revision.id}/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.post.refresh_from_db()
        self.assertEqual(self.post.title, 'First title')

    def test_restoring_snapshots_what_it_replaced(self):
        self.client.force_authenticate(self.author)
        self.client.patch(f'/api/posts/{self.post.slug}/', {'title': 'Second'}, format='json')
        revision = PostRevision.objects.filter(post=self.post).first()
        self.client.post(f'/api/posts/{self.post.slug}/revisions/{revision.id}/')

        # The pre-restore state is recoverable too.
        self.assertTrue(
            PostRevision.objects.filter(post=self.post, title='Second').exists()
        )


class SeriesTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.reader = make_user('r@example.com', 'reader')
        self.series = Series.objects.create(title='Web Hacking', author=self.author)
        self.one = make_post(self.author, title='HTTP Fundamentals')
        self.two = make_post(self.author, title='IDOR')

    def add(self, post, position=None):
        return SeriesPost.objects.create(
            series=self.series, post=post,
            position=position or self.series.next_position(),
        )

    def test_a_series_is_listed_publicly(self):
        response = self.client.get('/api/series/')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['title'], 'Web Hacking')

    def test_creating_a_series_requires_sign_in(self):
        response = self.client.post('/api/series/', {'title': 'New'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_adding_posts_keeps_them_ordered(self):
        self.client.force_authenticate(self.author)
        self.client.post(f'/api/series/{self.series.slug}/posts/',
                         {'post': self.one.slug}, format='json')
        response = self.client.post(f'/api/series/{self.series.slug}/posts/',
                                    {'post': self.two.slug}, format='json')

        positions = [entry['position'] for entry in response.data['entries']]
        self.assertEqual(positions, [1, 2])

    def test_adding_the_same_post_twice_does_not_duplicate_it(self):
        self.client.force_authenticate(self.author)
        self.client.post(f'/api/series/{self.series.slug}/posts/',
                         {'post': self.one.slug}, format='json')
        response = self.client.post(f'/api/series/{self.series.slug}/posts/',
                                    {'post': self.one.slug}, format='json')
        self.assertEqual(len(response.data['entries']), 1)

    def test_removing_a_part_closes_the_gap(self):
        self.add(self.one, 1)
        self.add(self.two, 2)
        three = make_post(self.author, title='XSS')
        self.add(three, 3)

        self.client.force_authenticate(self.author)
        response = self.client.delete(
            f'/api/series/{self.series.slug}/posts/?post={self.two.slug}'
        )
        positions = [entry['position'] for entry in response.data['entries']]
        self.assertEqual(positions, [1, 2])

    def test_reordering_applies_the_whole_running_order(self):
        self.add(self.one, 1)
        self.add(self.two, 2)

        self.client.force_authenticate(self.author)
        response = self.client.post(
            f'/api/series/{self.series.slug}/reorder/',
            {'slugs': [self.two.slug, self.one.slug]}, format='json',
        )
        order = [entry['post']['slug'] for entry in response.data['entries']]
        self.assertEqual(order, [self.two.slug, self.one.slug])

    def test_a_stranger_cannot_reorder(self):
        self.add(self.one, 1)
        self.client.force_authenticate(self.reader)
        response = self.client.post(f'/api/series/{self.series.slug}/reorder/',
                                    {'slugs': [self.one.slug]}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_progress_tracks_completed_parts(self):
        self.add(self.one, 1)
        self.add(self.two, 2)

        self.client.force_authenticate(self.reader)
        response = self.client.post(f'/api/series/{self.series.slug}/progress/',
                                    {'post': self.one.slug}, format='json')
        self.assertEqual(response.data['completed'], 1)

    def test_next_post_is_the_first_unfinished_part(self):
        self.add(self.one, 1)
        self.add(self.two, 2)
        SeriesProgress.objects.create(user=self.reader, series=self.series, post=self.one)

        self.client.force_authenticate(self.reader)
        response = self.client.get(f'/api/series/{self.series.slug}/')
        self.assertEqual(response.data['next_post_slug'], self.two.slug)

    def test_next_post_is_null_once_the_series_is_finished(self):
        self.add(self.one, 1)
        SeriesProgress.objects.create(user=self.reader, series=self.series, post=self.one)

        self.client.force_authenticate(self.reader)
        response = self.client.get(f'/api/series/{self.series.slug}/')
        self.assertIsNone(response.data['next_post_slug'])

    def test_unmarking_a_part_reduces_the_count(self):
        self.add(self.one, 1)
        SeriesProgress.objects.create(user=self.reader, series=self.series, post=self.one)

        self.client.force_authenticate(self.reader)
        response = self.client.delete(
            f'/api/series/{self.series.slug}/progress/?post={self.one.slug}'
        )
        self.assertEqual(response.data['completed'], 0)

    def test_an_anonymous_reader_has_no_progress(self):
        self.add(self.one, 1)
        response = self.client.get(f'/api/series/{self.series.slug}/')
        self.assertEqual(response.data['completed_count'], 0)
        self.assertEqual(response.data['completed_post_ids'], [])


class ReadingHistoryTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.reader = make_user('r@example.com', 'reader')
        self.post = make_post(self.author)

    def test_progress_is_recorded_once_per_post(self):
        self.client.force_authenticate(self.reader)
        self.client.post(f'/api/posts/{self.post.slug}/progress/', {'progress': 20},
                         format='json')
        self.client.post(f'/api/posts/{self.post.slug}/progress/', {'progress': 60},
                         format='json')

        rows = ReadingHistory.objects.filter(user=self.reader)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().progress, 60)

    def test_reaching_the_end_counts_as_finished(self):
        self.client.force_authenticate(self.reader)
        self.client.post(f'/api/posts/{self.post.slug}/progress/', {'progress': 97},
                         format='json')
        self.assertTrue(ReadingHistory.objects.get(user=self.reader).is_finished)

    def test_history_lists_what_i_read(self):
        ReadingHistory.objects.create(user=self.reader, post=self.post, progress=40)
        self.client.force_authenticate(self.reader)
        response = self.client.get('/api/reading-history/')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['post']['slug'], self.post.slug)

    def test_continue_reading_skips_finished_articles(self):
        finished = make_post(self.author, title='Done')
        ReadingHistory.objects.create(user=self.reader, post=self.post, progress=40)
        ReadingHistory.objects.create(user=self.reader, post=finished, progress=100,
                                      is_finished=True)

        self.client.force_authenticate(self.reader)
        response = self.client.get('/api/reading-history/', {'unfinished': 'true'})
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['post']['slug'], self.post.slug)

    def test_history_is_private_to_its_owner(self):
        ReadingHistory.objects.create(user=self.reader, post=self.post, progress=40)
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get('/api/reading-history/').data['count'], 0)

    def test_clearing_history(self):
        ReadingHistory.objects.create(user=self.reader, post=self.post, progress=40)
        self.client.force_authenticate(self.reader)
        self.client.delete('/api/reading-history/clear/')
        self.assertEqual(ReadingHistory.objects.filter(user=self.reader).count(), 0)

    def test_anonymous_readers_cannot_record_progress(self):
        response = self.client.post(f'/api/posts/{self.post.slug}/progress/',
                                    {'progress': 10}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
