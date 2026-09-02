"""Account deletion — irreversible, so it is fenced twice."""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.comment.models import Comment
from apps.post.models import Post
from apps.user.models import Follow

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule.'


def make_user(email='me@example.com', username='me', role='author', **extra):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Ada', last_name='Lovelace', is_verified=True, role=role, **extra
    )


class SummaryTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user('o@example.com', 'other')
        post = Post.objects.create(title='Mine', content=BODY, author=self.user,
                                   status=Post.Status.PUBLISHED)
        Comment.objects.create(post=post, author=self.user, content='Hi')
        Follow.objects.create(follower=self.other, following=self.user)

    def test_the_summary_needs_a_sign_in(self):
        self.assertEqual(self.client.get('/api/users/me/delete/').status_code,
                         status.HTTP_401_UNAUTHORIZED)

    def test_it_says_what_will_be_destroyed(self):
        """"Are you sure?" is far weaker than naming the numbers."""
        self.client.force_authenticate(self.user)
        data = self.client.get('/api/users/me/delete/').data
        self.assertEqual(data['posts'], 1)
        self.assertEqual(data['published_posts'], 1)
        self.assertEqual(data['comments'], 1)
        self.assertEqual(data['followers'], 1)
        self.assertTrue(data['can_delete'])

    def test_the_last_super_admin_is_blocked(self):
        boss = make_user('b@example.com', 'boss', role='super_admin')
        self.client.force_authenticate(boss)
        data = self.client.get('/api/users/me/delete/').data
        self.assertFalse(data['can_delete'])
        self.assertIn('only super admin', data['blocker'])

    def test_one_of_two_super_admins_may_leave(self):
        boss = make_user('b@example.com', 'boss', role='super_admin')
        make_user('b2@example.com', 'boss2', role='super_admin')
        self.client.force_authenticate(boss)
        self.assertTrue(self.client.get('/api/users/me/delete/').data['can_delete'])


class DeletionTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)

    def payload(self, **overrides):
        return {'password': 'StrongPass!234', 'confirm_username': 'me', **overrides}

    def test_the_wrong_password_is_refused(self):
        response = self.client.delete('/api/users/me/delete/',
                                      self.payload(password='wrong'), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_a_mistyped_username_is_refused(self):
        response = self.client.delete('/api/users/me/delete/',
                                      self.payload(confirm_username='nope'), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_the_username_check_ignores_case(self):
        response = self.client.delete('/api/users/me/delete/',
                                      self.payload(confirm_username='ME'), format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_both_confirmations_delete_the_account(self):
        response = self.client.delete('/api/users/me/delete/', self.payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_deleting_takes_the_content_with_it(self):
        post = Post.objects.create(title='Mine', content=BODY, author=self.user,
                                   status=Post.Status.PUBLISHED)
        self.client.delete('/api/users/me/delete/', self.payload(), format='json')
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())

    def test_a_social_account_needs_only_the_typed_username(self):
        """They were never given a password; asking for one would trap them."""
        social = make_user('s@example.com', 'social', auth_provider='github')
        social.set_unusable_password()
        social.save()

        self.client.force_authenticate(social)
        response = self.client.delete('/api/users/me/delete/',
                                      {'confirm_username': 'social'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_a_password_account_cannot_skip_the_password(self):
        response = self.client.delete('/api/users/me/delete/',
                                      {'confirm_username': 'me'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_you_cannot_delete_while_signed_out(self):
        self.client.force_authenticate(None)
        response = self.client.delete('/api/users/me/delete/', self.payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
