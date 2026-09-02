"""Authentication, profile and follow tests."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.post.models import Post
from apps.user.models import Follow, LoginCode, PasswordResetToken
from apps.user.social import SocialProfile
from apps.user.views import user_from_social

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


class PasswordResetTests(APITestCase):
    """The forgotten-password flow."""

    def setUp(self):
        self.user = make_user()
        self.request_url = '/api/auth/password-reset/'
        self.confirm_url = '/api/auth/password-reset/confirm/'

    def test_requesting_a_reset_for_an_unknown_address_looks_identical(self):
        known = self.client.post(self.request_url, {'email': self.user.email}, format='json')
        unknown = self.client.post(self.request_url, {'email': 'nobody@example.com'}, format='json')
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.data['message'], unknown.data['message'])

    def test_no_token_is_issued_for_an_unknown_address(self):
        self.client.post(self.request_url, {'email': 'nobody@example.com'}, format='json')
        self.assertEqual(PasswordResetToken.objects.count(), 0)

    def test_the_plain_token_is_never_stored(self):
        raw = PasswordResetToken.issue(self.user, 30)
        stored = PasswordResetToken.objects.get()
        self.assertNotEqual(stored.token_hash, raw)
        self.assertEqual(stored.token_hash, PasswordResetToken.hash_token(raw))

    def test_a_valid_token_sets_a_new_password_and_signs_in(self):
        raw = PasswordResetToken.issue(self.user, 30)
        response = self.client.post(self.confirm_url, {
            'token': raw,
            'new_password': 'BrandNewPass!99',
            'new_password_confirm': 'BrandNewPass!99',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BrandNewPass!99'))

    def test_a_token_can_only_be_used_once(self):
        raw = PasswordResetToken.issue(self.user, 30)
        payload = {
            'token': raw,
            'new_password': 'BrandNewPass!99',
            'new_password_confirm': 'BrandNewPass!99',
        }
        self.client.post(self.confirm_url, payload, format='json')
        second = self.client.post(self.confirm_url, payload, format='json')
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_an_expired_token_is_rejected(self):
        raw = PasswordResetToken.issue(self.user, 30)
        PasswordResetToken.objects.update(expires_at=timezone.now() - timedelta(minutes=1))

        response = self.client.post(self.confirm_url, {
            'token': raw,
            'new_password': 'BrandNewPass!99',
            'new_password_confirm': 'BrandNewPass!99',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_an_unknown_token_is_rejected(self):
        response = self.client.post(self.confirm_url, {
            'token': 'not-a-real-token',
            'new_password': 'BrandNewPass!99',
            'new_password_confirm': 'BrandNewPass!99',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mismatched_passwords_are_rejected(self):
        raw = PasswordResetToken.issue(self.user, 30)
        response = self.client.post(self.confirm_url, {
            'token': raw,
            'new_password': 'BrandNewPass!99',
            'new_password_confirm': 'SomethingElse!99',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_weak_password_is_rejected(self):
        raw = PasswordResetToken.issue(self.user, 30)
        response = self.client.post(self.confirm_url, {
            'token': raw,
            'new_password': '12345678',
            'new_password_confirm': '12345678',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('StrongPass!234'))

    def test_issuing_a_new_token_invalidates_the_previous_one(self):
        first = PasswordResetToken.issue(self.user, 30)
        PasswordResetToken.issue(self.user, 30)

        response = self.client.post(self.confirm_url, {
            'token': first,
            'new_password': 'BrandNewPass!99',
            'new_password_confirm': 'BrandNewPass!99',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# Social credentials are read from the environment, so these tests pin them
# explicitly. Without that, the suite would pass or fail depending on which
# providers the developer happens to have configured in their own .env.
NO_SOCIAL = override_settings(
    GITHUB_CLIENT_ID='', GITHUB_SECRET='',
    GOOGLE_CLIENT_ID='', GOOGLE_SECRET='',
)


@NO_SOCIAL
class SocialAuthTests(APITestCase):
    """Sign-in through GitHub and Google."""

    def test_providers_list_is_empty_without_credentials(self):
        response = self.client.get('/api/auth/providers/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    @override_settings(
        GITHUB_CLIENT_ID='id', GITHUB_SECRET='secret',
        GOOGLE_CLIENT_ID='', GOOGLE_SECRET='',
    )
    def test_a_configured_provider_is_advertised(self):
        response = self.client.get('/api/auth/providers/')
        names = [entry['name'] for entry in response.data]
        self.assertIn('github', names)
        self.assertNotIn('google', names)

    def test_an_unknown_provider_is_a_400(self):
        response = self.client.post('/api/auth/social/myspace/', {'code': 'x'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_an_unconfigured_provider_says_so_rather_than_failing_oddly(self):
        response = self.client.post('/api/auth/social/github/', {'code': 'x'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('not configured', response.data['detail'].lower())

    def test_a_missing_code_is_rejected(self):
        response = self.client.post('/api/auth/social/github/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_social_profile_creates_a_verified_account(self):
        profile = SocialProfile('newcomer@example.com', 'Grace', 'Hopper', 'grace', 'github')
        user, created = user_from_social(profile)

        self.assertTrue(created)
        self.assertTrue(user.is_verified)
        self.assertEqual(user.auth_provider, 'github')
        self.assertFalse(user.has_usable_password())

    def test_a_social_profile_matches_an_existing_account_by_email(self):
        profile = SocialProfile(self.existing.email, 'Ada', 'Lovelace', 'ada', 'google')
        user, created = user_from_social(profile)

        self.assertFalse(created)
        self.assertEqual(user.pk, self.existing.pk)
        self.assertEqual(User.objects.count(), 1)

    def test_signing_in_socially_verifies_a_pending_account(self):
        self.existing.is_verified = False
        self.existing.save(update_fields=['is_verified'])

        user, _ = user_from_social(
            SocialProfile(self.existing.email, '', '', 'ada', 'github')
        )
        self.assertTrue(user.is_verified)

    def test_a_taken_username_does_not_break_account_creation(self):
        make_user('taken@example.com', 'grace')
        user, created = user_from_social(
            SocialProfile('newcomer@example.com', 'Grace', 'Hopper', 'grace', 'github')
        )
        self.assertTrue(created)
        self.assertNotEqual(user.username, 'grace')

    def setUp(self):
        self.existing = make_user()
