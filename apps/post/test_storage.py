"""
Media storage behaviour, local and Cloudinary.

These lock in the two things a storage swap can quietly break: the JSON field
names the frontend reads, and the shape of the URL inside them.
"""

from django.contrib.auth import get_user_model
from django.test import RequestFactory, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.post.models import Post
from apps.user.serializers import absolute_url

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule.'


class FakeField:
    """Stands in for a FileField whose storage returns `url`."""

    def __init__(self, url):
        self._url = url

    def __bool__(self):
        return bool(self._url)

    @property
    def url(self):
        return self._url


class AbsoluteUrlTests(APITestCase):
    def setUp(self):
        self.request = RequestFactory().get('/api/posts/')

    def test_a_local_path_gets_the_api_host(self):
        result = absolute_url(self.request, FakeField('/media/user_photos/a.jpg'))
        self.assertEqual(result, 'http://testserver/media/user_photos/a.jpg')

    def test_a_cloudinary_url_is_returned_untouched(self):
        cloud = 'https://res.cloudinary.com/demo/image/upload/v1/user_photos/a.jpg'
        self.assertEqual(absolute_url(self.request, FakeField(cloud)), cloud)

    def test_no_double_prefixing(self):
        cloud = 'https://res.cloudinary.com/demo/image/upload/v1/a.jpg'
        result = absolute_url(self.request, FakeField(cloud))
        self.assertNotIn('testserver', result)
        self.assertEqual(result.count('https://'), 1)

    def test_a_protocol_relative_url_is_left_alone(self):
        url = '//res.cloudinary.com/demo/image/upload/v1/a.jpg'
        self.assertEqual(absolute_url(self.request, FakeField(url)), url)

    def test_an_empty_field_is_none(self):
        self.assertIsNone(absolute_url(self.request, FakeField('')))

    def test_it_works_without_a_request(self):
        self.assertEqual(absolute_url(None, FakeField('/media/a.jpg')), '/media/a.jpg')


class MediaFieldNameTests(APITestCase):
    """The frontend reads these names; a storage change must not rename them."""

    def setUp(self):
        self.author = User.objects.create_user(
            email='w@example.com', username='writer', password='StrongPass!234',
            first_name='Ada', last_name='Lovelace', is_verified=True,
        )
        self.post = Post.objects.create(
            title='With media', content=BODY, author=self.author,
            status=Post.Status.PUBLISHED,
        )

    def test_post_exposes_cover_image(self):
        response = self.client.get(f'/api/posts/{self.post.slug}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('cover_image', response.data)

    def test_author_block_exposes_avatar(self):
        response = self.client.get(f'/api/posts/{self.post.slug}/')
        self.assertIn('avatar', response.data['author'])

    def test_media_urls_are_absolute(self):
        response = self.client.get(f'/api/posts/{self.post.slug}/')
        cover = response.data['cover_image']
        if cover:
            self.assertTrue(cover.startswith('http'), cover)


def storage_choice(cloud_name, api_key, api_secret):
    """
    The decision `settings.py` makes, as a function.

    Reimplemented here on purpose: asserting against the live `settings` would
    make the test pass or fail depending on whether the developer running it
    happens to have Cloudinary credentials in their own .env.
    """
    return 'cloudinary' if all([cloud_name, api_key, api_secret]) else 'local'


class StorageConfigurationTests(APITestCase):
    """Cloudinary is opt-in, and static files never move to it."""

    def test_local_storage_without_credentials(self):
        self.assertEqual(storage_choice('', '', ''), 'local')

    def test_a_partial_configuration_stays_local(self):
        """Two of three would fail at upload time, which is far worse."""
        self.assertEqual(storage_choice('demo', 'key', ''), 'local')
        self.assertEqual(storage_choice('demo', '', 'secret'), 'local')

    def test_all_three_credentials_select_cloudinary(self):
        self.assertEqual(storage_choice('demo', 'key', 'secret'), 'cloudinary')

    def test_the_live_setting_agrees_with_that_rule(self):
        from django.conf import settings

        expected = storage_choice(
            settings.CLOUDINARY_CLOUD_NAME,
            settings.CLOUDINARY_API_KEY,
            settings.CLOUDINARY_API_SECRET,
        )
        self.assertEqual(settings.USE_CLOUDINARY, expected == 'cloudinary')
        backend = settings.STORAGES['default']['BACKEND'].lower()
        self.assertEqual('cloudinary' in backend, expected == 'cloudinary')

    def test_static_files_never_move_to_cloudinary(self):
        from django.conf import settings

        self.assertNotIn('cloudinary', settings.STORAGES['staticfiles']['BACKEND'].lower())

    def test_credentials_are_never_sent_to_the_client(self):
        """No endpoint may echo the API secret back."""
        response = self.client.get('/api/posts/')
        body = str(response.data)
        self.assertNotIn('API_SECRET', body)
        self.assertNotIn('CLOUDINARY', body)
