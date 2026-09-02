"""Multiple reactions, and @mentions in comments."""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.comment.mentions import extract_usernames
from apps.comment.models import Comment
from apps.notification.models import Notification
from apps.post.models import Like, Post

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule.'


def make_user(email='r@example.com', username='reader'):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Ada', last_name='Lovelace', is_verified=True,
    )


class ReactionTests(APITestCase):
    def setUp(self):
        self.author = make_user('a@example.com', 'author')
        self.reader = make_user()
        self.post = Post.objects.create(title='A post', content=BODY, author=self.author,
                                        status=Post.Status.PUBLISHED)
        self.url = f'/api/posts/{self.post.slug}/like/'
        self.client.force_authenticate(self.reader)

    def test_a_plain_like_still_works(self):
        """Existing clients send no kind at all."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_liked'])
        self.assertEqual(response.data['my_reaction'], 'like')

    def test_a_named_reaction(self):
        response = self.client.post(self.url, {'kind': 'insightful'}, format='json')
        self.assertEqual(response.data['my_reaction'], 'insightful')
        self.assertEqual(Like.objects.get().kind, 'insightful')

    def test_changing_reaction_replaces_rather_than_stacks(self):
        """One person reacting is one reaction, whatever they picked."""
        self.client.post(self.url, {'kind': 'like'}, format='json')
        response = self.client.post(self.url, {'kind': 'love'}, format='json')

        self.assertEqual(Like.objects.filter(post=self.post).count(), 1)
        self.assertEqual(response.data['like_count'], 1)
        self.assertEqual(response.data['my_reaction'], 'love')

    def test_the_breakdown_counts_each_kind(self):
        other = make_user('o@example.com', 'other')
        Like.objects.create(post=self.post, user=other, kind='funny')

        response = self.client.post(self.url, {'kind': 'love'}, format='json')
        self.assertEqual(response.data['reactions'], {'funny': 1, 'love': 1})

    def test_an_unknown_reaction_is_rejected(self):
        response = self.client.post(self.url, {'kind': 'shrug'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Like.objects.count(), 0)

    def test_removing_a_reaction(self):
        self.client.post(self.url, {'kind': 'love'}, format='json')
        response = self.client.delete(self.url)
        self.assertFalse(response.data['is_liked'])
        self.assertIsNone(response.data['my_reaction'])
        self.assertEqual(Like.objects.count(), 0)

    def test_the_post_payload_reports_my_reaction(self):
        self.client.post(self.url, {'kind': 'funny'}, format='json')
        response = self.client.get(f'/api/posts/{self.post.slug}/')
        self.assertEqual(response.data['my_reaction'], 'funny')

    def test_a_guest_has_no_reaction(self):
        self.client.force_authenticate(None)
        response = self.client.get(f'/api/posts/{self.post.slug}/')
        self.assertIsNone(response.data['my_reaction'])

    def test_reacting_still_notifies_the_author(self):
        self.client.post(self.url, {'kind': 'love'}, format='json')
        self.assertTrue(
            Notification.objects.filter(recipient=self.author,
                                        verb=Notification.Verb.LIKE).exists()
        )


class MentionParsingTests(APITestCase):
    def test_a_simple_mention(self):
        self.assertEqual(extract_usernames('thanks @ada for this'), ['ada'])

    def test_several_mentions(self):
        self.assertEqual(extract_usernames('@ada and @grace'), ['ada', 'grace'])

    def test_duplicates_collapse(self):
        self.assertEqual(extract_usernames('@ada @ada @ada'), ['ada'])

    def test_an_email_address_is_not_a_mention(self):
        """Otherwise every address in a comment would ping a stranger."""
        self.assertEqual(extract_usernames('write to ada@example.com'), [])

    def test_too_short_a_handle_is_ignored(self):
        self.assertEqual(extract_usernames('@ab'), [])

    def test_the_count_is_capped(self):
        text = ' '.join(f'@user{i:02d}' for i in range(30))
        self.assertEqual(len(extract_usernames(text)), 10)

    def test_empty_text_is_safe(self):
        self.assertEqual(extract_usernames(''), [])
        self.assertEqual(extract_usernames(None), [])


class MentionNotificationTests(APITestCase):
    def setUp(self):
        self.author = make_user('a@example.com', 'author')
        self.reader = make_user()
        self.bystander = make_user('b@example.com', 'bystander')
        self.post = Post.objects.create(title='A post', content=BODY, author=self.author,
                                        status=Post.Status.PUBLISHED)

    def test_a_mentioned_user_is_notified(self):
        Comment.objects.create(post=self.post, author=self.reader,
                               content='what do you think @bystander?')
        self.assertTrue(
            Notification.objects.filter(recipient=self.bystander,
                                        verb=Notification.Verb.MENTION).exists()
        )

    def test_an_unknown_handle_is_ignored(self):
        Comment.objects.create(post=self.post, author=self.reader,
                               content='hello @nobodyhere')
        self.assertFalse(
            Notification.objects.filter(verb=Notification.Verb.MENTION).exists()
        )

    def test_mentioning_yourself_notifies_nobody(self):
        Comment.objects.create(post=self.post, author=self.reader, content='I, @reader, say')
        self.assertFalse(
            Notification.objects.filter(recipient=self.reader,
                                        verb=Notification.Verb.MENTION).exists()
        )

    def test_the_post_author_gets_one_notification_not_two(self):
        """They are already told about the comment itself."""
        Comment.objects.create(post=self.post, author=self.reader,
                               content='nice one @author')
        self.assertEqual(
            Notification.objects.filter(recipient=self.author).count(), 1,
        )
        self.assertFalse(
            Notification.objects.filter(recipient=self.author,
                                        verb=Notification.Verb.MENTION).exists()
        )

    def test_a_mention_survives_alongside_a_reply(self):
        parent = Comment.objects.create(post=self.post, author=self.author, content='First')
        Comment.objects.create(post=self.post, author=self.reader, parent=parent,
                               content='agreed @bystander')
        self.assertTrue(
            Notification.objects.filter(recipient=self.bystander,
                                        verb=Notification.Verb.MENTION).exists()
        )
