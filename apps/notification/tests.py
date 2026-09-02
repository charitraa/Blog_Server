"""Notification generation, scoping and read state."""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.comment.models import Comment
from apps.notification.models import Notification
from apps.post.models import Like, Post
from apps.user.models import Follow

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule.'


def make_user(email='writer@example.com', username='writer'):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Ada', last_name='Lovelace', is_verified=True,
    )


class NotificationSignalTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.reader = make_user('reader@example.com', 'reader')
        self.post = Post.objects.create(
            title='A post', content=BODY, author=self.author, status=Post.Status.PUBLISHED,
        )

    def test_a_like_notifies_the_post_author(self):
        Like.objects.create(post=self.post, user=self.reader)
        notification = Notification.objects.get(recipient=self.author)
        self.assertEqual(notification.verb, Notification.Verb.LIKE)
        self.assertEqual(notification.actor, self.reader)

    def test_liking_your_own_post_notifies_nobody(self):
        Like.objects.create(post=self.post, user=self.author)
        self.assertEqual(Notification.objects.count(), 0)

    def test_unliking_and_liking_again_does_not_duplicate(self):
        like = Like.objects.create(post=self.post, user=self.reader)
        like.delete()
        Like.objects.create(post=self.post, user=self.reader)
        self.assertEqual(Notification.objects.filter(verb=Notification.Verb.LIKE).count(), 1)

    def test_a_comment_notifies_the_post_author(self):
        Comment.objects.create(post=self.post, author=self.reader, content='Nice work')
        notification = Notification.objects.get(recipient=self.author)
        self.assertEqual(notification.verb, Notification.Verb.COMMENT)

    def test_a_reply_notifies_the_parent_comment_author_not_the_post_author(self):
        parent = Comment.objects.create(post=self.post, author=self.reader, content='First')
        Notification.objects.all().delete()

        third = make_user('third@example.com', 'third')
        Comment.objects.create(post=self.post, author=third, parent=parent, content='Agreed')

        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.reader)
        self.assertEqual(notification.verb, Notification.Verb.REPLY)

    def test_a_follow_notifies_the_followed_user(self):
        Follow.objects.create(follower=self.reader, following=self.author)
        notification = Notification.objects.get(recipient=self.author)
        self.assertEqual(notification.verb, Notification.Verb.FOLLOW)

    def test_the_message_names_the_actor(self):
        Follow.objects.create(follower=self.reader, following=self.author)
        notification = Notification.objects.get()
        self.assertIn(self.reader.display_name, notification.message)


class NotificationApiTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.reader = make_user('reader@example.com', 'reader')
        self.post = Post.objects.create(
            title='A post', content=BODY, author=self.author, status=Post.Status.PUBLISHED,
        )
        Like.objects.create(post=self.post, user=self.reader)

    def test_inbox_requires_sign_in(self):
        self.assertEqual(self.client.get('/api/notifications/').status_code,
                         status.HTTP_401_UNAUTHORIZED)

    def test_a_user_sees_only_their_own_notifications(self):
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/notifications/').data['count'], 0)

        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get('/api/notifications/').data['count'], 1)

    def test_unread_count(self):
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get('/api/notifications/unread-count/').data['unread'], 1)

    def test_marking_all_read_clears_the_count(self):
        self.client.force_authenticate(self.author)
        response = self.client.post('/api/notifications/read/', {}, format='json')
        self.assertEqual(response.data['unread'], 0)
        self.assertFalse(Notification.objects.filter(is_read=False).exists())

    def test_marking_one_read_leaves_the_others(self):
        Follow.objects.create(follower=self.reader, following=self.author)
        first = Notification.objects.filter(recipient=self.author).first()

        self.client.force_authenticate(self.author)
        response = self.client.post(
            '/api/notifications/read/', {'ids': [str(first.id)]}, format='json'
        )
        self.assertEqual(response.data['unread'], 1)

    def test_marking_read_cannot_touch_somebody_elses_notification(self):
        target = Notification.objects.get(recipient=self.author)

        self.client.force_authenticate(self.reader)
        self.client.post('/api/notifications/read/', {'ids': [str(target.id)]}, format='json')

        target.refresh_from_db()
        self.assertFalse(target.is_read)

    def test_unread_filter(self):
        Notification.objects.update(is_read=True)
        self.client.force_authenticate(self.author)
        response = self.client.get('/api/notifications/', {'unread': 'true'})
        self.assertEqual(response.data['count'], 0)

    def test_dismissing_a_notification(self):
        target = Notification.objects.get(recipient=self.author)
        self.client.force_authenticate(self.author)
        response = self.client.delete(f'/api/notifications/{target.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Notification.objects.count(), 0)

    def test_cannot_dismiss_somebody_elses_notification(self):
        target = Notification.objects.get(recipient=self.author)
        self.client.force_authenticate(self.reader)
        response = self.client.delete(f'/api/notifications/{target.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_the_payload_carries_a_link_to_the_post(self):
        self.client.force_authenticate(self.author)
        result = self.client.get('/api/notifications/').data['results'][0]
        self.assertEqual(result['url'], f'/post/{self.post.slug}')
        self.assertEqual(result['post_title'], self.post.title)
