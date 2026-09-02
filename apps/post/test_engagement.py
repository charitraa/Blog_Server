"""Topic follows, the personalised feed, recommendations, comment likes and pinning."""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.comment.models import Comment, CommentLike
from apps.post.models import Bookmark, Category, Like, Post, Tag
from apps.user.models import Follow, TopicFollow

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule.'


def make_user(email='reader@example.com', username='reader', **extra):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Ada', last_name='Lovelace', is_verified=True, **extra
    )


def make_post(author, title='A post', **extra):
    extra.setdefault('content', BODY)
    extra.setdefault('status', Post.Status.PUBLISHED)
    return Post.objects.create(title=title, author=author, **extra)


class TopicFollowTests(APITestCase):
    def setUp(self):
        self.reader = make_user()
        self.category = Category.objects.create(name='Cybersecurity')
        self.tag = Tag.objects.create(name='React')

    def test_following_a_category(self):
        self.client.force_authenticate(self.reader)
        response = self.client.post(f'/api/topics/category/{self.category.slug}/follow/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_following'])
        self.assertEqual(response.data['follower_count'], 1)

    def test_following_a_tag(self):
        self.client.force_authenticate(self.reader)
        response = self.client.post(f'/api/topics/tag/{self.tag.slug}/follow/')
        self.assertTrue(response.data['is_following'])

    def test_following_twice_creates_one_row(self):
        self.client.force_authenticate(self.reader)
        self.client.post(f'/api/topics/category/{self.category.slug}/follow/')
        self.client.post(f'/api/topics/category/{self.category.slug}/follow/')
        self.assertEqual(TopicFollow.objects.count(), 1)

    def test_unfollowing(self):
        TopicFollow.objects.create(user=self.reader, category=self.category)
        self.client.force_authenticate(self.reader)
        response = self.client.delete(f'/api/topics/category/{self.category.slug}/follow/')
        self.assertFalse(response.data['is_following'])
        self.assertEqual(TopicFollow.objects.count(), 0)

    def test_an_unknown_kind_is_rejected(self):
        self.client.force_authenticate(self.reader)
        response = self.client.post('/api/topics/planet/mars/follow/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_following_requires_sign_in(self):
        response = self.client.post(f'/api/topics/tag/{self.tag.slug}/follow/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_my_topics_lists_both_kinds(self):
        TopicFollow.objects.create(user=self.reader, category=self.category)
        TopicFollow.objects.create(user=self.reader, tag=self.tag)

        self.client.force_authenticate(self.reader)
        response = self.client.get('/api/topics/following/')
        kinds = sorted(row['kind'] for row in response.data['results'])
        self.assertEqual(kinds, ['category', 'tag'])

    def test_topics_are_private_to_the_follower(self):
        TopicFollow.objects.create(user=self.reader, category=self.category)
        other = make_user('o@example.com', 'other')
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get('/api/topics/following/').data['count'], 0)


class FeedTests(APITestCase):
    def setUp(self):
        self.reader = make_user()
        self.author = make_user('a@example.com', 'author')
        self.stranger = make_user('s@example.com', 'stranger')
        self.category = Category.objects.create(name='Cybersecurity')
        self.tag = Tag.objects.create(name='React')

    def test_the_feed_needs_a_sign_in(self):
        self.assertEqual(self.client.get('/api/posts/feed/').status_code,
                         status.HTTP_401_UNAUTHORIZED)

    def test_an_empty_feed_when_following_nobody(self):
        make_post(self.author)
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/posts/feed/').data['count'], 0)

    def test_posts_from_a_followed_author_appear(self):
        make_post(self.author, title='From a followed author')
        Follow.objects.create(follower=self.reader, following=self.author)

        self.client.force_authenticate(self.reader)
        response = self.client.get('/api/posts/feed/')
        self.assertEqual(response.data['count'], 1)

    def test_posts_in_a_followed_category_appear(self):
        make_post(self.stranger, title='Security piece', category=self.category)
        TopicFollow.objects.create(user=self.reader, category=self.category)

        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/posts/feed/').data['count'], 1)

    def test_posts_with_a_followed_tag_appear(self):
        post = make_post(self.stranger, title='Hooks')
        post.tags.add(self.tag)
        TopicFollow.objects.create(user=self.reader, tag=self.tag)

        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/posts/feed/').data['count'], 1)

    def test_my_own_posts_are_not_in_my_feed(self):
        make_post(self.reader, title='Mine', category=self.category)
        TopicFollow.objects.create(user=self.reader, category=self.category)

        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/posts/feed/').data['count'], 0)

    def test_a_post_matching_twice_appears_once(self):
        post = make_post(self.author, title='Both', category=self.category)
        post.tags.add(self.tag)
        Follow.objects.create(follower=self.reader, following=self.author)
        TopicFollow.objects.create(user=self.reader, category=self.category)
        TopicFollow.objects.create(user=self.reader, tag=self.tag)

        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/posts/feed/').data['count'], 1)

    def test_drafts_never_reach_the_feed(self):
        make_post(self.author, title='Draft', status=Post.Status.DRAFT)
        Follow.objects.create(follower=self.reader, following=self.author)

        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/posts/feed/').data['count'], 0)


class RecommendationTests(APITestCase):
    def setUp(self):
        self.reader = make_user()
        self.author = make_user('a@example.com', 'author')
        self.category = Category.objects.create(name='Cybersecurity')
        self.tag = Tag.objects.create(name='XSS')

    def test_a_cold_start_falls_back_to_popular(self):
        popular = make_post(self.author, title='Popular', view_count=500)
        make_post(self.author, title='Quiet', view_count=1)

        self.client.force_authenticate(self.reader)
        response = self.client.get('/api/posts/recommended/')
        self.assertEqual(response.data['results'][0]['slug'], popular.slug)

    def test_liking_a_post_drives_recommendations_in_that_category(self):
        liked = make_post(self.author, title='Liked', category=self.category)
        match = make_post(self.author, title='Same category', category=self.category)
        make_post(self.author, title='Unrelated')
        Like.objects.create(post=liked, user=self.reader)

        self.client.force_authenticate(self.reader)
        slugs = [row['slug'] for row in self.client.get('/api/posts/recommended/').data['results']]
        self.assertIn(match.slug, slugs)

    def test_an_already_read_post_is_not_recommended_back(self):
        liked = make_post(self.author, title='Liked', category=self.category)
        Like.objects.create(post=liked, user=self.reader)
        make_post(self.author, title='Other', category=self.category)

        self.client.force_authenticate(self.reader)
        slugs = [row['slug'] for row in self.client.get('/api/posts/recommended/').data['results']]
        self.assertNotIn(liked.slug, slugs)

    def test_bookmarks_count_as_a_signal(self):
        saved = make_post(self.author, title='Saved', category=self.category)
        match = make_post(self.author, title='Match', category=self.category)
        Bookmark.objects.create(post=saved, user=self.reader)

        self.client.force_authenticate(self.reader)
        slugs = [row['slug'] for row in self.client.get('/api/posts/recommended/').data['results']]
        self.assertIn(match.slug, slugs)

    def test_my_own_posts_are_never_recommended(self):
        mine = make_post(self.reader, title='Mine', category=self.category)
        liked = make_post(self.author, title='Liked', category=self.category)
        Like.objects.create(post=liked, user=self.reader)

        self.client.force_authenticate(self.reader)
        slugs = [row['slug'] for row in self.client.get('/api/posts/recommended/').data['results']]
        self.assertNotIn(mine.slug, slugs)


class CommentEngagementTests(APITestCase):
    def setUp(self):
        self.author = make_user('a@example.com', 'author')
        self.reader = make_user()
        self.post = make_post(self.author)
        self.comment = Comment.objects.create(
            post=self.post, author=self.reader, content='Good read',
        )

    def test_liking_a_comment(self):
        self.client.force_authenticate(self.author)
        response = self.client.post(f'/api/comments/{self.comment.id}/like/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_liked'])
        self.assertEqual(response.data['like_count'], 1)

    def test_liking_twice_counts_once(self):
        self.client.force_authenticate(self.author)
        self.client.post(f'/api/comments/{self.comment.id}/like/')
        response = self.client.post(f'/api/comments/{self.comment.id}/like/')
        self.assertEqual(response.data['like_count'], 1)

    def test_unliking(self):
        CommentLike.objects.create(comment=self.comment, user=self.author)
        self.client.force_authenticate(self.author)
        response = self.client.delete(f'/api/comments/{self.comment.id}/like/')
        self.assertFalse(response.data['is_liked'])
        self.assertEqual(response.data['like_count'], 0)

    def test_the_thread_reports_like_state(self):
        CommentLike.objects.create(comment=self.comment, user=self.author)
        self.client.force_authenticate(self.author)
        row = self.client.get(f'/api/posts/{self.post.slug}/comments/').data['results'][0]
        self.assertEqual(row['like_count'], 1)
        self.assertTrue(row['is_liked'])

    def test_the_post_author_can_pin_a_comment(self):
        self.client.force_authenticate(self.author)
        response = self.client.post(f'/api/comments/{self.comment.id}/pin/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.comment.refresh_from_db()
        self.assertTrue(self.comment.is_pinned)

    def test_a_commenter_cannot_pin_their_own_comment(self):
        self.client.force_authenticate(self.reader)
        response = self.client.post(f'/api/comments/{self.comment.id}/pin/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_only_one_comment_stays_pinned(self):
        second = Comment.objects.create(post=self.post, author=self.reader, content='Another')
        self.client.force_authenticate(self.author)
        self.client.post(f'/api/comments/{self.comment.id}/pin/')
        self.client.post(f'/api/comments/{second.id}/pin/')

        self.comment.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(self.comment.is_pinned)
        self.assertTrue(second.is_pinned)

    def test_a_reply_cannot_be_pinned(self):
        reply = Comment.objects.create(
            post=self.post, author=self.reader, parent=self.comment, content='Reply',
        )
        self.client.force_authenticate(self.author)
        response = self.client.post(f'/api/comments/{reply.id}/pin/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_pinned_comment_sorts_first(self):
        newer = Comment.objects.create(post=self.post, author=self.reader, content='Newer')
        self.comment.is_pinned = True
        self.comment.save()

        rows = self.client.get(f'/api/posts/{self.post.slug}/comments/').data['results']
        self.assertEqual(rows[0]['id'], str(self.comment.id))
        self.assertEqual(rows[1]['id'], str(newer.id))

    def test_sorting_by_popularity(self):
        popular = Comment.objects.create(post=self.post, author=self.reader, content='Popular')
        CommentLike.objects.create(comment=popular, user=self.author)

        rows = self.client.get(
            f'/api/posts/{self.post.slug}/comments/', {'sort': 'popular'}
        ).data['results']
        self.assertEqual(rows[0]['id'], str(popular.id))

    def test_sorting_oldest_first(self):
        newer = Comment.objects.create(post=self.post, author=self.reader, content='Newer')
        rows = self.client.get(
            f'/api/posts/{self.post.slug}/comments/', {'sort': 'oldest'}
        ).data['results']
        self.assertEqual(rows[0]['id'], str(self.comment.id))

    def test_can_pin_flag_is_only_true_for_the_post_author(self):
        self.client.force_authenticate(self.reader)
        row = self.client.get(f'/api/posts/{self.post.slug}/comments/').data['results'][0]
        self.assertFalse(row['can_pin'])

        self.client.force_authenticate(self.author)
        row = self.client.get(f'/api/posts/{self.post.slug}/comments/').data['results'][0]
        self.assertTrue(row['can_pin'])
