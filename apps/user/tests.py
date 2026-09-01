"""Authentication, profile and follow tests."""

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.post.models import Post
from apps.user.models import Follow, LoginCode

User = get_user_model()

# Verification is exercised in its own test; the rest sign in directly.
NO_VERIFICATION = override_settings(REQUIRE_EMAIL_VERIFICATION=False)


def make_user(email='writer@example.com', username='writer', password='StrongPass!234', **extra):
    return User.objects.create_user(
        email=email, username=username, password=password,
        first_name='Ada', last_name='Lovelace', is_verified=True, **extra
    )


@NO_VERIFICATION
class RegistrationTests(APITestCase):
    url = '/api/auth/register/'

    def test_register_returns_tokens_and_user(self):
        response = self.client.post(self.url, {
            'first_name': 'Ada', 'last_name': 'Lovelace',
            'email': 'ada@example.com', 'username': 'ada',
            'password': 'StrongPass!234', 'confirm_password': 'StrongPass!234',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.data)
        self.assertEqual(response.data['user']['email'], 'ada@example.com')
        self.assertTrue(User.objects.filter(email='ada@example.com').exists())

    def test_password_mismatch_is_rejected(self):
        response = self.client.post(self.url, {
            'first_name': 'Ada', 'last_name': 'Lovelace', 'email': 'ada@example.com',
            'password': 'StrongPass!234', 'confirm_password': 'Different!234',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('confirm_password', response.data)

    def test_weak_password_is_rejected(self):
        response = self.client.post(self.url, {
            'first_name': 'Ada', 'last_name': 'Lovelace', 'email': 'ada@example.com',
            'password': 'password', 'confirm_password': 'password',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_email_is_rejected(self):
        make_user(email='ada@example.com', username='taken')
        response = self.client.post(self.url, {
            'first_name': 'Ada', 'last_name': 'L', 'email': 'ada@example.com',
            'password': 'StrongPass!234', 'confirm_password': 'StrongPass!234',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)

    def test_username_is_generated_when_omitted(self):
        response = self.client.post(self.url, {
            'first_name': 'Ada', 'last_name': 'L', 'email': 'ada.lovelace@example.com',
            'password': 'StrongPass!234', 'confirm_password': 'StrongPass!234',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['user']['username'])


@NO_VERIFICATION
class LoginTests(APITestCase):
    url = '/api/auth/login/'

    def setUp(self):
        self.user = make_user()

    def test_login_with_email(self):
        response = self.client.post(
            self.url, {'email': 'writer@example.com', 'password': 'StrongPass!234'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_login_with_username(self):
        response = self.client.post(
            self.url, {'email': 'writer', 'password': 'StrongPass!234'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_sets_httponly_cookies(self):
        response = self.client.post(
            self.url, {'email': 'writer@example.com', 'password': 'StrongPass!234'}, format='json'
        )
        self.assertTrue(response.cookies['access_token']['httponly'])
        self.assertTrue(response.cookies['refresh_token']['httponly'])

    def test_wrong_password_is_401(self):
        response = self.client.post(
            self.url, {'email': 'writer@example.com', 'password': 'wrong'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unknown_email_gives_the_same_answer_as_a_wrong_password(self):
        unknown = self.client.post(
            self.url, {'email': 'nobody@example.com', 'password': 'wrong'}, format='json'
        )
        known = self.client.post(
            self.url, {'email': 'writer@example.com', 'password': 'wrong'}, format='json'
        )
        self.assertEqual(unknown.status_code, known.status_code)
        self.assertEqual(unknown.data['detail'], known.data['detail'])


class EmailVerificationTests(APITestCase):
    @override_settings(REQUIRE_EMAIL_VERIFICATION=True)
    def test_unverified_login_sends_a_code_then_verifies(self):
        User.objects.create_user(
            email='new@example.com', username='newbie', password='StrongPass!234'
        )
        login = self.client.post(
            '/api/auth/login/', {'email': 'new@example.com', 'password': 'StrongPass!234'},
            format='json',
        )
        self.assertTrue(login.data['requires_verification'])
        self.assertNotIn('access', login.data)

        code = LoginCode.objects.get(user__email='new@example.com').code
        verify = self.client.post(
            '/api/auth/verify/', {'email': 'new@example.com', 'code': code}, format='json'
        )
        self.assertEqual(verify.status_code, status.HTTP_200_OK)
        self.assertIn('access', verify.data)
        self.assertTrue(User.objects.get(email='new@example.com').is_verified)

    @override_settings(REQUIRE_EMAIL_VERIFICATION=True)
    def test_wrong_code_is_rejected(self):
        User.objects.create_user(email='new@example.com', username='newbie', password='StrongPass!234')
        response = self.client.post(
            '/api/auth/verify/', {'email': 'new@example.com', 'code': '000000'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@NO_VERIFICATION
class CurrentUserTests(APITestCase):
    def setUp(self):
        self.user = make_user()

    def test_me_requires_authentication(self):
        response = self.client.get('/api/users/me/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_the_profile(self):
        self.client.force_authenticate(self.user)
        response = self.client.get('/api/users/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for field in ('id', 'username', 'email', 'name', 'avatar', 'bio',
                      'date_joined', 'post_count'):
            self.assertIn(field, response.data)

    def test_profile_update_ignores_protected_fields(self):
        self.client.force_authenticate(self.user)
        response = self.client.patch('/api/users/me/', {
            'bio': 'Writing about databases.',
            'is_staff': True,
            'is_superuser': True,
            'is_verified': False,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.bio, 'Writing about databases.')
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)

    def test_duplicate_username_is_rejected(self):
        make_user(email='other@example.com', username='taken')
        self.client.force_authenticate(self.user)
        response = self.client.patch('/api/users/me/', {'username': 'taken'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_change_requires_the_current_password(self):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/users/me/password/', {
            'current_password': 'wrong',
            'new_password': 'BrandNew!2345',
            'new_password_confirm': 'BrandNew!2345',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_change_succeeds(self):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/users/me/password/', {
            'current_password': 'StrongPass!234',
            'new_password': 'BrandNew!2345',
            'new_password_confirm': 'BrandNew!2345',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BrandNew!2345'))


@NO_VERIFICATION
class DashboardTests(APITestCase):
    def test_dashboard_counts_only_the_signed_in_author(self):
        author = make_user()
        other = make_user(email='other@example.com', username='other')
        Post.objects.create(title='Published one', content='x' * 60, author=author,
                            status=Post.Status.PUBLISHED)
        Post.objects.create(title='A draft', content='x' * 60, author=author)
        Post.objects.create(title='Someone else', content='x' * 60, author=other,
                            status=Post.Status.PUBLISHED)

        self.client.force_authenticate(author)
        response = self.client.get('/api/users/me/dashboard/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_posts'], 2)
        self.assertEqual(response.data['published_posts'], 1)
        self.assertEqual(response.data['draft_posts'], 1)


@NO_VERIFICATION
class PublicProfileTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        Post.objects.create(title='Hello world', content='x' * 60, author=self.author,
                            status=Post.Status.PUBLISHED)

    def test_public_profile_hides_the_email(self):
        response = self.client.get(f'/api/users/{self.author.username}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('email', response.data)
        self.assertEqual(response.data['post_count'], 1)

    def test_author_directory_lists_only_authors_with_published_posts(self):
        make_user(email='silent@example.com', username='silent')
        response = self.client.get('/api/users/')
        usernames = [row['username'] for row in response.data['results']]
        self.assertIn(self.author.username, usernames)
        self.assertNotIn('silent', usernames)


@NO_VERIFICATION
class FollowTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.target = make_user(email='target@example.com', username='target')

    def test_follow_then_unfollow(self):
        self.client.force_authenticate(self.user)
        follow = self.client.post(f'/api/users/{self.target.username}/follow/')
        self.assertTrue(follow.data['is_following'])
        self.assertEqual(follow.data['follower_count'], 1)

        unfollow = self.client.delete(f'/api/users/{self.target.username}/follow/')
        self.assertFalse(unfollow.data['is_following'])
        self.assertEqual(unfollow.data['follower_count'], 0)

    def test_following_twice_creates_one_row(self):
        self.client.force_authenticate(self.user)
        self.client.post(f'/api/users/{self.target.username}/follow/')
        self.client.post(f'/api/users/{self.target.username}/follow/')
        self.assertEqual(Follow.objects.filter(following=self.target).count(), 1)

    def test_cannot_follow_yourself(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(f'/api/users/{self.user.username}/follow/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
