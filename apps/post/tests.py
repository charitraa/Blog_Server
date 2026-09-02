"""Post CRUD, ownership, drafts, likes, search, filtering and pagination tests."""

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.post.models import Bookmark, Category, EditorImage, Like, Post, PostView, Tag
from apps.post.utils import build_excerpt, reading_time_minutes, sanitize_html

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule.'


def make_user(email='writer@example.com', username='writer'):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Ada', last_name='Lovelace', is_verified=True,
    )


def make_post(author, title='A published post', **extra):
    extra.setdefault('content', BODY)
    extra.setdefault('status', Post.Status.PUBLISHED)
    return Post.objects.create(title=title, author=author, **extra)


class ContentHelperTests(APITestCase):
    def test_scripts_are_stripped_from_content(self):
        cleaned = sanitize_html('<p>Safe</p><script>alert(1)</script>')
        self.assertIn('Safe', cleaned)
        self.assertNotIn('<script>', cleaned)
        self.assertNotIn('alert(1)', cleaned)

    def test_event_handlers_are_stripped(self):
        cleaned = sanitize_html('<p onclick="steal()">Text</p>')
        self.assertNotIn('onclick', cleaned)

    def test_javascript_urls_are_stripped(self):
        cleaned = sanitize_html('<a href="javascript:alert(1)">click</a>')
        self.assertNotIn('javascript:', cleaned)

    def test_formatting_tags_survive(self):
        cleaned = sanitize_html('<h2>Title</h2><p><strong>bold</strong></p><pre><code>x=1</code></pre>')
        for fragment in ('<h2>', '<strong>', '<code>'):
            self.assertIn(fragment, cleaned)

    def test_reading_time_is_at_least_one_minute(self):
        self.assertEqual(reading_time_minutes('one word'), 1)
        self.assertEqual(reading_time_minutes('word ' * 400), 2)

    def test_excerpt_is_trimmed_on_a_word_boundary(self):
        excerpt = build_excerpt('<p>' + 'word ' * 100 + '</p>', limit=50)
        self.assertLessEqual(len(excerpt), 51)
        self.assertTrue(excerpt.endswith('…'))


class PostModelTests(APITestCase):
    def setUp(self):
        self.author = make_user()

    def test_slug_is_generated_and_unique(self):
        first = make_post(self.author, title='Learning Django')
        second = make_post(self.author, title='Learning Django')
        self.assertEqual(first.slug, 'learning-django')
        self.assertNotEqual(first.slug, second.slug)

    def test_published_at_is_stamped_on_publish_and_cleared_on_unpublish(self):
        post = make_post(self.author, status=Post.Status.DRAFT)
        self.assertIsNone(post.published_at)

        post.status = Post.Status.PUBLISHED
        post.save()
        self.assertIsNotNone(post.published_at)

        post.status = Post.Status.DRAFT
        post.save()
        self.assertIsNone(post.published_at)

    def test_reading_time_and_excerpt_are_filled_in(self):
        post = make_post(self.author)
        self.assertGreaterEqual(post.reading_time, 1)
        self.assertTrue(post.excerpt)


class PostReadTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.other = make_user('other@example.com', 'other')
        self.published = make_post(self.author, title='Public post')
        self.draft = make_post(self.author, title='Secret draft', status=Post.Status.DRAFT)

    def test_anonymous_list_shows_only_published_posts(self):
        response = self.client.get('/api/posts/')
        titles = [row['title'] for row in response.data['results']]
        self.assertIn('Public post', titles)
        self.assertNotIn('Secret draft', titles)

    def test_another_user_cannot_see_a_draft(self):
        self.client.force_authenticate(self.other)
        response = self.client.get('/api/posts/')
        titles = [row['title'] for row in response.data['results']]
        self.assertNotIn('Secret draft', titles)

        detail = self.client.get(f'/api/posts/{self.draft.slug}/')
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

    def test_status_draft_filter_does_not_leak_other_authors_drafts(self):
        self.client.force_authenticate(self.other)
        response = self.client.get('/api/posts/?status=draft')
        self.assertEqual(response.data['count'], 0)

    def test_author_sees_their_own_draft(self):
        self.client.force_authenticate(self.author)
        response = self.client.get(f'/api/posts/{self.draft.slug}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_detail_is_reachable_by_slug_and_by_uuid(self):
        by_slug = self.client.get(f'/api/posts/{self.published.slug}/')
        by_id = self.client.get(f'/api/posts/{self.published.id}/')
        self.assertEqual(by_slug.status_code, status.HTTP_200_OK)
        self.assertEqual(by_id.status_code, status.HTTP_200_OK)
        self.assertEqual(by_slug.data['id'], by_id.data['id'])

    def test_list_response_carries_the_fields_the_ui_needs(self):
        response = self.client.get('/api/posts/')
        row = response.data['results'][0]
        for field in ('id', 'title', 'slug', 'excerpt', 'cover_image', 'author', 'category',
                      'tags', 'reading_time', 'like_count', 'comment_count', 'view_count',
                      'is_liked', 'published_at'):
            self.assertIn(field, row)
        self.assertIn('username', row['author'])
        self.assertNotIn('content', row)

    def test_list_does_not_scale_queries_with_post_count(self):
        for index in range(6):
            make_post(self.author, title=f'Extra {index}')
        with self.assertNumQueries(3):  # count, page, prefetched tags
            self.client.get('/api/posts/')


class PostWriteTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.other = make_user('other@example.com', 'other')
        self.category = Category.objects.create(name='Programming')

    def test_anonymous_cannot_create(self):
        response = self.client.post('/api/posts/', {'title': 'Nope', 'content': BODY}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_defaults_to_draft_and_assigns_the_author(self):
        self.client.force_authenticate(self.author)
        response = self.client.post('/api/posts/', {
            'title': 'My first post', 'content': BODY,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'draft')
        self.assertEqual(response.data['author']['username'], self.author.username)
        self.assertTrue(response.data['slug'])

    def test_author_cannot_be_spoofed(self):
        self.client.force_authenticate(self.author)
        response = self.client.post('/api/posts/', {
            'title': 'Whose post', 'content': BODY, 'author': str(self.other.id),
        }, format='json')
        self.assertEqual(Post.objects.get(pk=response.data['id']).author, self.author)

    def test_counters_cannot_be_set_by_the_client(self):
        self.client.force_authenticate(self.author)
        response = self.client.post('/api/posts/', {
            'title': 'Inflated', 'content': BODY, 'view_count': 9999, 'reading_time': 99,
        }, format='json')
        self.assertEqual(response.data['view_count'], 0)
        self.assertNotEqual(response.data['reading_time'], 99)

    def test_create_with_category_and_tags(self):
        self.client.force_authenticate(self.author)
        response = self.client.post('/api/posts/', {
            'title': 'Tagged post', 'content': BODY,
            'category': 'programming', 'tags': ['Python', 'Django'],
            'status': 'published',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['category']['slug'], 'programming')
        self.assertEqual({tag['name'] for tag in response.data['tags']}, {'Python', 'Django'})

    def test_tags_are_reused_case_insensitively(self):
        self.client.force_authenticate(self.author)
        self.client.post('/api/posts/', {'title': 'One', 'content': BODY, 'tags': ['Python']},
                         format='json')
        self.client.post('/api/posts/', {'title': 'Two', 'content': BODY, 'tags': ['python']},
                         format='json')
        self.assertEqual(Tag.objects.filter(name__iexact='python').count(), 1)

    def test_stored_content_is_sanitized(self):
        self.client.force_authenticate(self.author)
        response = self.client.post('/api/posts/', {
            'title': 'XSS attempt',
            'content': f'<p>{BODY}</p><script>alert("xss")</script>',
        }, format='json')
        stored = Post.objects.get(pk=response.data['id']).content
        self.assertNotIn('<script>', stored)

    def test_short_content_is_rejected(self):
        self.client.force_authenticate(self.author)
        response = self.client.post('/api/posts/', {'title': 'Too short', 'content': 'hi'},
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('content', response.data)

    def test_draft_can_be_published_then_edited(self):
        self.client.force_authenticate(self.author)
        created = self.client.post('/api/posts/', {'title': 'Draft first', 'content': BODY},
                                   format='json')
        slug = created.data['slug']

        published = self.client.patch(f'/api/posts/{slug}/', {'status': 'published'}, format='json')
        self.assertEqual(published.data['status'], 'published')
        self.assertIsNotNone(published.data['published_at'])

        edited = self.client.patch(f'/api/posts/{slug}/', {'title': 'Draft first, edited'},
                                   format='json')
        self.assertEqual(edited.data['title'], 'Draft first, edited')

    def test_slug_stays_stable_when_the_title_changes(self):
        self.client.force_authenticate(self.author)
        created = self.client.post('/api/posts/', {'title': 'Original title', 'content': BODY},
                                   format='json')
        slug = created.data['slug']
        edited = self.client.patch(f'/api/posts/{slug}/', {'title': 'Completely different'},
                                   format='json')
        self.assertEqual(edited.data['slug'], slug)

    def test_a_different_user_cannot_edit_or_delete(self):
        post = make_post(self.author)
        self.client.force_authenticate(self.other)

        edit = self.client.patch(f'/api/posts/{post.slug}/', {'title': 'Hijacked'}, format='json')
        self.assertEqual(edit.status_code, status.HTTP_403_FORBIDDEN)

        delete = self.client.delete(f'/api/posts/{post.slug}/')
        self.assertEqual(delete.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Post.objects.filter(pk=post.pk).exists())

    def test_a_different_user_cannot_publish_someone_elses_draft(self):
        draft = make_post(self.author, status=Post.Status.DRAFT)
        self.client.force_authenticate(self.other)
        response = self.client.patch(f'/api/posts/{draft.slug}/', {'status': 'published'},
                                     format='json')
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_author_can_delete_their_own_post(self):
        post = make_post(self.author)
        self.client.force_authenticate(self.author)
        response = self.client.delete(f'/api/posts/{post.slug}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        # Deleting is reversible: the row moves to the author's trash so its
        # comments and likes survive and a misclick can be undone.
        post.refresh_from_db()
        self.assertTrue(post.is_deleted)

    def test_a_deleted_post_disappears_from_public_lists(self):
        post = make_post(self.author)
        self.client.force_authenticate(self.author)
        self.client.delete(f'/api/posts/{post.slug}/')

        self.client.force_authenticate(None)
        listed = self.client.get('/api/posts/')
        self.assertNotIn(post.slug, [row['slug'] for row in listed.data['results']])

    def test_a_deleted_post_can_be_restored(self):
        post = make_post(self.author)
        self.client.force_authenticate(self.author)
        self.client.delete(f'/api/posts/{post.slug}/')

        restored = self.client.post(f'/api/posts/{post.slug}/restore/')
        self.assertEqual(restored.status_code, status.HTTP_200_OK)
        post.refresh_from_db()
        self.assertFalse(post.is_deleted)

    def test_trash_lists_only_my_deleted_posts(self):
        mine = make_post(self.author, title='Mine')
        theirs = make_post(self.other, title='Theirs')
        mine.soft_delete()
        theirs.soft_delete()

        self.client.force_authenticate(self.author)
        response = self.client.get('/api/posts/trash/')
        self.assertEqual([row['slug'] for row in response.data['results']], [mine.slug])

    def test_an_editor_may_moderate_another_users_post(self):
        post = make_post(self.author)
        staff = make_user('staff@example.com', 'staff')
        # Authority to touch someone else's content comes from the role, not
        # from the Django-admin `is_staff` flag.
        staff.role = 'editor'
        staff.save()
        self.client.force_authenticate(staff)
        response = self.client.delete(f'/api/posts/{post.slug}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class LikeTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.reader = make_user('reader@example.com', 'reader')
        self.post = make_post(self.author)

    def test_anonymous_cannot_like(self):
        response = self.client.post(f'/api/posts/{self.post.slug}/like/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_like_then_unlike(self):
        self.client.force_authenticate(self.reader)
        liked = self.client.post(f'/api/posts/{self.post.slug}/like/')
        self.assertEqual(liked.data, {'is_liked': True, 'like_count': 1})

        unliked = self.client.delete(f'/api/posts/{self.post.slug}/like/')
        self.assertEqual(unliked.data, {'is_liked': False, 'like_count': 0})

    def test_liking_twice_creates_only_one_like(self):
        self.client.force_authenticate(self.reader)
        self.client.post(f'/api/posts/{self.post.slug}/like/')
        second = self.client.post(f'/api/posts/{self.post.slug}/like/')
        self.assertEqual(second.data['like_count'], 1)
        self.assertEqual(Like.objects.filter(post=self.post).count(), 1)

    def test_duplicate_likes_are_blocked_at_the_database_level(self):
        from django.db import IntegrityError, transaction
        Like.objects.create(post=self.post, user=self.reader)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Like.objects.create(post=self.post, user=self.reader)

    def test_is_liked_reflects_the_requesting_user(self):
        Like.objects.create(post=self.post, user=self.reader)

        anonymous = self.client.get(f'/api/posts/{self.post.slug}/')
        self.assertFalse(anonymous.data['is_liked'])
        self.assertEqual(anonymous.data['like_count'], 1)

        self.client.force_authenticate(self.reader)
        signed_in = self.client.get(f'/api/posts/{self.post.slug}/')
        self.assertTrue(signed_in.data['is_liked'])


class ViewCountTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.post = make_post(self.author)

    def test_repeated_requests_count_once(self):
        self.client.get(f'/api/posts/{self.post.slug}/')
        self.client.get(f'/api/posts/{self.post.slug}/')
        self.client.get(f'/api/posts/{self.post.slug}/')

        self.post.refresh_from_db()
        self.assertEqual(self.post.view_count, 1)
        self.assertEqual(PostView.objects.filter(post=self.post).count(), 1)

    def test_the_author_does_not_inflate_their_own_count(self):
        self.client.force_authenticate(self.author)
        self.client.get(f'/api/posts/{self.post.slug}/')
        self.post.refresh_from_db()
        self.assertEqual(self.post.view_count, 0)


class SearchFilterSortTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.other = make_user('other@example.com', 'other')
        self.tech = Category.objects.create(name='Technology')
        self.design = Category.objects.create(name='Design')

        self.python_post = make_post(self.author, title='Learning Python properly',
                                     content='A guide to python generators and decorators.',
                                     category=self.tech)
        self.python_post.tags.set([Tag.get_or_create_by_name('Python')])

        self.design_post = make_post(self.other, title='Type scales in practice',
                                     content='Typography systems for the web.',
                                     category=self.design)

    def test_search_matches_the_title(self):
        response = self.client.get('/api/posts/?search=Python')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['title'], 'Learning Python properly')

    def test_search_matches_the_body(self):
        response = self.client.get('/api/posts/?search=typography')
        self.assertEqual(response.data['count'], 1)

    def test_search_matches_the_author(self):
        response = self.client.get('/api/posts/?search=other')
        self.assertGreaterEqual(response.data['count'], 1)

    def test_search_with_no_match_returns_an_empty_page(self):
        response = self.client.get('/api/posts/?search=zzzznotfound')
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])

    def test_filter_by_category(self):
        response = self.client.get('/api/posts/?category=technology')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['category']['slug'], 'technology')

    def test_filter_by_tag(self):
        response = self.client.get('/api/posts/?tag=python')
        self.assertEqual(response.data['count'], 1)

    def test_filter_by_author(self):
        response = self.client.get(f'/api/posts/?author={self.other.username}')
        self.assertEqual(response.data['count'], 1)

    def test_ordering_by_most_liked(self):
        Like.objects.create(post=self.design_post, user=self.author)
        response = self.client.get('/api/posts/?ordering=-like_count')
        self.assertEqual(response.data['results'][0]['title'], 'Type scales in practice')

    def test_unknown_ordering_field_is_ignored(self):
        response = self.client.get('/api/posts/?ordering=author__password')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class CategoryAndTagTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.category = Category.objects.create(name='Technology', description='Tech writing')
        post = make_post(self.author, category=self.category)
        post.tags.set([Tag.get_or_create_by_name('Django')])

    def test_category_list_is_public_and_counts_published_posts(self):
        response = self.client.get('/api/categories/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(item for item in response.data if item['slug'] == 'technology')
        self.assertEqual(row['post_count'], 1)

    def test_category_detail(self):
        response = self.client.get('/api/categories/technology/')
        self.assertEqual(response.data['name'], 'Technology')

    def test_tag_list_only_shows_tags_in_use(self):
        Tag.objects.create(name='Unused')
        response = self.client.get('/api/tags/')
        names = [row['name'] for row in response.data['results']]
        self.assertIn('Django', names)
        self.assertNotIn('Unused', names)


class PaginationTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        for index in range(15):
            make_post(self.author, title=f'Post number {index}')

    def test_default_page_size_and_envelope(self):
        response = self.client.get('/api/posts/')
        self.assertEqual(response.data['count'], 15)
        self.assertEqual(len(response.data['results']), 10)
        self.assertIsNotNone(response.data['next'])
        self.assertIsNone(response.data['previous'])

    def test_second_page(self):
        response = self.client.get('/api/posts/?page=2')
        self.assertEqual(len(response.data['results']), 5)
        self.assertIsNone(response.data['next'])
        self.assertIsNotNone(response.data['previous'])

    def test_page_size_is_capped(self):
        response = self.client.get('/api/posts/?page_size=500')
        self.assertLessEqual(len(response.data['results']), 50)

    def test_out_of_range_page_is_404(self):
        response = self.client.get('/api/posts/?page=99')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TrendingAndRelatedTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.reader = make_user('reader@example.com', 'reader')
        self.category = Category.objects.create(name='Technology')
        self.quiet = make_post(self.author, title='Quiet post', category=self.category)
        self.loud = make_post(self.author, title='Loud post', category=self.category)
        Like.objects.create(post=self.loud, user=self.reader)

    def test_trending_ranks_engagement_first(self):
        response = self.client.get('/api/posts/trending/')
        self.assertEqual(response.data['results'][0]['title'], 'Loud post')

    def test_related_posts_exclude_the_post_itself(self):
        response = self.client.get(f'/api/posts/{self.loud.slug}/related/')
        slugs = [row['slug'] for row in response.data]
        self.assertNotIn(self.loud.slug, slugs)
        self.assertIn(self.quiet.slug, slugs)


class LegacyRouteTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.post = make_post(self.author)

    def test_legacy_post_list_still_answers(self):
        response = self.client.get('/post/posts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_legacy_post_detail_by_uuid_still_answers(self):
        response = self.client.get(f'/post/posts/{self.post.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_legacy_author_post_count_still_answers(self):
        response = self.client.get(f'/post/posts/count/{self.author.id}/')
        self.assertEqual(response.data['post_count'], 1)

    def test_legacy_login_route_still_answers(self):
        with override_settings(REQUIRE_EMAIL_VERIFICATION=False):
            response = self.client.post(
                '/user/login/', {'email': self.author.email, 'password': 'StrongPass!234'},
                format='json',
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class BookmarkTests(APITestCase):
    """Saving posts for later."""

    def setUp(self):
        self.author = make_user()
        self.reader = make_user('reader@example.com', 'reader')
        self.post = make_post(self.author)
        self.url = f'/api/posts/{self.post.slug}/bookmark/'

    def test_bookmarking_requires_sign_in(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reader_can_bookmark_and_unbookmark(self):
        self.client.force_authenticate(self.reader)

        saved = self.client.post(self.url)
        self.assertEqual(saved.status_code, status.HTTP_200_OK)
        self.assertTrue(saved.data['is_bookmarked'])
        self.assertEqual(Bookmark.objects.filter(user=self.reader).count(), 1)

        removed = self.client.delete(self.url)
        self.assertFalse(removed.data['is_bookmarked'])
        self.assertEqual(Bookmark.objects.filter(user=self.reader).count(), 0)

    def test_bookmarking_twice_creates_one_row(self):
        self.client.force_authenticate(self.reader)
        self.client.post(self.url)
        self.client.post(self.url)
        self.assertEqual(Bookmark.objects.filter(user=self.reader, post=self.post).count(), 1)

    def test_unbookmarking_something_unsaved_is_not_an_error(self):
        self.client.force_authenticate(self.reader)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_bookmark_list_shows_only_my_saves(self):
        other = make_post(self.author, title='Another post')
        Bookmark.objects.create(post=self.post, user=self.reader)
        Bookmark.objects.create(post=other, user=self.author)

        self.client.force_authenticate(self.reader)
        response = self.client.get('/api/bookmarks/')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['slug'], self.post.slug)

    def test_post_list_reports_bookmark_state(self):
        Bookmark.objects.create(post=self.post, user=self.reader)
        self.client.force_authenticate(self.reader)
        response = self.client.get('/api/posts/')
        self.assertTrue(response.data['results'][0]['is_bookmarked'])

    def test_anonymous_reader_is_never_bookmarked(self):
        response = self.client.get('/api/posts/')
        self.assertFalse(response.data['results'][0]['is_bookmarked'])


class DraftPreviewTests(APITestCase):
    """Sharing an unpublished draft by link."""

    def setUp(self):
        self.author = make_user()
        self.draft = make_post(self.author, title='Secret draft', status=Post.Status.DRAFT)
        self.url = f'/api/posts/{self.draft.slug}/preview/'

    def test_a_valid_token_reads_the_draft_without_signing_in(self):
        response = self.client.get(self.url, {'token': str(self.draft.preview_token)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Secret draft')

    def test_a_wrong_token_is_a_404(self):
        import uuid
        response = self.client.get(self.url, {'token': str(uuid.uuid4())})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_missing_token_is_rejected(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_previewing_does_not_count_as_a_view(self):
        self.client.get(self.url, {'token': str(self.draft.preview_token)})
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.view_count, 0)

    def test_the_author_is_given_the_preview_token(self):
        self.client.force_authenticate(self.author)
        response = self.client.get(f'/api/posts/{self.draft.slug}/')
        self.assertEqual(str(response.data['preview_token']), str(self.draft.preview_token))

    def test_a_stranger_is_never_given_the_preview_token(self):
        published = make_post(self.author, title='Public one')
        stranger = make_user('stranger@example.com', 'stranger')
        self.client.force_authenticate(stranger)
        response = self.client.get(f'/api/posts/{published.slug}/')
        self.assertNotIn('preview_token', response.data)

    def test_rotating_the_token_invalidates_the_old_link(self):
        old_token = str(self.draft.preview_token)
        self.client.force_authenticate(self.author)

        rotated = self.client.post(f'/api/posts/{self.draft.slug}/preview-token/')
        self.assertEqual(rotated.status_code, status.HTTP_200_OK)
        self.assertNotEqual(str(rotated.data['preview_token']), old_token)

        self.client.force_authenticate(None)
        stale = self.client.get(self.url, {'token': old_token})
        self.assertEqual(stale.status_code, status.HTTP_404_NOT_FOUND)

    def test_only_the_author_may_rotate_the_token(self):
        stranger = make_user('stranger@example.com', 'stranger')
        self.client.force_authenticate(stranger)
        response = self.client.post(f'/api/posts/{self.draft.slug}/preview-token/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class EditorImageUploadTests(APITestCase):
    """Inline images uploaded from the post editor."""

    def setUp(self):
        self.author = make_user()
        self.url = '/api/uploads/images/'

    def make_image(self, name='inline.png'):
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buffer = io.BytesIO()
        Image.new('RGB', (40, 40), 'blue').save(buffer, format='PNG')
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

    def test_upload_requires_sign_in(self):
        response = self.client.post(self.url, {'image': self.make_image()}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_upload_returns_a_usable_url(self):
        self.client.force_authenticate(self.author)
        response = self.client.post(self.url, {'image': self.make_image()}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['url'].startswith('http'))
        self.assertEqual(EditorImage.objects.filter(uploaded_by=self.author).count(), 1)

    def test_a_non_image_is_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_authenticate(self.author)
        bad = SimpleUploadedFile('notes.txt', b'not an image', content_type='text/plain')
        response = self.client.post(self.url, {'image': bad}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_the_list_shows_only_my_uploads(self):
        other = make_user('other@example.com', 'other')
        self.client.force_authenticate(other)
        self.client.post(self.url, {'image': self.make_image()}, format='multipart')

        self.client.force_authenticate(self.author)
        response = self.client.get('/api/uploads/images/mine/')
        self.assertEqual(response.data['count'], 0)


class FeedAndSitemapTests(APITestCase):
    """Syndication and SEO surfaces."""

    def setUp(self):
        self.author = make_user()
        self.published = make_post(self.author, title='Indexed post')
        make_post(self.author, title='Hidden draft', status=Post.Status.DRAFT)

    def test_rss_feed_lists_published_posts(self):
        response = self.client.get('/feed/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.content.decode()
        self.assertIn('Indexed post', body)
        self.assertNotIn('Hidden draft', body)

    def test_atom_feed_is_served(self):
        response = self.client.get('/feed/atom/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_feed_links_point_at_the_frontend_not_the_api(self):
        from django.conf import settings

        body = self.client.get('/feed/').content.decode()
        self.assertIn(f'{settings.FRONTEND_URL.rstrip("/")}/post/{self.published.slug}', body)

    def test_author_feed_is_served(self):
        response = self.client.get(f'/feed/author/{self.author.username}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('Indexed post', response.content.decode())

    def test_sitemap_lists_published_posts_only(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.content.decode()
        self.assertIn(f'/post/{self.published.slug}', body)
        self.assertNotIn('hidden-draft', body)

    def test_robots_points_crawlers_at_the_sitemap(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.content.decode()
        self.assertIn('Disallow: /api/', body)
        self.assertIn('sitemap.xml', body)
